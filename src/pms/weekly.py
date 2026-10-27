"""The week in a few lines, for the summary pushed to the phone on Sunday
evening (`notify.py`, `docs/semaine.md`): what the last seven days cost
against an ordinary week, where the money went, how the month is going,
what falls due in the week ahead and what deadline is near.

Categories and amounts only -- never a payee: the message crosses a
notification server, and a régie or a person's name has no business there.
Every figure is computed here; the text only says them.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from . import analysis, lookback, upcoming

WEEK = 7
# An ordinary week: the median of the weeks before, over half a year.
HISTORY_WEEKS = 26
SHOWN_CATEGORIES = 3
DEADLINE_DAYS = 30


def _chf(value: float) -> str:
    return analysis.chf(value, 0)


def _week_sums(spend, end: dt.date, weeks: int, first: dt.date) -> list[float]:
    """Spending of each whole week before the one ending on `end`, newest
    first, as far back as the statement goes."""
    sums = []
    for w in range(1, weeks + 1):
        hi = end - dt.timedelta(days=WEEK * w)
        lo = hi - dt.timedelta(days=WEEK - 1)
        if lo < first:
            break
        sums.append(sum(-t.amount_chf for t in spend if lo <= t.date <= hi))
    return sums


def summary(statement, today: dt.date, budgets: dict[str, float] | None = None,
            floor: str | None = None) -> dict:
    """The week that ends on the statement's last day, and the one ahead of
    today. Facts first, then the lines of the message. `floor` is the
    forecast's cash alert, already a sentence (`plans.floor_alert`)."""
    end = statement.period_end
    start = end - dt.timedelta(days=WEEK - 1)
    spend = analysis.spending(statement)
    week = [t for t in spend if start <= t.date <= end]
    spent = sum(-t.amount_chf for t in week)
    before = _week_sums(spend, end, HISTORY_WEEKS, statement.period_start)
    ordinary = statistics.median(before) if len(before) >= 4 else None

    cats: dict[str, float] = defaultdict(float)
    for t in week:
        cats[t.category] += -t.amount_chf
    top = sorted(cats.items(), key=lambda kv: -kv[1])[:SHOWN_CATEGORIES]

    month_start = end.replace(day=1)
    pace = lookback.month_pace(statement, month_start, end, budgets or {})
    ahead_bills = upcoming.commitments(statement, end, max(today, end) + dt.timedelta(days=WEEK))
    first = max(today, end + dt.timedelta(days=1))
    due = sorted(((d, c) for c in ahead_bills for d in c["dues"]
                  if first <= d <= first + dt.timedelta(days=WEEK - 1)), key=lambda x: x[0])
    deadlines = [d for d in upcoming.deadlines(ahead_bills, today) if d["days"] <= DEADLINE_DAYS]
    over = [b for b in (pace or {}).get("budgets", []) if b["spent"] > b["budget"]]

    facts = {
        "start": start, "end": end, "stale": max((today - end).days, 0),
        "spent": round(spent, 2), "count": len(week),
        "ordinary": round(ordinary, 2) if ordinary is not None else None,
        "vs_ordinary": round(spent - ordinary, 2) if ordinary is not None else None,
        "top": [{"category": c, "amount": round(a, 2)} for c, a in top],
        "month": ({"spent": pace["spent"], "vs_ordinary": pace["vs_ordinary"],
                   "projected": pace["projected"], "done": pace["done"]} if pace else None),
        "due": [{"day": d, "what": c["subcategory"] or c["category"], "amount": c["amount"]} for d, c in due],
        "due_total": round(sum(c["amount"] for _, c in due), 2),
        "deadlines": [{"by": d["by"], "days": d["days"], "title": d["title"]} for d in deadlines],
        "over_budget": [{"category": b["category"], "over": round(b["spent"] - b["budget"], 2)} for b in over],
        "floor": floor,
    }
    return {**facts, **message(facts)}


def message(f: dict) -> dict:
    """The notification: a title and a few short lines, from the facts."""
    lines = []
    head = f"{_chf(f['spent'])} CHF dépensés du {f['start']:%d.%m} au {f['end']:%d.%m}"
    if f["vs_ordinary"] is not None:
        diff = f["vs_ordinary"]
        head += (f", {_chf(abs(diff))} de plus qu'une semaine ordinaire" if diff > 0.5
                 else f", {_chf(abs(diff))} de moins qu'une semaine ordinaire" if diff < -0.5
                 else ", comme une semaine ordinaire")
    lines.append(head + ".")
    if f["top"]:
        lines.append("Surtout : " + ", ".join(f"{t['category'].lower()} {_chf(t['amount'])}" for t in f["top"]) + ".")
    if f["month"]:
        m = f["month"]
        if m["done"]:
            lines.append(f"Le mois : {_chf(m['spent'])} CHF.")
        else:
            lines.append(f"Le mois : {_chf(m['spent'])} CHF à ce jour, fin probable ≈ {_chf(m['projected'])}.")
    for b in f["over_budget"]:
        lines.append(f"Budget {b['category'].lower()} dépassé de {_chf(b['over'])} CHF.")
    if f["due"]:
        items = ", ".join(f"{d['what'].lower()} {_chf(d['amount'])} le {d['day']:%d.%m}" for d in f["due"][:3])
        more = f" (+{len(f['due']) - 3})" if len(f["due"]) > 3 else ""
        lines.append(f"Les 7 prochains jours : {_chf(f['due_total'])} CHF à payer — {items}{more}.")
    for d in f["deadlines"]:
        lines.append(f"⏰ {d['title']} : avant le {d['by']:%d.%m} ({d['days']} j).")
    if f.get("floor"):
        lines.append(f"⚠ {f['floor']}")
    if f["stale"] > 10:
        lines.append(f"Le relevé s'arrête il y a {f['stale']} jours : un nouveau rendrait ce résumé juste.")
    title = "Ta semaine"
    if f["vs_ordinary"] is not None and f["ordinary"]:
        share = f["vs_ordinary"] / f["ordinary"] * 100
        if abs(share) >= 15:
            title += f" : {'+' if share > 0 else '−'}{abs(share):.0f} % de dépenses"
    return {"title": title, "lines": lines, "text": "\n".join(lines)}
