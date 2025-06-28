from datetime import datetime
import asyncio
import aiohttp
import time
import logging
from typing import Callable, Union, Awaitable, Optional, Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class PlaneMonitor:
    def __init__(self, headers: Dict[str, str], plane_hex: str, 
                 climb_threshold: float, descent_threshold: float, jump_run_altitude: float, hop_n_pop_altitude: float, 
                 runway_altitude: float, dz_lat: float, dz_lon: float, radius_nm: float, 
                 debug: bool, callback: Optional[Union[Callable[[str], None], Callable[[str], Awaitable[None]]]] = None):
        self.headers = headers
        self.plane_hex = plane_hex
        self.climb_threshold = climb_threshold
        self.descent_threshold = descent_threshold
        self.jump_run_altitude = jump_run_altitude
        self.hop_n_pop_altitude = hop_n_pop_altitude
        self.runway_altitude = runway_altitude
        self.dz_lat = dz_lat
        self.dz_lon = dz_lon
        self.radius_nm = radius_nm
        self.debug = debug
        self.state = None
        self.callback = callback
        self.state_changed = False  # Track if state has changed during this update
        self.tracking_active = True  # Flag to control the tracking loop
        self.descent_counter = 0  # Counter for consecutive descent readings
        self.ascent_counter = 0  # Counter for consecutive ascent readings
        self.plane_name = "Unknown aircraft"

    async def announce(self, state_msg: str) -> None:
        # logger.debug(f"[DEBUG] Announcing state: {state_msg}")
        message = f"[{datetime.now().strftime('%H:%M:%S %B %d, %Y')}] {state_msg}"
        logger.debug(message)
        if self.callback:
            logger.debug("[DEBUG] Callback is present, attempting to call")
            if asyncio.iscoroutinefunction(self.callback):
                logger.debug("[DEBUG] Calling async callback")
                await self.callback(message)
            else:
                logger.debug("[DEBUG] Calling sync callback")
                self.callback(message)

    async def get_plane_status(self) -> Optional[Dict[str, Any]]:
        hex_upper = self.plane_hex.upper()
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/icao/{hex_upper}"
        logger.info(f"Requesting data for plane {hex_upper} from URL: {url}")
        # logger.debug(f"Using headers: {self.headers}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers) as response:
                    logger.debug(f"Response status: {response.status}")
                    # logger.debug(f"Response headers: {dict(response.headers)}")
                    response.raise_for_status()
                    json_data = await response.json()
                    logger.debug(f"Raw API response: {json_data}")
                    
                    # Check if we got aircraft data
                    if not json_data.get('ac') or len(json_data['ac']) == 0:
                        if self.debug:
                            logger.debug(f"[DEBUG] No aircraft data found for {hex_upper}")
                        return None

                    # Get the first (and should be only) aircraft in the array
                    plane = json_data['ac'][0]
                    
                    # Return the processed aircraft data
                    result = {
                        "altitude": plane.get("alt_geom"),  # Using geometric altitude (GPS/WGS84 based)
                        "altitude_barometric": plane.get("alt_baro"),  # Keep barometric as reference
                        "aircraft_type": plane.get("t"),
                        "ground_speed": plane.get("gs"),
                        "ground_track": plane.get("track"),
                        "vertical_speed": plane.get("geom_rate"),
                        "latitude": plane.get("lat"),
                        "longitude": plane.get("lon")
                    }
                    # logger.debug(f"Processed plane data: {result}")
                    # if self.debug and result["altitude"] != result["altitude_barometric"]:
                    #     logger.debug(f"[DEBUG] Altitude difference: geom={result['altitude']} baro={result['altitude_barometric']}")
                    return result
            except aiohttp.ClientResponseError as e:
                if self.debug:
                    logger.debug(f"[DEBUG] API error {e.status}: {e.message}")
                return None
            except Exception as e:
                if self.debug:
                    logger.debug(f"[DEBUG] API request failed: {str(e)}")
                return None

    def set_state(self, new_state: str, message: str) -> None:
        if self.state != new_state:
            if self.debug:
                logger.info(f"[DEBUG] State transition: {self.state} → {new_state}")
                logger.info(f"[DEBUG] Reason: {message}")
            self.state = new_state
            self.state_changed = True  # Mark that we've changed state
            asyncio.create_task(self.announce(message))

    def update_state(self, data: Dict[str, Any]) -> None:
        altitude = data.get("altitude")  # Using geometric altitude
        altitude_barometric = data.get("altitude_barometric")
        vertical_speed = data.get("vertical_speed")
        ground_speed = data.get("ground_speed")
        ground_track = data.get("ground_track")
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        self.state_changed = False  # Reset state change tracker at start of update

        if altitude is not None:
            agl = altitude - self.runway_altitude
        else:
            agl = None

        # Log all relevant data for debugging
        logger.info(f"Current state: {self.state}")
        logger.info(f"Plane name: {self.plane_name}")
        logger.info(f"Altitude (geom/GPS): {altitude} ft")
        logger.info(f"Altitude (baro): {altitude_barometric} ft")
        logger.info(f"Geometric AGL: {agl} ft AGL")
        logger.info(f"Latitude: {latitude}")
        logger.info(f"Longitude: {longitude}")
        logger.info(f"Vertical Speed: {vertical_speed} ft/min")
        logger.info(f"Ground Speed: {ground_speed} kts")
        logger.info(f"Ground Track: {ground_track}°")

        # Check if we have enough data to determine state
        if agl is None and vertical_speed is None and ground_speed is None:
            logger.info("[DEBUG] Insufficient data to determine state")
            if self.state != "unknown":
                self.set_state("unknown", "[STATE] ❓ Unable to determine aircraft state - insufficient data")
            return

        # If we have ground speed and it's very low, plane is probably on ground
        if ground_speed is not None and ground_speed < 30:
            logger.info("[DEBUG] Ground speed indicates plane is on ground")
            if self.state != "landed":
                self.set_state("landed", f"[STATE] 🛬 Plane appears to be on ground (speed: {ground_speed} kts)")
            return

        # Check climbing state
        if agl is not None and self.climb_threshold <= agl <= self.jump_run_altitude:
            if vertical_speed is not None and vertical_speed > 300:
                self.ascent_counter += 1
                if self.ascent_counter >= 3:  # Three consecutive ascent readings
                    self.set_state("climbing", f"[STATE] ⬆️ {self.plane_name} load is climbing! Altitude: {agl} ft, Rate: {vertical_speed} ft/min")

        # Check jump run state - plane is at jump altitude, on the right heading, and past airport rd
        if agl is not None and abs(agl - self.jump_run_altitude) < 1000:
            if ground_track is not None and 270 <= ground_track <= 330:
                if longitude is not None and longitude < -105.155:
                    self.set_state("jump_run", f"[STATE] 🪂 {self.plane_name} jump run! Altitude: {agl} ft, Heading: {ground_track}°")
            else:
                self.set_state("at_altitude", f"[STATE] ✈️ Approaching jump altitude: {agl} ft")

        # Check hop and pop altitude
        if agl is not None and abs(agl - self.hop_n_pop_altitude) < 500:
            if ground_track is not None and 270 <= ground_track <= 330:
                if longitude is not None and longitude < -105.155:
                    self.set_state("hop_n_pop_run", f"[STATE] 🪂 {self.plane_name} hop and pop run! Altitude: {agl} ft, Heading: {ground_track}°")
            else:
                self.set_state("at_hop_n_pop_altitude", f"[STATE] ✈️ {self.plane_name} approaching hop and pop altitude: {agl} ft")

        # Check if descending
        if vertical_speed is not None and vertical_speed < self.descent_threshold:
            self.descent_counter += 1
            if self.descent_counter >= 3:  # Three consecutive descent readings
                self.set_state("descending", f"[STATE] ⬇️ {self.plane_name} plane descending at {vertical_speed} ft/min")
        else:
            self.descent_counter = 0  # Reset counter if not descending

        # Only set flying state if we haven't set any other state
        if not self.state and agl is not None:
            self.set_state("flying", f"[STATE] ✈️ {self.plane_name} Flying at {agl} ft")

    async def stop(self):
        # Stop the tracking loop gracefully
        self.tracking_active = False
        logger.info(f"Stop signal sent to tracker for {self.plane_hex} {self.plane_name}")

    async def track(self) -> None:
        logger.info("Starting tracking loop...")
        no_data_count = 0
        max_no_data = 5

        while self.tracking_active:
            logger.info("Fetching plane status...")
            data = await self.get_plane_status()
            
            if self.plane_hex == "acbc30":
                self.plane_name = "Mile-Hi King Air"
            elif self.plane_hex == "a06796":
                self.plane_name = "Mile-Hi Twin Otter"
            else:
                self.plane_name = "Unknown aircraft"
        
            if not data:
                logger.info(f"{self.plane_name} is on the ground or unavailable")
            else:
                logger.debug(f"[DEBUG] Status: {data}")

            if data:
                no_data_count = 0
                logger.debug("Updating state with received data...")
                self.update_state(data)
            else:
                no_data_count += 1
                logger.info(f"No data received. Count: {no_data_count}/{max_no_data}")
                self.set_state("landed", f"[STATE] 🛬 {self.plane_name} landed or transponder off")
                if no_data_count >= max_no_data:
                    await self.announce(f"[INFO] Stopping tracking {self.plane_name} after {max_no_data} no data responses")
                    break  # stop the loop

            await asyncio.sleep(10)
        
        logger.info(f"Tracking loop ended for {self.plane_name}")

if __name__ == '__main__':
    HEADERS = {
        "x-rapidapi-key": "YOUR_API_KEY_HERE", 
        "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
    }

    DEBUG = True

    async def main():
        test_plane = PlaneMonitor(
            headers=HEADERS,
            plane_hex="A65DDF",
            climb_threshold=5500,
            descent_threshold=-500,
            jump_run_altitude=12500,
            hop_n_pop_altitude=10500,
            runway_altitude=4950,
            dz_lat=40.16638,
            dz_lon=-105.16178,
            radius_nm=5,
            debug=DEBUG
        )

        await test_plane.track()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"[INFO] {__file__} Stopped by user input")
