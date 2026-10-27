"""What every page shares: the ledger's span and state, and the window."""

from __future__ import annotations

import datetime as dt

from flask import current_app, request

from ... import analysis, backup
from ... import plans as plans_module
from .. import news as news_module
from .. import periods
from ... import holdings as holdings_module
from . import api, payload, store


# A rolling window has no calendar name: "15.10.2025 → 14.10.2026" says the
# dates, the preset says what was asked for.
PRESET_TITLES = {
    "30d": "30 derniers jours", "90d": "3 derniers mois", "180d": "6 derniers mois",
    "12m": "12 derniers mois", "qtd": "Trimestre en cours", "all": "Tout l'historique",
}


def period_of(args) -> dict:
    """The window a query string names, with everything the period picker
    draws: presets, crumbs, neighbours, grains. No aggregation -- cheap
    enough to answer before the page's own data."""
    data = store()
    low, high = data.bounds
    period = periods.resolve(args, low, high)
    active = next((p for p in period["presets"] if p["active"]), None)
    if active and "→" in period["title"] and active["id"] in PRESET_TITLES:
        period["title"] = PRESET_TITLES[active["id"]]
    elif active and active["id"] == "ytd" and "→" in period["title"]:
        period["title"] = f"{high.year} à ce jour"
    period["neighbours"] = periods.neighbours(period["start"], period["end"], low, high)
    period["grains"] = [{"id": g, "label": analysis.GRAIN_LABELS[g]}
                        for g in analysis.GRAINS]
    period["bounds"] = {"low": low, "high": high}
    return period


@api.route("/api/period")
def period_route():
    return payload(period_of(request.args))


_FLOOR_CACHE: dict = {}


def floor_notice(data) -> dict | None:
    """The cash alert (`plans.floor_alert`) on the plan on screen, over a
    year: said on every page while the projection goes under the floor.
    Projected once per ledger and plan file, not on every page load."""
    path = data.path.with_name("plans.json")
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    key = (id(data.statement), len(data.statement.transactions), stamp, dt.date.today())
    if key not in _FLOOR_CACHE:
        plan = plans_module.Plan.load(path)
        alert = None
        if plan.floor is not None:
            alert = plans_module.floor_alert(plans_module.project(data.statement, plan, months_ahead=12),
                                             plan.floor)
        _FLOOR_CACHE.clear()
        _FLOOR_CACHE[key] = alert if alert and alert["below"] else None
    return _FLOOR_CACHE[key]


@api.route("/api/meta")
def meta():
    """The ledger as a whole: its span, its health, what just came in and
    what is due -- the shell shows these on every page."""
    data = store()
    empty = data.empty
    low, high = data.bounds
    fresh = None if empty else news_module.news(data.sources, high)
    return payload({
        "empty": empty,
        "ledger": str(data.path),
        "bounds": {"low": low, "high": high},
        "movements": len(data.statement.transactions),
        "gaps": data.gaps,
        "news": fresh,
        "late": [] if empty else news_module.late(data.sources, dt.date.today()),
        "watching": "pms_watcher" in current_app.extensions,
        "overrides": len(data.overrides),
        "crypto": data.path.with_name("crypto.json").exists(),
        # The pocket's name when some are declared ("Titres non cotés", or
        # "Hors marché" with a watch among them), else nothing.
        "titres": (holdings_module.pocket_name(declared)
                   if (declared := holdings_module.load(data.path.with_name("holdings.json"))) else None),
        "savings": data.path.with_name("ibkr.json").exists(),
        # Said only when something is wrong: a failed run, a copy that does
        # not read back, no run for two weeks (backup.health).
        "backup": None if empty else backup.health(data.path.parent),
        "floor": None if empty else floor_notice(data),
    })
