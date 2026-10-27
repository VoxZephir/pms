"""Forecast against what happened (`docs/previsions.md`, « Prévu contre réel »).

Two sources, the same comparison:

- **the plan**: what `plans.project` said with the plan on screen, kept once
  per month of the statement it started from (`data/forecasts.json`), so a
  month ends with what was expected of it a month or more before;
- **the method**: the projection replayed from past month-ends with no plan
  at all -- history only, as if the ledger stopped there. It needs no
  record, so it answers from the first day: how far off is a forecast made
  this way, and in which direction.

A month is compared once it is wholly in the ledger. The cash identity
holds on both sides (end = start + income - outflows), so the gap in cash
splits exactly into a gap in income and a gap in outflows; the categories
that ran above their own usual month say where the outflows came from.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import statistics
from dataclasses import replace
from pathlib import Path

from . import analysis, plans
from .models import AccountSummary, Statement

# History a forecast is built from before it is worth replaying: the
# medians of fewer months say little.
MIN_HISTORY_MONTHS = 6
# How far each replayed or kept forecast looks ahead.
HORIZON = 3
# Kept forecasts of the plan, one per month: three years.
KEEP = 36
# A bias worth saying: this many francs a month on average, the same sign in
# two months out of three.
BIAS_CHF = 100.0


def _month_end(key: str) -> dt.date:
    y, m = int(key[:4]), int(key[5:7])
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def complete_months(statement: Statement) -> list[str]:
    """Calendar months the ledger holds whole, oldest first."""
    first, last = statement.period_start, statement.period_end
    keys = []
    y, m = first.year, first.month
    if first.day != 1:
        m += 1
        if m == 13:
            y, m = y + 1, 1
    while True:
        key = f"{y:04d}-{m:02d}"
        if _month_end(key) > last:
            break
        keys.append(key)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return keys


def cash_at(statement: Statement, day: dt.date) -> float:
    """CHF held at the end of `day`, every account summed (the same chains
    as `analysis.closing_chf`)."""
    held: dict[tuple[str, str], float] = {
        (a.account, a.currency): a.opening_balance for a in statement.accounts if a.currency == "CHF"}
    for t in statement.transactions:
        if t.currency == "CHF" and t.date <= day:
            held[(t.account, t.currency)] = held.get((t.account, t.currency), 0.0) + t.amount
    return round(sum(held.values()), 2)


def truncate(statement: Statement, cutoff: dt.date) -> Statement:
    """The ledger as it stood on `cutoff`: its rows up to that day, each
    account closing at its opening plus those rows. The rows are the same
    objects, already converted to francs over the whole ledger."""
    rows = [t for t in statement.transactions if t.date <= cutoff]
    accounts = []
    for a in statement.accounts:
        net = sum(t.amount for t in rows if t.account == a.account and t.currency == a.currency)
        accounts.append(AccountSummary(currency=a.currency, opening_balance=a.opening_balance,
                                       closing_balance=round(a.opening_balance + net, 2),
                                       credit_total=0.0, debit_total=0.0, account=a.account))
    return replace(statement, period_end=cutoff, accounts=accounts, transactions=rows)


def actuals(statement: Statement) -> dict[str, dict]:
    """Per whole month: income, outflows (what left the cash, transfers
    included), cash at the end, and spending per category."""
    by_month = {row["month"]: row for row in analysis.monthly(statement)}
    out = {}
    keys = complete_months(statement)
    for key in keys:
        start_day = _month_end(key).replace(day=1) - dt.timedelta(days=1)
        start = cash_at(statement, start_day)
        end = cash_at(statement, _month_end(key))
        row = by_month.get(key, {"income": 0.0, "categories": {}})
        income = round(row["income"], 2)
        out[key] = {"start": start, "end": end, "income": income,
                    "outflow": round(start + income - end, 2),
                    "categories": row["categories"]}
    return out


def _why(key: str, actual: dict[str, dict], keys: list[str]) -> list[dict]:
    """The categories that ran furthest above their own median of the
    twelve months before: where an overrun came from."""
    before = [k for k in keys if k < key][-12:]
    if len(before) < 3:
        return []
    cats = set(actual[key]["categories"])
    for k in before:
        cats |= set(actual[k]["categories"])
    over = []
    for c in cats:
        usual = statistics.median([actual[k]["categories"].get(c, 0.0) for k in before])
        diff = actual[key]["categories"].get(c, 0.0) - usual
        if diff >= 50:
            over.append({"category": c, "over": round(diff, 2)})
    return sorted(over, key=lambda o: -o["over"])[:3]


def _compare(forecasts: list[dict], actual: dict[str, dict], keys: list[str]) -> dict:
    """Each forecast's months that are now whole, against what happened."""
    runs = []
    pairs = []   # one month ahead: the calibration
    for f in forecasts:
        points = []
        for ahead, row in enumerate(f["rows"], start=1):
            a = actual.get(row["key"])
            if a is None:
                continue
            point = {"key": row["key"], "label": row["label"], "ahead": ahead,
                     "forecast": row["end"], "actual": a["end"],
                     "gap": round(a["end"] - row["end"], 2),
                     "income_gap": round(a["income"] - row["income"], 2),
                     "outflow_gap": round(a["outflow"] - row["spend"], 2)}
            points.append(point)
            if ahead == 1:
                pairs.append({**point, "made": f["made"], "plan": f.get("plan"),
                              "forecast_income": row["income"], "forecast_outflow": row["spend"],
                              "income": a["income"], "outflow": a["outflow"],
                              "why": _why(row["key"], actual, keys)})
        if points:
            runs.append({"made": f["made"], "plan": f.get("plan"), "start": f["start"], "points": points})
    pairs = sorted(pairs, key=lambda p: p["key"])[-12:]
    return {"runs": runs[-12:], "months": pairs, "bias": _bias(pairs)}


def _bias(pairs: list[dict]) -> dict | None:
    """The average gap a month ahead, in income and in outflows, and
    whether it is a habit (same sign two months in three) or noise."""
    if len(pairs) < 3:
        return None
    def side(key: str) -> dict:
        values = [p[key] for p in pairs]
        mean = statistics.fmean(values)
        same = sum(1 for v in values if (v > 0) == (mean > 0)) / len(values)
        return {"mean": round(mean, 2), "steady": abs(mean) >= BIAS_CHF and same >= 2 / 3}
    return {"count": len(pairs), "income": side("income_gap"), "outflow": side("outflow_gap"),
            "cash": side("gap")}


def _forecast_of(projection: dict, made: dt.date, plan_name: str | None, horizon: int) -> dict:
    rows = [r for r in projection["rows"] if not r.get("partial")][:horizon]
    return {"made": made.isoformat(), "plan": plan_name, "start": projection["cash"],
            "rows": [{"key": r["key"], "label": r["label"], "income": r["income"],
                      "spend": r["spend"], "end": r["end"]} for r in rows]}


def replay(statement: Statement, horizon: int = HORIZON) -> list[dict]:
    """The method, from each past month-end with enough history behind it:
    `plans.project` on the ledger cut there, with no plan."""
    keys = complete_months(statement)
    out = []
    for i, key in enumerate(keys[:-1]):
        if i + 1 < MIN_HISTORY_MONTHS:
            continue
        cutoff = _month_end(key)
        past = truncate(statement, cutoff)
        projection = plans.project(past, None, months_ahead=horizon)
        out.append(_forecast_of(projection, cutoff, None, horizon))
    return out[-12:]


def method(statement: Statement) -> dict:
    """How the history-only forecast would have done, month by month."""
    actual = actuals(statement)
    return _compare(replay(statement), actual, sorted(actual))


# --- the plan's own forecasts, kept --------------------------------------------------------

def load(path: Path) -> list[dict]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [f for f in raw.get("forecasts", []) if isinstance(f, dict) and f.get("rows")] \
        if isinstance(raw, dict) else []


def record(path: Path, statement: Statement, projection: dict, plan_name: str | None,
           horizon: int = 12) -> bool:
    """Keep what the plan forecasts from this statement, once per month of
    its last day: the first look of the month is the one compared, before
    any hindsight. True when something was written."""
    forecasts = load(path)
    month = statement.period_end.strftime("%Y-%m")
    if any(f["made"][:7] == month for f in forecasts):
        return False
    forecast = _forecast_of(projection, statement.period_end, plan_name, horizon)
    if not forecast["rows"]:
        return False
    forecasts = sorted(forecasts + [forecast], key=lambda f: f["made"])[-KEEP:]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"forecasts": forecasts}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    temporary.replace(path)
    return True


def kept(statement: Statement, path: Path) -> dict:
    """The plan's kept forecasts against what happened since."""
    actual = actuals(statement)
    forecasts = load(path)
    out = _compare(forecasts, actual, sorted(actual))
    out["kept"] = len(forecasts)
    out["first"] = forecasts[0]["made"] if forecasts else None
    return out
