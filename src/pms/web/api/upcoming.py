"""What comes next (`/a-venir`): the commitments with their due dates,
the deadlines to change them, and the health franchise replayed. No window:
what is coming is read from today, against everything the ledger knows."""

from __future__ import annotations

import datetime as dt

from flask import request

from ... import health, upcoming
from ..palette import colour_map
from . import api, payload, store


def health_path():
    return store().path.with_name("health.json")


def _costs(args, default: float) -> float:
    try:
        value = float(str(args.get("costs") or "").replace("'", ""))
    except ValueError:
        return default
    return min(max(value, 0.0), float(health.AXIS_MAX))


def upcoming_data(args, today: dt.date | None = None) -> dict:
    data = store()
    if data.empty:
        return {"empty": True}
    today = today or dt.date.today()
    statement = data.statement
    end = statement.period_end
    until = max(today, end) + dt.timedelta(days=max(upcoming.HORIZONS))
    bills = upcoming.commitments(statement, end, until)
    pay = upcoming.income(statement, end, until)

    ranked = {}
    for c in bills:
        ranked[c["category"]] = ranked.get(c["category"], 0.0) + c["yearly"]
    slots, legend = colour_map([{"category": k} for k in sorted(ranked, key=lambda k: -ranked[k])])
    for c in bills:
        c["slot"] = slots.get(c["category"], slots["Autres"])

    start = max(today, end + dt.timedelta(days=1))
    ahead = upcoming.calendar_ahead(bills, pay, start, slots, shown_from=end + dt.timedelta(days=1))

    settings = health.load_settings(health_path())
    premium = health.detected_premium(bills)
    years = health.care_by_year(statement, premium["label"] if premium else None, settings["franchise"])
    whole = [y for y in years if y["whole"]]
    default_costs = (whole or years or [{"costs": 0.0}])[-1]["costs"]
    replay = (health.replay(settings["franchise"], premium["monthly"], _costs(args, default_costs), years)
              if premium else None)

    return {
        "today": today, "statement_end": end, "start": start,
        "stale": (today - end).days if today > end else 0,
        "commitments": bills,
        "income": pay,
        "summary": upcoming.summary(bills),
        "ahead": ahead,
        "legend": legend,
        "deadlines": upcoming.deadlines(bills, today),
        "health": {
            "settings": settings, "premium": premium, "years": years,
            "default_costs": default_costs, "franchises": list(health.FRANCHISES),
            "replay": replay,
        },
    }


@api.route("/api/a-venir")
def upcoming_page():
    return payload(upcoming_data(request.args))


@api.route("/api/health", methods=["POST"])
def health_edit():
    body = request.get_json(silent=True) or {}
    try:
        franchise = int(body.get("franchise"))
        health.save_settings(health_path(), franchise)
    except (TypeError, ValueError):
        return payload({"error": "Franchise inconnue."}), 400
    return payload({"ok": True, "franchise": franchise})


#: A deadline enters the dashboard's to-do card this many days ahead.
SOON_DAYS = 45


def soon(statement, today: dt.date | None = None) -> dict:
    """For the dashboard: the deadlines close enough to act on, and the next
    due dates of the coming month -- the page itself has the rest."""
    today = today or dt.date.today()
    end = statement.period_end
    until = max(today, end) + dt.timedelta(days=max(upcoming.HORIZONS))
    bills = upcoming.commitments(statement, end, until)
    start = max(today, end + dt.timedelta(days=1))
    ahead = upcoming.calendar_ahead(bills, [], start, {}, shown_from=start)
    month = ahead["totals"][0]
    return {
        "deadlines": [d for d in upcoming.deadlines(bills, today) if d["days"] <= SOON_DAYS],
        "next": [r for r in ahead["rows"] if r["day"] <= month["until"]][:5],
        "month": month,
    }
