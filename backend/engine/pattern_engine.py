"""
pattern_engine.py

Pattern-Classified Hazard Assessment (PCHA).

WHY THIS REPLACES THE SCORING STAGE
-----------------------------------
The previous decision stage computed a 0-1 score and compared it against
saturation constants. That design had a structural problem: soil moisture
rises during every rainstorm, so a constant chosen for one rainfall rate
misfires on another. Measured across two synthetic datasets whose wetting
rates differed by roughly 4x, the same constant produced either near-zero
lead time or hundreds of false alerts, with no value that worked for both.

This stage decides on SHAPE instead of magnitude. Is moisture rising or
flat? Is tilt speeding up or slowing down? Shape is far more stable across
different soils and rainfall intensities than any absolute rate, so the
decision no longer depends on where an arbitrary number happens to sit.


CREEP THEORY - THE BACKBONE OF THE TILT CLASSIFIER
--------------------------------------------------
Ground movement before failure passes through three stages:

    primary    - rate DECREASES over time   (slope is settling; safe)
    secondary  - rate is CONSTANT           (steady movement; watch)
    tertiary   - rate INCREASES until failure (failing; alert)

The previous engine measured tilt rate only, so primary and tertiary creep
at the same instantaneous rate scored identically - even though one means
the slope is stabilising and the other means it is about to fail. This
engine measures ACCELERATION as well, which is what separates them.

Published thresholds (Uchimura et al., and subsequent model-test work):
    precaution at 0.01 deg/hour
    warning    at 0.1  deg/hour
In the tertiary stage the rate starts between 0.01 and 0.1 deg/h and exceeds
0.1 deg/h near failure, with roughly one hour of warning at 0.1 deg/h.


TWO MOISTURE WINDOWS
--------------------
Rainfall thresholds for landslides are expressed in DAYS, not minutes. For
Matara district, the reported chance of a landslide exceeds 90% when the
day's rainfall approaches 300 mm with about 80 mm on the previous day. Today's
rain matters only in the context of yesterday's, so a 15-minute window alone
cannot distinguish a harmless shower from rain falling on already-saturated
ground. Four of the nine moisture patterns are invisible without both windows.


KNOWN LIMITATION - TRANSLATIONAL MOVEMENT
-----------------------------------------
An accelerometer senses the direction of gravity, so it detects ROTATION.
If a block of soil slides down-slope without rotating, the sensor's
orientation does not change and the movement is invisible. Tilt sensors are
point sensors and cannot extract deformations where there is no inclination,
i.e. translational landslides. The interrupt burst channel catches the
transient acceleration when movement starts suddenly, but steady or very slow
translation remains undetectable by this sensor type. Detecting it requires
extensometers, GNSS or borehole inclinometer chains.
"""

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, List

from sqlalchemy import text

import acs_engine as base   # reuse trend regression, MAD rejection, haversine

# ===========================================================================
# Windows
# ===========================================================================

MOISTURE_SHORT_MIN = 15
MOISTURE_LONG_HOURS = 24
# The averaging window is set by SENSOR NOISE, not by preference. With about
# 0.09 deg of tilt jitter per reading (from 0.002 g axis noise) and a 5-minute
# heartbeat, the standard error of the fitted slope is:
#      1 h  -> 0.090 deg/h   cannot even resolve the 0.1 deg/h warning level
#      2 h  -> 0.032 deg/h   resolves 0.1 deg/h
#     12 h  -> 0.002 deg/h   resolves 0.01 deg/h
# A 1-hour window therefore reports pure noise as creep, which it did: dry
# ground classified as secondary creep 926 times in testing.
TILT_RATE_WINDOW_MIN = 120
TILT_LONG_HOURS = 6                # for detecting "was moving, now stopped"

# ===========================================================================
# Tilt thresholds - from published field work, not fitted to our data
# ===========================================================================

TILT_PRECAUTION_DEG_PER_H = 0.01
TILT_WARNING_DEG_PER_H = 0.10
# Acceleration is judged by comparing the rate in the second half of the
# window against the first half. A relative change smaller than this is
# treated as steady (secondary creep).
TILT_ACCEL_REL_TOLERANCE = 0.25
# A fitted slope is only believed when it is large compared with its own
# standard error. This adapts to however noisy a given node actually is,
# rather than assuming a fixed window is sufficient.
SLOPE_SIGNIFICANCE = 2.0

# ===========================================================================
# Moisture - all change tests are relative to the node's OWN variability,
# so no absolute wetting-rate constant is required anywhere.
# ===========================================================================

MOISTURE_CHANGE_SIGMA = 1.5        # change counts as real at 1.5 std of own baseline
MOISTURE_HIGH_SIGMA = 1.0          # "high for this node" at 1 std above own mean
MOISTURE_HIGH_ABSOLUTE = 60.0      # fallback when no baseline exists yet
MIN_FIT_R2 = 0.25                  # below this a slope is scatter, not trend

# Quality gates
BOUNCING_RESIDUAL_SIGMA = 3.0      # residual scatter this far above normal = faulty
DEAD_SENSOR_VALUE = 0.5            # pinned at ~zero


# ===========================================================================
# Pattern labels
# ===========================================================================

MOISTURE_PATTERNS = [
    "dry_flat", "brief_shower", "sustained_wetting",
    "saturated_flat", "rain_on_wet", "draining",
    "glitch", "bouncing", "dead",
]

TILT_PATTERNS = [
    "stable", "primary_creep", "secondary_creep", "tertiary_creep",
    "near_failure", "knock", "thermal", "stopped",
]

MOISTURE_UNRELIABLE = {"bouncing", "dead"}
TILT_UNRELIABLE = {"knock", "thermal"}


# ===========================================================================
# Decision matrix - 6 trustworthy moisture patterns x 6 trustworthy tilt
#
# N  = normal      W  = watch
# !  = warning     !! = critical      SD = stand_down
# ===========================================================================

MATRIX = {
    #                  dry_flat  brief_shower  sustained  saturated  rain_on_wet  draining
    "stable":         ["normal", "normal",  "watch",    "watch",   "warning",  "normal"],
    "primary_creep":  ["normal", "normal",  "watch",    "watch",   "warning",  "normal"],
    "secondary_creep":["watch",  "watch",   "warning",  "warning", "warning",  "watch"],
    "tertiary_creep": ["warning","warning", "critical", "critical","critical", "critical"],
    "near_failure":   ["critical","critical","critical","critical","critical", "critical"],
    "stopped":        ["stand_down","stand_down","watch","watch",  "watch",    "stand_down"],
}

MOISTURE_ORDER = ["dry_flat", "brief_shower", "sustained_wetting",
                  "saturated_flat", "rain_on_wet", "draining"]

# Combinations the hydrological model does not explain. Not impossible - the
# two sensors are independent - but movement without any water signal implies
# a cause outside this system's scope (seismic activity, excavation,
# undercutting). These are still alerted on, but flagged so an operator knows
# the system is seeing something it cannot account for.
UNEXPLAINED = {
    ("tertiary_creep", "dry_flat"),
    ("tertiary_creep", "brief_shower"),
    ("near_failure", "dry_flat"),
    ("near_failure", "brief_shower"),
}


# ===========================================================================
# Helpers
# ===========================================================================

def _series(records, field):
    return sorted(((r["time"], r["value"]) for r in records if r["field"] == field),
                  key=lambda p: p[0])


def _slope_and_fit(points):
    """Returns (slope per minute, fitted end level, r2, n_rejected, n)."""
    if len(points) < base.MIN_POINTS_FOR_TREND:
        return 0.0, (points[-1][1] if points else 0.0), 0.0, 0, len(points)
    cleaned, n_rej = base._reject_outliers(points)
    ts = [t for t, _ in cleaned]
    vs = [v for _, v in cleaned]
    slope, level, r2 = base._linear_regression(ts, vs)
    return slope, level, r2, n_rej, len(cleaned)


def _slope_std_error(points):
    """
    Standard error of the fitted slope, in units per minute.

        SE = s_residual / sqrt( sum (x - xbar)^2 )

    Comparing the slope against this is what separates a real trend from a
    line fitted through noise, and it adapts to each node's actual noise
    level instead of assuming a window length is adequate.
    """
    if len(points) < 3:
        return float("inf")
    ts = [t for t, _ in points]
    vs = [v for _, v in points]
    t0 = ts[0]
    x = [(t - t0).total_seconds() / 60.0 for t in ts]
    xbar = sum(x) / len(x)
    sxx = sum((xi - xbar) ** 2 for xi in x)
    if sxx <= 0:
        return float("inf")
    slope, _, _ = base._linear_regression(ts, vs)
    ybar = sum(vs) / len(vs)
    intercept = ybar - slope * xbar
    dof = len(vs) - 2
    if dof <= 0:
        return float("inf")
    ss_res = sum((v - (intercept + slope * xi)) ** 2 for xi, v in zip(x, vs))
    return math.sqrt(ss_res / dof) / math.sqrt(sxx)


def _residual_sigma(points):
    """Standard deviation of residuals about the fitted line."""
    if len(points) < 3:
        return 0.0
    ts = [t for t, _ in points]
    vs = [v for _, v in points]
    slope, _, _ = base._linear_regression(ts, vs)
    t0 = ts[0]
    x = [(t - t0).total_seconds() / 60.0 for t in ts]
    mean_x = sum(x) / len(x)
    mean_y = sum(vs) / len(vs)
    intercept = mean_y - slope * mean_x
    res = [v - (intercept + slope * xi) for xi, v in zip(x, vs)]
    m = sum(res) / len(res)
    return math.sqrt(sum((r - m) ** 2 for r in res) / len(res))


# ===========================================================================
# Moisture classifier
# ===========================================================================

@dataclass
class MoisturePattern:
    pattern: str
    short_change: float          # index points across the short window
    long_change: float           # index points across 24 h
    level: float
    is_high: bool
    baseline_std: Optional[float]
    detail: str


def classify_moisture(short_pts, long_pts, baseline):
    """
    Nine patterns. All change tests are expressed in units of the node's own
    baseline variability, so no absolute wetting-rate constant appears here -
    which is precisely the constant that made the previous scoring stage
    unstable between datasets.
    """
    if len(short_pts) < base.MIN_POINTS_FOR_TREND:
        return MoisturePattern("dry_flat", 0, 0, 0, False, None, "insufficient-data")

    sigma = (baseline.std if (baseline and not baseline.is_cold and baseline.std)
             else None)
    ref_sigma = sigma if (sigma and sigma > 0.2) else 1.0

    s_slope, s_level, s_r2, s_rej, s_n = _slope_and_fit(short_pts)
    short_span = (short_pts[-1][0] - short_pts[0][0]).total_seconds() / 60.0
    short_change = s_slope * short_span

    if long_pts and len(long_pts) >= base.MIN_POINTS_FOR_TREND:
        l_slope, l_level, l_r2, _, _ = _slope_and_fit(long_pts)
        long_span = (long_pts[-1][0] - long_pts[0][0]).total_seconds() / 60.0
        long_change = l_slope * long_span
    else:
        l_r2, long_change = 0.0, 0.0

    # --- sensor-health checks first -------------------------------------
    values = [v for _, v in short_pts]

    if all(v <= DEAD_SENSOR_VALUE for v in values):
        return MoisturePattern("dead", short_change, long_change, s_level,
                               False, sigma, "readings pinned at zero")

    resid = _residual_sigma(short_pts)
    if resid > BOUNCING_RESIDUAL_SIGMA * ref_sigma and s_r2 < MIN_FIT_R2:
        return MoisturePattern("bouncing", short_change, long_change, s_level,
                               False, sigma,
                               f"residual {resid:.1f} vs normal {ref_sigma:.1f}")

    if s_rej > 0 and s_r2 < MIN_FIT_R2:
        return MoisturePattern("glitch", short_change, long_change, s_level,
                               False, sigma, f"{s_rej} outlier(s) rejected")

    # --- antecedent level -----------------------------------------------
    # "Already wet" must be judged from the ground's condition BEFORE the
    # current short window, not from its level now. Rain naturally raises the
    # level, so using the current value would classify every shower as rain
    # falling on saturated ground. This mirrors how rainfall thresholds are
    # actually expressed: today's rain matters in the context of yesterday's.
    cutoff = short_pts[0][0]
    antecedent = [v for t, v in long_pts if t < cutoff]
    if antecedent:
        ante_level = sum(antecedent) / len(antecedent)
    else:
        ante_level = s_level - short_change      # fall back to window start

    if sigma and baseline.mean is not None:
        is_high = ante_level > baseline.mean + MOISTURE_HIGH_SIGMA * sigma
    else:
        is_high = ante_level > MOISTURE_HIGH_ABSOLUTE

    thresh = MOISTURE_CHANGE_SIGMA * ref_sigma
    short_rising = short_change > thresh and s_r2 >= MIN_FIT_R2
    short_falling = short_change < -thresh and s_r2 >= MIN_FIT_R2
    long_rising = long_change > thresh and l_r2 >= MIN_FIT_R2
    long_falling = long_change < -thresh and l_r2 >= MIN_FIT_R2

    # --- the six hazard patterns ----------------------------------------
    if short_rising and is_high:
        p = "rain_on_wet"
    elif long_rising:
        p = "sustained_wetting"
    elif short_rising:
        p = "brief_shower"
    elif short_falling or long_falling:
        p = "draining"
    elif is_high:
        p = "saturated_flat"
    else:
        p = "dry_flat"

    return MoisturePattern(p, short_change, long_change, s_level, is_high, sigma,
                           f"short {short_change:+.1f}, 24h {long_change:+.1f}, "
                           f"antecedent {ante_level:.1f}, thresh {thresh:.1f}")


# ===========================================================================
# Tilt classifier
# ===========================================================================

@dataclass
class TiltPattern:
    pattern: str
    rate_deg_per_h: float
    accel_ratio: float           # second-half rate / first-half rate
    accelerating: bool
    decelerating: bool
    detail: str


def classify_tilt(rate_pts, long_pts, baseline, had_knock=False):
    """
    Eight patterns, built on creep theory.

    Rate alone cannot distinguish primary creep (slowing, safe) from tertiary
    creep (speeding up, failing). Acceleration is therefore estimated by
    splitting the rate window in half and comparing the fitted slope of the
    second half against the first.
    """
    if len(rate_pts) < base.MIN_POINTS_FOR_TREND:
        return TiltPattern("stable", 0.0, 1.0, False, False, "insufficient-data")

    slope, level, r2, n_rej, n = _slope_and_fit(rate_pts)
    rate_h = slope * 60.0

    se = _slope_std_error(rate_pts)
    significant = (se > 0) and (abs(slope) / se >= SLOPE_SIGNIFICANCE)

    # --- artifacts ------------------------------------------------------
    if had_knock or (n_rej > 0 and r2 < MIN_FIT_R2):
        return TiltPattern("knock", rate_h, 1.0, False, False,
                           f"{n_rej} spike(s) rejected")

    # Thermal drift: small oscillation within the node's own normal band and
    # no coherent trend. MEMS sensors drift with temperature, and outdoor
    # temperature cycles daily, so this appears as apparent tilt that is not
    # ground movement.
    if (abs(rate_h) < TILT_PRECAUTION_DEG_PER_H and r2 < MIN_FIT_R2
            and baseline and not baseline.is_cold and baseline.std
            and abs(level - (baseline.mean or 0)) < 2 * baseline.std):
        return TiltPattern("thermal", rate_h, 1.0, False, False,
                           "within own band, no coherent trend")

    # --- acceleration ---------------------------------------------------
    mid = len(rate_pts) // 2
    first, second = rate_pts[:mid], rate_pts[mid:]
    if len(first) >= 2 and len(second) >= 2:
        r1 = _slope_and_fit(first)[0] * 60.0
        r2h = _slope_and_fit(second)[0] * 60.0
    else:
        r1 = r2h = rate_h

    if abs(r1) < 1e-9:
        ratio = 1.0 if abs(r2h) < 1e-9 else 10.0
    else:
        ratio = r2h / r1

    accelerating = ratio > (1.0 + TILT_ACCEL_REL_TOLERANCE) and r2h > 0
    decelerating = ratio < (1.0 - TILT_ACCEL_REL_TOLERANCE) and r1 > 0

    # --- was moving, now stopped ----------------------------------------
    if long_pts and len(long_pts) >= base.MIN_POINTS_FOR_TREND:
        l_rate_h = _slope_and_fit(long_pts)[0] * 60.0
        if (l_rate_h > TILT_PRECAUTION_DEG_PER_H
                and abs(rate_h) < TILT_PRECAUTION_DEG_PER_H):
            return TiltPattern("stopped", rate_h, ratio, False, True,
                               f"6h rate {l_rate_h:.3f} deg/h, now {rate_h:.3f}")

    # --- creep stages ---------------------------------------------------
    # A slope indistinguishable from zero given its own noise is not movement,
    # however large the fitted number happens to be.
    if not significant:
        return TiltPattern("stable", rate_h, ratio, False, False,
                           f"{rate_h:+.4f} deg/h not significant "
                           f"(SE {se*60:.4f} deg/h)")

    if abs(rate_h) < TILT_PRECAUTION_DEG_PER_H:
        return TiltPattern("stable", rate_h, ratio, False, False,
                           f"{rate_h:+.4f} deg/h below precaution threshold")

    if rate_h >= TILT_WARNING_DEG_PER_H and accelerating:
        return TiltPattern("near_failure", rate_h, ratio, True, False,
                           f"{rate_h:.3f} deg/h and accelerating")

    if accelerating:
        return TiltPattern("tertiary_creep", rate_h, ratio, True, False,
                           f"{rate_h:.3f} deg/h, rate rising (x{ratio:.2f})")

    if decelerating:
        return TiltPattern("primary_creep", rate_h, ratio, False, True,
                           f"{rate_h:.3f} deg/h, rate falling (x{ratio:.2f})")

    return TiltPattern("secondary_creep", rate_h, ratio, False, False,
                       f"{rate_h:.3f} deg/h, steady")


# ===========================================================================
# Decision
# ===========================================================================

@dataclass
class Assessment:
    node_id: str
    tier: str                       # normal watch warning critical stand_down unreliable
    moisture: MoisturePattern
    tilt: TiltPattern
    event_rate_per_hour: float
    corroboration: Optional[object]
    unexplained: bool
    reason: str


def decide(moisture: MoisturePattern, tilt: TiltPattern):
    """
    Applies the matrix, with fault handling.

    A failed moisture sensor must never be able to silence a real landslide,
    so a node with unusable moisture can still reach critical on tilt alone.
    """
    m_bad = moisture.pattern in MOISTURE_UNRELIABLE
    t_bad = tilt.pattern in TILT_UNRELIABLE

    if m_bad and t_bad:
        return ("unreliable", False,
                f"both channels unusable (moisture {moisture.pattern}, "
                f"tilt {tilt.pattern}) - node needs service")

    if m_bad:
        row = MATRIX.get(tilt.pattern)
        if row is None:
            return ("unreliable", False, f"moisture {moisture.pattern}, tilt artifact")
        # Judge on tilt alone, using the most neutral moisture column.
        tier = row[MOISTURE_ORDER.index("dry_flat")]
        return (tier, False,
                f"moisture sensor suspect ({moisture.pattern}); decided on tilt "
                f"{tilt.pattern}")

    if t_bad:
        # Judge on moisture alone, using the stable tilt row. A moisture
        # glitch has no matrix column, so fall back to the neutral one.
        col = moisture.pattern if moisture.pattern in MOISTURE_ORDER else "dry_flat"
        tier = MATRIX["stable"][MOISTURE_ORDER.index(col)]
        return (tier, False,
                f"tilt reading rejected ({tilt.pattern}); decided on moisture "
                f"{col}")

    if moisture.pattern == "glitch":
        # One bad sample, rest of the window fine - treat level as usable but
        # do not trust the trend.
        tier = MATRIX[tilt.pattern][MOISTURE_ORDER.index("dry_flat")]
        return (tier, False, f"moisture glitch filtered; decided on tilt "
                             f"{tilt.pattern}")

    row = MATRIX.get(tilt.pattern)
    if row is None:
        return ("normal", False, "unclassified")

    tier = row[MOISTURE_ORDER.index(moisture.pattern)]
    unexp = (tilt.pattern, moisture.pattern) in UNEXPLAINED
    reason = f"{tilt.pattern} + {moisture.pattern}"
    if unexp:
        reason += " (movement without a water signal - cause outside model)"
    return (tier, unexp, reason)


def evaluate(pg_engine, query_api, bucket, org, node_id, now,
             short_records, long_moisture, tilt_rate_records, tilt_long_records,
             moisture_baseline, tilt_baseline):
    """
    Full assessment for one node at one instant.

    Spatial corroboration is consulted only for a critical candidate, and only
    to confirm it. Note the asymmetry: neighbours AGREEING confirms a movement
    signal, but during rainfall neighbours agreeing is evidence it is merely
    raining. Corroboration is therefore applied to the tilt-driven critical
    tiers, not used to escalate moisture-only patterns.
    """
    m_short = _series(short_records, "moisture_index")
    m_long = _series(long_moisture, "moisture_index")
    t_rate = _series(tilt_rate_records, "tilt_deg")
    t_long = _series(tilt_long_records, "tilt_deg")

    moisture = classify_moisture(m_short, m_long, moisture_baseline)
    tilt = classify_tilt(t_rate, t_long, tilt_baseline)

    event_rate, _ = base.compute_event_rate(short_records, "tilt_event",
                                            MOISTURE_SHORT_MIN)

    tier, unexplained, reason = decide(moisture, tilt)

    corr = None
    if tier == "critical":
        corr = base.check_corroboration(pg_engine, query_api, bucket, org, node_id)
        if not corr.corroborated:
            tier = "warning"
            reason += f"; held at warning: {corr.reason}"
        else:
            reason += f"; {corr.reason}"

    return Assessment(node_id=node_id, tier=tier, moisture=moisture, tilt=tilt,
                      event_rate_per_hour=event_rate, corroboration=corr,
                      unexplained=unexplained, reason=reason)
