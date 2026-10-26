"""The forecast: cash month by month, net worth, the plan and its scenarios.

GET reads the forecast; POST applies one edit to the plan through
`apply_plan_action`, and answers with the errors keyed by field when it
refuses -- nothing is saved then, and the page keeps what was typed.
"""

from __future__ import annotations

from flask import request
from werkzeug.datastructures import MultiDict

from ... import crypto as crypto_module
from ... import finpension as finpension_module
from ... import freedom, holdings
from ... import ibkr as ibkr_module
from ... import plans as plans_module
from ..views.common import scale_mode, titres_mode
from ..views.previsions import (
    HORIZON_PRESETS, WEALTH_VIEWS, YSCALES, _compare, _declared_one_offs, _plan,
    _evolution_row, _suggestions, _wealth, apply_plan_action, months_ahead, months_label, wealth_mode,
    yscale_mode,
)
from . import api, payload, store


@api.route("/api/previsions")
def previsions():
    data = store()
    if data.empty:
        return payload({"empty": True})
    plan = _plan()
    horizon = months_ahead(request.args)
    projection = plans_module.project(data.statement, plan, months_ahead=horizon)
    # What an ordinary month leaves: the plan's summary line says it, and
    # the browser does no arithmetic.
    projection["margin"] = round(projection["income"] - projection["baseline"], 2)
    wealth, observed = _wealth(data, plan, projection)
    profile = plans_module.monthly_profile(data.statement)
    comparison = _compare(data, plan, horizon, wealth)
    for c in comparison:
        # The cash line of each scenario: its month ends, nothing else.
        c["line"] = [r["end"] for r in c.pop("rows")]
    return payload({
        "freedom": _freedom(data, plan, projection, wealth),
        "as_of": data.statement.period_end,
        "months": horizon,
        "horizon_label": months_label(horizon),
        "horizons": [{"id": n, "label": months_label(n)} for n in HORIZON_PRESETS],
        "projection": projection,
        "wealth": wealth or None,
        "wealth_observed": observed,
        "wealth_view": wealth_mode(request.args),
        "wealth_views": [{"id": k, "label": v["label"], "title": v["aria"], "note": v["note"]}
                         for k, v in WEALTH_VIEWS.items()],
        "scale": scale_mode(request.args),
        "yscale": yscale_mode(request.args),
        "yscales": [{"id": k, "label": v} for k, v in YSCALES.items()],
        "profile": profile if len(profile) >= 2 else [],
        "comparison": comparison,
        "active": plan.active,
        "plan": {
            "income": plan.income, "spend": plan.spend, "vol": plan.vol,
            "rate_segments": [[m, r] for m, r in plan.rate_segments],
            "rate_years": plans_module.rate_years(plan.rate_segments,
                                                  [r["key"] for r in projection["rows"]]),
            "declared": _declared_one_offs(plan),
            "contributions": [{**c, "every_label": plans_module.CONTRIBUTION_LABELS[c["every"]],
                               "start_label": (plans_module.month_label(c["start"])
                                               if c["start"] else "le mois prochain")}
                              for c in plan.contributions],
            "ignored": [{"category": c, "month": m,
                         "label": plans_module.MONTH_NAMES[m - 1].capitalize()}
                        for c, m in plan.ignored],
            "scenarios": [{"name": name, "summary": plans_module.scenario_summary(
                              s["rate_segments"], s["vol"], s.get("months", 0)),
                           **_market(s["rate_segments"], s["vol"], s.get("months", 0), saved=True)}
                          for name, s in sorted(plan.scenarios.items(),
                                                key=lambda kv: kv[0].casefold())],
        },
        "suggestions": _suggestions(data, plan, projection),
        "builtin_scenarios": [{"key": k, "label": v["label"], "note": v.get("note", ""),
                               **_market(v["rate_segments"], v["vol"], v.get("months", 0)),
                               "pockets": [{"id": pk, "label": plans_module.POCKET_LABELS[pk],
                                            "rate": segs[0][1], "vol": pv}
                                           for pk, (segs, pv) in v.get("pockets", {}).items()]}
                              for k, v in plans_module.BUILTIN_SCENARIOS.items()],
        # The barème in force, over the horizon on screen.
        "growth": plans_module.growth_path(plan.rate_segments, horizon),
        "destinations": [{"id": k, "label": plans_module.DESTINATION_LABELS[k]}
                         for k in plans_module.DESTINATIONS],
        "every_options": [{"id": k, "label": v}
                          for k, v in plans_module.CONTRIBUTION_LABELS.items()],
        "pockets": [{"id": plans_module.SHELTERED, "label": "le 3a"},
                    {"id": plans_module.TAXABLE, "label": "le placement"}],
    })


def _freedom(data, plan, projection: dict, wealth: dict) -> dict | None:
    """Financial independence (`freedom.py`) on today's whole net worth:
    cash, brokerage, 3a and coins -- whatever view the curve is in."""
    worth = projection["cash"]
    # A share held outside the statement counts too, at its declared value
    # (unless `?titres=0`, as everywhere).
    securities = holdings.load(data.path.with_name("holdings.json")) if titres_mode(request.args) else []
    ibkr = ibkr_module.load(data.path.with_name("ibkr.json"))
    parts = []
    if ibkr:
        finpension = finpension_module.load(data.path.with_name("finpension.json"))
        crypto = crypto_module.load(data.path.with_name("crypto.json"))
        today = _evolution_row(data.statement, ibkr, finpension, data.statement.period_end, crypto, securities)
        worth = today["total"]
        # The pockets with a barème of their own grow by it.
        parts = [(today.get(k) or 0.0, s) for k, s in plan.schedules().items() if today.get(k)]
    else:
        worth += holdings.worth(securities, data.statement.period_end.year)
    out = freedom.independence(data.statement, worth, projection["income"], plan,
                               freedom.withdrawal_rate(request.args), parts)
    if out:
        end = data.statement.period_end
        out["date"] = plans_module._add_months(end, out["months"]) if out["months"] is not None else None
        out["date_flat"] = (plans_module._add_months(end, out["months_flat"])
                            if out["months_flat"] is not None else None)
    return out


def _market(segments, vol, months: int, saved: bool = False) -> dict:
    """A market scenario as its card shows it: its periods, and what it does
    to a franc over the horizon it carries (ten years when it carries none,
    long enough to see its shape). A saved one carries the horizon it was
    saved on, often shorter than its periods: its curve runs at least to the
    start of its last period, plus a year of it, so no period goes unseen."""
    span = months or max(120, sum(m for m, _ in segments))
    if saved and segments:
        span = max(span, sum(m for m, _ in segments[:-1]) + 12)
    return {"segments": [{"months": m, "rate": r} for m, r in segments],
            "vol": vol, "months": months or None,
            "path": plans_module.growth_path(segments, span)}


@api.route("/api/previsions", methods=["POST"])
def previsions_edit():
    """`{"action": ..., field: value}` -- the page's form fields, as JSON.
    Lists (a barème's months and rates) are JSON arrays."""
    body = request.get_json(silent=True) or {}
    form = MultiDict()
    for key, value in body.items():
        if isinstance(value, list):
            for item in value:
                form.add(key, "" if item is None else str(item))
        elif value is not None:
            form.add(key, str(value))
    plan = _plan()
    errors, values, applied = apply_plan_action(plan, form, months_ahead(request.args))
    if errors:
        return payload({"errors": errors, "values": values}), 400
    plan.save()
    return payload({"ok": True, "months": applied})
