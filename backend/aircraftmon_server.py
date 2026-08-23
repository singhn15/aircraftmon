from fastapi import FastAPI, Request, Body
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import asyncio
import aiohttp
import boto3
from botocore.exceptions import ClientError
from aircraftmon import PlaneMonitor
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG)
# Reduce boto3 logging noise
logging.getLogger("boto3").setLevel(logging.INFO)
logging.getLogger("botocore").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Initialize AWS clients
secrets = boto3.client("secretsmanager")

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite's default dev server port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global dict to store active trackers
active_trackers = {}


async def get_secret(secret_name: str) -> str:
    try:
        response = await asyncio.to_thread(
            secrets.get_secret_value, SecretId=secret_name
        )
        secret_string = response["SecretString"]

        # Handle JSON-formatted secrets
        try:
            secret_dict = json.loads(secret_string)
            return secret_dict.get(secret_name, "")
        except json.JSONDecodeError:
            # If not JSON, return as is
            return secret_string
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "DecryptionFailureException":
            logger.error(
                f"Secret {secret_name}: Unable to decrypt using provided KMS key"
            )
        elif error_code == "InternalServiceErrorException":
            logger.error(f"Secret {secret_name}: Internal service error in AWS")
        elif error_code == "InvalidParameterException":
            logger.error(f"Secret {secret_name}: Invalid parameter provided")
        elif error_code == "InvalidRequestException":
            logger.error(f"Secret {secret_name}: Invalid request to AWS")
        elif error_code == "ResourceNotFoundException":
            logger.error(f"Secret {secret_name} not found in Secrets Manager")
        else:
            logger.error(f"Unknown error retrieving secret {secret_name}: {e}")
        return ""


async def start_tracking(plane_hex: str):
    # Normalize hex to lowercase
    plane_hex = plane_hex.lower()
    
    # Check if already tracking
    if plane_hex in active_trackers:
        return f"Tracking already in progress for {plane_hex}!"

    # Get API key from Secrets Manager
    api_key = await get_secret("RAPIDAPI_KEY")
    if not api_key:
        return "API key not configured"

    logger.debug(
        f"Starting tracking for {plane_hex} with API key length: {len(api_key)}"
    )

    # Initialize the tracker with your configuration
    tracker = PlaneMonitor(
        headers={
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com",
        },
        plane_hex=plane_hex,
        climb_threshold=500,
        descent_threshold=-500,
        jump_run_altitude=12500,
        hop_n_pop_altitude=5500,
        runway_altitude=4950,
        dz_lat=40.16638,
        dz_lon=-105.16178,
        radius_nm=5,
        debug=True
    )

    # Start tracking in the background
    logger.debug("Creating tracking task...")
    task = asyncio.create_task(tracker.track())
    logger.debug("Tracking task created")

    # Store the tracker and task
    active_trackers[plane_hex] = (tracker, task)

    return "Started tracking aircraft!"


async def stop_tracking(plane_hex: str):
    # Normalize hex to lowercase
    plane_hex = plane_hex.lower()
    
    if plane_hex not in active_trackers:
        return "No tracking in progress"

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
    # Normalize hex to lowercase
    plane_hex = plane_hex.lower()
    
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
    return {"message": result}


class AircraftRequest(BaseModel):
    hex: str

@app.post("/aircraft")
async def get_aircraft(request: AircraftRequest):
    logger.debug(f"Incoming request: {request.hex}")
    result = await start_tracking(request.hex)
    logger.debug(f"Result: {result}")
    return result


@app.get("/")
async def root():
    logger.debug("hello, world! aircraftmon fastapi. port 4200")
    return {"message": "hello, world! aircraftmon fastapi. port 4200"}


@app.post("/stop/{plane_hex}")
async def stop_states(plane_hex: str):
    result = await stop_tracking(plane_hex)
    return {"message": result}


@app.get("/status/{plane_hex}")
async def get_status(plane_hex: str):
    # Normalize hex to lowercase
    plane_hex = plane_hex.lower()
    
    if plane_hex not in active_trackers:
        return JSONResponse(status_code=404, content={"error": "Aircraft not being tracked"})
    
    tracker, _ = active_trackers[plane_hex]
    data = await tracker.get_plane_status()
    
    if not data:
        return JSONResponse(status_code=404, content={"error": "No data available"})
    
    return {
        "state": tracker.state,
        "altitude": data.get("altitude"),
        "altitude_agl": data.get("altitude_agl"),
        "vertical_speed": data.get("vertical_speed"),
        "ground_speed": data.get("ground_speed"),
        "ground_track": data.get("ground_track"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude")
    }

