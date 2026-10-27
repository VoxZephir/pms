"""The weekly summary (`weekly.py`) and its push to the phone (`notify.py`):
the preview, the settings, a test send."""

from __future__ import annotations

import datetime as dt

from flask import request

from ... import budgets as budgets_module
from ... import notify, weekly
from . import api, payload, store
from .shell import floor_notice


def notify_path(data=None):
    return (data or store()).path.with_name("notify.json")


def compose(data, today: dt.date | None = None) -> dict:
    """This week's message, from the store as it stands."""
    if data.empty:
        raise RuntimeError("aucun relevé")
    budgets = budgets_module.Budgets.load(data.path.with_name("budgets.json"))
    alert = floor_notice(data)
    return weekly.summary(data.statement, today or dt.date.today(), budgets.amounts,
                          floor=alert["text"] if alert else None)


def _settings_out(settings: dict, now: dt.datetime) -> dict:
    return {**settings, "next": notify.next_slot(settings, now) if settings["enabled"] else None,
            "weekdays": notify.WEEKDAYS}


@api.route("/api/semaine")
def weekly_page():
    data = store()
    if data.empty:
        return payload({"empty": True})
    now = dt.datetime.now()
    return payload({"summary": compose(data), "settings": _settings_out(notify.load(notify_path()), now)})


@api.route("/api/semaine", methods=["POST"])
def weekly_edit():
    """save (enabled, server, weekday, hour), topic (draw a new one), test
    (send this week's summary now)."""
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    path = notify_path()
    settings = notify.load(path)
    if action == "save":
        server = str(body.get("server") or settings["server"]).strip()
        if not server.startswith(("https://", "http://")):
            return payload({"error": "L'adresse du serveur doit commencer par https://"}), 400
        try:
            weekday, hour = int(body.get("weekday", settings["weekday"])), int(body.get("hour", settings["hour"]))
        except (TypeError, ValueError):
            return payload({"error": "Jour ou heure invalide."}), 400
        settings.update(enabled=bool(body.get("enabled")), server=server,
                        weekday=weekday % 7, hour=min(max(hour, 0), 23),
                        # Where a tap on the notification opens: this app, as the
                        # phone reached it.
                        app_url=request.host_url)
        if settings["enabled"] and not settings["topic"]:
            settings["topic"] = notify.new_topic()
    elif action == "topic":
        settings["topic"] = notify.new_topic()
    elif action == "test":
        if not settings["topic"]:
            return payload({"error": "Aucun sujet : active d'abord l'envoi."}), 400
        message = compose(store())
        try:
            notify.send(settings, message["title"], message["text"])
        except RuntimeError as exc:
            return payload({"error": f"Envoi impossible : {exc}"}), 502
        settings["last_sent"] = dt.datetime.now().isoformat(timespec="seconds")
        settings["last_error"] = None
    else:
        return payload({"error": "Action inconnue."}), 400
    notify.save(path, settings)
    return payload({"ok": True, "settings": _settings_out(settings, dt.datetime.now())})
