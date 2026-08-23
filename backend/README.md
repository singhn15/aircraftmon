# Aircraft Monitoring System (`aircraftmon`)

A backend service that tracks specific aircraft via their ADS-B transponder data and
classifies their flight phase in real time. It was built for a skydiving dropzone
(Mile-Hi, near Longmont, CO) to answer the question *"where is the jump plane and what
is it doing right now?"* — e.g. climbing to altitude, on jump run, or back on the
ground.

The service exposes a small HTTP API (FastAPI) that a separate Vue frontend
(`~/Projects/aircraftmon-frontend`) polls for live aircraft state. An older Slack
notification path exists in the code but is **no longer used** (see
[Legacy: Slack integration](#legacy-slack-integration)).

---

## Table of contents

- [Architecture overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [AWS Secrets Manager configuration](#aws-secrets-manager-configuration)
- [Build & run](#build--run)
- [HTTP API reference](#http-api-reference)
- [Code reference](#code-reference)
  - [`aircraftmon.py` — `PlaneMonitor`](#aircraftmonpy--planemonitor)
  - [`aircraftmon_fastapi.py` — HTTP layer](#aircraftmon_fastapipy--http-layer)
- [Domain concepts & tuning](#domain-concepts--tuning)
- [Dependencies — what each is for](#dependencies--what-each-is-for)
- [Known issues & gotchas](#known-issues--gotchas)
- [Legacy: Slack integration](#legacy-slack-integration)

---

## Architecture overview

```
                 ┌─────────────────────────┐
   HTTP (4200)   │   aircraftmon_fastapi    │      AWS Secrets Manager (us-east-2)
 ◄──────────────►│   FastAPI app            │◄──── RAPIDAPI_KEY, SLACK_WEBHOOK_URL
   Vue frontend  │   - endpoint handlers    │
                 │   - active_trackers{}    │
                 │   - get_secret()         │
                 └───────────┬─────────────┘
                             │ creates one per tracked hex
                             ▼
                 ┌─────────────────────────┐
                 │   aircraftmon.PlaneMonitor │     ADS-B Exchange (RapidAPI)
                 │   - async track() loop   │────► GET /v2/icao/{hex}
                 │   - update_state()       │◄──── live telemetry JSON
                 │   - state machine        │
                 └─────────────────────────┘
```

- **`aircraftmon.py`** is the pure tracking/state-machine engine. It has no web
  framework or AWS dependencies and can be run standalone (`python aircraftmon.py`)
  for local testing.
- **`aircraftmon_fastapi.py`** is the HTTP/orchestration layer. It owns secrets,
  manages the lifecycle of one `PlaneMonitor` per tracked aircraft, and exposes the
  REST API the frontend consumes.

One `PlaneMonitor` instance == one tracked aircraft == one background `asyncio` task.
They are held in the module-global `active_trackers` dict, keyed by lowercase hex.

---

## Prerequisites

| Requirement | Version / notes |
|---|---|
| Python | 3.14 (pinned in `Pipfile`; `pyenv` recommended) |
| pipenv | Used for dependency + virtualenv management |
| AWS credentials | A profile with `secretsmanager:GetSecretValue` on the two secrets below, in **`us-east-2`** |
| RapidAPI account | Subscription to the **ADS-B Exchange** API (`adsbexchange-com1.p.rapidapi.com`) |

> **Region matters.** The boto3 Secrets Manager client is hardcoded to `us-east-2`
> in `aircraftmon_fastapi.py`. The secrets must live there. If you move regions,
> update the `boto3.client(...)` call.

AWS auth is resolved by the standard boto3 credential chain (env vars, shared
`~/.aws/credentials`, instance role, etc.). No region env var is required because the
client sets the region explicitly.

---

## AWS Secrets Manager configuration

The app reads two secrets at request time (not at startup). **They are stored in two
different shapes**, and `get_secret()` handles both:

| Secret name | Stored as | Shape | Consumed by |
|---|---|---|---|
| `RAPIDAPI_KEY` | **plain string** | the raw API key | `start_tracking()` |
| `SLACK_WEBHOOK_URL` | **JSON object** | `{"webhook": "https://hooks.slack.com/..."}` | `post_to_slack()` (legacy, unused) |

`get_secret()` first attempts `json.loads()`; if that fails (as it does for the
plain-string `RAPIDAPI_KEY`) it returns the raw string. For `SLACK_WEBHOOK_URL` it
parses the JSON and returns the `webhook` field.

To create / update the API key secret:

```bash
aws secretsmanager create-secret \
  --region us-east-2 \
  --name RAPIDAPI_KEY \
  --secret-string 'your-rapidapi-key-here'
```

(Only `RAPIDAPI_KEY` is required for current functionality; `SLACK_WEBHOOK_URL` is
only needed if you re-enable the Slack path.)

---

## Build & run

Dependencies are managed with **pipenv** (`Pipfile` / `Pipfile.lock`). The version
pins were loosened to `*` so wheels resolve cleanly on Python 3.14.

```bash
# 1. Install dependencies into a managed virtualenv
cd ~/Projects/aircraftmon
pipenv install

# 2a. Run via pipenv (no manual activation)
pipenv run uvicorn aircraftmon_fastapi:app --host 0.0.0.0 --port 4200

# 2b. ...or activate the shell first, then run uvicorn directly
pipenv shell
uvicorn aircraftmon_fastapi:app --host 0.0.0.0 --port 4200
```

The server listens on **port 4200**, which is the URL the frontend (`API_BASE_URL`)
hardcodes. CORS is configured to allow `http://localhost:5173` (Vite's default dev
port).

Smoke test:

```bash
curl http://localhost:4200/                         # → {"message":"hello, world! ..."}
curl -X POST http://localhost:4200/aircraft \
     -H 'Content-Type: application/json' \
     -d '{"hex":"acbc30"}'                           # → "Started tracking aircraft!"
curl http://localhost:4200/status/acbc30            # → telemetry, or 404 if not airborne
```

> A `"Started tracking aircraft!"` response confirms the RapidAPI secret loaded
> correctly. `"No data available"` simply means the aircraft is on the ground / has
> its transponder off — that is normal, not an error.

### Logging

`logging.json` defines a JSON-formatted config with console output and a midnight
`TimedRotatingFileHandler` (7-day retention, `aircraftmon_fastapi.json.log`).
**Note:** this file is currently *not wired up* — `aircraftmon_fastapi.py` calls
`logging.basicConfig(level=logging.DEBUG)` instead. To activate structured logging,
load `logging.json` via `logging.config.dictConfig()` at startup.

---

## HTTP API reference

| Method | Path | Body | Purpose |
|---|---|---|---|
| `GET` | `/` | — | Health check. |
| `POST` | `/aircraft` | `{"hex": "<icao_hex>"}` | Start a background tracker for the aircraft. Idempotent — returns a message if already tracking. |
| `GET` | `/status/{plane_hex}` | — | Current state + a fresh telemetry snapshot. `404` if not tracked or no data available. |
| `POST` | `/stop` | Slack-event-shaped JSON (see below) | Stop a tracker. Parses a Slack `event.text` of the form `@aircraftmon_app stop <hex>`. **Legacy shape.** |
| `POST` | `/clear` | — | Stop and remove **all** active trackers. |

`/status/{plane_hex}` returns:

```json
{
  "state": "climbing",
  "altitude": 12500,
  "altitude_agl": 7550,
  "vertical_speed": 850,
  "ground_speed": 110,
  "ground_track": 295,
  "latitude": 40.17,
  "longitude": -105.18
}
```

> **Note on `/stop`:** its request shape is a holdover from the Slack integration
> (it parses a fake Slack event payload). The frontend currently calls `/stop/{hex}`,
> which does **not** match this route — stop-from-UI is effectively broken and should
> be reworked into a clean `POST /stop {"hex": ...}` or `DELETE /aircraft/{hex}`
> endpoint. See [Known issues](#known-issues--gotchas).

---

## Code reference

### `aircraftmon.py` — `PlaneMonitor`

The tracking engine and flight-phase state machine. One instance per aircraft.

**Constructor parameters** (all tuning lives here — see
[Domain concepts](#domain-concepts--tuning)):

| Param | Meaning |
|---|---|
| `headers` | RapidAPI auth headers (`x-rapidapi-key`, `x-rapidapi-host`). |
| `plane_hex` | ICAO 24-bit hex of the target aircraft. |
| `climb_threshold` | Lower AGL bound for the "climbing" phase. |
| `descent_threshold` | Vertical-speed (ft/min) below which the plane is "descending" (negative). |
| `jump_run_altitude` | Target jump altitude (AGL ft). |
| `hop_n_pop_altitude` | Lower-altitude jump-run altitude (AGL ft). |
| `runway_altitude` | Field elevation (MSL ft); subtracted from barometric altitude to derive AGL. |
| `dz_lat` / `dz_lon` | Dropzone coordinates, used for distance-from-DZ calc. |
| `radius_nm` | Intended geofence radius (currently informational only). |
| `debug` | Verbose state-transition logging. |

**Methods:**

| Method | What it does |
|---|---|
| `get_plane_status()` | Async GET to ADS-B Exchange `/v2/icao/{HEX}`. Returns a normalized dict (altitude, AGL, type, ground speed/track, vertical speed, lat/lon) or `None` on no-data / error. AGL is derived as `alt_baro - runway_altitude`, with `"ground"` mapped to `0`. |
| `update_state(data)` | The state machine core. Reads the telemetry dict and transitions through `unknown → landed → climbing → at_altitude/jump_run → at_hop_n_pop_altitude/hop_n_pop_run → descending → flying`. Uses consecutive-reading counters (`ascent_counter`, `descent_counter`, threshold 3) to debounce noisy readings. |
| `set_state(new_state, message)` | Transition guard — only fires (and schedules `announce`) when the state actually changes, preventing duplicate notifications. |
| `announce(state_msg)` | Timestamps the message and invokes `callback` (await if coroutine). No-op when `callback` is `None`. |
| `track()` | The main async loop. Resolves a human-readable `plane_name` from known hex codes, then polls every 10s, logs distance-from-DZ, updates state, and self-terminates after `max_no_data` (5) consecutive empty responses. |
| `stop()` | Sets `tracking_active = False` to break the loop gracefully. |

**Jump-run detection logic** (the domain heart of `update_state`): a "jump run" is
declared only when the aircraft is *near jump altitude* **and** *on a heading of
270–330°* **and** *west of longitude −105.155* (past the airport, over the spot).
"Hop and pop" is the same logic at the lower `hop_n_pop_altitude`.

**Standalone run:** the `if __name__ == "__main__"` block constructs a `PlaneMonitor`
with hardcoded test config and runs `track()` — handy for engine testing without the
web layer. (You must paste a real key into `HEADERS` first.)

### `aircraftmon_fastapi.py` — HTTP layer

| Function | What it does |
|---|---|
| `get_secret(secret_name)` | Fetches a secret from AWS Secrets Manager (off-thread via `asyncio.to_thread`). Handles both JSON and plain-string secrets; maps AWS `ClientError` codes to log messages; returns `""` on failure. |
| `start_tracking(plane_hex)` | Normalizes hex, dedupes against `active_trackers`, loads `RAPIDAPI_KEY`, constructs a `PlaneMonitor` with the dropzone config, launches `track()` as a background task, and registers it. |
| `stop_tracking(plane_hex)` | Signals the tracker to stop, waits up to 2s for graceful shutdown, and removes it from `active_trackers`. |
| `get_tracker_status(plane_hex)` | Returns active/inactive for a hex. |
| `clear_trackers()` | Stops and removes every tracker. |

**Module-level state:** `active_trackers: dict[str, tuple[PlaneMonitor, asyncio.Task]]`.
This is in-process and not persisted — restarting the server drops all tracking state.

---

## Domain concepts & tuning

- **ICAO hex codes** uniquely identify aircraft on ADS-B. Known fleet:
  - `acbc30` → Mile-Hi King Air
  - `a06796` → Mile-Hi Twin Otter
  - Names are resolved in `track()`; unknown hexes get `"Unknown aircraft"`.
- **AGL vs barometric.** The API returns barometric altitude MSL (`alt_baro`).
  AGL is computed by subtracting `runway_altitude` (field elevation, 4950 ft for
  Mile-Hi). All state thresholds are expressed in **AGL**.
- **Current production thresholds** (set in `start_tracking`): `climb_threshold=500`,
  `descent_threshold=-500`, `jump_run_altitude=12500`, `hop_n_pop_altitude=5500`,
  `runway_altitude=4950`. The geofence (`radius_nm=5`) is computed and logged but not
  yet used to gate state.
- **The `longitude < -105.155` check** is a hardcoded proxy for "past the airport."
  This is geometry specific to Mile-Hi and would need to change for another dropzone.

---

## Dependencies — what each is for

| Package | Why it's here |
|---|---|
| **fastapi** | The HTTP framework / routing layer for the REST API. |
| **uvicorn** | ASGI server that actually runs the FastAPI app. |
| **aiohttp** | Async HTTP client for non-blocking calls to ADS-B Exchange (and Slack). Chosen over `requests` so polling doesn't block the event loop. |
| **boto3 / botocore** | AWS SDK — used solely to read secrets from Secrets Manager. |
| **pydantic** | Request-body validation/parsing (`AircraftRequest` model). Comes transitively with FastAPI but pinned explicitly. |
| **python-dotenv** | Local `.env` loading. Present for convenience; secrets currently come from AWS, not `.env`. |
| **python-json-logger** | JSON log formatter referenced by `logging.json` (structured logs). Not active until `dictConfig` is wired up. |

Standard-library modules of note: **`asyncio`** (concurrency — one task per tracker),
**`math`** (haversine), **`datetime`** (announce timestamps), **`logging`**, **`json`**.

---

## Known issues & gotchas

These are live papercuts a maintainer should know about:

1. **Frontend stop is broken.** The Vue app calls `POST /stop/{hex}`, but the backend
   only defines `POST /stop` expecting a Slack-event body. Stopping from the UI does
   not work. Recommend adding a clean `DELETE /aircraft/{hex}` (or `POST /stop`
   accepting `{"hex": ...}`) and updating the frontend.
2. **In-memory state only.** `active_trackers` is lost on restart; there is no
3. **`logging.json` is unused** — see [Logging](#logging).