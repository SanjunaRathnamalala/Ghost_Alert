"""
Runs PCHA for one node at one instant (topic 4a).

The engine files are NOT edited. This wrapper:
  1. fetches the four time windows ending at `now` (so the simulator can replay
     the past: decision 4.6),
  2. builds the per-node 24 h baselines exactly like acs_engine.get_adaptive_baseline,
  3. calls the engine's own classify_moisture / classify_tilt / decide,
  4. checks neighbours like acs_engine.check_corroboration, but skips retired
     nodes (decision 3.15) and uses the same `now`,
  5. turns "no data from either sensor" into tier "no_data" (decision 4.1).
"""
import math
import sys
from datetime import timedelta
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import acs_engine as base        # noqa: E402
import pattern_engine as pe      # noqa: E402

INSUFFICIENT = "insufficient-data"
CORROBORATION_MINUTES = int(base.CORROBORATION_WINDOW.strip("-m"))


def baseline_from(records):
    """Same maths as acs_engine.get_adaptive_baseline, on already-fetched records."""
    values = [r["value"] for r in records]
    n = len(values)
    if n < base.MIN_POINTS_FOR_BASELINE:
        return base.Baseline(None, None, n, is_cold=True)
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    return base.Baseline(mean, std, n, is_cold=False)


def fetch_windows(store, node_id, now):
    stop = now + timedelta(seconds=1)            # include a point stamped exactly at `now`
    short = store.fetch(node_id, ["moisture_index", "tilt_event"],
                        now - timedelta(minutes=pe.MOISTURE_SHORT_MIN), stop)
    m_long = store.fetch(node_id, ["moisture_index"], now - timedelta(hours=pe.MOISTURE_LONG_HOURS), stop)
    t_24h = store.fetch(node_id, ["tilt_deg"], now - timedelta(hours=24), stop)
    t_rate = [r for r in t_24h if r["time"] >= now - timedelta(minutes=pe.TILT_RATE_WINDOW_MIN)]
    t_long = [r for r in t_24h if r["time"] >= now - timedelta(hours=pe.TILT_LONG_HOURS)]
    return {"short": short, "m_long": m_long, "t_rate": t_rate, "t_long": t_long,
            "m_base": baseline_from(m_long), "t_base": baseline_from(t_24h)}


def corroborate(store, neighbours, now):
    """neighbours: list of (node_id, distance_m), already filtered to active landslide nodes in range."""
    need = base.MIN_CORROBORATING_NEIGHBOURS
    if len(neighbours) < need:
        return base.CorroborationResult(
            False, len(neighbours), 0,
            f"insufficient-neighbours ({len(neighbours)} within {base.CORROBORATION_RADIUS_M:.0f} m, need {need})")
    stop = now + timedelta(seconds=1)
    agreeing = 0
    for nid, _dist in neighbours:
        recs = store.fetch(nid, ["moisture_index", "tilt_deg", "tilt_event"],
                           now - timedelta(minutes=CORROBORATION_MINUTES), stop)
        if base._score_node_quick(recs) >= base.CORROBORATION_SCORE_MIN:
            agreeing += 1
    return base.CorroborationResult(agreeing >= need, len(neighbours), agreeing,
                                    f"{agreeing}/{len(neighbours)} neighbours agree (need {need})")


def neighbours_in_range(node, candidates, radius_m=None):
    """node / candidates: dicts with id, latitude, longitude. Distance by haversine, like the engine."""
    radius_m = base.CORROBORATION_RADIUS_M if radius_m is None else radius_m
    out = []
    for c in candidates:
        if str(c["id"]) == str(node["id"]) or c["latitude"] is None or node["latitude"] is None:
            continue
        d = base.haversine_m(node["latitude"], node["longitude"], c["latitude"], c["longitude"])
        if d <= radius_m:
            out.append((str(c["id"]), d))
    return out


def assess(store, node_id, now, neighbours_fn):
    """neighbours_fn() -> list of (node_id, distance). Only called for a critical candidate."""
    w = fetch_windows(store, node_id, now)
    moisture = pe.classify_moisture(pe._series(w["short"], "moisture_index"),
                                    pe._series(w["m_long"], "moisture_index"), w["m_base"])
    tilt = pe.classify_tilt(pe._series(w["t_rate"], "tilt_deg"),
                            pe._series(w["t_long"], "tilt_deg"), w["t_base"])
    event_rate, _ = base.compute_event_rate(w["short"], "tilt_event", pe.MOISTURE_SHORT_MIN)
    tier, unexplained, reason = pe.decide(moisture, tilt)

    corr = None
    if tier == "critical":
        corr = corroborate(store, neighbours_fn(), now)
        if not corr.corroborated:
            tier = "warning"
            reason += f"; held at warning: {corr.reason}"
        else:
            reason += f"; {corr.reason}"

    m_none, t_none = moisture.detail == INSUFFICIENT, tilt.detail == INSUFFICIENT
    if m_none and t_none:
        tier, reason = "no_data", "not enough recent data from either sensor"
    elif m_none:
        reason += "; moisture: no recent data"
    elif t_none:
        reason += "; tilt: no recent data"

    return pe.Assessment(node_id=str(node_id), tier=tier, moisture=moisture, tilt=tilt,
                         event_rate_per_hour=event_rate, corroboration=corr,
                         unexplained=unexplained, reason=reason)
