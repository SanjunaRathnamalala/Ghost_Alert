"""Raw values -> what PCHA reads (decision 2.3: nodes send raw, the backend converts)."""
import math

# A resting accelerometer measures about 1 g. Far outside this range means a bad reading.
GRAVITY_MIN_MG = 500.0
GRAVITY_MAX_MG = 1500.0


def accel_mg(raw_tenths: int) -> float:
    """Packet accel values are in tenths of mg."""
    return raw_tenths / 10.0


def tilt_deg(ax_mg: float, ay_mg: float, az_mg: float):
    """Angle between measured gravity and the node's vertical axis: theta = arccos(az/|a|).
    Returns None when the reading cannot be a resting gravity vector."""
    mag = math.sqrt(ax_mg * ax_mg + ay_mg * ay_mg + az_mg * az_mg)
    if not (GRAVITY_MIN_MG <= mag <= GRAVITY_MAX_MG):
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, az_mg / mag))))


def moisture_index(raw: int, dry_raw: int, wet_raw: int):
    """0 = as dry as calibration 'dry', 100 = as wet as calibration 'wet'.
    Capacitive sensors give a LOWER reading when wetter."""
    if dry_raw == wet_raw:
        return None
    idx = (dry_raw - raw) / (dry_raw - wet_raw) * 100.0
    return max(0.0, min(100.0, idx))
