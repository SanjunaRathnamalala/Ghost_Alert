# Ghost_Alert backend (v1 design, demo version)

This follows the v1 system design. Some parts are cut for the 2-day demo (see the end).
Your engine files `engine/pattern_engine.py` and `engine/acs_engine.py` are **unchanged**.

## Folder map
```
app/
  config.py    settings from .env
  packets.py   binary LoRa packet decoder + encoder (design topic 2a)
  convert.py   raw -> tilt angle, moisture index (2.3)
  store.py     InfluxDB (and an in-memory version for tests / fallback)
  pcha.py      runs your engine at any time "now"; adds no_data (4.1), skips retired neighbours (3.15)
  events.py    event life cycle (4b): open, raise, lower after hold time, ready to close
  worker.py    PCHA queue + safety round (offline, reminders, wildlife auto-close)
  ingest.py    POST /api/v1/ingest  (used by the ESP32 gateway)
  api.py       endpoints for the dashboard
  notify.py    Telegram alerts
  schema.sql   7 PostgreSQL tables
engine/        your PCHA files (unchanged)
scripts/seed_demo.py   registers the demo nodes (2 real + 3 VIRTUAL neighbours)
tools/fake_gateway.py  sends real binary packets without hardware
tests/         31 automatic tests
```

## Set up (about 20 minutes)
1. **Change the leaked secrets first.** The old InfluxDB token, Postgres password `1111` and
   admin password `ghostadmin2026` were written in code. Do not reuse them.
2. `cp .env.example .env` and fill in every `CHANGE_ME` with new random values.
3. Databases: `docker compose up -d` (or use your existing PostgreSQL / InfluxDB, but with a
   **new empty bucket** `ghost_alert_v1`: the old bucket has integer fields that clash).
4. Python:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```
5. Register demo nodes: `python -m scripts.seed_demo`
6. Start: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
   (`0.0.0.0` so the ESP32 on your Wi-Fi can reach it: use your laptop's IP address.)
7. Check: open http://localhost:8000/api/v1/health and http://localhost:8000/docs

## Test without hardware
```
python -m tools.fake_gateway boot      --radio 1 --counter 1
python -m tools.fake_gateway heartbeat --radio 1 --counter 2 --tilt 0.8 --moisture 450
python -m tools.fake_gateway pir       --radio 2 --counter 1 --triggers 2
```

## What the ESP32 gateway must send
`POST http://<laptop-ip>:8000/api/v1/ingest` with header `X-Gateway-Key: <GATEWAY_API_KEY>`
```json
{"gateway_id": "esp32-gw-01", "received_at": "2026-10-07T10:15:30Z", "clock_ok": true,
 "rssi": -87, "snr": 7.5, "payload_hex": "<the LoRa packet bytes as hex>"}
```
`received_at` = the time the radio heard the packet (from NTP). If unknown, leave it out.

## Packet format (little-endian): the node firmware must match this
| Part | Bytes |
|---|---|
| Header | `(1<<4)\|type` (1), radio ID (2), boot number (2), counter (2) |
| Seal | 4 zero bytes at the end |

| Type | Body | Total |
|---|---|---|
| 1 boot | firmware ver (1), reset reason MCUSR (1), node type 1=landslide 2=wildlife (1) | 14 |
| 2 heartbeat | accel x,y,z int16 in 0.1 mg (6), 5x moisture ADC uint16 (10), battery mV (2), temp int16 0.1 °C (2), flags (1) | 32 |
| 3 burst | accel x,y,z after movement (6), peak change mg (2), duration s (1), flags (1) | 21 |
| 4 PIR event | triggers (1), battery mV (2), flags (1) | 15 |
| 5 PIR heartbeat | triggers since last (2), battery mV (2), flags (1) | 16 |

Flags: bit0 soil sensor error, bit1 accel error, bit2 battery low.
Send a **boot** packet at start-up: it restarts the counter check (needed after re-flashing).

## Run the tests
`TEST_PG_URL=postgresql+psycopg2://user:pw@localhost:5432/EMPTY_TEST_DB pytest -q`
(The test database is wiped. Never point it at your real database.)

## Cut for the demo (say "next step" if asked)
Login and roles, gateway table, recipients, notification history table, audit log,
public zone map endpoints, HMAC seal check, HTTPS, backups. The InfluxDB token from
docker compose is an all-access token: later replace it with a bucket-only token.
**The API has no login yet: run it only on your own laptop / local network.**
