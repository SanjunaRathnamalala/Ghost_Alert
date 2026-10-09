"""
acs_engine.py

Adaptive Corroborated Scoring (ACS) - hazard evaluation engine.

ACS replaces Fixed-Threshold Gating (FTG), the original scheme in which a
single global moisture threshold was AND-ed with a single global tilt
threshold and OR-ed across two trigger conditions.

    FTG:  (rise > 10% over 15 min AND level > 60)  OR  (tilt > 0.5 AND level > 60)

    ACS:  two independent sensing modalities, each passing through outlier
          rejection, trend regression and a per-node adaptive baseline to
          produce a 0-1 score; the two scores are then combined and, when
          both are high, checked against neighbouring nodes before the
          highest tier is issued.


UNITS - IMPORTANT
-----------------
The moisture channel is a RELATIVE SATURATION INDEX, not volumetric water
content. A capacitive probe is conventionally calibrated so that its reading
in dry air is 0 and fully submerged is 100, and the value is linear between
those two points. That scale is specific to the sensor, the soil and the
calibration procedure; it is NOT volumetric water content, which saturates
near 40-50% in real soil because the remaining volume is solid particles.

Two consequences:
  * Any fixed index threshold (such as FTG's 60) has no physical meaning
    until sensor-and-soil-specific calibration is performed.
  * Index values are only comparable BETWEEN nodes if every probe was
    calibrated identically.

This is a positive argument for the adaptive baseline: comparing a node only
against its own history sidesteps the cross-node calibration problem
entirely, rather than assuming it away.


TELEMETRY MODEL
---------------
Moisture arrives on a regular schedule (nominally 1 min).

Tilt arrives on TWO channels, because the ADXL362 supports autonomous
interrupt processing and a motion-triggered wake-up mode, and using only one
of them loses information:

  "tilt_deg"    HEARTBEAT. Regular scheduled samples (nominally 5 min),
                sent whether or not anything is happening. Feeds the
                baseline and the creep trend.

  "tilt_event"  BURST. Interrupt-driven samples, roughly 1 s apart within a
                burst, emitted only when the accelerometer detects motion.

The separation is not cosmetic. An interrupt-driven channel only reports
when something is happening, so its history is a record of the node's most
active moments, not of its normal state. Computing a mean and standard
deviation from burst data would yield "normal while already moving", which
is exactly the wrong reference. Only heartbeat samples are therefore used
for the baseline and the trend.

Burst samples instead contribute a third signal: EVENT RATE, the number of
distinct motion events per hour. This needs no regression and no baseline -
it is a count, and a count cannot be moved by one bad reading. It also
covers the gap that slow telemetry cannot: an actual slide takes seconds,
so no realistic sampling interval will catch it in the values, but the
hardware interrupt fires every time and the rate rises accordingly.


TILT INPUT
----------
Tilt is degrees of deviation from the node's installed reference
orientation, derived on the node from the three-axis output:

    d_theta = arccos( (a_now . a_ref) / (|a_now| * |a_ref|) )

Absolute orientation is irrelevant - a node installed on a 30 degree slope
reads 30 degrees forever. What matters is change from the reference.

KNOWN CONFOUND: MEMS accelerometers drift with temperature, and outdoor
temperature follows a daily cycle, so thermal drift appears as slow apparent
tilt that is not ground movement. The ADXL362 carries an on-chip temperature
sensor intended for this compensation. ACS does not compensate explicitly;
it relies on the 24 h adaptive baseline absorbing a full diurnal cycle into
"normal for this node". That is a partial mitigation, not a correction, and
is stated as a limitation.


Pure-logic functions take no database handles, so they can be unit tested
against synthetic data with no live database.
"""

import math
from dataclasses import dataclass
from typing import Optional, List, Tuple

from sqlalchemy import text

# ===========================================================================
# Configuration
# ===========================================================================

WINDOW_MINUTES = 15.0

# --- trend validity ---
MIN_POINTS_FOR_TREND = 4
# A slope expressed per minute must not be extrapolated from a handful of
# samples spanning a few seconds. An interrupt burst can deliver 20 readings
# across 19 s; fitting those and reporting "per minute" multiplies timing
# noise by roughly 3x and produces enormous spurious rates. Points alone are
# therefore not sufficient - the samples must also SPAN enough time.
MIN_TREND_SPAN_MIN = 5.0
MAD_REJECT_THRESHOLD = 3.5
# Goodness-of-fit gate on the regression slope. Below R2_FLOOR the fitted
# slope is treated as scatter and contributes nothing; above R2_FULL it is
# trusted fully; between, it ramps.
R2_FLOOR = 0.25
R2_FULL = 0.65

# --- baseline ---
BASELINE_WINDOW = "-24h"
MIN_POINTS_FOR_BASELINE = 12

# --- moisture (relative saturation index, see UNITS above) ---
STATIC_MOISTURE_FLOOR = 40.0
STATIC_MOISTURE_CEIL = 80.0
MOISTURE_Z_SATURATION = 3.0
# OPERATING POINT, DISCLOSED. This constant does not have a single correct
# value; it selects a position on a lead-time / false-alarm trade-off curve,
# because soil moisture rises during EVERY rainstorm and velocity alone
# cannot separate "it is raining" from "this slope is failing". A sweep gave:
#     0.10 index/min -> 276 false alerts, 238 min mean lead, 0.50 precision
#     0.45 index/min ->  15 false alerts, 125 min mean lead, 1.00 precision
#     0.70 index/min ->   9 false alerts,  20 min mean lead, 1.00 precision
# FTG's inherited threshold corresponds to 0.67 index/min, i.e. 40 index
# points per hour, which soil does not reach - so FTG's moisture branch is
# effectively unreachable and its alerts come from the tilt branch alone.
# 0.45 was SELECTED from that curve on synthetic data. It is the single most
# important field-calibration target for any real deployment.
MOISTURE_VELOCITY_SATURATION = 0.45

# --- tilt ---
STATIC_TILT_FLOOR = 0.2                 # degrees from installed reference
STATIC_TILT_CEIL = 1.0
TILT_Z_SATURATION = 3.0
TILT_VELOCITY_SATURATION = 0.02         # deg/min (0.3 deg per 15-min window)
# Motion events per hour mapping to a full event-rate factor. Not empirically
# validated; depends on the accelerometer's activity threshold setting.
TILT_EVENT_RATE_SATURATION = 12.0
# Burst readings closer together than this belong to the same motion event.
EVENT_CLUSTER_GAP_S = 30.0

# --- tiers ---
WATCH_THRESHOLD = 0.40
WARNING_THRESHOLD = 0.60
HIGH_THRESHOLD = 0.60                   # what counts as "this modality is high"

# --- spatial corroboration ---
CORROBORATION_RADIUS_M = 50.0
MIN_CORROBORATING_NEIGHBOURS = 3
CORROBORATION_SCORE_MIN = 0.50
CORROBORATION_WINDOW = "-15m"

# --- optional relaxation ---
# Default OFF: critical requires BOTH modalities high plus corroboration.
# Trade-off, which must be reported: in rainfall-triggered failures moisture
# typically rises BEFORE tilt becomes measurable, so demanding tilt before
# critical costs lead time. Under the default, WARNING is the actionable tier.
ALLOW_SINGLE_MODALITY_CRITICAL = False
SINGLE_MODALITY_CRITICAL_MIN = 0.90


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ===========================================================================
# Stage 1 + 2: outlier rejection and trend
# ===========================================================================

@dataclass
class TrendResult:
    n_points: int
    span_min: float = 0.0
    slope: float = 0.0            # units per minute
    level: float = 0.0            # regression-fitted value at end of window
    r_squared: float = 0.0        # goodness of fit - see fit_quality()
    n_outliers_rejected: int = 0
    sufficient: bool = False
    reason: str = ""

    def fit_quality(self):
        """
        0-1 confidence that the fitted slope reflects a real trend rather
        than scatter.

        A degraded sensor produces sustained high-variance noise. The MAD
        filter does not catch this - MAD removes individual outliers, not
        general scatter - and random scatter readily produces a large
        spurious regression slope. Measured on the dataset, a faulty node in
        dry weather reached a moisture score of 1.000 through noise alone.

        R-squared separates the two cases directly: a genuine trend leaves
        small residuals about the fitted line, while noise leaves large ones.
        Slope is therefore discounted by how well the line actually fits.
        """
        return _clamp((self.r_squared - R2_FLOOR) / (R2_FULL - R2_FLOOR))


def _linear_regression(timestamps, values):
    """Returns (slope per minute, fitted level at window end, r_squared)."""
    n = len(values)
    if n < 2:
        return 0.0, (values[-1] if values else 0.0), 0.0
    t0 = timestamps[0]
    x = [(t - t0).total_seconds() / 60.0 for t in timestamps]
    x_mean = sum(x) / n
    y_mean = sum(values) / n
    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
    den = sum((xi - x_mean) ** 2 for xi in x)
    slope = num / den if den else 0.0
    intercept = y_mean - slope * x_mean

    ss_tot = sum((yi - y_mean) ** 2 for yi in values)
    ss_res = sum((yi - (intercept + slope * xi)) ** 2 for xi, yi in zip(x, values))
    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    return slope, intercept + slope * x[-1], max(0.0, r2)


def _reject_outliers(points):
    """
    Median-absolute-deviation filter. Drops samples more than
    MAD_REJECT_THRESHOLD robust-sigmas from the window median. MAD is used
    rather than mean/std because those are themselves distorted by the
    outlier being searched for.

    KNOWN LIMITATION: MAD scales with the window's own spread, so during a
    genuinely steep trend the spread is already large and a glitch landing on
    top of it may survive. Strong on quiet traces, weaker on active ones.
    """
    values = [v for _, v in points]
    med = _median(values)
    mad = _median([abs(v - med) for v in values])
    if mad == 0:
        return points, 0

    sigma = 1.4826 * mad
    kept = [(t, v) for (t, v) in points if abs(v - med) / sigma <= MAD_REJECT_THRESHOLD]
    if len(kept) < MIN_POINTS_FOR_TREND:
        return points, 0
    return kept, len(points) - len(kept)


def compute_trend(records, field_name):
    """
    Outlier rejection then regression over one field.

    Rejects the window as insufficient if either too few points OR too short
    a time span - see MIN_TREND_SPAN_MIN.
    """
    points = sorted(
        ((r["time"], r["value"]) for r in records if r["field"] == field_name),
        key=lambda p: p[0],
    )
    n = len(points)
    if n < MIN_POINTS_FOR_TREND:
        return TrendResult(n_points=n,
                           level=points[-1][1] if points else 0.0,
                           sufficient=False, reason="too-few-points")

    span = (points[-1][0] - points[0][0]).total_seconds() / 60.0
    if span < MIN_TREND_SPAN_MIN:
        # Enough points, but clustered in time. The level is still usable;
        # the slope is not.
        return TrendResult(n_points=n, span_min=span, slope=0.0,
                           level=points[-1][1], sufficient=False,
                           reason=f"span-too-short ({span:.1f} min)")

    cleaned, n_rejected = _reject_outliers(points)
    ts = [t for t, _ in cleaned]
    vs = [v for _, v in cleaned]
    slope, level, r2 = _linear_regression(ts, vs)

    return TrendResult(n_points=len(cleaned), span_min=span, slope=slope,
                       level=level, r_squared=r2, n_outliers_rejected=n_rejected,
                       sufficient=True, reason="ok")


# ===========================================================================
# Event rate (burst channel only)
# ===========================================================================

def compute_event_rate(records, field_name="tilt_event",
                       window_minutes=WINDOW_MINUTES):
    """
    Motion events per hour, from the interrupt-driven burst channel.

    Individual burst readings are clustered: readings closer together than
    EVENT_CLUSTER_GAP_S belong to the same motion event, since one interrupt
    produces many readings. Counting clusters rather than readings keeps the
    measure independent of how many samples a burst happens to contain.

    A count is robust in a way the value-based signals are not: no single bad
    reading can move it.
    """
    times = sorted(r["time"] for r in records if r["field"] == field_name)
    if not times:
        return 0.0, 0

    events = 1
    for a, b in zip(times, times[1:]):
        if (b - a).total_seconds() > EVENT_CLUSTER_GAP_S:
            events += 1

    rate_per_hour = events * (60.0 / window_minutes)
    return rate_per_hour, events


# ===========================================================================
# Stage 3: adaptive baseline
# ===========================================================================

@dataclass
class Baseline:
    mean: Optional[float]
    std: Optional[float]
    n_points: int
    is_cold: bool


def get_adaptive_baseline(query_api, bucket, org, node_id, field_name):
    """
    Per-node baseline from that node's own last 24 h.

    Only ever called with a HEARTBEAT field. Burst data must not be used
    here - an interrupt channel reports only when something is happening, so
    its statistics describe the node's active moments rather than its normal
    state.
    """
    flux = f'''
        from(bucket: "{bucket}")
        |> range(start: {BASELINE_WINDOW})
        |> filter(fn: (r) => r["_measurement"] == "node_telemetry")
        |> filter(fn: (r) => r["node_id"] == "{node_id}")
        |> filter(fn: (r) => r["_field"] == "{field_name}")
    '''
    tables = query_api.query(flux, org=org)
    values = [rec.get_value() for t in tables for rec in t.records]
    n = len(values)
    if n < MIN_POINTS_FOR_BASELINE:
        return Baseline(None, None, n, is_cold=True)
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    return Baseline(mean, std, n, is_cold=False)


# ===========================================================================
# Stage 4: per-modality score
# ===========================================================================

@dataclass
class ModalityScore:
    score: float
    level_factor: float
    velocity_factor: float
    event_factor: float
    baseline_used: str
    slope: float
    level: float
    detail: str


def compute_modality_score(trend: TrendResult, baseline: Baseline,
                           static_floor, static_ceil,
                           velocity_saturation, z_saturation,
                           event_rate=0.0, event_saturation=None):
    """
    One modality's 0-1 score.

      level_factor    how elevated the value is, taking the LARGER of
                      "unusual for this node" (adaptive) and "high in
                      absolute terms" (static).

                      Both terms are required. A purely adaptive term
                      normalises away genuine absolute risk, since a
                      chronically saturated slope is unstable even though
                      saturation is normal FOR IT.

      change_factor   the larger of the regression velocity and, where
                      applicable, the interrupt event rate.

      score = change_factor * (0.5 + 0.5 * level_factor)

    CHANGE drives the score; LEVEL amplifies it. An earlier formulation let
    level alone carry the score, which meant a completely static wet slope
    scored 0.599 - just under the warning line, so noise alone tipped it
    over. That is physically wrong: saturated soil is a precondition for
    failure, not evidence of it. Multiplying by change means a static reading
    scores zero however extreme, while the level term scales that change by
    how dangerous the current state is.
    """
    # Level is usable even when the slope is not (e.g. a short burst span).
    absolute = _clamp((trend.level - static_floor) / (static_ceil - static_floor))

    if not baseline.is_cold and baseline.std and baseline.std > 0:
        z = (trend.level - baseline.mean) / baseline.std
        level_factor = max(_clamp(z / z_saturation), absolute)
        used = "adaptive"
    else:
        level_factor = absolute
        used = "static-fallback"

    # Slope is discounted by goodness of fit, so scatter cannot masquerade
    # as a trend (see TrendResult.fit_quality).
    velocity_factor = (_clamp(trend.slope / velocity_saturation) * trend.fit_quality()
                       if trend.sufficient else 0.0)

    event_factor = 0.0
    if event_saturation:
        event_factor = _clamp(event_rate / event_saturation)

    change_factor = max(velocity_factor, event_factor)
    score = _clamp(change_factor * (0.5 + 0.5 * level_factor))

    detail = trend.reason
    if not trend.sufficient and event_factor > 0:
        detail += "; slope unusable, event rate carried the score"

    return ModalityScore(score, level_factor, velocity_factor, event_factor,
                         used, trend.slope, trend.level, detail)


# ===========================================================================
# Stage 5: spatial corroboration by physical distance
# ===========================================================================

@dataclass
class CorroborationResult:
    corroborated: bool
    n_neighbours_in_range: int
    n_agreeing: int
    reason: str


def find_neighbours(pg_engine, node_id, radius_m=CORROBORATION_RADIUS_M):
    """
    Landslide nodes within radius_m, by great-circle distance.

    Distance, not zone_id: a zone is an administrative label in the database
    and carries no guarantee of proximity. Two nodes in one zone may sit on
    different slopes; two nodes in different zones may be metres apart.
    """
    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT latitude, longitude FROM sensor_nodes WHERE id = :nid"),
            {"nid": node_id}).fetchone()
        if not row:
            return []
        lat0, lon0 = float(row[0]), float(row[1])
        others = conn.execute(
            text("""SELECT id, latitude, longitude FROM sensor_nodes
                    WHERE node_type = 'landslide' AND id != :nid
                      AND latitude IS NOT NULL AND longitude IS NOT NULL"""),
            {"nid": node_id}).fetchall()

    near = [(str(oid), haversine_m(lat0, lon0, float(la), float(lo)))
            for oid, la, lo in others]
    near = [p for p in near if p[1] <= radius_m]
    near.sort(key=lambda p: p[1])
    return near


def _score_node_quick(records):
    """Cold-baseline score for a neighbour, used only to answer 'is this node
    also elevated right now'. A full adaptive lookup per neighbour per
    request would be expensive and is not needed for a yes/no."""
    cold = Baseline(None, None, 0, is_cold=True)
    m = compute_modality_score(
        compute_trend(records, "moisture_index"), cold,
        STATIC_MOISTURE_FLOOR, STATIC_MOISTURE_CEIL,
        MOISTURE_VELOCITY_SATURATION, MOISTURE_Z_SATURATION)
    rate, _ = compute_event_rate(records)
    t = compute_modality_score(
        compute_trend(records, "tilt_deg"), cold,
        STATIC_TILT_FLOOR, STATIC_TILT_CEIL,
        TILT_VELOCITY_SATURATION, TILT_Z_SATURATION,
        event_rate=rate, event_saturation=TILT_EVENT_RATE_SATURATION)
    return max(m.score, t.score)


def check_corroboration(pg_engine, query_api, bucket, org, node_id):
    """
    Requires MIN_CORROBORATING_NEIGHBOURS neighbours inside
    CORROBORATION_RADIUS_M to independently show an elevated score.

    A node with too few neighbours in range cannot be corroborated and is
    reported as "insufficient-neighbours", so under-provisioned deployments
    are visible rather than silently unable to escalate.
    """
    neighbours = find_neighbours(pg_engine, node_id)
    if len(neighbours) < MIN_CORROBORATING_NEIGHBOURS:
        return CorroborationResult(
            False, len(neighbours), 0,
            f"insufficient-neighbours ({len(neighbours)} within "
            f"{CORROBORATION_RADIUS_M:.0f} m, need {MIN_CORROBORATING_NEIGHBOURS})")

    agreeing = 0
    for nid, _d in neighbours:
        flux = f'''
            from(bucket: "{bucket}")
            |> range(start: {CORROBORATION_WINDOW})
            |> filter(fn: (r) => r["_measurement"] == "node_telemetry")
            |> filter(fn: (r) => r["node_id"] == "{nid}")
            |> filter(fn: (r) => r["_field"] == "moisture_index"
                              or r["_field"] == "tilt_deg"
                              or r["_field"] == "tilt_event")
        '''
        tables = query_api.query(flux, org=org)
        recs = [{"time": r.get_time(), "field": r.get_field(), "value": r.get_value()}
                for t in tables for r in t.records]
        if _score_node_quick(recs) >= CORROBORATION_SCORE_MIN:
            agreeing += 1

    return CorroborationResult(
        agreeing >= MIN_CORROBORATING_NEIGHBOURS, len(neighbours), agreeing,
        f"{agreeing}/{len(neighbours)} neighbours agree "
        f"(need {MIN_CORROBORATING_NEIGHBOURS})")


# ===========================================================================
# Stage 6: combine
# ===========================================================================

@dataclass
class HazardAssessment:
    node_id: str
    tier: str                     # normal | watch | warning | critical
    moisture: ModalityScore
    tilt: ModalityScore
    event_rate_per_hour: float
    corroboration: Optional[CorroborationResult]
    reason: str


def combine_scores(moisture: ModalityScore, tilt: ModalityScore):
    """
    Tier reached BEFORE corroboration, and whether corroboration is needed.

      both modalities high  -> candidate for critical, consult neighbours
      one modality high     -> warning, no neighbour check
      otherwise             -> watch / normal on the higher score
    """
    m_high = moisture.score >= HIGH_THRESHOLD
    t_high = tilt.score >= HIGH_THRESHOLD
    top = max(moisture.score, tilt.score)

    if m_high and t_high:
        return "critical-candidate", True, "both-modalities-high"

    if ALLOW_SINGLE_MODALITY_CRITICAL and top >= SINGLE_MODALITY_CRITICAL_MIN:
        which = "moisture" if moisture.score >= tilt.score else "tilt"
        return "critical-candidate", True, f"single-modality-extreme ({which})"

    if m_high or t_high:
        which = "moisture" if m_high else "tilt"
        return "warning", False, f"single-modality-high ({which})"

    if top >= WATCH_THRESHOLD:
        return "watch", False, "elevated-below-warning"

    return "normal", False, "nominal"


def evaluate_hazard(pg_engine, query_api, bucket, org, node_id, records):
    """
    Full ACS evaluation for one node over one window.

    `records` is the 15-minute window, containing:
        moisture_index   regular schedule
        tilt_deg         regular heartbeat
        tilt_event       interrupt bursts (may be absent)
    """
    m_trend = compute_trend(records, "moisture_index")
    t_trend = compute_trend(records, "tilt_deg")
    event_rate, n_events = compute_event_rate(records, "tilt_event")

    m_base = (get_adaptive_baseline(query_api, bucket, org, node_id, "moisture_index")
              if m_trend.sufficient else Baseline(None, None, 0, True))
    # Baseline from the HEARTBEAT channel only - never from bursts.
    t_base = (get_adaptive_baseline(query_api, bucket, org, node_id, "tilt_deg")
              if t_trend.sufficient else Baseline(None, None, 0, True))

    moisture = compute_modality_score(
        m_trend, m_base, STATIC_MOISTURE_FLOOR, STATIC_MOISTURE_CEIL,
        MOISTURE_VELOCITY_SATURATION, MOISTURE_Z_SATURATION)

    tilt = compute_modality_score(
        t_trend, t_base, STATIC_TILT_FLOOR, STATIC_TILT_CEIL,
        TILT_VELOCITY_SATURATION, TILT_Z_SATURATION,
        event_rate=event_rate, event_saturation=TILT_EVENT_RATE_SATURATION)

    tier, needs_corr, reason = combine_scores(moisture, tilt)
    corr = None

    if needs_corr:
        corr = check_corroboration(pg_engine, query_api, bucket, org, node_id)
        if corr.corroborated:
            tier = "critical"
            reason = f"{reason}; {corr.reason}"
        else:
            tier = "warning"
            reason = f"{reason}; not escalated: {corr.reason}"

    return HazardAssessment(node_id=node_id, tier=tier, moisture=moisture,
                            tilt=tilt, event_rate_per_hour=event_rate,
                            corroboration=corr, reason=reason)
