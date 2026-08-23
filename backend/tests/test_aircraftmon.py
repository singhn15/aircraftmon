import pytest
from aircraftmon import PlaneMonitor

@pytest.fixture
def monitor():
    return PlaneMonitor(
        headers = {},
        plane_hex="A65DDF",
        climb_threshold=5500,
        descent_threshold=-500,
        jump_run_altitude=12500,
        hop_n_pop_altitude=10500,
        runway_altitude=4950,
        dz_lat=40.16638,
        dz_lon=-105.16178,
        radius_nm=5,
        debug=False
    )

def test_landed(monitor):
    monitor.update_state({"altitude_agl": 0, "ground_speed": 0})
    assert monitor.state == "landed"

def test_unknown_state(monitor):
    monitor.update_state({"altitude_agl": None, "vertical_speed": None, "ground_speed": None})
    assert monitor.state == "unknown"

def test_climbing(monitor):
    monitor.update_state({"altitude_agl": 6000, "vertical_speed": 1550})
    monitor.update_state({"altitude_agl": 6500, "vertical_speed": 1600})
    monitor.update_state({"altitude_agl": 7000, "vertical_speed": 1650})
    assert monitor.state == "climbing"

def test_climbing_requires_three_readings(monitor):
    monitor.update_state({"altitude_agl": 6000, "vertical_speed": 1550})
    monitor.update_state({"altitude_agl": 6500, "vertical_speed": 1600})
    assert monitor.state != "climbing"

def test_jump_run(monitor):
    monitor.update_state({"altitude_agl": 12400, "ground_track": 290, "longitude": -105.20})
    assert monitor.state == "jump_run"

def test_at_altitude(monitor):
    monitor.update_state({"altitude_agl": 12400, "ground_track": 250, "longitude": -105.20})
    assert monitor.state == "at_altitude"

def test_hop_n_pop_run(monitor):
    monitor.update_state({"altitude_agl": 10400, "ground_track": 290, "longitude": -105.20})
    assert monitor.state == "hop_n_pop_run"

def test_at_hop_n_pop_altitude(monitor):
    monitor.update_state({"altitude_agl": 10400, "ground_track": 180, "longitude": -105.20})
    assert monitor.state == "at_hop_n_pop_altitude"

def test_descending(monitor):
    monitor.update_state({"altitude_agl": 8000, "vertical_speed": -600})
    monitor.update_state({"altitude_agl": 7500, "vertical_speed": -650})
    monitor.update_state({"altitude_agl": 7000, "vertical_speed": -700})
    assert monitor.state == "descending"

def test_descending_requires_three_readings(monitor):
    monitor.update_state({"altitude_agl": 8000, "vertical_speed": -600})
    monitor.update_state({"altitude_agl": 7500, "vertical_speed": -650})
    assert monitor.state != "descending"

def test_flying_default(monitor):
    monitor.update_state({"altitude_agl": 3000, "vertical_speed": 100})
    assert monitor.state == "flying"

def test_set_state_no_repeat(monitor):
    monitor.update_state({"altitude_agl": 0, "ground_speed": 0})
    assert monitor.state == "landed"
    monitor.state_changed = False
    monitor.update_state({"altitude_agl": 0, "ground_speed": 0})
    assert monitor.state_changed == False