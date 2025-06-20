import os
import threading
from flask import Flask, request, jsonify, Response
import requests
from dotenv import load_dotenv
from aircraftmon import PlaneMonitor

# Load environment variables
load_dotenv()

app = Flask(__name__)

# === Config from environment ===
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
TRACKER_THREADS = {}

# === Plane and Dropzone settings ===
PLANES = {
    "king_air": {
        "hex": "ACBC30",
        "name": "Mile-Hi Skydiving King Air"
    },
    "twin_otter": {
        "hex": "A06796",
        "name": "Mile-Hi Skydiving Twin Otter"
    }
}

DZ_SETTINGS = {
    "mile_hi": {
        "dz_lat": 40.16638,
        "dz_lon": -105.16178,
        "climb_threshold": 5300,
        "jump_run_altitude": 12500,
        "descent_threshold": -500,
        "runway_altitude": 5000
    }
}

# === Helper to post to Slack ===
def post_to_slack(text):
    if SLACK_WEBHOOK_URL:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text})

# === Background tracker thread ===
def run_tracker_thread(plane_hex, plane_name, dz_config):
    tracker = PlaneMonitor(
        headers={
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
        },
        plane_hex=plane_hex,
        plane_name=plane_name,
        climb_threshold=dz_config["climb_threshold"],
        descent_threshold=dz_config["descent_threshold"],
        jump_run_altitude=dz_config["jump_run_altitude"],
        runway_altitude=dz_config["runway_altitude"],
        dz_lat=dz_config["dz_lat"],
        dz_lon=dz_config["dz_lon"],
        radius_nm=5,
        debug=True
    )
    tracker.track()

# === Slack Event Handler ===
@app.route("/slack/events", methods=["POST"])
def slack_event():
    data = request.get_json()
    print("[DEBUG] Incoming payload:", data)

    # Handle Slack URL verification
    if data.get("type") == "url_verification":
        return Response(data["challenge"], status=200, mimetype='text/plain')

    event = data.get("event", {})
    if event.get("type") == "message" and "bot_id" not in event:
        text = event.get("text", "").lower()
        print(f"[DEBUG] Message text: {text}")

        if "start" in text:
            parts = text.split()
            plane_key = next((p.split("=")[1] for p in parts if p.startswith("plane=")), None)
            dz_key = next((p.split("=")[1] for p in parts if p.startswith("dz=")), None)

            print(f"[DEBUG] plane_key: {plane_key}, dz_key: {dz_key}")

            if plane_key not in PLANES or dz_key not in DZ_SETTINGS:
                post_to_slack("❌ Invalid plane or DZ key")
                return Response("OK", status=200)

            key = f"{plane_key}:{dz_key}"
            if key in TRACKER_THREADS:
                post_to_slack(f"🔄 Already tracking {plane_key} at {dz_key}")
            else:
                thread = threading.Thread(
                    target=run_tracker_thread,
                    args=(
                        PLANES[plane_key]["hex"],
                        PLANES[plane_key]["name"],
                        DZ_SETTINGS[dz_key]
                    ),
                    daemon=True
                )
                TRACKER_THREADS[key] = thread
                thread.start()
                post_to_slack(f"✅ Started tracking {plane_key} at {dz_key}")

        elif "stop" in text:
            TRACKER_THREADS.clear()  # TODO: Graceful stop
            post_to_slack("🛑 Stopped all trackers (manual restart required)")

        elif "status" in text:
            if not TRACKER_THREADS:
                post_to_slack("❌ No active tracking threads")
            else:
                active = ", ".join(TRACKER_THREADS.keys())
                post_to_slack(f"✅ Currently tracking: {active}")

    return Response("OK", status=200)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
