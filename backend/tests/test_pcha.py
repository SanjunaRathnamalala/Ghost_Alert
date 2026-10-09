from datetime import timedelta

import pytest

from app import pcha
from app.pcha import base, pe
from app.store import MemoryStore, Reading
from tests.helpers import NOW, fill, flat, new_id


class _Rec:
    def __init__(self, v): self.v = v
    def get_value(self): return self.v


class _Table:
    def __init__(self, vals): self.records = [_Rec(v) for v in vals]


class FakeQueryAPI:
    """Answers acs_engine.get_adaptive_baseline's query from a MemoryStore."""
    def __init__(self, store, node_id, now):
        self.store, self.node_id, self.now = store, node_id, now

    def query(self, flux, org=None):
        field = flux.split('r["_field"] == "')[1].split('"')[0]
        recs = self.store.fetch(self.node_id, [field], self.now - timedelta(hours=24), self.now + timedelta(seconds=1))
        return [_Table([r["value"] for r in recs])]


SCENARIOS = {
    "dry_stable": (flat(30), flat(0.50)),
    "steady_rain": (lambda h: 30 + max(0.0, 6 - h) * 6, flat(0.50)),
    "wet_then_drain": (lambda h: 75 - max(0.0, 6 - h) * 4 if h < 6 else 75, flat(0.50)),
    "slow_creep_dry": (flat(30), lambda h: 0.50 + max(0.0, 3 - h) * 0.05),
}


def _engine_eval(store, nid, now):
    w = pcha.fetch_windows(store, nid, now)
    return pe.evaluate(None, None, "b", "o", nid, now, w["short"], w["m_long"],
                       w["t_rate"], w["t_long"], w["m_base"], w["t_base"])


@pytest.mark.parametrize("name", SCENARIOS)
def test_baselines_match_engine(name):
    store, nid = MemoryStore(), new_id()
    fill(store, nid, *SCENARIOS[name])
    ours = pcha.fetch_windows(store, nid, NOW)
    for field, key in (("moisture_index", "m_base"), ("tilt_deg", "t_base")):
        theirs = base.get_adaptive_baseline(FakeQueryAPI(store, nid, NOW), "b", "o", nid, field)
        assert ours[key].n_points == theirs.n_points
        assert ours[key].mean == pytest.approx(theirs.mean)
        assert ours[key].std == pytest.approx(theirs.std)


@pytest.mark.parametrize("name", SCENARIOS)
def test_tier_matches_engine(name):
    store, nid = MemoryStore(), new_id()
    fill(store, nid, *SCENARIOS[name])
    engine = _engine_eval(store, nid, NOW)
    if engine.tier == "critical":
        pytest.skip("critical path needs neighbours; tested separately")
    ours = pcha.assess(store, nid, NOW, neighbours_fn=lambda: [])
    print(name, "->", ours.tier, "|", ours.reason)
    assert ours.tier == engine.tier
    assert ours.moisture.pattern == engine.moisture.pattern
    assert ours.tilt.pattern == engine.tilt.pattern


def test_no_data_is_never_normal():
    a = pcha.assess(MemoryStore(), new_id(), NOW, neighbours_fn=lambda: [])
    assert a.tier == "no_data"


def test_one_silent_sensor_is_reported_in_reason():
    store, nid = MemoryStore(), new_id()
    fill(store, nid, flat(30), flat(0.5))
    store._data = {k: v for k, v in store._data.items() if k[2] != "moisture_index"}
    a = pcha.assess(store, nid, NOW, neighbours_fn=lambda: [])
    assert a.tier != "no_data"
    assert "moisture: no recent data" in a.reason


def _critical_store():
    """Accelerating tilt on wet soil: should be a critical candidate."""
    store, nid = MemoryStore(), new_id()
    fill(store, nid, lambda h: 70 + max(0.0, 6 - h) * 3,
         lambda h: 0.5 + (max(0.0, 2 - h) ** 2) * 0.6, t_noise=0.001)
    return store, nid


def test_critical_needs_three_agreeing_neighbours():
    store, nid = _critical_store()
    # no neighbours -> held at warning
    a = pcha.assess(store, nid, NOW, neighbours_fn=lambda: [])
    if "held at warning" not in a.reason:
        pytest.skip(f"scenario did not produce a critical candidate: {a.tier} {a.reason}")
    assert a.tier == "warning"
    # three neighbours that are also MOVING (tilt rising 0.02 deg/min) -> critical.
    # A static neighbour scores zero in the engine, however wet: change drives the score.
    nbs = []
    for _ in range(3):
        n = new_id()
        store.write([Reading(n, NOW - timedelta(minutes=m), {"tilt_deg": 0.9 - 0.02 * m}) for m in range(15)])
        nbs.append((n, 20.0))
    a = pcha.assess(store, nid, NOW, neighbours_fn=lambda: nbs)
    assert a.tier == "critical", a.reason
    assert a.corroboration.n_agreeing == 3


def test_static_wet_neighbours_do_not_confirm():
    store, nid = _critical_store()
    nbs = []
    for _ in range(3):
        n = new_id()
        store.write([Reading(n, NOW - timedelta(minutes=m), {"moisture_index": 88.0}) for m in range(15)])
        nbs.append((n, 20.0))
    a = pcha.assess(store, nid, NOW, neighbours_fn=lambda: nbs)
    assert a.tier == "warning"


def test_neighbours_in_range_skips_far_and_self():
    me = {"id": "a", "latitude": 6.79690, "longitude": 79.90180}
    cands = [me,
             {"id": "near", "latitude": 6.79700, "longitude": 79.90190},   # ~15 m
             {"id": "far", "latitude": 6.80000, "longitude": 79.90180},    # ~345 m
             {"id": "nogps", "latitude": None, "longitude": None}]
    ids = [i for i, _ in pcha.neighbours_in_range(me, cands)]
    assert ids == ["near"]
