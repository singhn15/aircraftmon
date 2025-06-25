from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import logging
from dotenv import load_dotenv
import os
import asyncio
import aiohttp
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from aircraftmon import PlaneMonitor
from datetime import datetime

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

load_dotenv()

# Initialize AWS clients if AWS credentials are available
try:
    dynamodb = boto3.resource('dynamodb')
    secrets = boto3.client('secretsmanager')
    table = dynamodb.Table('aircraft_tracking')
    USE_AWS = True
except:
    USE_AWS = False
    logger.info("AWS credentials not found, using local environment variables")

app = FastAPI()

async def get_secret(secret_name: str) -> str:
    # First try environment variables
    env_value = os.environ.get(secret_name)
    if env_value:
        return env_value
        
    # Then try AWS Secrets Manager if available
    if USE_AWS:
        try:
            response = secrets.get_secret_value(SecretId=secret_name)
            return response['SecretString']
        except ClientError as e:
            logger.error(f"Error fetching secret {secret_name}: {e}")
    
    return ""

async def get_tracker_state(plane_hex: str) -> dict:
    if not USE_AWS:
        return {}
        
    try:
        response = table.get_item(Key={'plane_hex': plane_hex})
        return response.get('Item', {})
    except ClientError as e:
        logger.error(f"Error fetching state: {e}")
        return {}

async def update_tracker_state(plane_hex: str, state: str, task_id: Optional[str] = None):
    if not USE_AWS:
        return
        
    try:
        table.put_item(Item={
            'plane_hex': plane_hex,
            'state': state,
            'task_id': task_id,
            'updated_at': int(datetime.now().timestamp())
        })
    except ClientError as e:
        logger.error(f"Error updating state: {e}")

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

        event = data.get("event")
        text = event.get("text", "").lower()
        
        # Safely get plane_hex from command
        words = text.split(" ")
        plane_hex = words[2] if len(words) > 2 else None

        if "start" in text:
            if plane_hex:
                response_text = await start_tracking(plane_hex)
            else:
                response_text = "Please provide a plane hex to track (e.g. 'start tracking A65DDF')"
        elif "status" in text:
            response_text = await get_tracker_status(plane_hex or "")
        elif "stop" in text:
            response_text = await stop_tracking(plane_hex or "")
        else:
            response_text = "Available commands: 'start' to begin tracking, 'status' to check current state, 'stop' to stop tracking"

        await post_to_slack(response_text)
        return JSONResponse(status_code=200, content={})
    except Exception as e:
        logger.error(f"Error processing Slack event: {e}")
        return JSONResponse(status_code=400, content={"error": "Invalid request"})