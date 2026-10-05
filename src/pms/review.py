"""What changed this month.

The dashboard answers well when it is asked; it never says what moved. This
compares one month against the ledger's own history and keeps four short
lists, each a question the reader would otherwise answer panel by panel:

- a fixed-price commitment whose price changed (a premium that rose in January);
- a payee never paid before;
- a debit that looks doubled;
- a category above its own habit.

Every threshold is named here. A review that cries wolf teaches its reader to
skip it -- the lesson of the late-commitments panel -- so each rule says why
it does not fire on the ordinary case.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from . import analysis, plans
from .models import Statement, Transaction

# A price is fixed when its last charges agree within this share. Anything
# beyond it, on such a price, is a real change -- whatever its size.
PRICE_STABLE = 0.01
PRICE_HISTORY = 3           # charges that must agree before the month
PRICE_MIN_CHANGE = 0.50     # below this, in the charge's own currency: rounding
# Billed at most about monthly. A canteen at 8.00 is stable too, and its
# occasional 11.50 is a different dish, not a price rise.
PRICE_MIN_INTERVAL_DAYS = 20

# A new counterparty on a transfer -- a new landlord, a new tax office, a new
# e-bill -- is news from 50 CHF. A new merchant on the card is ordinary life:
# measured on the real ledger, most months brought four or five new
# restaurants, and a list of them buries the one new landlord. So a card
# merchant is news only as a large purchase.
NEW_PAYEE_MIN = 50.0
NEW_CARD_PAYEE_MIN = 250.0
CARD_KIND = "Paiement par carte"

DUPLICATE_DAYS = 3
DUPLICATE_MIN = 20.0        # CHF: two coffees at 4.50 are two coffees
# More payments than this to one payee in the month is a habit; two equal
# amounts among them are expected, not suspicious.
HABIT_MAX_PER_MONTH = 4

# A category is above its habit past Q3 + 1.5 IQR of its whole months -- the
# outlier fence, on medians and quartiles like the rest of the app, which an
# annual bill cannot stretch -- and by at least this much.
CATEGORY_MIN_EXCESS = 100.0
SEASONAL_FACTOR = 1.5       # a seasonal month against the same month last year

HISTORY_MIN_MONTHS = 3      # whole months before the month, or no comparison
LIST_LIMIT = 6


def _order(txn: Transaction) -> tuple:
    return txn.date, txn.seq


def _whole_months(statement: Statement, before: dt.date) -> list[dict]:
    if statement.period_start >= before:
        return []
    months = analysis.timeseries(statement, "month", statement.period_start,
                                 before - dt.timedelta(days=1))
    return [m for m in months
            if (m["start"], m["end"]) == analysis.bucket_bounds(m["start"], "month")]


def _price_changes(month: list[Transaction], before: list[Transaction]) -> list[dict]:
    past: dict[str, list[Transaction]] = defaultdict(list)
    for txn in before:
        past[txn.label].append(txn)
    now: dict[str, list[Transaction]] = defaultdict(list)
    for txn in month:
        now[txn.label].append(txn)

    out = []
    for label, charges in now.items():
        history = past.get(label, [])
        if len(history) < PRICE_HISTORY:
            continue
        recent = history[-PRICE_HISTORY:]
        # Compared in the charge's own currency: a subscription billed in USD
        # moves in francs every month with the exchange rate, and that is not
        # the payee changing its price.
        if len({t.currency for t in recent + charges}) != 1:
            continue
        gaps = [(b.date - a.date).days for a, b in zip(history, history[1:])]
        if not gaps or statistics.median(gaps) < PRICE_MIN_INTERVAL_DAYS:
            continue
        amounts = [abs(t.amount) for t in recent]
        reference = amounts[-1]
        if max(amounts) - min(amounts) > PRICE_STABLE * reference:
            continue
        latest = charges[-1]
        delta = abs(latest.amount) - reference
        if abs(delta) < max(PRICE_MIN_CHANGE, PRICE_STABLE * reference):
            continue
        out.append({"label": label, "category": latest.category,
                    "currency": latest.currency, "before": reference,
                    "now": abs(latest.amount), "delta": delta,
                    "pct": delta / reference * 100, "date": latest.date})
    return sorted(out, key=lambda r: -abs(r["delta"]))[:LIST_LIMIT]


def _new_payees(month: list[Transaction], before: list[Transaction]) -> list[dict]:
    known = {t.label for t in before}
    fresh: dict[str, dict] = {}
    for txn in month:
        if txn.label in known:
            continue
        row = fresh.setdefault(txn.label, {"label": txn.label, "amount": 0.0,
                                           "count": 0, "category": txn.category,
                                           "date": txn.date, "card": True})
        row["amount"] += abs(txn.amount_chf)
        row["count"] += 1
        row["card"] = row["card"] and txn.kind.startswith(CARD_KIND)
    rows = [r for r in fresh.values()
            if r["amount"] >= (NEW_CARD_PAYEE_MIN if r["card"] else NEW_PAYEE_MIN)]
    return sorted(rows, key=lambda r: -r["amount"])[:LIST_LIMIT]


def _duplicates(month: list[Transaction]) -> list[dict]:
    by_label: dict[str, list[Transaction]] = defaultdict(list)
    for txn in month:
        by_label[txn.label].append(txn)
    out = []
    for label, rows in by_label.items():
        if len(rows) > HABIT_MAX_PER_MONTH:
            continue
        rows = sorted(rows, key=lambda t: (t.date, t.seq))
        for i, first in enumerate(rows):
            for second in rows[i + 1:]:
                if (second.date - first.date).days > DUPLICATE_DAYS:
                    break
                if (first.currency == second.currency
                        and round(first.amount, 2) == round(second.amount, 2)
                        and abs(first.amount_chf) >= DUPLICATE_MIN):
                    out.append({"label": label, "category": first.category,
                                "amount": abs(first.amount_chf),
                                "dates": [first.date, second.date]})
    return sorted(out, key=lambda r: -r["amount"])[:LIST_LIMIT]


def _quartiles(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return values[0], values[0]
    q1, _, q3 = statistics.quantiles(values, n=4)
    return q1, q3


def _above_habit(month: list[Transaction], history: list[dict],
                 seasonal: set[tuple[str, int]], first: dt.date) -> list[dict]:
    spent: dict[str, float] = defaultdict(float)
    for txn in month:
        spent[txn.category] += abs(txn.amount_chf)

    out = []
    for category, amount in spent.items():
        values = [m["categories"].get(category, 0.0) for m in history]
        if (category, first.month) in seasonal:
            # An annual bill compared against the ordinary month would be
            # flagged every year. It is compared against itself instead.
            last_year = next((m["categories"].get(category, 0.0) for m in history
                              if m["start"] == first.replace(year=first.year - 1)),
                             None)
            if last_year is None:
                continue
            if (amount > SEASONAL_FACTOR * last_year
                    and amount - last_year >= CATEGORY_MIN_EXCESS):
                out.append({"category": category, "amount": amount,
                            "habit": last_year, "seasonal": True})
            continue
        median = statistics.median(values)
        q1, q3 = _quartiles(values)
        if amount > q3 + 1.5 * (q3 - q1) and amount - median >= CATEGORY_MIN_EXCESS:
            out.append({"category": category, "amount": amount,
                        "habit": median, "seasonal": False})
    return sorted(out, key=lambda r: -(r["amount"] - r["habit"]))[:LIST_LIMIT]


def month_review(statement: Statement, first: dt.date, last: dt.date) -> dict | None:
    """The month [first, last] against everything the ledger holds before it.

    `statement` is the whole ledger. `last` may stop before the month's end
    -- the month in progress -- and the review says so: a new payee or a
    doubled debit is as real on the 21st as on the 31st, and a category
    already above its habit will not come back under it. None when fewer
    than `HISTORY_MIN_MONTHS` whole months precede the month: "unusual" needs
    a usual.
    """
    history = _whole_months(statement, first)
    if len(history) < HISTORY_MIN_MONTHS:
        return None

    spend = analysis.spending(statement)
    month = sorted((t for t in spend if first <= t.date <= last), key=_order)
    before = sorted((t for t in spend if t.date < first), key=_order)
    seasonal = {(s["category"], s["month"]) for s in plans.seasonal_one_offs(
        analysis.slice_period(statement, None, first - dt.timedelta(days=1)))}

    month_end = analysis.bucket_bounds(first, "month")[1]
    totals = [m["spending"] for m in history]
    spent = sum(abs(t.amount_chf) for t in month)
    median = statistics.median(totals)
    return {
        "first": first, "last": last, "partial": last < month_end,
        "label": plans.month_label(first.strftime("%Y-%m")).capitalize(),
        "history_months": len(history),
        "spent": spent, "median": median,
        "delta_pct": (spent / median - 1) * 100 if median else None,
        "prices": _price_changes(month, before),
        "new_payees": _new_payees(month, before),
        "duplicates": _duplicates(month),
        "categories": _above_habit(month, history, seasonal, first),
    }
