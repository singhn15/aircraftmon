from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import logging
import asyncio
import aiohttp
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from aircraftmon import PlaneMonitor
from datetime import datetime
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG)
# Reduce boto3 logging noise
logging.getLogger('boto3').setLevel(logging.INFO)
logging.getLogger('botocore').setLevel(logging.INFO)
logging.getLogger('urllib3').setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
secrets = boto3.client('secretsmanager')
table = dynamodb.Table('aircraft_tracking')

app = FastAPI()

async def get_secret(secret_name: str) -> str:
    try:
        response = await asyncio.to_thread(
            secrets.get_secret_value,
            SecretId=secret_name
        )
        secret_string = response['SecretString']
        
        # Handle JSON-formatted secrets
        try:
            secret_dict = json.loads(secret_string)
            if secret_name == 'SLACK_WEBHOOK_URL':
                return secret_dict.get('webhook', '')
            return secret_dict.get(secret_name, '')
        except json.JSONDecodeError:
            # If not JSON, return as is
            return secret_string
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'DecryptionFailureException':
            logger.error(f"Secret {secret_name}: Unable to decrypt using provided KMS key")
        elif error_code == 'InternalServiceErrorException':
            logger.error(f"Secret {secret_name}: Internal service error in AWS")
        elif error_code == 'InvalidParameterException':
            logger.error(f"Secret {secret_name}: Invalid parameter provided")
        elif error_code == 'InvalidRequestException':
            logger.error(f"Secret {secret_name}: Invalid request to AWS")
        elif error_code == 'ResourceNotFoundException':
            logger.error(f"Secret {secret_name} not found in Secrets Manager")
        else:
            logger.error(f"Unknown error retrieving secret {secret_name}: {e}")
        return ""

async def get_tracker_state(plane_hex: str) -> dict:
    try:
        response = await asyncio.to_thread(
            table.get_item,
            Key={'plane_hex': plane_hex}
        )
        return response.get('Item', {})
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceNotFoundException':
            logger.error("DynamoDB table 'aircraft_tracking' not found")
        elif error_code == 'ProvisionedThroughputExceededException':
            logger.error("DynamoDB throughput exceeded - consider increasing capacity")
        else:
            logger.error(f"DynamoDB error retrieving state for {plane_hex}: {e}")
        return {}

async def update_tracker_state(plane_hex: str, state: str, task_id: Optional[str] = None):
    try:
        item = {
            'plane_hex': plane_hex,
            'state': state,
            'updated_at': int(datetime.now().timestamp())
        }
        if task_id:
            item['task_id'] = task_id
            
        await asyncio.to_thread(
            table.put_item,
            Item=item
        )
        logger.debug(f"Successfully updated state for {plane_hex} to {state}")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceNotFoundException':
            logger.error("DynamoDB table 'aircraft_tracking' not found")
        elif error_code == 'ProvisionedThroughputExceededException':
            logger.error("DynamoDB throughput exceeded - consider increasing capacity")
        else:
            logger.error(f"DynamoDB error updating state for {plane_hex}: {e}")

async def post_to_slack(message: str):
    webhook_url = await get_secret('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.error("SLACK_WEBHOOK_URL not configured in Secrets Manager")
        return
        
    payload = {"text": message}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(webhook_url, json=payload) as response:
                logger.debug(f"posting to slack... {response.status} {await response.text()}")
        except Exception as e:
            logger.error(f"Failed to post to slack. {e}")

async def start_tracking(plane_hex: str):
    # Check if already tracking
    state = await get_tracker_state(plane_hex)
    if state.get('state') == 'active':
        return f"Tracking already in progress for {plane_hex}!"
    
    # Get API key from Secrets Manager
    api_key = await get_secret('RAPIDAPI_KEY')
    if not api_key:
        return "API key not configured"

    # Initialize the tracker with your configuration
    tracker = PlaneMonitor(
        headers={
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
        },
        plane_hex=plane_hex,
        plane_name="Skydiving Aircraft",
        climb_threshold=5300,
        descent_threshold=-500,
        jump_run_altitude=12500,
        runway_altitude=5000,
        dz_lat=40.16638,
        dz_lon=-105.16178,
        radius_nm=5,
        debug=True,
        callback=post_to_slack
    )
    
    # Start tracking in the background
    task = asyncio.create_task(tracker.track())
    await update_tracker_state(plane_hex, 'active', str(id(task)))
    return "Started tracking aircraft!"

async def stop_tracking(plane_hex: str):
    state = await get_tracker_state(plane_hex)
    if state.get('state') != 'active':
        return "No tracking in progress"

    await post_to_slack("Stopping aircraft tracking...")
    await update_tracker_state(plane_hex, 'stopped')
    return "Aircraft tracking has stopped."

async def get_tracker_status(plane_hex: str):
    state = await get_tracker_state(plane_hex)
    if not state:
        return "No tracker initialized"
    return f"Tracker Status: {state.get('state', 'Unknown')}"
        
@app.get("/")
async def root():
    logger.debug("hello, world! aircraftmon fastapi. port 4200")
    return {"message": "hello, world! aircraftmon fastapi. port 4200"}

@app.post("/slack/events")
async def slack_events(request: Request):
    try:
        data = await request.json()
        logger.debug(f"Incoming Slack payload: {data}")

        if data.get("type") == "url_verification":
            challenge = data.get("challenge")
            logger.debug(f"challenge: {challenge}")
            return PlainTextResponse(content=challenge)

        event = data.get("event", {})
        text = event.get("text", "").lower().strip()
        
        # Parse command and plane_hex
        parts = text.split()
        if len(parts) < 2:
            response_text = "Please provide a command: 'start tracking <plane_hex>', 'status <plane_hex>', or 'stop <plane_hex>'"
            await post_to_slack(response_text)
            return JSONResponse(status_code=200, content={})

        command = parts[1]
        
        # Extract plane_hex if provided
        plane_hex = parts[2] if len(parts) > 2 else None
        
        if command == "start":
            if not plane_hex:
                response_text = "Please provide a plane hex to track (e.g. 'start tracking A65DDF')"
            else:
                response_text = await start_tracking(plane_hex)
        elif command == "status":
            if not plane_hex:
                response_text = "Please provide a plane hex to check status (e.g. 'status A65DDF')"
            else:
                response_text = await get_tracker_status(plane_hex)
        elif command == "stop":
            if not plane_hex:
                response_text = "Please provide a plane hex to stop tracking (e.g. 'stop A65DDF')"
            else:
                response_text = await stop_tracking(plane_hex)
        else:
            response_text = "Available commands:\n• 'start tracking <plane_hex>' to begin tracking\n• 'status <plane_hex>' to check current state\n• 'stop <plane_hex>' to stop tracking"

        await post_to_slack(response_text)
        return JSONResponse(status_code=200, content={})
    except Exception as e:
        logger.error(f"Error processing Slack event: {e}")
        await post_to_slack("❌ Error processing command. Please check the format and try again.")
        return JSONResponse(status_code=400, content={"error": "Invalid request"})