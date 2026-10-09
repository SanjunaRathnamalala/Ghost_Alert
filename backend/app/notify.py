"""
Alert sender (topic 5). Demo version: an in-memory "mailbox" + one sender thread.
The PCHA worker only drops a message in the mailbox and never waits (decision 5.5).
Retries after 1, 5 and 15 minutes. Without a Telegram token, messages are logged only.
"""
import json
import logging
import queue
import threading
import time
import urllib.request
from datetime import timedelta, timezone

log = logging.getLogger("ghost_alert.notify")
SL_TIME = timezone(timedelta(hours=5, minutes=30))
RETRY_DELAYS_S = [60, 300, 900]
ICON = {"critical": "🔴", "warning": "🟠", "watch": "🟡", "normal": "🟢", "stand_down": "🔵"}


def sl_time(t):
    return t.astimezone(SL_TIME).strftime("%H:%M")


def event_text(action, node, level, reason, event_id, at, dashboard_url, virtual=False):
    head = {
        "open": f"{ICON.get(level, '')} {level.upper()} – Landslide risk",
        "raise": f"{ICON.get(level, '')} RAISED to {level.upper()} – Landslide risk",
        "lower": f"{ICON.get(level, '')} Lowered to {level}",
        "ready": "✅ Ready to close (calm for 6 h)",
        "reminder": f"⏰ REMINDER – {level.upper()} not acknowledged",
        "wildlife": "🐘 Wildlife detected",
        "offline": "🔌 Node offline – needs service",
    }[action]
    lines = [head, f"Node: {node['name']}" + (" (SIMULATED)" if virtual else "")]
    if reason:
        lines.append(f"Reason: {reason}")
    lines.append(f"Time: {sl_time(at)} (Sri Lanka time)")
    if node.get("latitude") is not None:
        lines.append(f"Map: https://maps.google.com/?q={node['latitude']:.5f},{node['longitude']:.5f}")
    if event_id:
        lines.append(f"Open: {dashboard_url}/events/{event_id}")
    return "\n".join(lines)


class Notifier:
    def __init__(self, bot_token="", chat_id=""):
        self.bot_token, self.chat_id = bot_token, chat_id
        self.sent = []                      # kept for the dashboard / tests
        self._q = queue.Queue()
        self._stop = threading.Event()
        self._thread = None

    def send(self, text):
        self._q.put((text, 0, 0.0))

    def start(self):
        self._thread = threading.Thread(target=self._run, name="notifier", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _deliver(self, text):
        if not (self.bot_token and self.chat_id):
            log.warning("ALERT (Telegram not configured):\n%s", text)
            return True
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            data=json.dumps({"chat_id": self.chat_id, "text": text}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200

    def deliver_now(self, text):
        """Synchronous delivery, used by tests and when no thread is running."""
        ok = self._deliver(text)
        if ok:
            self.sent.append(text)
        return ok

    def _run(self):
        while not self._stop.is_set():
            try:
                text, tries, not_before = self._q.get(timeout=1)
            except queue.Empty:
                continue
            if time.monotonic() < not_before:
                self._q.put((text, tries, not_before))
                time.sleep(0.5)
                continue
            try:
                ok = self.deliver_now(text)
            except Exception as exc:              # network error, Telegram down...
                log.error("send failed: %s", exc)
                ok = False
            if not ok and tries < len(RETRY_DELAYS_S):
                self._q.put((text, tries + 1, time.monotonic() + RETRY_DELAYS_S[tries]))
            elif not ok:
                log.error("giving up on message after %d tries", tries + 1)
