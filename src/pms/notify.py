"""The weekly summary, pushed to the phone (`docs/semaine.md`): settings in
`data/notify.json`, the message sent to an ntfy server, and the clock that
sends it once a week from the serving process.

ntfy (ntfy.sh, or one's own server on the tailnet) delivers a POST to every
phone subscribed to its topic. The topic is the only secret: whoever knows
it can read the messages. It is drawn here, at random, shown in the app so
the phone can subscribe, and never printed in a log or an error.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import secrets
import threading
import urllib.error
import urllib.request
from pathlib import Path

DEFAULTS = {"enabled": False, "server": "https://ntfy.sh", "topic": "", "weekday": 6, "hour": 19,
            "app_url": "", "last_sent": None, "last_try": None, "last_error": None}
# A send that failed is tried again this much later, until it goes through.
RETRY = dt.timedelta(hours=1)
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
TIMEOUT = 10
# The clock looks this often; a summary is late by at most this much.
INTERVAL = 300


def new_topic() -> str:
    """A topic nobody guesses: 16 random characters behind a readable prefix."""
    return "pms-" + secrets.token_hex(8)


def load(path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    out["weekday"] = int(out["weekday"]) % 7
    out["hour"] = min(max(int(out["hour"]), 0), 23)
    return out


def save(path, settings: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({k: settings.get(k, v) for k, v in DEFAULTS.items()},
                                    indent=1, default=str), encoding="utf-8")
    temporary.replace(path)


def slot(settings: dict, now: dt.datetime) -> dt.datetime:
    """This week's sending time: the chosen day and hour on or before `now`."""
    back = (now.weekday() - settings["weekday"]) % 7
    at = (now - dt.timedelta(days=back)).replace(hour=settings["hour"], minute=0, second=0, microsecond=0)
    return at if at <= now else at - dt.timedelta(days=7)


def next_slot(settings: dict, now: dt.datetime) -> dt.datetime:
    return slot(settings, now) + dt.timedelta(days=7)


def _when(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def due(settings: dict, now: dt.datetime) -> bool:
    """Enabled, a topic, this week's slot passed without a send, and no
    failed try in the last hour."""
    if not settings["enabled"] or not settings["topic"]:
        return False
    at = slot(settings, now)
    last, tried = _when(settings.get("last_sent")), _when(settings.get("last_try"))
    if last is not None and last >= at:
        return False
    return tried is None or tried < at or now - tried >= RETRY


def send(settings: dict, title: str, text: str) -> None:
    """POST the message to the topic. Raises `RuntimeError` with a reason
    that never names the topic."""
    server = settings["server"].rstrip("/")
    if not server.startswith(("https://", "http://")):
        raise RuntimeError("L'adresse du serveur doit commencer par https://")
    # HTTP headers are latin-1: an accented title goes RFC 2047-encoded,
    # which ntfy decodes.
    headers = {"Title": "=?UTF-8?B?" + base64.b64encode(title.encode()).decode() + "?=",
               "Tags": "moneybag"}
    if settings.get("app_url"):
        headers["Click"] = settings["app_url"]
    request = urllib.request.Request(f"{server}/{settings['topic']}", data=text.encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if response.status >= 300:
                raise RuntimeError(f"le serveur a répondu {response.status}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"le serveur a répondu {exc.code}") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"serveur injoignable ({type(reason).__name__})") from None


class Clock:
    """Sends the summary when it is due, from the serving process only --
    like the Downloads watcher, never in the reloader's supervisor nor in
    the tests."""

    def __init__(self, path, compose, sender=send):
        self.path = Path(path)
        self.compose = compose
        self.sender = sender

    def tick(self, now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now()
        settings = load(self.path)
        if not due(settings, now):
            return False
        settings["last_try"] = now.isoformat(timespec="seconds")
        try:
            message = self.compose()
            self.sender(settings, message["title"], message["text"])
            settings["last_sent"], settings["last_error"] = settings["last_try"], None
        except Exception as exc:  # the clock must outlive a bad week
            settings["last_error"] = str(exc)
        save(self.path, settings)
        return True

    def run(self, stop: threading.Event, interval: float = INTERVAL) -> None:
        while not stop.wait(interval):
            self.tick()

    def start(self, interval: float = INTERVAL) -> threading.Event:
        stop = threading.Event()
        threading.Thread(target=self.run, args=(stop, interval), daemon=True, name="pms-weekly").start()
        return stop
