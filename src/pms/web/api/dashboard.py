"""The dashboard's data: one window, every spending panel.

The same gates as the server-rendered page decide which panels exist -- a
panel that cannot say anything is absent (`panels`) -- and the same analysis
functions fill them. What the old page did with chart geometry the browser
now does, at the width of the screen it is on.
"""

from __future__ import annotations

import datetime as dt
import statistics

from flask import request

from ... import analysis, buckets, lookback, plans
from ... import budgets as budgets_module
from ... import review as review_module
from ...categories import UNCATEGORISED
from ..palette import MAX_SLOTS, colour_map
from ..views.common import BUCKET_FILL, STACKS, stack_mode
from . import api, payload, store
from . import upcoming as upcoming_api
from .shell import period_of

GRAIN_FR = {"year": "année", "month": "mois", "week": "semaine", "day": "jour"}


def drill_target(rows: list[dict], grain: str) -> tuple[str | None, str]:
    """Where clicking a column lands, and how to say it.

    The window goes to the same `suggest_grain` the rest of the app uses, so
    the destination is whatever it picks for a bucket that size -- a month
    goes straight to days, not to weeks. The hint comes from that same call,
    or it would promise a level the click does not deliver.
    """
    if grain == "day":
        return "detail", "une colonne ouvre le détail de la journée"
    if not rows:
        return None, ""
    sample = rows[len(rows) // 2]
    target = analysis.suggest_grain(sample["start"], sample["end"])
    if target == grain:
        target = analysis.finer_grain(grain) or grain
    if target == grain:
        return None, "niveau le plus fin"
    return target, f"une colonne descend au niveau {GRAIN_FR[target]}"


def _span(rows) -> float:
    return sum(abs(t.amount_chf) for t in rows)


def _kpis(window, previous, period) -> dict:
    spending_rows = analysis.spending(window)
    spend = _span(spending_rows)
    earn = sum(t.amount_chf for t in analysis.income(window))
    prev_spending = analysis.spending(previous)
    prev_spend = _span(prev_spending)
    prev_earn = sum(t.amount_chf for t in analysis.income(previous))
    days = max(period["days"], 1)
    prev_days = max((previous.period_end - previous.period_start).days + 1, 1)
    return {
        "spend": spend, "earn": earn, "net": earn - spend,
        "per_day": spend / days,
        # The mean is dragged up by rent and tax days; the median says what an
        # ordinary day costs.
        "median_day": analysis.median_daily(spending_rows, period["start"], period["end"]),
        "closing": analysis.closing_chf(window),
        "previous": ({"spend": prev_spend, "earn": prev_earn,
                      "per_day": prev_spend / prev_days,
                      "median_day": analysis.median_daily(
                          prev_spending, previous.period_start, previous.period_end)}
                     if previous.transactions else None),
    }


def _previous_label(start: dt.date, end: dt.date) -> str:
    """The window compared with, said shortly: a month, a year, or dates."""
    if start.day == 1 and end == analysis.bucket_bounds(start, "month")[1]:
        return analysis.bucket_label(start, "month")
    if (start.month, start.day, end.month, end.day) == (1, 1, 12, 31) and start.year == end.year:
        return str(start.year)
    return f"{start:%d.%m.%y} → {end:%d.%m.%y}"


def _versus(spend, before, slots) -> list[dict]:
    """Each category against the window before, in francs: the "why" of
    the spending tile's change. Sorted by the size of the move."""
    def totals(rows):
        out: dict[str, float] = {}
        for t in rows:
            out[t.category] = out.get(t.category, 0.0) + abs(t.amount_chf)
        return out
    now, then = totals(spend), totals(before)
    rows = [{"category": c, "now": round(now.get(c, 0.0), 2), "before": round(then.get(c, 0.0), 2),
             "delta": round(now.get(c, 0.0) - then.get(c, 0.0), 2),
             "slot": slots.get(c, slots[analysis.OTHER])}
            for c in set(now) | set(then)]
    return sorted((r for r in rows if abs(r["delta"]) >= 0.5), key=lambda r: -abs(r["delta"]))


def _monthly(window, categories) -> list[dict]:
    """Months x categories: one row per category, one bar per month, each
    row scaled to its own busiest month (the shape of the year, not a
    comparison of heights across categories)."""
    m_rows = analysis.monthly(window)
    if len(m_rows) < 2:
        return []
    keys = [r["month"] for r in m_rows]
    named = [c["category"] for c in categories][:MAX_SLOTS - 1]
    slot_of = {c["category"]: c["slot"] for c in categories}

    def row(name, slot, values):
        return {"name": name, "slot": slot,
                "total": round(sum(values), 2),
                "median": round(statistics.median(values), 2),
                "months": [{"key": k, "label": plans.month_label(k), "amount": round(v, 2)}
                           for k, v in zip(keys, values)]}

    out = [row(name, slot_of[name], [r["categories"].get(name, 0.0) for r in m_rows])
           for name in named]
    others = [sum(v for c, v in r["categories"].items() if c not in named) for r in m_rows]
    if sum(others):
        out.append(row(analysis.OTHER, len(named), others))
    return out


def _income(window, period) -> dict | None:
    """Who was paying, and when that changed -- two payers at least, three
    months at least."""
    sources = analysis.income_sources(window)
    if len(sources) < 2 or period["days"] < 90:
        return None
    named, tail = sources[:analysis.INCOME_SLOTS], sources[analysis.INCOME_SLOTS:]
    slots = {row["label"]: i for i, row in enumerate(named)}
    slots[analysis.OTHER] = analysis.INCOME_SLOTS
    table = [{**row, "slot": slots[row["label"]]} for row in named]
    if tail:
        table.append({
            "label": f"{analysis.OTHER} ({len(tail)} payeurs)",
            "slot": analysis.INCOME_SLOTS,
            "amount": sum(r["amount"] for r in tail),
            "share": sum(r["share"] for r in tail),
            "count": sum(r["count"] for r in tail),
            "first": min(r["first"] for r in tail),
            "last": max(r["last"] for r in tail),
            "folded": True,
        })
    rows = analysis.income_timeline(window, period["grain"], period["start"], period["end"])
    return {"payers": len(sources), "slots": slots, "table": table, "rows": rows}


@api.route("/api/budgets", methods=["POST"])
def budgets_edit():
    """Declare or remove a monthly budget. A budget that does not parse is
    refused with the reason, never silently dropped."""
    body = request.get_json(silent=True) or {}
    category = str(body.get("category") or "").strip()
    store_ = budgets_module.Budgets.load(store().path.with_name("budgets.json"))
    if not category:
        return payload({"error": "Catégorie manquante."}), 400
    if body.get("action") == "delete":
        store_.remove(category)
    else:
        try:
            amount = float(str(body.get("amount") or "").replace("'", "").replace("’", ""))
        except ValueError:
            return payload({"error": "Utilisez le point décimal, pas la virgule."}), 400
        if amount <= 0:
            return payload({"error": "Montant invalide."}), 400
        store_.set_budget(category, amount)
    store_.save()
    return payload({"category": category, "budgets": store_.amounts})


@api.route("/api/dashboard")
def dashboard():
    data = store()
    if data.empty:
        return payload({"empty": True})
    args = request.args
    period = period_of(args)
    start, end, grain = period["start"], period["end"], period["grain"]
    low, high = data.bounds

    window = data.window(start, end)
    prev_start, prev_end = analysis.previous_window(start, end)
    previous = data.window(prev_start, prev_end)

    spend = analysis.spending(window)
    categories = analysis.by_category(spend)
    slots, legend = colour_map(categories)
    for row in categories:
        row["slot"] = slots.get(row["category"], slots[analysis.OTHER])

    rows = analysis.timeseries(window, grain, start, end)
    drill, drill_hint = drill_target(rows, grain)

    days = period["days"]
    years_spanned = end.year - start.year + 1
    custodian = analysis.custodian_costs(window)
    fixed = analysis.fixed_vs_variable(window) if days >= 60 else None
    missing = analysis.missing_commitments(window) if days >= 60 else []
    geo = analysis.by_country(spend)
    daily = analysis.daily_totals(spend)

    # What changed this month: one calendar month only, the month in
    # progress included.
    month_end = analysis.bucket_bounds(start, "month")[1]
    one_month = start.day == 1 and (end == month_end or (end == high and end < month_end))
    review = review_module.month_review(data.statement, start, end) if one_month else None

    monthly = _monthly(window, categories)
    budgets = budgets_module.Budgets.load(data.path.with_name("budgets.json"))
    for row in monthly:
        row["budget"] = budgets.amounts.get(row["name"])

    # The bucket bar over time: read from the whole ledger, so a rolling
    # sum reaches back before the window; whole months only.
    share_base = (args.get("shares") or "").strip()
    share_base = share_base if share_base in buckets.SHARE_BASES else buckets.DEFAULT_SHARE_BASE
    try:
        smooth = int(args.get("smooth") or 1)
    except ValueError:
        smooth = 1
    smooth = smooth if smooth in buckets.SMOOTHING else 1
    share_rows = buckets.shares_by_month(data.statement, start, end, share_base, smooth)

    income = _income(window, period)
    stack = stack_mode(args)

    # The month on screen, while it is the statement's latest: its pace
    # against an ordinary month, and the budgets against the days gone.
    pace = (lookback.month_pace(data.statement, start, end, budgets.amounts)
            if one_month and end == high else None)

    panels = {
        "balance": bool(window.transactions),
        "highlights": days >= 14 and len(spend) >= 10,
        "fixed": fixed is not None and len(fixed["months"]) >= 2,
        "missing": bool(missing),
        "income": bool(income and income["rows"]),
        "calendar": days >= 45,
        "strip": days <= 92 and bool(daily),
        "years": years_spanned >= 2,
        "season": days >= 300,
        "country": bool(geo["rows"]),
        "custodian": custodian["count"] > 0,
        "monthly": bool(monthly),
        "review": review is not None,
        "shares": len(share_rows) >= 2,
    }

    return payload({
        "period": period,
        "previous": {"start": prev_start, "end": prev_end,
                     "exists": bool(previous.transactions),
                     "label": _previous_label(prev_start, prev_end)},
        "versus": _versus(spend, analysis.spending(previous), slots) if previous.transactions else [],
        "pace": pace,
        "count": len(window.transactions),
        "kpis": _kpis(window, previous, period),
        "panels": panels,
        "categories": categories,
        "legend": legend,
        "timeline": {
            "rows": rows, "drill": drill, "hint": drill_hint,
            "stack": stack,
            "stacks": [{"id": k, "label": v["label"]} for k, v in STACKS.items()],
        },
        "bucket_order": buckets.ORDER,
        "bucket_fill": BUCKET_FILL,
        "buckets": buckets.summarise(window),
        "custodian": custodian,
        "top_merchants": analysis.top_merchants(spend, limit=12),
        "daily": {day: [round(v["amount"], 2), v["count"]] for day, v in daily.items()},
        "review": review,
        "highlights": analysis.highlights(window, custodian) if panels["highlights"] else [],
        "income": income,
        "missing": missing,
        "fixed": fixed if panels["fixed"] else None,
        "monthly": monthly,
        "balance": (analysis.cash_points(window.transactions) if panels["balance"] else []),
        "years": analysis.year_cumulative(spend) if panels["years"] else [],
        "weekday": analysis.weekday_profile(spend),
        "season": analysis.seasonality(spend) if panels["season"] else [],
        "geo": geo,
        "shares": {
            "base": share_base, "smooth": smooth, "rows": share_rows,
            "names": buckets.share_names(share_base),
            "bases": [{"id": k, "label": v.capitalize()} for k, v in buckets.SHARE_BASES.items()],
            "smoothings": list(buckets.SMOOTHING),
            "targets": buckets.TARGET,
        },
        "uncategorised": _span(t for t in spend if t.category == UNCATEGORISED),
        "categories_present": sorted({t.category for t in window.transactions}),
        "today": dt.date.today(),
        # What is coming, read from today: only beside the latest days.
        "soon": upcoming_api.soon(data.statement) if end == high else None,
    })
