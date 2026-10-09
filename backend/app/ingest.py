"""
POST /api/v1/ingest - called by the gateway for every LoRa packet (topics 1, 2, 3).

Order of work (one database transaction, the node's status row is locked):
  1. check the gateway key, decode the packet
  2. unknown radio ID -> unknown_packets (1.5); retired node -> ignored
  3. (boot, counter) must be newer than last time, else it is a copy (2.10)
     gaps in the counter = lost packets (2.9); a BOOT packet always restarts counting
  4. convert raw values (2.3) and write InfluxDB; bad clock -> untimed measurement (2.7)
  5. update node_status; PIR event -> wildlife event (4.14)
  6. after commit: queue a PCHA check (4.2); a burst jumps the queue (4.4)
"""
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import convert, db, packets
from .notify import event_text
from .store import MEASUREMENT, MEASUREMENT_UNTIMED, Reading

log = logging.getLogger("ghost_alert.ingest")
router = APIRouter(prefix="/api/v1", tags=["ingest"])

HB_GAP_MIN, HB_GAP_MAX = timedelta(seconds=10), timedelta(minutes=15)
MAX_CLOCK_AHEAD = timedelta(minutes=5)


class IngestIn(BaseModel):
    gateway_id: str = Field(min_length=1, max_length=64)
    received_at: Optional[datetime] = None
    clock_ok: bool = True
    rssi: Optional[int] = Field(default=None, ge=-200, le=50)
    snr: Optional[float] = Field(default=None, ge=-50, le=50)
    payload_hex: str = Field(min_length=28, max_length=128, pattern=r"^[0-9a-fA-F]+$")
    # Set only by the simulator when it writes past history: stored, but no PCHA check is queued
    # (a half-written history window must not raise alerts). The gateway never sets it.
    replay: bool = False


class IngestError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


def _arrival_time(body, server_now):
    t = body.received_at or server_now
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    clock_ok = body.clock_ok and t <= server_now + MAX_CLOCK_AHEAD
    return t.astimezone(timezone.utc), clock_ok


def _moisture_step(st, p, t):
    """Decision 2.8: spread the 5 readings over the real gap between heartbeats."""
    if st["last_heartbeat_at"] is not None and st["boot_number"] == p.boot:
        gap = t - st["last_heartbeat_at"]
        if HB_GAP_MIN <= gap <= HB_GAP_MAX:
            return gap / 5
    return timedelta(seconds=60)


def build_readings(p, node, st, t, rssi, snr, measurement):
    nid, b = str(node["id"]), p.body
    radio = {"rssi": rssi, "snr": snr}
    out = []
    if p.msg_type == packets.HEARTBEAT:
        ax, ay, az = (convert.accel_mg(b[k]) for k in ("accel_x", "accel_y", "accel_z"))
        f = dict(radio, battery_mv=b["battery_mv"], temp_c=b["temp_c10"] / 10.0)
        if not b["flags"] & packets.FLAG_ACCEL_ERROR:
            f.update(accel_x=ax, accel_y=ay, accel_z=az, tilt_deg=convert.tilt_deg(ax, ay, az))
        out.append(Reading(nid, t, f, measurement))
        if not b["flags"] & packets.FLAG_SOIL_ERROR:
            step = _moisture_step(st, p, t)
            for k, raw in enumerate(p.moisture_raw):
                out.append(Reading(nid, t - (4 - k) * step, {
                    "moisture_raw": raw,
                    "moisture_index": convert.moisture_index(raw, node["moisture_dry_raw"], node["moisture_wet_raw"]),
                }, measurement))
    elif p.msg_type == packets.BURST:
        ax, ay, az = (convert.accel_mg(b[k]) for k in ("accel_x", "accel_y", "accel_z"))
        out.append(Reading(nid, t, dict(radio, accel_x=ax, accel_y=ay, accel_z=az,
                                        tilt_event=convert.tilt_deg(ax, ay, az),
                                        burst_peak_mg=b["peak_change_mg"],
                                        burst_duration_s=b["duration_s"]), measurement))
    elif p.msg_type in (packets.PIR_EVENT, packets.PIR_HEARTBEAT):
        out.append(Reading(nid, t, dict(radio, pir_triggers=b["triggers"], battery_mv=b["battery_mv"]), measurement))
    else:  # BOOT
        out.append(Reading(nid, t, radio, measurement))
    return out


def process(engine, store, body: IngestIn, server_now=None):
    """Returns (result_dict, messages_to_send, (node_id, urgent) or None)."""
    server_now = server_now or datetime.now(timezone.utc)
    try:
        p = packets.decode_hex(body.payload_hex)
    except packets.PacketError as exc:
        raise IngestError(422, f"bad packet: {exc}")
    t, clock_ok = _arrival_time(body, server_now)
    messages = []

    with engine.begin() as conn:
        node = db.node_by_radio(conn, p.radio_id)
        if node is None:
            conn.execute(text("""
                INSERT INTO unknown_packets (radio_id, last_gateway_id, first_seen_at, last_seen_at, last_payload_hex)
                VALUES (:r, :g, :t, :t, :h)
                ON CONFLICT (radio_id) DO UPDATE SET last_gateway_id = :g, last_seen_at = :t,
                    times_seen = unknown_packets.times_seen + 1, last_payload_hex = :h"""),
                {"r": p.radio_id, "g": body.gateway_id, "t": server_now, "h": body.payload_hex.lower()})
            return {"status": "unknown_node", "radio_id": p.radio_id}, [], None
        if node["lifecycle"] == "retired":
            return {"status": "retired_node"}, [], None

        nid = str(node["id"])
        db.ensure_status_row(conn, nid)
        st = conn.execute(text("""SELECT boot_number, last_counter, last_heartbeat_at
                                  FROM node_status WHERE node_id = :i FOR UPDATE"""), {"i": nid}).mappings().first()

        lost, restarted = 0, False
        if st["boot_number"] is not None:
            reset_by_boot_packet = p.msg_type == packets.BOOT and p.boot != st["boot_number"]
            if (p.boot, p.counter) <= (st["boot_number"], st["last_counter"]) and not reset_by_boot_packet:
                return {"status": "duplicate", "boot": p.boot, "counter": p.counter}, [], None
            if p.boot == st["boot_number"]:
                lost = p.counter - st["last_counter"] - 1
            else:
                restarted = True

        measurement = MEASUREMENT if clock_ok else MEASUREMENT_UNTIMED
        try:
            store.write(build_readings(p, node, st, t, body.rssi, body.snr, measurement))
        except Exception:
            log.exception("time-series write failed")
            raise IngestError(503, "time-series database unavailable; send again later")

        b = p.body
        conn.execute(text("""
            UPDATE node_status SET
              last_seen_at = GREATEST(COALESCE(last_seen_at, :t), :t), online = TRUE,
              last_gateway_id = :g, rssi = COALESCE(:rssi, rssi), snr = COALESCE(:snr, snr),
              battery_mv = COALESCE(:batt, battery_mv), sensor_flags = COALESCE(:flags, sensor_flags),
              boot_number = :boot, last_counter = :ctr,
              packets_received = packets_received + 1, packets_lost = packets_lost + :lost,
              last_heartbeat_at = CASE WHEN :hb THEN :t ELSE last_heartbeat_at END,
              firmware_version = COALESCE(:fw, firmware_version),
              last_reset_reason = COALESCE(:rr, last_reset_reason)
            WHERE node_id = :i"""),
            {"t": t, "g": body.gateway_id, "rssi": body.rssi, "snr": body.snr,
             "batt": b.get("battery_mv"), "flags": b.get("flags"), "boot": p.boot, "ctr": p.counter,
             "lost": max(lost, 0), "hb": p.msg_type == packets.HEARTBEAT,
             "fw": b.get("firmware_version"), "rr": b.get("reset_reason"), "i": nid})
        if node["lifecycle"] == "registered":
            conn.execute(text("UPDATE sensor_nodes SET lifecycle = 'active' WHERE id = :i"), {"i": nid})

        if p.msg_type == packets.PIR_EVENT:
            messages += _wildlife(conn, node, b["triggers"], t)

    job = None
    if (node["node_type"] == "landslide" and clock_ok and not body.replay
            and p.msg_type in (packets.HEARTBEAT, packets.BURST)):
        job = (nid, p.msg_type == packets.BURST)
    return {"status": "ok", "kind": p.kind, "lost": max(lost, 0), "restarted": restarted,
            "clock_ok": clock_ok}, messages, job


def _wildlife(conn, node, triggers, t):
    """Decision 4.14: open at warning, count triggers; auto-close happens in the worker."""
    nid = str(node["id"])
    ev = conn.execute(text("""SELECT id FROM hazard_events WHERE node_id = :i AND event_type = 'wildlife'
                              AND state = 'open' FOR UPDATE"""), {"i": nid}).first()
    if ev:
        conn.execute(text("""UPDATE hazard_events SET trigger_count = trigger_count + :n,
                             last_trigger_at = :t, last_changed_at = :t WHERE id = :e"""),
                     {"n": triggers, "t": t, "e": ev[0]})
        return []
    eid = conn.execute(text("""
        INSERT INTO hazard_events (node_id, event_type, current_level, peak_level, opened_at,
                                   last_changed_at, last_notified_at, reason, trigger_count, last_trigger_at)
        VALUES (:i, 'wildlife', 'warning', 'warning', :t, :t, :t, 'PIR motion detected', :n, :t)
        RETURNING id"""), {"i": nid, "t": t, "n": triggers}).scalar_one()
    db.log_event(conn, eid, t, "open", None, "warning")
    return [("wildlife", node, "warning", f"{triggers} trigger(s)", eid, t)]


@router.post("/ingest")
def ingest(body: IngestIn, request: Request, x_gateway_key: str = Header(default="")):
    app = request.app
    if not hmac.compare_digest(x_gateway_key.encode(), app.state.settings.gateway_api_key.encode()):
        raise HTTPException(status_code=401, detail="invalid gateway key")
    try:
        result, messages, job = process(app.state.engine, app.state.store, body)
    except IngestError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    for action, node, level, reason, eid, at in messages:
        app.state.notifier.send(event_text(action, node, level, reason, eid, at,
                                           app.state.settings.dashboard_url, node["is_virtual"]))
    if job:
        app.state.worker.enqueue(*job)
    return result
