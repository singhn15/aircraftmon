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
secrets = boto3.client('secretsmanager')

app = FastAPI()

# Global dict to store active trackers
active_trackers = {}

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

async def post_to_slack(message: str):
    logger.debug(f"[DEBUG] Attempting to post to Slack: {message}")
    webhook_url = await get_secret('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.error("SLACK_WEBHOOK_URL not configured in Secrets Manager")
        return
    
    logger.debug("[DEBUG] Got webhook URL from secrets")
    payload = {"text": message}
    async with aiohttp.ClientSession() as session:
        try:
            logger.debug("[DEBUG] Sending POST request to Slack")
            async with session.post(webhook_url, json=payload) as response:
                response_text = await response.text()
                logger.debug(f"[DEBUG] Slack response: {response.status} {response_text}")
        except Exception as e:
            logger.error(f"Failed to post to slack: {str(e)}")

async def start_tracking(plane_hex: str):
    # Check if already tracking
    if plane_hex in active_trackers:
        return f"Tracking already in progress for {plane_hex}!"
    
    # Get API key from Secrets Manager
    api_key = await get_secret('RAPIDAPI_KEY')
    if not api_key:
        return "API key not configured"
    
    logger.debug(f"Starting tracking for {plane_hex} with API key length: {len(api_key)}")

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
        jump_run_altitude=18500,
        hop_n_pop_altitude=5000,
        runway_altitude=5000,
        dz_lat=40.16638,
        dz_lon=-105.16178,
        radius_nm=5,
        debug=True,
        callback=post_to_slack
    )
    
    # Start tracking in the background
    logger.debug("Creating tracking task...")
    task = asyncio.create_task(tracker.track())
    logger.debug("Tracking task created")
    
    # Store the tracker and task
    active_trackers[plane_hex] = (tracker, task)
    
    return "Started tracking aircraft!"

async def stop_tracking(plane_hex: str):
    if plane_hex not in active_trackers:
        return "No tracking in progress"

    await post_to_slack("Stopping aircraft tracking...")
    
    # Stop the tracker if it exists
    tracker, task = active_trackers[plane_hex]
    await tracker.stop()  # Signal the tracker to stop
    # Wait a moment for the tracker to stop gracefully
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.TimeoutError:
        logger.warning(f"Tracker for {plane_hex} taking longer than expected to stop")
    
    # Remove from active trackers
    del active_trackers[plane_hex]
    return "Aircraft tracking has stopped."

async def get_tracker_status(plane_hex: str):
    if plane_hex in active_trackers:
        return "Tracker Status: active"
    return "Tracker Status: inactive"

async def clear_trackers():
    if not active_trackers:
        return "No active trackers to clear"
    
    # Stop all active trackers
    for plane_hex in list(active_trackers.keys()):
        await stop_tracking(plane_hex)
    
    return f"Cleared all active trackers"

@app.post("/clear")
async def clear_states():
    result = await clear_trackers()
    await post_to_slack(f"🧹 {result}")
    return {"message": result}

@app.get("/")
async def root():
    logger.debug("hello, world! aircraftmon fastapi. port 4200")
    return {"message": "hello, world! aircraftmon fastapi. port 4200"}

@app.post("/slack/events")
async def slack_events(request: Request):
    try:
        data = await request.json()
        # logger.debug(f"Incoming Slack payload: {data}")

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
        elif command == "clear":
            response_text = await clear_trackers()
        else:
            response_text = "Available commands:\n• 'start tracking <plane_hex>' to begin tracking\n• 'status <plane_hex>' to check current state\n• 'stop <plane_hex>' to stop tracking"

        await post_to_slack(response_text)
        return JSONResponse(status_code=200, content={})
    except Exception as e:
        logger.error(f"Error processing Slack event: {e}")
        await post_to_slack("❌ Error processing command. Please check the format and try again.")
        return JSONResponse(status_code=400, content={"error": "Invalid request"})