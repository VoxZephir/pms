"""The past spending read several ways, for `/analyse`: the year against the
one before, how regular each category is, the rhythm of a month, the days of
the week, and one category up close.

Everything here counts **whole calendar months** only: the first month of
the ledger usually starts mid-month and the last one is still running, and
either would read as a cheap month (`docs/analyse.md`, « La page Analyse »).
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from . import analysis
from .models import Statement
from .review import CARD_KIND

# The year-on-year comparison wants twelve months on each side; a shorter
# history compares halves, down to this many months a side.
COMPARE_MONTHS = 12
MIN_COMPARE = 3

# How many months a category's small line shows.
SPARK_MONTHS = 24

WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def _next(month: dt.date) -> dt.date:
    return (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def whole_months(statement: Statement) -> list[str]:
    """The calendar months the ledger covers from their first day to their
    last, as `YYYY-MM`, oldest first."""
    first = min((t.date for t in statement.transactions), default=None)
    if first is None:
        return []
    start = max(first, statement.period_start)
    end = statement.period_end
    month = start.replace(day=1) if start.day == 1 else _next(start)
    out = []
    while _next(month) - dt.timedelta(days=1) <= end:
        out.append(f"{month:%Y-%m}")
        month = _next(month)
    return out


def _label(key: str) -> str:
    return analysis.bucket_label(dt.date.fromisoformat(key + "-01"), "month")


def _span(keys: list[str]) -> dict:
    return {"from": keys[0], "to": keys[-1], "label": f"{_label(keys[0])} – {_label(keys[-1])}"}


def compare_span(months: list[str]) -> int:
    """Months on each side of the year-on-year comparison: twelve, or half
    the history when it is shorter; 0 when it is too short to say anything."""
    n = min(COMPARE_MONTHS, len(months) // 2)
    return n if n >= MIN_COMPARE else 0


def year_change(statement: Statement, monthly: list[dict], months: list[str]) -> dict | None:
    """Each category over the last `n` whole months against the `n` before:
    what rose, what fell, in francs. The rows are sorted by the size of the
    move, so the page reads the biggest change first."""
    n = compare_span(months)
    if not n:
        return None
    last, before = months[-n:], months[-2 * n:-n]
    by_month = {row["month"]: row for row in monthly}

    def totals(keys):
        out: dict[str, float] = defaultdict(float)
        for key in keys:
            for category, amount in by_month.get(key, {}).get("categories", {}).items():
                out[category] += amount
        return out

    now, then = totals(last), totals(before)
    rows = []
    for category in sorted(set(now) | set(then)):
        a, b = now.get(category, 0.0), then.get(category, 0.0)
        if a < 0.5 and b < 0.5:
            continue
        rows.append({"category": category, "now": round(a, 2), "before": round(b, 2),
                     "delta": round(a - b, 2), "pct": round((a / b - 1) * 100, 1) if b >= 1 else None})
    rows.sort(key=lambda r: -abs(r["delta"]))
    total_now, total_then = sum(now.values()), sum(then.values())
    return {"months": n, "last": _span(last), "before": _span(before), "rows": rows,
            "total": {"now": round(total_now, 2), "before": round(total_then, 2),
                      "delta": round(total_now - total_then, 2),
                      "pct": round((total_now / total_then - 1) * 100, 1) if total_then >= 1 else None}}


def headline(monthly: list[dict], months: list[str], change: dict | None) -> dict:
    """The page's four figures, over whole months: what a month costs and
    brings in (medians), how much of the income stays, and the last year's
    spending against the one before."""
    rows = [r for r in monthly if r["month"] in set(months)]
    spend = [r["spending"] for r in rows]
    earn = [r["income"] for r in rows]
    rates = [(r["income"] - r["spending"]) / r["income"] for r in rows if r["income"] > 0]
    return {
        "months": len(rows),
        "spending": round(statistics.median(spend), 2) if spend else None,
        "income": round(statistics.median(earn), 2) if earn else None,
        "saving_rate": round(statistics.median(rates), 4) if rates else None,
        "year": change["total"] if change else None,
        "year_months": change["months"] if change else None,
    }


def category_lines(monthly: list[dict], months: list[str], categories: list[dict],
                   seasonal: set[str]) -> dict[str, dict]:
    """Per category: its last `SPARK_MONTHS` whole months (0 where nothing
    was spent -- a month without spend is a fact here, the profile is where
    an absent month means "not observed"), its share of the last twelve
    months, and how regular it is.

    Regular: spent in nine months out of ten, with a spread (IQR) under
    half its median -- the rent, a subscription. Variable: spent most
    months. Occasional: the rest. A seasonal category is said so whatever
    its months, its bill is the story."""
    by_month = {row["month"]: row["categories"] for row in monthly}
    shown = months[-SPARK_MONTHS:]
    year = months[-COMPARE_MONTHS:]
    year_total = sum(sum(by_month.get(k, {}).values()) for k in year) or 1.0
    out = {}
    for c in categories:
        name = c["category"]
        values = [by_month.get(k, {}).get(name, 0.0) for k in months]
        present = [v for v in values if v > 0]
        share = len(present) / len(values) if values else 0.0
        spread = None
        if len(present) >= 4:
            q = statistics.quantiles(present, n=4)
            spread = (q[2] - q[0]) / statistics.median(present)
        if name in seasonal:
            kind = "seasonal"
        elif share >= 0.9 and spread is not None and spread < 0.5:
            kind = "regular"
        elif share >= 0.6:
            kind = "variable"
        else:
            kind = "occasional"
        out[name] = {
            "spark": [round(by_month.get(k, {}).get(name, 0.0), 2) for k in shown],
            "share": round(sum(by_month.get(k, {}).get(name, 0.0) for k in year) / year_total * 100, 1),
            "months_with": len(present), "months": len(values), "kind": kind,
        }
    return out


def rhythm(statement: Statement, months: list[str]) -> dict | None:
    """How a month spends itself: the money gone by each day of the month,
    the median of the last twelve whole months with its middle half, and
    the latest month -- running or not -- against them. Days past a short
    month's end keep its total, so February ends where it ended."""
    recent = months[-COMPARE_MONTHS:]
    if len(recent) < 3:
        return None
    daily: dict[str, list[float]] = {}
    latest = f"{statement.period_end:%Y-%m}"
    wanted = set(recent) | {latest}
    for txn in analysis.spending(statement):
        key = f"{txn.date:%Y-%m}"
        if key in wanted:
            daily.setdefault(key, [0.0] * 31)[txn.date.day - 1] += abs(txn.amount_chf)

    def running(values):
        out, total = [], 0.0
        for v in values:
            total += v
            out.append(total)
        return out

    curves = [running(daily.get(key, [0.0] * 31)) for key in recent]
    median, low, high = [], [], []
    for day in range(31):
        values = sorted(c[day] for c in curves)
        q = statistics.quantiles(values, n=4) if len(values) >= 2 else [values[0]] * 3
        median.append(round(statistics.median(values), 2))
        low.append(round(q[0], 2))
        high.append(round(q[2], 2))
    current = None
    if latest in daily:
        upto = statement.period_end.day
        values = running(daily[latest])[:upto]
        current = {"month": latest, "label": _label(latest), "values": [round(v, 2) for v in values],
                   "day": upto, "whole": latest in set(recent),
                   "vs_median": round(values[-1] - median[upto - 1], 2)}
    half = next((d + 1 for d, v in enumerate(median) if v >= median[-1] / 2), None)
    return {"months": len(recent), "span": _span(recent), "median": median, "low": low,
            "high": high, "current": current, "half_day": half}


def weekdays(statement: Statement, months: list[str]) -> dict | None:
    """Card spending by day of the week over the last twelve whole months:
    the francs a weekday costs on average, and how many payments. Cards
    only -- a rent or a tax bill lands on whatever day the bank books it."""
    recent = set(months[-COMPARE_MONTHS:])
    if not recent:
        return None
    days = [0.0] * 7
    counts = [0] * 7
    for txn in analysis.spending(statement):
        if f"{txn.date:%Y-%m}" in recent and (txn.kind or "").startswith(CARD_KIND):
            days[txn.date.weekday()] += abs(txn.amount_chf)
            counts[txn.date.weekday()] += 1
    if not sum(counts):
        return None
    first = dt.date.fromisoformat(min(recent) + "-01")
    last = _next(dt.date.fromisoformat(max(recent) + "-01")) - dt.timedelta(days=1)
    seen = [0] * 7
    day = first
    while day <= last:
        seen[day.weekday()] += 1
        day += dt.timedelta(days=1)
    rows = [{"day": WEEKDAYS[i], "amount": round(days[i], 2), "count": counts[i],
             "per_day": round(days[i] / seen[i], 2) if seen[i] else 0.0} for i in range(7)]
    weekend = sum(days[5:]) / (seen[5] + seen[6]) if seen[5] + seen[6] else 0.0
    week = sum(days[:5]) / sum(seen[:5]) if sum(seen[:5]) else 0.0
    return {"rows": rows, "weekend": round(weekend, 2), "week": round(week, 2)}


def category_detail(statement: Statement, monthly: list[dict], months: list[str],
                    category: str) -> dict:
    """One category up close: its figures over the whole months, who the
    money went to over the last twelve, and each year month by month -- the
    season and the drift side by side."""
    by_month = {row["month"]: row["categories"] for row in monthly}
    values = [by_month.get(k, {}).get(category, 0.0) for k in months]
    year = set(months[-COMPARE_MONTHS:])
    txns = [t for t in analysis.spending(statement)
            if t.category == category and f"{t.date:%Y-%m}" in year]
    merchants = analysis.top_merchants(txns, limit=8)
    total = sum(m["amount"] for m in analysis.top_merchants(txns, limit=10_000)) or 1.0
    years: dict[int, list[float | None]] = {}
    for key, value in zip(months, values):
        y, m = int(key[:4]), int(key[5:])
        years.setdefault(y, [None] * 12)[m - 1] = round(value, 2)
    return {
        "months": len(values),
        "total_year": round(sum(by_month.get(k, {}).get(category, 0.0) for k in year), 2),
        "mean": round(statistics.mean(values), 2) if values else 0.0,
        "max": round(max(values), 2) if values else 0.0,
        "max_month": _label(months[values.index(max(values))]) if values and max(values) > 0 else None,
        "count_year": len(txns),
        "merchants": [{"name": m["name"], "amount": round(m["amount"], 2), "count": m["count"],
                       "median": round(m["median"], 2), "share": round(m["amount"] / total * 100, 1),
                       "last": m["last"]} for m in merchants],
        "years": [{"year": y, "months": v} for y, v in sorted(years.items())],
    }


def month_pace(statement, start: dt.date, upto: dt.date, budgets: dict[str, float]) -> dict | None:
    """The month in progress against an ordinary one: what is gone by
    `upto`, what an ordinary month had spent by the same day (median and
    middle half of the last twelve whole months, `rhythm`), and where the
    month would end if the rest of it went the ordinary way -- what is
    spent, plus what an ordinary month still spends after this day. Each
    budget against the share of the month gone, so a budget reads "on
    pace" rather than "not yet exceeded"."""
    months = [m for m in whole_months(statement) if m < f"{start:%Y-%m}"]
    shape = rhythm(statement, months)
    if shape is None:
        return None
    last = _next(start) - dt.timedelta(days=1)
    day = min(upto, last).day
    spent_by_day = [0.0] * last.day
    by_cat: dict[str, float] = defaultdict(float)
    for txn in analysis.spending(statement):
        if start <= txn.date <= upto:
            spent_by_day[txn.date.day - 1] += abs(txn.amount_chf)
            by_cat[txn.category] += abs(txn.amount_chf)
    running, total = [], 0.0
    for v in spent_by_day[:day]:
        total += v
        running.append(round(total, 2))
    ordinary_now = shape["median"][day - 1]
    ordinary_end = shape["median"][last.day - 1]
    gone = day / last.day
    return {
        "day": day, "days": last.day, "done": day == last.day,
        "spent": round(total, 2), "values": running,
        "median": shape["median"][:last.day], "low": shape["low"][:last.day], "high": shape["high"][:last.day],
        "ordinary_now": ordinary_now, "ordinary_end": ordinary_end,
        "vs_ordinary": round(total - ordinary_now, 2),
        "projected": round(total + max(ordinary_end - ordinary_now, 0.0), 2),
        "span": shape["span"], "months": shape["months"],
        "budgets": sorted(({"category": name, "budget": amount, "spent": round(by_cat.get(name, 0.0), 2),
                            "pace": round(amount * gone, 2),
                            "share": by_cat.get(name, 0.0) / amount * 100 if amount else None}
                           for name, amount in budgets.items()),
                          key=lambda b: -(b["share"] or 0)),
    }
