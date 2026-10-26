"""Need / Want / Save — the 50-30-20 view.

Shares are computed **against income**, not against spending, so the four
buckets add up to 100% of what came in:

    Need + Want + Non classé + Save == income

`Save` is therefore two things at once: money deliberately moved to a savings
or investment vehicle (3a, brokerage), plus whatever simply stayed on the
account at the end. That is what the account holder asked for, and it is also
the only definition that balances -- money that was not spent and not moved is
still money that was saved.

`Non classé` is a deliberate bucket, not a failure. Person-to-person transfers
are genuinely ambiguous (a shared rent, a gift, a reimbursement all look the
same on a statement), so they are reported separately rather than guessed at.
The Flask app will let them be reassigned by hand.

Mapping happens per category, with per-subcategory overrides where a category
straddles the line -- streaming inside "Télécom & abonnements", furniture
inside "Logement", flights inside "Transport".
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .analysis import bucket_bounds, is_internal, spending, timeseries
from .categories import INTERNAL
from .models import Statement, Transaction

NEED = "Need"
WANT = "Want"
SAVE = "Save"
UNSORTED = "Non classé"

# The two halves of `Save`. Display labels only -- never persisted, never a
# filter value, so they are written in the language of the interface.
MOVED = "Versé"
UNSPENT = "Non dépensé"

# Whole categories.
CATEGORY_BUCKET: dict[str, str] = {
    "Logement": NEED,
    "Santé & assurance": NEED,
    "Impôts": NEED,
    "Administration": NEED,
    "Alimentation": NEED,
    "Transport": NEED,
    "Télécom & abonnements": NEED,
    "Frais bancaires": NEED,
    "Restaurants & bars": WANT,
    "Loisirs & voyages": WANT,
    "Shopping": WANT,
    "Épargne & investissement": SAVE,
    "Transferts P2P": UNSORTED,
    "Twint non identifié": UNSORTED,
    "Non catégorisé": UNSORTED,
}

# Subcategories that sit on the other side of the line from their parent.
SUBCATEGORY_BUCKET: dict[tuple[str, str], str] = {
    ("Télécom & abonnements", "Streaming, jeux & logiciels"): WANT,
    ("Télécom & abonnements", "Formation & autres abonnements"): WANT,
    ("Logement", "Ameublement & bricolage"): WANT,
    ("Transport", "Avion & car longue distance"): WANT,
}

ORDER = [NEED, WANT, UNSORTED, SAVE]

DESCRIPTION = {
    NEED: "Charges contraintes : logement, santé et assurances, impôts, "
          "alimentation, transport, téléphonie.",
    WANT: "Dépenses choisies : restaurants et bars, loisirs et voyages, "
          "shopping, abonnements de confort.",
    UNSORTED: "Transferts entre particuliers et bénéficiaires non identifiés — "
              "trop ambigus pour être tranchés automatiquement.",
    SAVE: "Versements vers l'épargne et l'investissement, plus le solde non "
          "dépensé resté sur le compte.",
}


def bucket_of(txn: Transaction) -> str:
    # A manual correction beats every derived answer: it is the one signal that
    # comes from someone who actually knows what the payment was for.
    if txn.bucket_override:
        return txn.bucket_override
    # Money moved between one's own accounts is neither a need, a want nor
    # a saving: no bucket at all, rather than "Non classé" -- which made the
    # bucket's list open on rows its count had rightly left out.
    if txn.category == INTERNAL:
        return ""
    override = SUBCATEGORY_BUCKET.get((txn.category, txn.subcategory))
    if override:
        return override
    return CATEGORY_BUCKET.get(txn.category, UNSORTED)


def annotate(transactions) -> None:
    for txn in transactions:
        txn.bucket = bucket_of(txn)


def summarise(statement: Statement) -> dict:
    """Bucket totals as a share of income, with the residual folded into Save."""
    annotate(statement.transactions)

    spend = spending(statement)
    income = sum(t.amount_chf for t in statement.transactions
                 if t.amount_chf > 0 and not is_internal(t))

    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    categories: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for txn in spend:
        name = txn.bucket
        totals[name] += abs(txn.amount_chf)
        counts[name] += 1
        categories[name][txn.category] += abs(txn.amount_chf)

    transferred = totals[SAVE]
    residual = income - sum(totals[b] for b in (NEED, WANT, UNSORTED, SAVE))
    # More went out than came in -- typically a month whose salary has not
    # landed yet. Shares of income then read thousands of percent either way, true and
    # useless; they are taken of what went out instead, and the overshoot is
    # said in words rather than folded into Save as a negative block.
    basis = "income" if income and residual >= 0 else "spend"
    if basis == "income":
        totals[SAVE] += residual
        base = income
    else:
        base = sum(totals[b] for b in (NEED, WANT, UNSORTED, SAVE)) or 1.0

    # `Save` is the only bucket holding two unlike things, so it is the only one
    # that has to show its seam. Money moved to a savings vehicle is a decision;
    # money that merely never left the account is an outcome. Reporting their
    # sum as "saved" credits the decision to the outcome -- and on this
    # statement the deliberate half is exactly zero, so the merged figure would
    # be entirely the outcome wearing the decision's name.
    parts = []
    for label, amount, count, hollow in (
            (MOVED, transferred, counts[SAVE], False),
            (UNSPENT, residual if basis == "income" else 0, 0, True)):
        if amount <= 0:
            continue
        parts.append({"name": label, "amount": amount, "count": count,
                      "share": amount / base * 100, "hollow": hollow})

    rows = []
    for name in ORDER:
        rows.append({
            "name": name,
            "amount": totals[name],
            "count": counts[name],
            "share": totals[name] / base * 100,
            "description": DESCRIPTION[name],
            # Non-empty on `Save` alone; every other row draws as one segment.
            "parts": parts if name == SAVE else [],
            "categories": sorted(
                ({"name": k, "amount": v} for k, v in categories[name].items()),
                key=lambda c: -c["amount"],
            ),
        })

    return {
        "rows": rows,
        "income": income,
        # What the shares are of: "income", or "spend" when more went out.
        "basis": basis,
        "base": base,
        "overspend": -residual if basis == "spend" else 0.0,
        "residual": residual if basis == "income" else 0.0,
        "transferred_to_savings": transferred,
        "spend_total": sum(totals[b] for b in (NEED, WANT, UNSORTED)),
        # 50/30/20 is the usual yardstick; shown next to the actual split.
        "target": TARGET,
    }


# --- the shares over time ----------------------------------------------------

TARGET = {NEED: 50, WANT: 30, SAVE: 20}

# What a month's percentages are taken of. Same money, two denominators --
# like the timeline's stack switch.
SHARE_BASES = {
    # The bucket bar's own definition: the four parts make 100 % of what came
    # in, Save being what was not spent. Unbounded: negative in a month that
    # spent more than it earned, huge in a month that earned almost nothing.
    "income": "revenus",
    # What was consumed, split three ways. Always defined and bounded, but
    # Save has no place in it.
    "spending": "dépenses",
}
DEFAULT_SHARE_BASE = "income"
SMOOTHING = (1, 3, 6, 12)


def share_names(base: str) -> list[str]:
    return [NEED, WANT, UNSORTED, SAVE] if base == "income" else [NEED, WANT, UNSORTED]


def _shares(amounts: dict[str, float], base: str) -> dict[str, float | None]:
    need, want, unsorted = (amounts[NEED], amounts[WANT], amounts[UNSORTED])
    if base == "income":
        income = amounts["income"]
        if income <= 0:
            return {name: None for name in share_names(base)}
        return {NEED: need / income * 100, WANT: want / income * 100,
                UNSORTED: unsorted / income * 100,
                SAVE: (income - need - want - unsorted) / income * 100}
    consumed = need + want + unsorted
    if consumed <= 0:
        return {name: None for name in share_names(base)}
    return {NEED: need / consumed * 100, WANT: want / consumed * 100,
            UNSORTED: unsorted / consumed * 100}


def _ordinal(day: dt.date) -> int:
    return day.year * 12 + day.month


def shares_by_month(statement: Statement, start: dt.date, end: dt.date,
                    base: str = DEFAULT_SHARE_BASE, smooth: int = 1) -> list[dict]:
    """Need / Want / Save as a share of each whole month of [start, end].

    `statement` is the whole ledger, not the window: a rolling sum reaches
    back before `start` when the ledger holds those months.

    Whole months only. A month the ledger covers in part swings for reasons
    that are not the reader's -- the salary has landed, the rent not yet --
    and smoothing must not launder that into a trend.

    Smoothing is a ratio of rolling sums -- sum of the bucket over the last
    `smooth` months, divided by the sum of the base -- and never a mean of
    monthly ratios: in a mean, a month with 200 CHF of income weighs as much
    as a salary month, and its thousands of percent negative drown everything else. Before the
    ledger holds `smooth` consecutive whole months, the value is None: a
    series stops where its data stops.
    """
    months = timeseries(statement, "month", statement.period_start,
                        statement.period_end)
    whole = [m for m in months
             if (m["start"], m["end"]) == bucket_bounds(m["start"], "month")]

    def amounts(run: list[dict]) -> dict[str, float]:
        out = {name: sum(m["buckets"].get(name, 0.0) for m in run)
               for name in (NEED, WANT, UNSORTED)}
        out["income"] = sum(m["income"] for m in run)
        return out

    rows = []
    for i, month in enumerate(whole):
        if not (start <= month["start"] and month["end"] <= end):
            continue
        run = whole[max(0, i - smooth + 1):i + 1]
        complete = (len(run) == smooth and _ordinal(run[-1]["start"])
                    - _ordinal(run[0]["start"]) == smooth - 1)
        own = amounts([month])
        rows.append({
            "key": month["key"], "label": month["label"],
            "start": month["start"], "end": month["end"],
            "income": own["income"],
            "amounts": {name: own[name] for name in (NEED, WANT, UNSORTED)},
            "raw": _shares(own, base),
            "smooth": (_shares(amounts(run), base) if complete
                       else {name: None for name in share_names(base)}),
        })
    return rows
