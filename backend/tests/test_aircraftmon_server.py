import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from aircraftmon_server import app, active_trackers


@pytest.fixture(autouse=True)
def clear_trackers():
    active_trackers.clear()
    yield
    active_trackers.clear()


@pytest.fixture
def client():
    return TestClient(app)


# GET /

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "hello, world! aircraftmon fastapi. port 4200"}


# POST /aircraft

def test_start_tracking(client):
    with patch("aircraftmon_server.get_secret", new=AsyncMock(return_value="fake-api-key")), \
         patch("aircraftmon.PlaneMonitor.track", new=AsyncMock()):
        response = client.post("/aircraft", json={"hex": "acbc30"})
    assert response.status_code == 200
    assert response.json() == "Started tracking aircraft!"

def test_start_tracking_duplicate(client):
    with patch("aircraftmon_server.get_secret", new=AsyncMock(return_value="fake-api-key")), \
         patch("aircraftmon.PlaneMonitor.track", new=AsyncMock()):
        client.post("/aircraft", json={"hex": "acbc30"})
        response = client.post("/aircraft", json={"hex": "acbc30"})
    assert "Tracking already in progress" in response.json()

def test_start_tracking_no_api_key(client):
    with patch("aircraftmon_server.get_secret", new=AsyncMock(return_value="")):
        response = client.post("/aircraft", json={"hex": "acbc30"})
    assert response.json() == "API key not configured"


# GET /status/{hex}

def test_status_not_tracking(client):
    response = client.get("/status/acbc30")
    assert response.status_code == 404

def test_status_no_data(client):
    with patch("aircraftmon_server.get_secret", new=AsyncMock(return_value="fake-api-key")), \
         patch("aircraftmon.PlaneMonitor.track", new=AsyncMock()), \
         patch("aircraftmon.PlaneMonitor.get_plane_status", new=AsyncMock(return_value=None)):
        client.post("/aircraft", json={"hex": "acbc30"})
        response = client.get("/status/acbc30")
    assert response.status_code == 404

def test_status_with_data(client):
    fake_telemetry = {
        "altitude": 17450,
        "altitude_agl": 12500,
        "vertical_speed": 0,
        "ground_speed": 90,
        "ground_track": 295,
        "latitude": 40.17,
        "longitude": -105.20,
    }
    with patch("aircraftmon_server.get_secret", new=AsyncMock(return_value="fake-api-key")), \
         patch("aircraftmon.PlaneMonitor.track", new=AsyncMock()), \
         patch("aircraftmon.PlaneMonitor.get_plane_status", new=AsyncMock(return_value=fake_telemetry)):
        client.post("/aircraft", json={"hex": "acbc30"})
        response = client.get("/status/acbc30")
    assert response.status_code == 200
    data = response.json()
    assert data["altitude_agl"] == 12500
    assert data["ground_track"] == 295
    assert data["latitude"] == 40.17


# POST /clear

def test_clear_no_trackers(client):
    response = client.post("/clear")
    assert response.status_code == 200
    assert "No active trackers" in response.json()["message"]

def test_clear_with_trackers(client):
    with patch("aircraftmon_server.get_secret", new=AsyncMock(return_value="fake-api-key")), \
         patch("aircraftmon.PlaneMonitor.track", new=AsyncMock()):
        client.post("/aircraft", json={"hex": "acbc30"})
    with patch("aircraftmon.PlaneMonitor.stop", new=AsyncMock()):
        response = client.post("/clear")
    assert response.status_code == 200
    assert len(active_trackers) == 0
