from datetime import datetime, timedelta, timezone

from app.events import step


def at(hh, mm):
    return datetime(2026, 10, 7, hh, mm, tzinfo=timezone.utc)


def run(timeline, every=5):
    """timeline: list of (start_time, tier) - each tier repeats every `every` minutes until the next."""
    ev, log = None, []
    for (t0, tier), nxt in zip(timeline, timeline[1:] + [(timeline[-1][0] + timedelta(minutes=every), None)]):
        t = t0
        while t < nxt[0]:
            ev, actions = step(ev, tier, t)
            log += [(t, a.kind, a.from_level, a.to_level) for a in actions]
            t += timedelta(minutes=every)
    return ev, log


def test_design_example_timeline():
    """The exact example table from design topic 4b, step 5."""
    ev, log = run([
        (at(10, 0), "watch"),
        (at(10, 5), "warning"),
        (at(10, 20), "critical"),
        (at(10, 25), "warning"),
        (at(12, 0), "no_data"),
        (at(13, 0), "normal"),
        (at(19, 30), "normal"),
    ])
    kinds = [(t.strftime("%H:%M"), k, f, to) for t, k, f, to in log]
    print(*kinds, sep="\n")
    assert kinds[0] == ("10:05", "open", None, "warning")
    assert kinds[1] == ("10:20", "raise", "warning", "critical")
    assert kinds[2] == ("11:25", "lower", "critical", "warning")        # 60 min hold from critical
    assert kinds[3] == ("13:30", "lower", "warning", "normal")          # no_data did not lower it
    assert kinds[4] == ("19:00", "ready", "normal", "normal")           # 6 h after 13:00
    assert ev.peak_level == "critical"


def test_watch_alone_never_opens():
    ev, log = run([(at(10, 0), "watch"), (at(12, 0), "watch")])
    assert ev is None and log == []


def test_silence_never_closes_or_lowers():
    ev, log = run([(at(10, 0), "critical"), (at(10, 5), "no_data"), (at(20, 0), "unreliable")])
    assert ev.current_level == "critical"
    assert [k for _, k, _, _ in log] == ["open"]


def test_flicker_does_not_spam():
    tl = [(at(10, 0), "warning")]
    for i in range(1, 12):                      # watch / warning every 5 minutes for an hour
        tl.append((at(10, 0) + timedelta(minutes=5 * i), "watch" if i % 2 else "warning"))
    ev, log = run(tl)
    assert [k for _, k, _, _ in log] == ["open"]
    assert ev.current_level == "warning"


def test_rising_again_cancels_ready():
    ev, log = run([(at(10, 0), "warning"), (at(10, 5), "normal"), (at(17, 0), "warning")])
    kinds = [k for _, k, _, _ in log]
    assert "ready" in kinds and kinds[-1] == "raise"
    assert ev.ready_to_close_at is None and ev.current_level == "warning"
