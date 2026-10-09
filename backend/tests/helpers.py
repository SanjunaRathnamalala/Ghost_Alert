import random
import uuid
from datetime import datetime, timedelta, timezone

from app.store import MemoryStore, Reading

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def new_id():
    return str(uuid.uuid4())


def fill(store: MemoryStore, node_id, moisture_fn, tilt_fn, hours=26, now=NOW, seed=1,
         m_noise=0.3, t_noise=0.003):
    """moisture every 1 min, tilt every 5 min, for `hours` before `now`.
    moisture_fn(h) / tilt_fn(h) take hours-before-now (h >= 0) and return the clean value."""
    rnd = random.Random(seed)
    readings = []
    start = now - timedelta(hours=hours)
    minutes = int(hours * 60)
    for i in range(minutes + 1):
        t = start + timedelta(minutes=i)
        h = (now - t).total_seconds() / 3600
        f = {"moisture_index": moisture_fn(h) + rnd.gauss(0, m_noise)}
        if i % 5 == 0:
            f["tilt_deg"] = tilt_fn(h) + rnd.gauss(0, t_noise)
        readings.append(Reading(node_id, t, f))
    store.write(readings)


def flat(v):
    return lambda h: v
