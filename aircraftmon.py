import requests
import time
from datetime import datetime

class PlaneMonitor:
    def __init__(self, headers, plane_hex, plane_name, climb_threshold, descent_threshold, jump_run_altitude, runway_altitude, dz_lat, dz_lon, radius_nm, debug):
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

    def announce(self, state_msg):
        print(f"[{datetime.now().strftime('%H:%M:%S %B %d, %Y')}] {state_msg}")

    def get_plane_status(self):
        url = f"https://adsbexchange-com1.p.rapidapi.com/v2/icao/{self.plane_hex}"
        r = requests.get(url, headers=self.headers)

        if r.status_code != 200:
            if self.debug:
                self.announce(f"[DEBUG] API error {r.status_code}: {r.text}")
            return None

        json_data = r.json()
        ac_list = json_data.get("ac")

        if not ac_list:
            if self.debug:
                self.announce(f"[DEBUG] {self.plane_name} is on the ground")
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

    def update_state(self, data):
        altitude = data.get("altitude")
        vertical_speed = data.get("vertical_speed")
        ground_track = data.get("ground_track")

        if altitude is None or vertical_speed is None:
            if self.state != "landed":
                self.state = "landed"
                self.announce("[STATE] 🛬 Plane landed or transponder off")
            return

        if altitude < self.climb_threshold and vertical_speed > 0:
            self.set_state("taxiing", "[STATE] 🛬 Plane is taxiing or taking off!")

        elif self.climb_threshold <= altitude <= self.jump_run_altitude:
            self.set_state("climbing", f"[STATE] 🛬 Load is climbing! Vertical speed: {vertical_speed}")

        elif vertical_speed < self.descent_threshold:
            self.set_state("descending", "⬇️ Plane descending after jump")

        elif abs(altitude - self.jump_run_altitude) < 1000 and 270 < ground_track < 330:
            self.set_state("jump_run", f"🪂 Jump run! Plane at {altitude} ft")

    def set_state(self, new_state, message):
        if self.state != new_state:
            if self.debug:
                self.announce(f"[DEBUG] Transition: {self.state} → {new_state}")
            self.state = new_state
            self.announce(message)

    def track(self):
        while True:
            data = self.get_plane_status()

            if self.debug:
                if not data:
                    self.announce(f"[DEBUG] {self.plane_name} is on the ground or unavailable")
                else:
                    self.announce(f"[DEBUG] Status: {data}")

            if data:
                self.update_state(data)
            else:
                self.set_state("landed", "[STATE] 🛬 Plane landed or transponder off")

            time.sleep(10)

if __name__ == '__main__':
    HEADERS = {
        "x-rapidapi-key": "bb7a790a58mshfeacd21c2074de8p1321ebjsneeb21ecf885b",
        "x-rapidapi-host": "adsbexchange-com1.p.rapidapi.com"
    }

    DEBUG = True

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

    try:
        test_plane.track()
    except KeyboardInterrupt:
        print(f"[INFO] {__file__} Stopped by user input")
