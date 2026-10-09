"""Every simulator scenario, run through the real ingest + PCHA worker, gives its intended tiers
at the end of the history AND stays there for 4 minutes of live data."""
import io
import contextlib
import dataclasses
from datetime import timedelta

import pytest
from sqlalchemy import text

from tools import simulate as sim
from tests.test_pipeline import PG, KEY, env  # noqa: F401  (reuses the database fixture)


def _mem(app):
    return dataclasses.replace(app.state.settings, telemetry_store="memory")


@pytest.mark.parametrize("name", sorted(sim.SCENARIOS))
def test_scenario_gives_intended_tiers(env, name):  # noqa: F811
    client, app, engine, store, notifier = env
    post = lambda body: client.post("/api/v1/ingest", json=body, headers={"X-Gateway-Key": KEY}).json()
    with contextlib.redirect_stdout(io.StringIO()):
        sims, anchor = sim.run(name, None, None, live=False, poster=post,
                               settings=_mem(app), fresh=True)
    with engine.connect() as c:
        ids = {r: str(c.execute(text("SELECT id FROM sensor_nodes WHERE radio_id = :r"), {"r": r}).scalar())
               for r in sims}
    expect = sim.SCENARIOS[name].expect
    for k in range(0, 7):                                   # end of history + 6 live steps
        t = anchor + timedelta(seconds=k * sim.LIVE_STEP_S)
        if k:
            for s in sims.values():
                for p in sim.live_packets(s, sim.HISTORY_H + k * sim.LIVE_STEP_S / 3600, t):
                    post(sim.ingest_body(p, t, s, replay=False))
        for r, nid in ids.items():
            tier = app.state.worker.evaluate_node(nid, t).tier
            assert tier in expect[r], f"{name}: V0{r - 100} gave {tier} at live step {k}"


def test_replay_does_not_queue_checks(env):  # noqa: F811
    client, app, *_ = env
    sims = sim.build_sims(sim.SCENARIOS["calm"], 1)
    with contextlib.redirect_stdout(io.StringIO()):
        sim.prepare_database(_mem(app), fresh=True)
    s = sims[101]
    from datetime import datetime, timezone
    t = datetime.now(timezone.utc)
    client.post("/api/v1/ingest", json=sim.ingest_body(s.boot_packet(), t, s, True), headers={"X-Gateway-Key": KEY})
    client.post("/api/v1/ingest", json=sim.ingest_body(s.heartbeat(1.0, 300, 10.0), t, s, True),
                headers={"X-Gateway-Key": KEY})
    assert app.state.worker._q == type(app.state.worker._q)()      # nothing queued
