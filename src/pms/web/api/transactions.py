"""The table: filtered, sorted, paged -- the same functions as the export,
so the file holds exactly the rows the screen listed, in the same order."""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from flask import abort, request

from ... import analysis
from ..palette import colour_map
from ..views.common import PAGE_SIZE, _filtered, _sorted, account_options, page_size
from ..views.corrections import _target_choices
from . import api, payload, store
from .shell import period_of


@api.route("/api/transactions")
def transactions():
    data = store()
    args = request.args
    period = period_of(args)
    window = data.window(period["start"], period["end"])
    rows = _sorted(_filtered(window, args), args)
    size = page_size(args, PAGE_SIZE)
    total = len(rows)
    pages = max(-(-total // size), 1)
    try:
        page = int(args.get("page") or 1)
    except ValueError:
        page = 1
    page = min(max(page, 1), pages)
    # One hue per category for the window, by spend: the chips of the rows
    # and the bar of the summary agree, as on the dashboard.
    slots, _ = colour_map(analysis.by_category(analysis.spending(window)))
    return payload({
        "period": period,
        "rows": rows[(page - 1) * size: page * size],
        "total": total, "page": page, "pages": pages, "page_size": size,
        "debit_total": sum(abs(t.amount_chf) for t in rows if t.amount_chf < 0),
        "credit_total": sum(t.amount_chf for t in rows if t.amount_chf > 0),
        "categories": sorted({t.category for t in window.transactions}),
        # Shown only when there is a choice: a ledger fed by one bank has none.
        "accounts": account_options(window.transactions, data.sources),
        "slots": {c: slots.get(c, slots[analysis.OTHER])
                  for c in {t.category for t in window.transactions}},
        "summary": summary(rows, period["start"], period["end"], slots),
        "query": {k: (args.get(k) or "") for k in
                  ("q", "category", "bucket", "dir", "sort", "dir_sort",
                   "amin", "amax", "fix", "todo", "acct")},
    })


# How many categories the summary's bar names before folding the rest.
SUMMARY_PARTS = 5


def summary(rows: list, start: dt.date, end: dt.date, slots: dict[str, int]) -> dict:
    """The filtered rows in brief: what went out and came in, what a payment
    usually costs, where the money went by category, and when -- the answer
    to "how much at Coop this year" without adding up the table. Conversions
    and moves between own accounts are not spending, as everywhere."""
    out = [t for t in rows if t.amount_chf < 0 and not analysis.is_internal(t)]
    came = [t for t in rows if t.amount_chf > 0 and not analysis.is_internal(t)]
    spent = sum(-t.amount_chf for t in out)
    by_cat: dict[str, float] = defaultdict(float)
    for t in out:
        by_cat[t.category] += -t.amount_chf
    ranked = sorted(by_cat.items(), key=lambda kv: -kv[1])
    parts = [{"name": name, "amount": round(v, 2), "share": v / spent * 100 if spent else 0.0,
              "slot": slots.get(name, slots.get(analysis.OTHER))}
             for name, v in ranked[:SUMMARY_PARTS]]
    rest = sum(v for _, v in ranked[SUMMARY_PARTS:])
    if rest > 0.005:
        parts.append({"name": analysis.OTHER, "amount": round(rest, 2),
                      "share": rest / spent * 100, "slot": None, "rest": len(ranked) - SUMMARY_PARTS})

    grain = analysis.suggest_grain(start, end)
    grain = "month" if grain == "year" else grain
    series: dict[str, dict] = {}
    cursor = start
    while cursor <= end:
        key = analysis.bucket_key(cursor, grain)
        if key not in series:
            first, _ = analysis.bucket_bounds(cursor, grain)
            series[key] = {"key": key, "label": analysis.bucket_label(first, grain),
                           "out": 0.0, "in": 0.0}
        cursor += dt.timedelta(days=1)
    for t in out:
        series[analysis.bucket_key(t.date, grain)]["out"] += -t.amount_chf
    for t in came:
        series[analysis.bucket_key(t.date, grain)]["in"] += t.amount_chf
    payees: dict[str, list[float]] = defaultdict(list)
    for t in out:
        payees[t.label].append(-t.amount_chf)
    top = sorted(payees.items(), key=lambda kv: -sum(kv[1]))[:5]
    return {
        "count": len(rows), "out_count": len(out),
        "out": round(spent, 2), "in": round(sum(t.amount_chf for t in came), 2),
        "net": round(sum(t.amount_chf for t in came) - spent, 2),
        "median": round(statistics.median(-t.amount_chf for t in out), 2) if out else None,
        "parts": parts,
        "grain": grain,
        "series": [{**v, "out": round(v["out"], 2), "in": round(v["in"], 2)} for v in series.values()],
        "payees": [{"name": name, "amount": round(sum(v), 2), "count": len(v)} for name, v in top],
        "internal": sum(1 for t in rows if analysis.is_internal(t)),
    }


@api.route("/api/day/<iso>")
def day(iso: str):
    """Every movement of one day, in statement order."""
    try:
        target = dt.date.fromisoformat(iso)
    except ValueError:
        abort(404)
    data = store()
    window = data.window(target, target)
    spend = analysis.spending(window)
    low, high = data.bounds
    return payload({
        "date": target,
        "rows": sorted(window.transactions, key=lambda t: t.seq),
        "spending": sum(abs(t.amount_chf) for t in spend),
        "income": sum(t.amount_chf for t in analysis.income(window)),
        "categories": analysis.by_category(spend),
        "prev": target - dt.timedelta(days=1) if target > low else None,
        "next": target + dt.timedelta(days=1) if target < high else None,
    })


@api.route("/api/choices")
def choices():
    """What a row can be moved to: the rule engine's vocabulary plus what the
    ledger already holds."""
    return payload(_target_choices(store().statement))
