"""
Endpoints the dashboard uses (topic 6).
DEMO NOTE: login and roles (topic 7) are cut for the 2-day demo. Run on localhost only.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import db
from .store import ALLOWED_FIELDS

router = APIRouter(prefix="/api/v1", tags=["dashboard"])

CHART_FIELDS = ["moisture_index", "tilt_deg", "tilt_event", "temp_c", "battery_mv", "rssi", "pir_triggers"]


def _uuid(value):
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")


def _iso(row):
    return {k: (v.isoformat() if isinstance(v, datetime) else str(v) if isinstance(v, uuid.UUID) else v)
            for k, v in dict(row).items()}


NODE_SELECT = """
    SELECT n.id, n.radio_id, n.name, n.node_type, n.latitude, n.longitude, n.lifecycle, n.is_virtual,
           z.name AS zone_name,
           s.last_seen_at, s.online, s.battery_mv, s.rssi, s.snr, s.sensor_flags, s.firmware_version,
           s.last_reset_reason, s.packets_received, s.packets_lost, s.tier, s.moisture_pattern,
           s.tilt_pattern, s.reason, s.evaluated_at, s.tier_since
    FROM sensor_nodes n
    LEFT JOIN zones z ON z.id = n.zone_id
    LEFT JOIN node_status s ON s.node_id = n.id
"""


@router.get("/nodes")
def list_nodes(request: Request):
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(text(NODE_SELECT + " WHERE n.lifecycle <> 'retired' ORDER BY n.name")).mappings()
        return {"nodes": [_iso(r) for r in rows]}


@router.get("/nodes/{node_id}")
def get_node(node_id: str, request: Request):
    with request.app.state.engine.connect() as conn:
        r = conn.execute(text(NODE_SELECT + " WHERE n.id = :i"), {"i": _uuid(node_id)}).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail="node not found")
    return _iso(r)


@router.get("/nodes/{node_id}/telemetry")
def telemetry(node_id: str, request: Request, hours: float = Query(24, gt=0, le=168),
              fields: str = Query(",".join(CHART_FIELDS))):
    wanted = [f for f in fields.split(",") if f]
    if set(wanted) - ALLOWED_FIELDS:
        raise HTTPException(status_code=422, detail="unknown field")
    now = datetime.now(timezone.utc)
    recs = request.app.state.store.fetch(_uuid(node_id), wanted, now - timedelta(hours=hours),
                                         now + timedelta(minutes=1))
    series = {f: [] for f in wanted}
    for r in recs:
        series[r["field"]].append([r["time"].isoformat(), round(r["value"], 4)])
    return {"node_id": node_id, "hours": hours, "series": series}


@router.get("/nodes/{node_id}/tiers")
def tier_history(node_id: str, request: Request, hours: float = Query(24, gt=0, le=168)):
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(text("""SELECT at, from_tier, to_tier, reason FROM tier_history
                                    WHERE node_id = :i AND at >= :since ORDER BY at"""),
                            {"i": _uuid(node_id),
                             "since": datetime.now(timezone.utc) - timedelta(hours=hours)}).mappings()
        return {"history": [_iso(r) for r in rows]}


EVENT_SELECT = """
    SELECT e.id, e.node_id, n.name AS node_name, n.is_virtual, n.latitude, n.longitude, e.event_type,
           e.current_level, e.peak_level, e.state, e.opened_at, e.last_changed_at, e.ready_to_close_at,
           e.acknowledged_at, e.acknowledged_by, e.resolved_at, e.resolved_by, e.resolve_note,
           e.reason, e.trigger_count, e.last_trigger_at
    FROM hazard_events e JOIN sensor_nodes n ON n.id = e.node_id
"""


@router.get("/events")
def list_events(request: Request, state: str = Query("open", pattern="^(open|resolved|all)$"),
                limit: int = Query(100, ge=1, le=500)):
    where = "" if state == "all" else " WHERE e.state = :s"
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(text(EVENT_SELECT + where + " ORDER BY e.last_changed_at DESC LIMIT :l"),
                            {"s": state, "l": limit}).mappings()
        return {"events": [_iso(r) for r in rows]}


@router.get("/events/{event_id}")
def get_event(event_id: int, request: Request):
    with request.app.state.engine.connect() as conn:
        ev = conn.execute(text(EVENT_SELECT + " WHERE e.id = :e"), {"e": event_id}).mappings().first()
        if not ev:
            raise HTTPException(status_code=404, detail="event not found")
        log = conn.execute(text("""SELECT at, action, from_level, to_level, actor, note FROM event_log
                                   WHERE event_id = :e ORDER BY at, id"""), {"e": event_id}).mappings()
        return dict(_iso(ev), log=[_iso(r) for r in log])


class AckIn(BaseModel):
    by: str = Field("operator", min_length=1, max_length=64)


class CloseIn(BaseModel):
    by: str = Field("operator", min_length=1, max_length=64)
    note: str = Field(min_length=3, max_length=500)       # decision 4.13: closing needs a note


@router.post("/events/{event_id}/acknowledge")
def acknowledge(event_id: int, body: AckIn, request: Request):
    now = datetime.now(timezone.utc)
    with request.app.state.engine.begin() as conn:
        r = conn.execute(text("""UPDATE hazard_events SET acknowledged_at = :now, acknowledged_by = :by
                                 WHERE id = :e AND state = 'open' AND acknowledged_at IS NULL RETURNING id"""),
                         {"now": now, "by": body.by, "e": event_id}).first()
        if not r:
            raise HTTPException(status_code=409, detail="event is not open or already acknowledged")
        db.log_event(conn, event_id, now, "acknowledged", actor=body.by)
    return {"status": "acknowledged"}


@router.post("/events/{event_id}/close")
def close(event_id: int, body: CloseIn, request: Request):
    """A person can close an event, but not switch off the detector: if PCHA still says
    warning at the next check, a NEW event opens (decision 4.13)."""
    now = datetime.now(timezone.utc)
    with request.app.state.engine.begin() as conn:
        r = conn.execute(text("""UPDATE hazard_events SET state = 'resolved', resolved_at = :now,
                                   resolved_by = :by, resolve_note = :note, last_changed_at = :now
                                 WHERE id = :e AND state = 'open' RETURNING current_level"""),
                         {"now": now, "by": body.by, "note": body.note, "e": event_id}).first()
        if not r:
            raise HTTPException(status_code=409, detail="event is not open")
        db.log_event(conn, event_id, now, "closed", r[0], None, actor=body.by, note=body.note)
    return {"status": "closed"}


@router.get("/health")
def health(request: Request):
    """The dashboard shows a stale-data banner if this fails (decision 6.5)."""
    s = request.app.state
    out = {"time": datetime.now(timezone.utc).isoformat(), "worker_alive": s.worker.alive,
           "worker_last_round": s.worker.last_round_at.isoformat() if s.worker.last_round_at else None,
           "worker_last_error": s.worker.last_error, "evaluations": s.worker.evaluations}
    try:
        with s.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        out["postgres"] = "ok"
    except Exception as exc:
        out["postgres"] = f"error: {type(exc).__name__}"
    try:
        out["influx"] = "ok" if s.store.ping() else "error"
    except Exception as exc:
        out["influx"] = f"error: {type(exc).__name__}"
    return out
