"""
End-to-end: binary packet -> /ingest -> PostgreSQL + store -> worker -> events -> API.
Needs PostgreSQL: set TEST_PG_URL (an EMPTY test database - tables are wiped).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db, packets
from app.config import Settings
from app.main import create_app
from app.notify import Notifier
from app.store import MemoryStore, Reading

PG = os.getenv("TEST_PG_URL", "postgresql+psycopg2://ghost:testpw@localhost:5432/ghost_test")
KEY = "test-gateway-key-1234567890"


class CaptureNotifier(Notifier):
    def send(self, text_):
        self.sent.append(text_)


@pytest.fixture()
def env():
    engine = db.make_engine(PG)
    try:
        with engine.begin() as c:
            c.exec_driver_sql("DROP TABLE IF EXISTS event_log, tier_history, hazard_events, node_status, "
                              "unknown_packets, sensor_nodes, zones CASCADE")
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    settings = Settings(pg_url=PG, influx_url="", influx_token="x", influx_org="x", influx_bucket="x",
                        gateway_api_key=KEY, cors_origins=["http://localhost:5173"])
    store, notifier = MemoryStore(), CaptureNotifier()
    app = create_app(settings, engine, store, notifier, start_background=False)
    with TestClient(app) as client:
        with engine.begin() as c:
            c.execute(text("INSERT INTO zones (name) VALUES ('Demo slope')"))
            for radio, name, kind, lat in [(1, "GA-LS-001", "landslide", 6.79690),
                                           (2, "GA-PIR-001", "wildlife", 6.79700)]:
                c.execute(text("""INSERT INTO sensor_nodes (radio_id, name, node_type, zone_id, latitude, longitude)
                                  VALUES (:r, :n, :k, 1, :lat, 79.90180)"""),
                          {"r": radio, "n": name, "k": kind, "lat": lat})
        yield client, app, engine, store, notifier


def send(client, msg_type, radio, boot, counter, at=None, key=KEY, **body):
    payload = packets.encode(msg_type, radio, boot, counter, **body).hex()
    return client.post("/api/v1/ingest", headers={"X-Gateway-Key": key}, json={
        "gateway_id": "esp32-gw-01", "received_at": (at or datetime.now(timezone.utc)).isoformat(),
        "clock_ok": True, "rssi": -87, "snr": 7.5, "payload_hex": payload})


HB = dict(accel_x=0, accel_y=87, accel_z=9996, m0=520, m1=519, m2=518, m3=517, m4=516,
          battery_mv=3950, temp_c10=291, flags=0)


def node_id(engine, name):
    with engine.connect() as c:
        return str(c.execute(text("SELECT id FROM sensor_nodes WHERE name = :n"), {"n": name}).scalar())


def test_wrong_key_rejected(env):
    client, *_ = env
    assert send(client, packets.HEARTBEAT, 1, 1, 1, key="wrong-key-000000000", **HB).status_code == 401


def test_heartbeat_is_stored_and_converted(env):
    client, app, engine, store, _ = env
    t = datetime.now(timezone.utc).replace(microsecond=0)
    r = send(client, packets.HEARTBEAT, 1, 1, 1, at=t, **HB)
    assert r.status_code == 200 and r.json()["status"] == "ok"
    nid = node_id(engine, "GA-LS-001")
    recs = store.fetch(nid, ["moisture_index", "tilt_deg", "battery_mv"], t - timedelta(minutes=10), t + timedelta(seconds=1))
    moist = [x for x in recs if x["field"] == "moisture_index"]
    tilt = [x for x in recs if x["field"] == "tilt_deg"]
    assert len(moist) == 5 and len(tilt) == 1
    assert moist[-1]["time"] == t and moist[0]["time"] == t - timedelta(minutes=4)
    assert tilt[0]["value"] == pytest.approx(0.4985, abs=1e-3)


def test_second_heartbeat_spreads_readings_over_real_gap(env):
    client, app, engine, store, _ = env
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=10)
    send(client, packets.HEARTBEAT, 1, 1, 1, at=t0, **HB)
    t1 = t0 + timedelta(minutes=5, seconds=30)
    send(client, packets.HEARTBEAT, 1, 1, 2, at=t1, **HB)
    recs = app.state.store.fetch(node_id(engine, "GA-LS-001"), ["moisture_index"], t0 + timedelta(seconds=1), t1 + timedelta(seconds=1))
    gaps = [(b["time"] - a["time"]).total_seconds() for a, b in zip(recs, recs[1:])]
    assert gaps == [66.0, 66.0, 66.0, 66.0]


def test_demo_speed_heartbeats_spread_over_40s(env):
    client, app, engine, store, _ = env
    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    send(client, packets.HEARTBEAT, 1, 1, 1, at=t0, **HB)
    t1 = t0 + timedelta(seconds=40)
    send(client, packets.HEARTBEAT, 1, 1, 2, at=t1, **HB)
    recs = app.state.store.fetch(node_id(engine, "GA-LS-001"), ["moisture_index"], t0 + timedelta(seconds=1), t1 + timedelta(seconds=1))
    assert [(b["time"] - a["time"]).total_seconds() for a, b in zip(recs, recs[1:])] == [8.0, 8.0, 8.0, 8.0]


def test_duplicate_and_lost_packets(env):
    client, app, engine, *_ = env
    assert send(client, packets.HEARTBEAT, 1, 1, 10, **HB).json()["status"] == "ok"
    assert send(client, packets.HEARTBEAT, 1, 1, 10, **HB).json()["status"] == "duplicate"
    assert send(client, packets.HEARTBEAT, 1, 1, 13, **HB).json()["lost"] == 2
    assert send(client, packets.HEARTBEAT, 1, 1, 5, **HB).json()["status"] == "duplicate"
    r = send(client, packets.BOOT, 1, 2, 1, firmware_version=3, reset_reason=8, node_type=1).json()
    assert r["status"] == "ok" and r["restarted"]


def test_unknown_radio_id_is_logged(env):
    client, app, engine, *_ = env
    assert send(client, packets.HEARTBEAT, 999, 1, 1, **HB).json()["status"] == "unknown_node"
    send(client, packets.HEARTBEAT, 999, 1, 2, **HB)
    with engine.connect() as c:
        assert c.execute(text("SELECT times_seen FROM unknown_packets WHERE radio_id = 999")).scalar() == 2


def test_pir_opens_one_wildlife_event_and_counts(env):
    client, app, engine, store, notifier = env
    send(client, packets.PIR_EVENT, 2, 1, 1, triggers=1, battery_mv=4010, flags=0)
    send(client, packets.PIR_EVENT, 2, 1, 2, triggers=2, battery_mv=4010, flags=0)
    events = client.get("/api/v1/events").json()["events"]
    assert len(events) == 1 and events[0]["trigger_count"] == 3
    app.state.worker.safety_round(datetime.now(timezone.utc) + timedelta(minutes=16))
    assert client.get("/api/v1/events").json()["events"] == []


def test_worker_fast_movement_opens_event_and_full_lifecycle(env):
    client, app, engine, store, notifier = env
    nid = node_id(engine, "GA-LS-001")
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    readings = []
    for i in range(26 * 60):
        t = now - timedelta(minutes=26 * 60 - i)
        h = (now - t).total_seconds() / 3600
        f = {"moisture_index": 30.0 + (i % 3) * 0.2}
        if i % 5 == 0:
            f["tilt_deg"] = 0.5 + (max(0.0, 2 - h) ** 2) * 0.6 + (i % 2) * 0.001
        readings.append(Reading(nid, t, f))
    store.write(readings)
    with engine.begin() as c:
        c.execute(text("UPDATE sensor_nodes SET lifecycle = 'active' WHERE id = :i"), {"i": nid})
    a = app.state.worker.evaluate_node(nid, now)
    assert a.tier == "warning" and "held at warning" in a.reason
    eid = client.get("/api/v1/events").json()["events"][0]["id"]
    app.state.worker.evaluate_node(nid, now + timedelta(minutes=1))
    assert sum("Landslide risk" in m for m in notifier.sent) == 1
    assert client.post(f"/api/v1/events/{eid}/close", json={"note": ""}).status_code == 422
    assert client.post(f"/api/v1/events/{eid}/acknowledge", json={"by": "operator"}).status_code == 200
    assert client.post(f"/api/v1/events/{eid}/close", json={"by": "operator", "note": "test OK"}).status_code == 200
    app.state.worker.evaluate_node(nid, now + timedelta(minutes=2))
    events = client.get("/api/v1/events").json()["events"]
    assert len(events) == 1 and events[0]["id"] != eid


def test_no_data_node_and_offline(env):
    client, app, engine, store, notifier = env
    nid = node_id(engine, "GA-LS-001")
    send(client, packets.HEARTBEAT, 1, 1, 1, at=datetime.now(timezone.utc) - timedelta(minutes=30), **HB)
    a = app.state.worker.evaluate_node(nid, datetime.now(timezone.utc))
    assert a.tier == "no_data"
    app.state.worker.safety_round(datetime.now(timezone.utc))
    assert client.get(f"/api/v1/nodes/{nid}").json()["online"] is False
    assert any("offline" in m for m in notifier.sent)


def test_health(env):
    client, *_ = env
    h = client.get("/api/v1/health").json()
    assert h["postgres"] == "ok" and h["influx"] == "ok"
