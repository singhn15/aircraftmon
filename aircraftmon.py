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
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/icao/{self.plane_hex}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers) as response:
                    response.raise_for_status()  # This will raise an exception if status != 200
                    json_data = await response.json()
                    ac_list = json_data.get("ac")

                    if not ac_list:
                        if self.debug:
                            logger.debug(f"[DEBUG] {self.plane_name} is on the ground")
                        return None

                    plane = ac_list[0]
                    altitude = plane.get("alt_geom")

                    return {
                        "altitude": altitude if isinstance(altitude, (int, float)) else None,
                        "aircraft_type": plane.get("t"),
                        "ground_speed": plane.get("gs"),
                        "ground_track": plane.get("track"),
                        "vertical_speed": plane.get("geom_rate"),
                        "latitude": plane.get("lat"),
                        "longitude": plane.get("lon")
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
        ground_track = data.get("ground_track")

        if altitude is None or vertical_speed is None:
            if self.state != "landed":
                self.state = "landed"
                asyncio.create_task(self.announce("[STATE] 🛬 Plane landed or transponder off"))
            return

        if altitude < self.climb_threshold and vertical_speed > 0:
            self.set_state("taxiing", "[STATE] 🛬 Plane is taxiing or taking off!")

        elif self.climb_threshold <= altitude <= self.jump_run_altitude:
            self.set_state("climbing", f"[STATE] 🛬 Load is climbing! Vertical speed: {vertical_speed}")

        elif vertical_speed < self.descent_threshold:
            self.set_state("descending", "[STATE] ⬇️ Plane descending after jump")

        elif abs(altitude - self.jump_run_altitude) < 1000 and ground_track is not None and 270 < ground_track < 330:
            self.set_state("jump_run", f"[STATE] 🪂 Jump run! Plane at {altitude} ft")

    def set_state(self, new_state: str, message: str) -> None:
        if self.state != new_state:
            if self.debug:
                asyncio.create_task(self.announce(f"[DEBUG] Transition: {self.state} → {new_state}"))
            self.state = new_state
            asyncio.create_task(self.announce(message))

    async def track(self) -> None:
        no_data_count = 0
        max_no_data = 5

        while True:
            data = await self.get_plane_status()

            if self.debug:
                if not data:
                    await self.announce(f"[DEBUG] {self.plane_name} is on the ground or unavailable")
                else:
                    await self.announce(f"[DEBUG] Status: {data}")

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
