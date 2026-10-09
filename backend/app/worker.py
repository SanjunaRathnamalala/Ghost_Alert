"""
The PCHA worker (topic 4a): one queue, one thread ("one cashier, one queue").

- A node is checked when new data arrives (4.2); a burst jumps the queue (4.4).
- A safety round every few minutes: re-check all active landslide nodes (real and
  simulated), mark silent nodes offline (3.11), re-send unacknowledged critical
  alerts (5.2), and close quiet wildlife events (4.14).
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from . import db, events, pcha
from .notify import event_text

log = logging.getLogger("ghost_alert.worker")

OFFLINE_AFTER = {"landslide": timedelta(minutes=15), "wildlife": timedelta(minutes=45)}
REMIND_EVERY = timedelta(minutes=15)
WILDLIFE_QUIET = timedelta(minutes=15)

EVENT_COLS = ("current_level", "peak_level", "lower_candidate", "lower_since",
              "calm_since", "ready_to_close_at")


def utcnow():
    return datetime.now(timezone.utc)


class Worker:
    def __init__(self, engine, store, notifier, dashboard_url, safety_round_s=300):
        self.engine, self.store, self.notifier = engine, store, notifier
        self.dashboard_url, self.safety_round_s = dashboard_url, safety_round_s
        self._q, self._queued = deque(), set()
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._thread = None
        self.last_round_at = None
        self.last_error = None
        self.evaluations = 0

    # ---------------------------------------------------------------- queue
    def enqueue(self, node_id, urgent=False):
        node_id = str(node_id)
        with self._cv:
            if node_id in self._queued:
                if urgent:                       # move to the front
                    self._q.remove(node_id)
                    self._q.appendleft(node_id)
                return
            self._queued.add(node_id)
            (self._q.appendleft if urgent else self._q.append)(node_id)
            self._cv.notify()

    def _take(self, timeout):
        with self._cv:
            if not self._q:
                self._cv.wait(timeout)
            if not self._q:
                return None
            node_id = self._q.popleft()
            self._queued.discard(node_id)
            return node_id

    def drain(self, now=None):
        """Process everything queued now (used by tests)."""
        while True:
            node_id = self._take(0)
            if node_id is None:
                return
            self.evaluate_node(node_id, now or utcnow())

    # --------------------------------------------------------------- thread
    def start(self):
        self._thread = threading.Thread(target=self._run, name="pcha-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        with self._cv:
            self._cv.notify_all()

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        next_round = time.monotonic()
        while not self._stop.is_set():
            if time.monotonic() >= next_round:
                self._safe(self.safety_round, utcnow())
                next_round = time.monotonic() + self.safety_round_s
            node_id = self._take(timeout=max(0.1, min(1.0, next_round - time.monotonic())))
            if node_id:
                self._safe(self.evaluate_node, node_id, utcnow())

    def _safe(self, fn, *args):
        try:
            fn(*args)
        except Exception as exc:                  # one bad node must not stop the worker
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("worker error")

    # ----------------------------------------------------------- evaluation
    def evaluate_node(self, node_id, now):
        with self.engine.connect() as conn:
            node = db.node_by_id(conn, node_id)
            if not node or node["node_type"] != "landslide" or node["lifecycle"] == "retired":
                return None
            candidates = db.landslide_candidates(conn)
        a = pcha.assess(self.store, str(node_id), now, lambda: pcha.neighbours_in_range(node, candidates))
        self.evaluations += 1
        to_send = []
        with self.engine.begin() as conn:
            db.ensure_status_row(conn, node_id)
            prev = conn.execute(text("SELECT tier FROM node_status WHERE node_id = :i FOR UPDATE"),
                                {"i": str(node_id)}).scalar()
            conn.execute(text("""
                UPDATE node_status SET tier = :tier, moisture_pattern = :mp, tilt_pattern = :tp,
                  reason = :reason, evaluated_at = :now,
                  tier_since = CASE WHEN tier IS DISTINCT FROM :tier THEN :now ELSE tier_since END
                WHERE node_id = :i"""),
                {"tier": a.tier, "mp": a.moisture.pattern, "tp": a.tilt.pattern,
                 "reason": a.reason, "now": now, "i": str(node_id)})
            if prev != a.tier:
                conn.execute(text("""INSERT INTO tier_history (node_id, at, from_tier, to_tier, reason)
                                     VALUES (:i, :now, :f, :t, :r)"""),
                             {"i": str(node_id), "now": now, "f": prev, "t": a.tier, "r": a.reason})
            to_send = self._apply_event(conn, node, a, now)
        for msg in to_send:
            self.notifier.send(msg)
        return a

    def _apply_event(self, conn, node, a, now):
        row = conn.execute(text(f"""SELECT id, {', '.join(EVENT_COLS)} FROM hazard_events
                                    WHERE node_id = :i AND event_type = 'landslide' AND state = 'open'
                                    FOR UPDATE"""), {"i": str(node["id"])}).mappings().first()
        state = events.EventState(**{k: row[k] for k in EVENT_COLS}) if row else None
        state, actions = events.step(state, a.tier, now)
        if state is None:
            return []
        values = {k: getattr(state, k) for k in EVENT_COLS}
        if row is None:
            eid = conn.execute(text("""
                INSERT INTO hazard_events (node_id, event_type, current_level, peak_level, opened_at,
                                           last_changed_at, reason)
                VALUES (:i, 'landslide', :current_level, :peak_level, :now, :now, :reason)
                RETURNING id"""), dict(values, i=str(node["id"]), now=now, reason=a.reason)).scalar_one()
        else:
            eid = row["id"]
            changed = any(x.kind in ("raise", "lower") for x in actions)
            conn.execute(text(f"""
                UPDATE hazard_events SET {', '.join(f'{k} = :{k}' for k in EVENT_COLS)},
                  last_changed_at = CASE WHEN :changed THEN :now ELSE last_changed_at END,
                  reason = CASE WHEN :changed THEN :reason ELSE reason END
                WHERE id = :e"""), dict(values, changed=changed, now=now, reason=a.reason, e=eid))
        msgs = []
        for x in actions:
            db.log_event(conn, eid, now, x.kind, x.from_level, x.to_level, note=a.reason)
            if x.notify:
                msgs.append(event_text(x.kind, node, x.to_level, a.reason, eid, now,
                                       self.dashboard_url, node["is_virtual"]))
        if msgs:
            conn.execute(text("UPDATE hazard_events SET last_notified_at = :now WHERE id = :e"),
                         {"now": now, "e": eid})
        return msgs

    # --------------------------------------------------------- safety round
    def safety_round(self, now):
        self.last_round_at = now
        msgs = []
        with self.engine.begin() as conn:
            for (nid,) in conn.execute(text("""SELECT id FROM sensor_nodes WHERE node_type = 'landslide'
                                               AND lifecycle = 'active'""")):
                self.enqueue(nid)

            for kind, after in OFFLINE_AFTER.items():
                rows = conn.execute(text("""
                    UPDATE node_status s SET online = FALSE
                    FROM sensor_nodes n
                    WHERE s.node_id = n.id AND s.online AND n.node_type = :k
                      AND n.lifecycle <> 'retired' AND s.last_seen_at < :cut
                    RETURNING n.id"""), {"k": kind, "cut": now - after}).fetchall()
                for (nid,) in rows:
                    node = db.node_by_id(conn, nid)
                    msgs.append(event_text("offline", node, "", "no packets received", None, now,
                                           self.dashboard_url, node["is_virtual"]))

            for r in conn.execute(text("""
                    SELECT e.id, e.node_id, e.reason FROM hazard_events e
                    WHERE e.event_type = 'landslide' AND e.state = 'open' AND e.current_level = 'critical'
                      AND e.acknowledged_at IS NULL AND (e.last_notified_at IS NULL OR e.last_notified_at < :cut)
                    FOR UPDATE"""), {"cut": now - REMIND_EVERY}).mappings().fetchall():
                node = db.node_by_id(conn, r["node_id"])
                msgs.append(event_text("reminder", node, "critical", r["reason"], r["id"], now,
                                       self.dashboard_url, node["is_virtual"]))
                conn.execute(text("UPDATE hazard_events SET last_notified_at = :now WHERE id = :e"),
                             {"now": now, "e": r["id"]})
                db.log_event(conn, r["id"], now, "reminder", "critical", "critical")

            for (eid,) in conn.execute(text("""
                    UPDATE hazard_events SET state = 'resolved', resolved_at = :now, resolved_by = 'system',
                      resolve_note = 'no triggers for 15 min', last_changed_at = :now
                    WHERE event_type = 'wildlife' AND state = 'open' AND last_trigger_at < :cut
                    RETURNING id"""), {"now": now, "cut": now - WILDLIFE_QUIET}).fetchall():
                db.log_event(conn, eid, now, "closed", "warning", None, note="no triggers for 15 min")
        for m in msgs:
            self.notifier.send(m)
