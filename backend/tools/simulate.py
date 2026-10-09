"""
Ghost_Alert simulator - moves the VIRTUAL nodes (GA-LS-V01..V04) through realistic scenarios.

Every packet is a real binary LoRa packet, posted to POST /api/v1/ingest exactly like the
ESP32 gateway does, so the whole pipeline (decode -> InfluxDB -> PCHA -> events -> alerts)
is exercised. Virtual nodes are marked is_virtual in the database and labelled
SIMULATED everywhere (map, node page, Telegram).

How a run works:
  1. (default) clear the virtual nodes' old data, so scenarios never mix
  2. write 26 h of history in a few seconds (flagged "replay": stored, no alerts)
  3. continue LIVE in real time: one heartbeat per node every 40 s (demo timing),
     so the map changes in front of the audience. Stop with Ctrl+C.

Run from the backend folder (backend must be running):
  python -m tools.simulate --list
  python -m tools.simulate tour
  python -m tools.simulate slope_failure
  python -m tools.simulate calm --minutes 5
"""
import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app import packets

HISTORY_H = 26.0            # 24 h baseline + margin
BACKFILL_STEP_S = 300       # history: one heartbeat every 5 min (field timing)
LIVE_STEP_S = 40            # live: one heartbeat every 40 s (demo timing, like the bench node)
DEMO_TIMING_H = 2.5         # the last 2.5 h of history also use the 40 s timing
SL_TZ = timezone(timedelta(hours=5, minutes=30))
CENTER_LAT, CENTER_LON = 6.79690, 79.90180   # same demo slope as scripts/seed_demo.py
M_PER_DEG = 111_320.0


# ---------------------------------------------------------------------------------------
# Building blocks. Every function takes `a` = hours since the start of the history.
# At the end of the history a = HISTORY_H; during the live phase a keeps growing.
# ---------------------------------------------------------------------------------------
A0 = HISTORY_H


def ramp(a, start, rate):
    return max(0.0, a - start) * rate


def calm_moisture(a):
    return 31.0


def rain_moisture(a):
    """Steady rain for the whole period: soil gets wetter all day (sustained wetting)."""
    return 22.0 + 2.2 * a


def storm_moisture(a):
    """Wet day, then a heavy downpour in the last hour (rain on already-wet ground)."""
    return min(98.0, 22.0 + 2.2 * a + ramp(a, A0 - 1.0, 20.0))


def flat_tilt(base):
    return lambda a: base


def creep_tilt(base, rate_per_h):
    """Steady movement (secondary creep)."""
    return lambda a: base + rate_per_h * a


def failing_tilt(base, k):
    """Slow creep that starts to speed up about 3 h before 'now' (tertiary -> near failure)."""
    return lambda a: base + 0.02 * a + k * max(0.0, a - (A0 - 3.0)) ** 2


@dataclass
class Behaviour:
    moisture: Callable[[float], float]
    tilt: Callable[[float], float]
    bursts_from: Optional[float] = None      # motion bursts every 4 min from this `a`
    silent_from: Optional[float] = None      # node stops sending from this `a`
    soil_dead_from: Optional[float] = None   # soil sensor output pinned (reads "bone dry")
    note: str = ""


@dataclass
class Scenario:
    title: str
    story: str
    nodes: dict = field(default_factory=dict)     # radio -> Behaviour
    expect: dict = field(default_factory=dict)    # radio -> set of acceptable tiers (checked in tests)


CALM = Behaviour(calm_moisture, flat_tilt(1.2), note="dry and still")

SCENARIOS = {
    "calm": Scenario(
        "Calm day", "Dry soil, no movement anywhere. Everything should be normal (green).",
        {101: CALM, 102: CALM, 103: CALM, 104: CALM},
        {101: {"normal"}, 102: {"normal"}, 103: {"normal"}, 104: {"normal"}}),
    "rain": Scenario(
        "Rainy day, no movement", "Soil wets steadily all day but nothing moves -> watch, not alarm.",
        {r: Behaviour(rain_moisture, flat_tilt(1.2), note="steady rain") for r in (101, 102, 103, 104)},
        {r: {"watch"} for r in (101, 102, 103, 104)}),
    "creep": Scenario(
        "Steady creep in wet soil", "V04 creeps steadily (about 0.08 deg/h) while the soil wets -> warning.",
        {101: CALM, 102: CALM, 103: CALM,
         104: Behaviour(rain_moisture, creep_tilt(1.0, 0.08), note="steady creep + rain")},
        {101: {"normal"}, 102: {"normal"}, 103: {"normal"}, 104: {"warning"}}),
    "localised": Scenario(
        "One node failing, neighbours calm",
        "V04 shows accelerating movement, but no neighbour agrees -> held at WARNING, not critical "
        "(neighbour confirmation stops a single faulty or knocked node from raising a critical).",
        {101: CALM, 102: CALM, 103: CALM,
         104: Behaviour(storm_moisture, failing_tilt(1.0, 0.12), note="accelerating, alone")},
        {101: {"normal"}, 102: {"normal"}, 103: {"normal"}, 104: {"warning"}}),
    "slope_failure": Scenario(
        "Slope-wide failure",
        "Heavy rain on wet ground; all virtual nodes accelerate and report motion bursts. "
        "Neighbours confirm each other -> CRITICAL.",
        {101: Behaviour(storm_moisture, failing_tilt(1.1, 0.12), bursts_from=A0 - 0.5),
         102: Behaviour(storm_moisture, failing_tilt(0.9, 0.10), bursts_from=A0 - 0.5),
         103: Behaviour(storm_moisture, failing_tilt(1.3, 0.11), bursts_from=A0 - 0.5),
         104: Behaviour(storm_moisture, failing_tilt(1.0, 0.13), bursts_from=A0 - 0.5)},
        {101: {"critical", "warning"}, 102: {"critical", "warning"},
         103: {"critical", "warning"}, 104: {"critical"}}),
    "tour": Scenario(
        "Feature tour (one story per node)",
        "V01 rain only -> watch | V02 dead soil sensor but its tilt is accelerating -> still warns "
        "(a faulty sensor never hides a landslide) | V03 goes silent -> no data, never 'safe' | "
        "V04 calm -> normal.",
        {101: Behaviour(rain_moisture, flat_tilt(1.2), note="rain only"),
         102: Behaviour(storm_moisture, failing_tilt(1.0, 0.12), soil_dead_from=A0 - 1.5,
                        note="dead soil sensor, accelerating tilt"),
         103: Behaviour(calm_moisture, flat_tilt(1.2), silent_from=A0 - 2.5, note="silent for 2.5 h"),
         104: CALM},
        {101: {"watch"}, 102: {"warning"}, 103: {"no_data"}, 104: {"normal"}}),
}

VIRTUAL_NODES = [   # radio, name, metres north / east of the demo slope centre, tilt direction
    (101, "GA-LS-V01", 20, 10, 30),
    (102, "GA-LS-V02", -15, 25, 120),
    (103, "GA-LS-V03", 30, -20, 210),
    (104, "GA-LS-V04", -10, -20, 300),   # 40-45 m from V01..V03, clear of GA-LS-001 on the map
]


# ---------------------------------------------------------------------------------------
# Packet generation
# ---------------------------------------------------------------------------------------
class NodeSim:
    """Turns a Behaviour into real binary packets for one virtual node."""

    def __init__(self, radio, azimuth_deg, behaviour, boot, seed, dry_raw=620, wet_raw=280):
        self.radio, self.az, self.b = radio, math.radians(azimuth_deg), behaviour
        self.boot, self.counter = boot, 0
        self.dry, self.wet = dry_raw, wet_raw
        self.rnd = random.Random(seed)
        self.last_burst_a = None

    def _next(self):
        self.counter += 1
        return self.counter

    def silent(self, a):
        return self.b.silent_from is not None and a >= self.b.silent_from

    def _accel(self, tilt_deg):
        t = math.radians(tilt_deg)
        return (int(round(math.sin(t) * math.cos(self.az) * 10000)),
                int(round(math.sin(t) * math.sin(self.az) * 10000)),
                int(round(math.cos(t) * 10000)))

    def _soil_raw(self, a):
        if self.b.soil_dead_from is not None and a >= self.b.soil_dead_from:
            return self.dry + 5                      # stuck output: reads as "bone dry"
        idx = max(0.0, min(100.0, self.b.moisture(a) + self.rnd.gauss(0, 0.15)))   # 8x averaged ADC
        return int(round(self.dry - idx / 100.0 * (self.dry - self.wet)))

    def boot_packet(self):
        return packets.encode(packets.BOOT, self.radio, self.boot, self._next(),
                              firmware_version=9, reset_reason=1, node_type=1)

    def heartbeat(self, a, step_s, local_hour):
        tilt = self.b.tilt(a) + self.rnd.gauss(0, 0.01)          # averaged ADXL362 noise
        ax, ay, az = self._accel(tilt)
        m = [self._soil_raw(a - (4 - k) * step_s / 5 / 3600) for k in range(5)]
        temp = 26 + 4 * math.sin(2 * math.pi * (local_hour - 9) / 24) + self.rnd.gauss(0, 0.2)
        batt = int(4050 - 0.4 * a + self.rnd.gauss(0, 3))
        return packets.encode(packets.HEARTBEAT, self.radio, self.boot, self._next(),
                              accel_x=ax, accel_y=ay, accel_z=az,
                              m0=m[0], m1=m[1], m2=m[2], m3=m[3], m4=m[4],
                              battery_mv=batt, temp_c10=int(round(temp * 10)), flags=0)

    def maybe_burst(self, a):
        if self.b.bursts_from is None or a < self.b.bursts_from:
            return None
        if self.last_burst_a is not None and a - self.last_burst_a < 4 / 60:
            return None
        self.last_burst_a = a
        ax, ay, az = self._accel(self.b.tilt(a))
        return packets.encode(packets.BURST, self.radio, self.boot, self._next(),
                              accel_x=ax, accel_y=ay, accel_z=az,
                              peak_change_mg=int(80 + self.rnd.random() * 120), duration_s=2, flags=0)

    def radio_quality(self):
        return int(-78 + self.rnd.gauss(0, 4)), round(8 + self.rnd.gauss(0, 1.5), 1)


def history_packets(sims, anchor):
    """Yields (received_at, NodeSim, payload) for the 26 h before `anchor`, oldest first."""
    start = anchor - timedelta(hours=HISTORY_H)
    for s in sims.values():
        yield start - timedelta(seconds=30), s, s.boot_packet()
    # Older history at field timing (5 min); the last DEMO_TIMING_H at the live timing (40 s),
    # so PCHA's 2-hour tilt window always sees one even cadence (the engine splits it by count).
    switch = HISTORY_H - DEMO_TIMING_H
    a, step = 0.0, BACKFILL_STEP_S
    while True:
        step = BACKFILL_STEP_S if a + BACKFILL_STEP_S / 3600 <= switch else LIVE_STEP_S
        a = round(a + step / 3600, 9)
        if a > HISTORY_H + 1e-9:
            break
        t = start + timedelta(seconds=round(a * 3600))
        local_hour = t.astimezone(SL_TZ).hour + t.astimezone(SL_TZ).minute / 60
        for s in sims.values():
            if s.silent(a):
                continue
            burst = s.maybe_burst(a)
            if burst:
                yield t - timedelta(seconds=10), s, burst
            yield t, s, s.heartbeat(a, step, local_hour)


def live_packets(sim, a, t):
    """Packets one node sends at live time t (a = hours since history start)."""
    if sim.silent(a):
        return []
    local_hour = t.astimezone(SL_TZ).hour + t.astimezone(SL_TZ).minute / 60
    out = []
    burst = sim.maybe_burst(a)
    if burst:
        out.append(burst)
    out.append(sim.heartbeat(a, LIVE_STEP_S, local_hour))
    return out


def ingest_body(payload, received_at, sim, replay):
    rssi, snr = sim.radio_quality()
    return {"gateway_id": "simulator", "received_at": received_at.isoformat(), "clock_ok": True,
            "rssi": rssi, "snr": snr, "payload_hex": payload.hex(), "replay": replay}


# ---------------------------------------------------------------------------------------
# Database setup / clean-up (uses the backend's own settings from .env)
# ---------------------------------------------------------------------------------------
def node_position(north_m, east_m):
    lat = CENTER_LAT + north_m / M_PER_DEG
    lon = CENTER_LON + east_m / (M_PER_DEG * math.cos(math.radians(CENTER_LAT)))
    return lat, lon


def prepare_database(settings, fresh):
    """Registers V01..V04 if missing and (if fresh) removes their old data and alerts."""
    from sqlalchemy import text
    from app import db
    engine = db.make_engine(settings.pg_url)
    db.apply_schema(engine)
    ids = {}
    with engine.begin() as c:
        zid = c.execute(text("""INSERT INTO zones (name, description, center_lat, center_lon, radius_m)
                                VALUES ('Demo slope', 'Bench prototype + virtual neighbours', :lat, :lon, 80)
                                ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"""),
                        {"lat": CENTER_LAT, "lon": CENTER_LON}).scalar_one()
        for radio, name, north, east, _az in VIRTUAL_NODES:
            lat, lon = node_position(north, east)
            nid = c.execute(text("""
                INSERT INTO sensor_nodes (radio_id, name, node_type, zone_id, latitude, longitude,
                                          is_virtual, lifecycle, notes)
                VALUES (:r, :n, 'landslide', :z, :lat, :lon, TRUE, 'active', 'SIMULATED node')
                ON CONFLICT (radio_id) DO UPDATE SET is_virtual = TRUE, lifecycle = 'active',
                    latitude = :lat, longitude = :lon
                RETURNING id"""), {"r": radio, "n": name, "z": zid, "lat": lat, "lon": lon}).scalar_one()
            ids[radio] = str(nid)
        if fresh:
            vids = list(ids.values())
            c.execute(text("""DELETE FROM event_log WHERE event_id IN
                              (SELECT id FROM hazard_events WHERE node_id = ANY(CAST(:v AS uuid[])))"""), {"v": vids})
            c.execute(text("DELETE FROM hazard_events WHERE node_id = ANY(CAST(:v AS uuid[]))"), {"v": vids})
            c.execute(text("DELETE FROM tier_history WHERE node_id = ANY(CAST(:v AS uuid[]))"), {"v": vids})
            c.execute(text("DELETE FROM node_status WHERE node_id = ANY(CAST(:v AS uuid[]))"), {"v": vids})
    if fresh:
        if settings.telemetry_store == "memory":
            print("  !! TELEMETRY_STORE=memory: this script cannot clear readings inside the running backend.\n"
                  "  !! If you ran another scenario since the backend started, stop the backend (Ctrl+C),\n"
                  "  !! start it again, then re-run this command. Otherwise old and new readings mix\n"
                  "  !! and the tiers will be wrong (e.g. 'knock' instead of critical).")
        else:
            from app.store import InfluxStore
            store = InfluxStore(settings.influx_url, settings.influx_token, settings.influx_org,
                                settings.influx_bucket)
            now = datetime.now(timezone.utc)
            for nid in ids.values():
                store.delete_node(nid, now - timedelta(days=30), now + timedelta(days=1))
            store.client.close()
    return ids


# ---------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------
class Poster:
    def __init__(self, url, key):
        self.url, self.key = url, key

    def __call__(self, body):
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Gateway-Key": self.key})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return {"status": f"HTTP {exc.code}", "detail": exc.read().decode()[:200]}


def build_sims(scenario, seed):
    boot = 1 + int(time.time() // 60) % 60000          # new boot number every run
    sims = {}
    for radio, _name, _n, _e, az in VIRTUAL_NODES:
        sims[radio] = NodeSim(radio, az, scenario.nodes[radio], boot, seed + radio)
    return sims


def run(scenario_name, url, key, minutes=None, live=True, seed=7, poster=None, settings=None, fresh=True):
    scenario = SCENARIOS[scenario_name]
    print(f"\n=== {scenario.title}  [SIMULATED DATA] ===\n{scenario.story}\n")
    if settings is not None:
        print("Preparing virtual nodes" + (" (clearing their old data)" if fresh else "") + " ...")
        prepare_database(settings, fresh)
    post = poster or Poster(url, key)
    sims = build_sims(scenario, seed)
    anchor = datetime.now(timezone.utc).replace(microsecond=0)

    n, bad, t0 = 0, 0, time.time()
    print(f"Writing {HISTORY_H:.0f} h of history ...")
    for received_at, sim, payload in history_packets(sims, anchor):
        r = post(ingest_body(payload, received_at, sim, replay=True))
        n += 1
        if n % 500 == 0:
            print(f"  ... {n} packets")
        if r.get("status") not in ("ok",):
            bad += 1
            if bad <= 3:
                print("  backend said:", r)
    print(f"  {n} packets in {time.time() - t0:.1f} s" + (f" ({bad} not ok)" if bad else ""))
    if not live:
        return sims, anchor

    print(f"\nLIVE: one heartbeat per node every {LIVE_STEP_S} s. Watch the dashboard. Ctrl+C to stop.")
    start = time.time()
    k = 0
    try:
        while minutes is None or time.time() - start < minutes * 60:
            k += 1
            t = datetime.now(timezone.utc)
            a = HISTORY_H + (t - anchor).total_seconds() / 3600
            line = []
            for radio, sim in sims.items():
                pk = live_packets(sim, a, t)
                for p in pk:
                    post(ingest_body(p, t, sim, replay=False))
                line.append(f"V0{radio - 100}:" + ("silent" if not pk else f"tilt {sim.b.tilt(a):.2f}"))
            print(f"  [{t.astimezone(SL_TZ):%H:%M:%S}] " + "  ".join(line))
            time.sleep(max(1.0, LIVE_STEP_S - (time.time() - start) % LIVE_STEP_S))
    except KeyboardInterrupt:
        print("\nStopped. (Virtual nodes stop sending: after 15 min they show offline / no data.)")
    return sims, anchor


def main():
    ap = argparse.ArgumentParser(description="Ghost_Alert scenario simulator (virtual nodes only)")
    ap.add_argument("scenario", nargs="?", choices=sorted(SCENARIOS))
    ap.add_argument("--list", action="store_true", help="show the scenarios")
    ap.add_argument("--minutes", type=float, help="stop the live phase after this many minutes")
    ap.add_argument("--no-live", action="store_true", help="only write the history, then exit")
    ap.add_argument("--keep", action="store_true", help="do not clear the virtual nodes' old data first")
    ap.add_argument("--url", default=None, help="backend URL (default from .env BACKEND_URL or localhost:8000)")
    a = ap.parse_args()

    if a.list or not a.scenario:
        print("Scenarios (all data is SIMULATED, on virtual nodes V01-V04 only):\n")
        for name in sorted(SCENARIOS):
            s = SCENARIOS[name]
            print(f"  {name:14s} {s.title}\n  {'':14s} {s.story}\n")
        return

    import os
    from app.config import load_settings
    settings = load_settings()
    url = (a.url or os.getenv("BACKEND_URL", "http://localhost:8000")).rstrip("/") + "/api/v1/ingest"
    try:
        urllib.request.urlopen(url.replace("/ingest", "/health"), timeout=5).read()
    except Exception as exc:
        sys.exit(f"Backend not reachable at {url} ({exc}). Start it first.")
    run(a.scenario, url, settings.gateway_api_key, minutes=a.minutes, live=not a.no_live,
        settings=settings, fresh=not a.keep)


if __name__ == "__main__":
    main()
