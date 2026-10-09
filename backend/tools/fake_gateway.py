"""
Fake gateway: sends REAL binary packets to the backend, exactly like the ESP32 will.
Useful to test the backend and the dashboard without hardware.

Examples (from the backend folder):
  python -m tools.fake_gateway heartbeat --radio 1 --counter 1
  python -m tools.fake_gateway heartbeat --radio 1 --counter 2 --tilt 1.5 --moisture 400
  python -m tools.fake_gateway burst     --radio 1 --counter 3 --tilt 2.0
  python -m tools.fake_gateway pir       --radio 2 --counter 1 --triggers 2
  python -m tools.fake_gateway boot      --radio 1 --boot 2 --counter 1
"""
import argparse
import json
import math
import os
import urllib.request
from datetime import datetime, timezone

from dotenv import load_dotenv

from app import packets

load_dotenv()


def accel_for_tilt(tilt_deg):
    """Accel (tenths of mg) for a node tilted by tilt_deg around the X axis."""
    r = math.radians(tilt_deg)
    return 0, int(round(math.sin(r) * 10000)), int(round(math.cos(r) * 10000))


def build(a):
    if a.type in ("heartbeat", "burst"):
        ax, ay, az = accel_for_tilt(a.tilt)
    if a.type == "heartbeat":
        return packets.encode(packets.HEARTBEAT, a.radio, a.boot, a.counter, accel_x=ax, accel_y=ay, accel_z=az,
                              m0=a.moisture, m1=a.moisture, m2=a.moisture, m3=a.moisture, m4=a.moisture,
                              battery_mv=a.battery, temp_c10=int(a.temp * 10), flags=0)
    if a.type == "burst":
        return packets.encode(packets.BURST, a.radio, a.boot, a.counter, accel_x=ax, accel_y=ay, accel_z=az,
                              peak_change_mg=a.peak, duration_s=a.duration, flags=0)
    if a.type == "pir":
        return packets.encode(packets.PIR_EVENT, a.radio, a.boot, a.counter, triggers=a.triggers,
                              battery_mv=a.battery, flags=0)
    return packets.encode(packets.BOOT, a.radio, a.boot, a.counter, firmware_version=1, reset_reason=1,
                          node_type=2 if a.radio == 2 else 1)


def post(url, key, payload_hex, rssi=-80, snr=8.0, at=None):
    body = json.dumps({"gateway_id": "fake-gw", "received_at": (at or datetime.now(timezone.utc)).isoformat(),
                       "clock_ok": True, "rssi": rssi, "snr": snr, "payload_hex": payload_hex}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                          "X-Gateway-Key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("type", choices=["heartbeat", "burst", "pir", "boot"])
    ap.add_argument("--radio", type=int, default=1)
    ap.add_argument("--boot", type=int, default=1)
    ap.add_argument("--counter", type=int, required=True)
    ap.add_argument("--tilt", type=float, default=0.5, help="degrees")
    ap.add_argument("--moisture", type=int, default=520, help="raw ADC 0-1023 (lower = wetter)")
    ap.add_argument("--battery", type=int, default=3950)
    ap.add_argument("--temp", type=float, default=29.0)
    ap.add_argument("--peak", type=int, default=150)
    ap.add_argument("--duration", type=int, default=2)
    ap.add_argument("--triggers", type=int, default=1)
    ap.add_argument("--url", default=os.getenv("BACKEND_URL", "http://localhost:8000") + "/api/v1/ingest")
    a = ap.parse_args()
    raw = build(a)
    print(f"packet ({len(raw)} bytes): {raw.hex()}")
    print("backend says:", post(a.url, os.environ["GATEWAY_API_KEY"], raw.hex()))


if __name__ == "__main__":
    main()
