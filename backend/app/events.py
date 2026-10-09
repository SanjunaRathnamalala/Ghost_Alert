"""
Landslide event life cycle (design topic 4b). Pure functions: no database, easy to test.

Rules:
  4.8  only warning / critical open an event
  4.9  silence never closes or lowers an alarm (no_data, unreliable are ignored)
  4.10 one open event per node: it is raised, not duplicated
  4.11 up immediately; down only after the lower tier lasted a hold time
  4.12 peak_level never goes down; current_level is shown on the map
  4.13 "ready to close" after 6 h of normal / stand_down; only a person closes
"""
from dataclasses import dataclass
from datetime import timedelta

RANK = {"normal": 0, "stand_down": 0, "watch": 1, "warning": 2, "critical": 3}
OPENING = {"warning", "critical"}
IGNORED = {"no_data", "unreliable"}
CALM = {"normal", "stand_down"}

# Starting values, to be tuned with the simulator (decision 4.16).
HOLD = {"critical": timedelta(minutes=60), "warning": timedelta(minutes=30), "watch": timedelta(minutes=30)}
READY_AFTER = timedelta(hours=6)


@dataclass
class EventState:
    current_level: str
    peak_level: str
    lower_candidate: str = None
    lower_since: object = None
    calm_since: object = None
    ready_to_close_at: object = None


@dataclass
class Action:
    kind: str            # open | raise | lower | ready | not_ready
    from_level: str
    to_level: str

    @property
    def notify(self):
        """Which changes send a message (topic 5)."""
        if self.kind in ("open", "ready"):
            return True
        if self.kind == "raise":
            return self.to_level in OPENING
        if self.kind == "lower":
            return self.from_level in OPENING
        return False


def step(ev, tier, now):
    """Apply one PCHA result. Returns (new_state_or_None, [actions])."""
    if tier not in RANK and tier not in IGNORED:
        raise ValueError(f"unknown tier {tier}")

    if ev is None:
        if tier in OPENING:
            return EventState(tier, tier), [Action("open", None, tier)]
        return None, []

    if tier in IGNORED:
        return ev, []                                    # 4.9

    actions = []
    if tier in CALM:
        if ev.calm_since is None:
            ev.calm_since = now
    else:
        ev.calm_since = None
        if ev.ready_to_close_at is not None:
            ev.ready_to_close_at = None
            actions.append(Action("not_ready", ev.current_level, ev.current_level))

    new, cur = RANK[tier], RANK[ev.current_level]
    if new > cur:                                        # up: immediately
        old = ev.current_level
        ev.current_level = tier
        if new > RANK[ev.peak_level]:
            ev.peak_level = tier
        ev.lower_since = ev.lower_candidate = None
        actions.append(Action("raise", old, tier))
    elif new < cur:                                      # down: only after the hold time
        if ev.lower_since is None:
            ev.lower_since, ev.lower_candidate = now, tier
        elif new > RANK[ev.lower_candidate]:
            ev.lower_candidate = tier                    # lower only as far as the highest tier seen
        if now - ev.lower_since >= HOLD.get(ev.current_level, timedelta(minutes=30)):
            old = ev.current_level
            ev.current_level = ev.lower_candidate
            actions.append(Action("lower", old, ev.current_level))
            if new < RANK[ev.current_level]:
                ev.lower_since, ev.lower_candidate = now, tier
            else:
                ev.lower_since = ev.lower_candidate = None
    else:
        ev.lower_since = ev.lower_candidate = None

    if ev.calm_since is not None and ev.ready_to_close_at is None and now - ev.calm_since >= READY_AFTER:
        ev.ready_to_close_at = now
        actions.append(Action("ready", ev.current_level, ev.current_level))
    return ev, actions
