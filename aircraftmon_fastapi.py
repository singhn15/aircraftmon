from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
import logging
from dotenv import load_dotenv
import os
import asyncio
import aiohttp
from typing import Optional
from aircraftmon import PlaneMonitor

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

load_dotenv()
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

app = FastAPI()

# Global tracker task and instance
tracker_task: Optional[asyncio.Task] = None
tracker: Optional[PlaneMonitor] = None

async def post_to_slack(message: str):
    if not SLACK_WEBHOOK_URL:
        logger.error("SLACK_WEBHOOK_URL not configured")
        return
        
    payload = {"text": message}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(SLACK_WEBHOOK_URL, json=payload) as response:
                logger.debug(f"posting to slack... {response.status} {await response.text()}")
        except Exception as e:
            logger.error(f"Failed to post to slack. {e}")

async def start_tracking():
    global tracker, tracker_task
    
    if tracker_task and not tracker_task.done():
        return "Tracking already in progress!"
    
    # Initialize the tracker with your configuration
    tracker = PlaneMonitor(
        headers={
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
        },
        plane_hex="A65DDF",  # You might want to make this configurable
        plane_name="Skydiving Aircraft",
        climb_threshold=5300,
        descent_threshold=-500,
        jump_run_altitude=12500,
        runway_altitude=5000,
        dz_lat=40.16638,
        dz_lon=-105.16178,
        radius_nm=5,
        debug=True,
        callback=post_to_slack  # This will send all announcements to Slack
    )
    
    # Start tracking in the background using the PlaneMonitor's track method
    tracker_task = asyncio.create_task(tracker.track())
    return "Started tracking aircraft!"

async def stop_tracking():
    global tracker, tracker_task
    if tracker_task:
        await post_to_slack("Stopping aircraft tracking...")
        tracker_task.cancel()
        try:
            await tracker_task
        except asyncio.CancelledError:
            pass
        tracker = None
        tracker_task = None
        return "Aircraft tracking has stopped."
    return "No tracking in progress"

def get_tracker_status():
    global tracker
    if not tracker:
        return "No tracker initialized"
    return f"Tracker Status: {tracker.state or 'Unknown'}"
        
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
        
        if "start" in text:
            response_text = await start_tracking()
        elif "status" in text:
            response_text = get_tracker_status()
        elif "stop" in text:
            response_text = await stop_tracking()
        else:
            response_text = "Available commands: 'start' to begin tracking, 'status' to check current state, 'stop' to stop tracking"

        await post_to_slack(response_text)
        return JSONResponse(status_code=200, content={})
    except Exception as e:
        logger.error(f"Error processing Slack event: {e}")
        return JSONResponse(status_code=400, content={"error": "Invalid request"})