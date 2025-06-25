from datetime import datetime
import asyncio
import aiohttp
import logging
from typing import Callable, Union, Awaitable, Optional, Dict, Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

class PlaneMonitor:
    def __init__(self, headers: Dict[str, str], plane_hex: str, plane_name: str, 
                 climb_threshold: float, descent_threshold: float, jump_run_altitude: float, 
                 runway_altitude: float, dz_lat: float, dz_lon: float, radius_nm: float, 
                 debug: bool, callback: Optional[Union[Callable[[str], None], Callable[[str], Awaitable[None]]]] = None):
        self.headers = headers
        self.plane_hex = plane_hex
        self.plane_name = plane_name
        self.climb_threshold = climb_threshold
        self.descent_threshold = descent_threshold
        self.jump_run_altitude = jump_run_altitude
        self.runway_altitude = runway_altitude
        self.dz_lat = dz_lat
        self.dz_lon = dz_lon
        self.radius_nm = radius_nm
        self.debug = debug
        self.state = None
        self.callback = callback

    async def announce(self, state_msg: str) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S %B %d, %Y')}] {state_msg}")
        if self.callback:
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(state_msg)
            else:
                self.callback(state_msg)

    async def get_plane_status(self) -> Optional[Dict[str, Any]]:
        hex_upper = self.plane_hex.upper()
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/hex/{hex_upper}"
        logger.debug(f"Requesting data for plane {hex_upper} from URL: {url}")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers) as response:
                    logger.debug(f"Response headers: {dict(response.headers)}")
                    response.raise_for_status()  # This will raise an exception if status != 200
                    json_data = await response.json()
                    logger.debug(f"Raw API response: {json_data}")
                    
                    # Check if we got aircraft data (hex field should be present)
                    if not json_data.get('hex'):
                        if self.debug:
                            logger.debug(f"[DEBUG] No aircraft data found for {hex_upper}")
                        return None

                    # Return the data directly since it's a single aircraft response
                    return {
                        "altitude": json_data.get("alt_geom"),
                        "aircraft_type": json_data.get("t"),
                        "ground_speed": json_data.get("gs"),
                        "ground_track": json_data.get("track"),
                        "vertical_speed": json_data.get("baro_rate"),
                        "latitude": json_data.get("lat"),
                        "longitude": json_data.get("lon")
                    }
            except Exception as e:
                if self.debug:
                    if isinstance(e, aiohttp.ClientResponseError):
                        logger.debug(f"[DEBUG] API error {e.status}: {e.message}")
                    else:
                        logger.debug(f"[DEBUG] API request failed: {e}")
                return None

    def update_state(self, data: Dict[str, Any]) -> None:
        altitude = data.get("altitude")
        vertical_speed = data.get("vertical_speed")
        ground_speed = data.get("ground_speed")
        ground_track = data.get("ground_track")

        # Log all relevant data for debugging
        if self.debug:
            logger.debug(f"[DEBUG] Current state: {self.state}")
            logger.debug(f"[DEBUG] Altitude: {altitude} ft")
            logger.debug(f"[DEBUG] Vertical Speed: {vertical_speed} ft/min")
            logger.debug(f"[DEBUG] Ground Speed: {ground_speed} kts")
            logger.debug(f"[DEBUG] Ground Track: {ground_track}°")

        # Check if we have enough data to determine state
        if altitude is None and vertical_speed is None and ground_speed is None:
            if self.state != "unknown":
                self.set_state("unknown", "[STATE] ❓ Unable to determine aircraft state - insufficient data")
            return

        # If we have ground speed and it's very low, plane is probably on ground
        if ground_speed is not None and ground_speed < 30:
            if self.state != "landed":
                self.set_state("landed", f"[STATE] 🛬 Plane appears to be on ground (speed: {ground_speed} kts)")
            return

        # If we have altitude and it's below threshold, check if taking off
        if altitude is not None and altitude < self.climb_threshold:
            if vertical_speed is not None and vertical_speed > 300:  # More than 300 ft/min climb
                self.set_state("taking_off", f"[STATE] 🛫 Plane is taking off! Climbing at {vertical_speed} ft/min")
            elif self.state != "landed":
                self.set_state("landed", f"[STATE] 🛬 Plane at low altitude: {altitude} ft")
            return

        # Check climbing state
        if self.climb_threshold <= altitude <= self.jump_run_altitude:
            if vertical_speed is not None and vertical_speed > 300:
                self.set_state("climbing", f"[STATE] ⬆️ Load is climbing! Altitude: {altitude} ft, Rate: {vertical_speed} ft/min")
            return

        # Check jump run state - plane is at jump altitude and on the right heading
        if abs(altitude - self.jump_run_altitude) < 1000:
            if ground_track is not None and 270 <= ground_track <= 330:
                self.set_state("jump_run", f"[STATE] 🪂 Jump run! Altitude: {altitude} ft, Heading: {ground_track}°")
            else:
                self.set_state("at_altitude", f"[STATE] ✈️ At jump altitude: {altitude} ft")
            return

        # Check if descending
        if vertical_speed is not None and vertical_speed < self.descent_threshold:
            self.set_state("descending", f"[STATE] ⬇️ Plane descending at {vertical_speed} ft/min")
            return

        # If we get here and have altitude but don't match other conditions
        if altitude is not None:
            self.set_state("flying", f"[STATE] ✈️ Flying at {altitude} ft")

    def set_state(self, new_state: str, message: str) -> None:
        if self.state != new_state:
            if self.debug:
                logger.debug(f"[DEBUG] State transition: {self.state} → {new_state}")
                logger.debug(f"[DEBUG] Reason: {message}")
            self.state = new_state
            asyncio.create_task(self.announce(message))

    async def track(self) -> None:
        no_data_count = 0
        max_no_data = 5

        while True:
            data = await self.get_plane_status()

            if self.debug:
                if not data:
                    # await self.announce(f"[DEBUG] {self.plane_name} is on the ground or unavailable")
                    logger.debug(f"[DEBUG] {self.plane_name} is on the ground or unavailable")
                else:
                    # await self.announce(f"[DEBUG] Status: {data}")
                    logger.debug(f"[DEBUG] Status: {data}")

            if data:
                no_data_count = 0
                self.update_state(data)
            else:
                no_data_count += 1
                self.set_state("landed", "[STATE] 🛬 Plane landed or transponder off")
                if no_data_count >= max_no_data:
                    await self.announce(f"[INFO] Stopping tracking after {max_no_data} no data responses")
                    break  # stop the loop

            await asyncio.sleep(10)

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
            plane_name="random plane for testing",
            climb_threshold=5300,
            descent_threshold=-500,
            jump_run_altitude=12500,
            runway_altitude=5000,
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
