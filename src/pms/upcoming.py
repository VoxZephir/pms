"""What comes next, for `/a-venir`: the commitments the ledger already knows
-- rent, premiums, subscriptions, a yearly insurance, the tax instalments --
when each falls due again, what it costs a year, how its price moved, and
the cancellation deadlines that go with them (`docs/a-venir.md`).

Everything is read off the payments themselves: a commitment is a payee
paid at a steady rhythm and a steady amount, never a list typed by hand.
Nothing here writes.
"""

from __future__ import annotations

import calendar
import datetime as dt
import statistics
from collections import defaultdict

from . import analysis, health
from . import categories as categories_module
from .review import CARD_KIND

# A rhythm needs three payments to be one -- two gaps that agree. A yearly
# bill is the exception: two years of history hold only two, and waiting a
# third year to announce the insurance would be waiting for nothing.
MIN_PAYMENTS = 3
MIN_YEARLY_PAYMENTS = 2

# Under three weeks it is a habit (the canteen, the bakery), not a bill with
# a due date; over 13 months there is no rhythm left to read.
MIN_INTERVAL = 20
MAX_INTERVAL = 400

# The gaps must agree (median deviation against the median gap) and the
# amounts must hold (coefficient of variation): the electricity bill varies
# within that, a restaurant visited "regularly" does not.
MAX_JITTER = 0.25
MAX_VARIATION = 0.6

# Silent for this many rhythms (plus a week of bank slack) and the
# commitment is over or late -- `analysis.missing_commitments` says which.
# It is not announced as coming.
ALIVE_FACTOR = 1.5
ALIVE_SLACK = 7

# A price that moved less than this is rounding, not a change.
PRICE_MOVE = 0.01

# Money to people and Twints nobody identified are not commitments, whatever
# their rhythm: a friend repaid on the 25th is not a direct debit.
NOT_BILLS = {categories_module.TWINT_UNKNOWN, "Transferts P2P", categories_module.UNCATEGORISED}

# A card payment is a choice made at the till -- the canteen, the pharmacy,
# the petrol station -- unless it renews by itself: a subscription. Only
# those filed under subscriptions count.
SUBSCRIPTIONS = "Télécom & abonnements"
# What is chosen each time is never a commitment, however regular: the
# restaurant visited every month, the weekly groceries (owner, 19.10).
CHOSEN = {"Restaurants & bars", "Alimentation", "Shopping", "Loisirs & voyages"}

# A yearly commitment seen only twice must weigh something: two small
# payments a year apart are as likely a coincidence as a contract.
MIN_YEARLY_AMOUNT = 50.0

CADENCES = [
    (7, "chaque semaine"), (14, "toutes les deux semaines"), (30.44, "chaque mois"),
    (60.9, "tous les deux mois"), (91.3, "chaque trimestre"), (182.6, "chaque semestre"),
    (365.25, "chaque année"),
]

HORIZONS = (30, 60, 90)


def _cadence(interval: float) -> tuple[float, str, int]:
    """The named rhythm nearest the measured gap, and its step in months (0
    when it is counted in days)."""
    days, label = min(CADENCES, key=lambda c: abs(c[0] - interval) / c[0])
    months = round(days / 30.44) if days >= 28 else 0
    return days, label, months


def _add_months(day: dt.date, months: int, anchor: int) -> dt.date:
    """`day` moved by whole months, on the commitment's usual day of the
    month (`anchor`), clamped to the month's length -- a rent paid on the
    31st falls on the 30th in November, and back on the 31st in December."""
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return dt.date(year, month, min(anchor, calendar.monthrange(year, month)[1]))


def _per_day(rows) -> list[tuple[dt.date, float]]:
    """One payment per day: a bill split in two lines on the same day is one."""
    days: dict[dt.date, float] = defaultdict(float)
    for t in rows:
        days[t.date] += abs(t.amount_chf)
    return sorted(days.items())


def _price(points: list[tuple[dt.date, float]], interval: float) -> dict | None:
    """How the price moved: the latest payment against the one about a year
    before it (or the first one, when the history is shorter). Only for a
    fixed price -- a bill that varies has no price to have changed."""
    amounts = [a for _, a in points]
    if len(set(round(a, 2) for a in amounts[-3:])) > 1 and interval < 300:
        return None  # the last payments disagree: a variable bill, not a price
    last_day, last = points[-1]
    year_before = last_day - dt.timedelta(days=365)
    before = min(points[:-1], key=lambda p: abs((p[0] - year_before).days))
    if abs(last - before[1]) < PRICE_MOVE * before[1]:
        first_day, first = points[0]
        if abs(last - first) < PRICE_MOVE * first:
            return None
        before = (first_day, first)
    # The day the new price first appeared: the first payment at today's price.
    since = next(d for d, a in points if abs(a - last) < PRICE_MOVE * last and d > before[0])
    return {
        "before": round(before[1], 2), "before_day": before[0],
        "now": round(last, 2), "since": since,
        "delta": round(last - before[1], 2),
        "pct": (last - before[1]) / before[1] * 100,
        "yearly_delta": round((last - before[1]) * 365.25 / interval, 2),
    }


def _year_ago(points: list[tuple[dt.date, float]]) -> float | None:
    """The payment about a year before the latest (within six weeks), the
    price the latest is compared with -- None when the history is shorter."""
    last_day = points[-1][0]
    target = last_day - dt.timedelta(days=365)
    day, amount = min(points[:-1], key=lambda p: abs((p[0] - target).days), default=(None, None))
    if day is None or abs((day - target).days) > 42:
        return None
    return round(amount, 2)


def commitments(statement, asof: dt.date, until: dt.date | None = None) -> list[dict]:
    """Every payee the ledger pays at a steady rhythm and a steady amount,
    still alive at `asof` (the statement's last day: a stale export must not
    make every bill look silent), with its due dates up to `until`. The
    largest yearly cost first."""
    until = until or asof + dt.timedelta(days=max(HORIZONS))
    groups: dict[str, list] = defaultdict(list)
    for t in analysis.spending(statement):
        if t.category in NOT_BILLS or not t.label:
            continue
        groups[t.label].append(t)

    out = []
    for label, rows in groups.items():
        points = _per_day(rows)
        if len(points) < MIN_YEARLY_PAYMENTS:
            continue
        gaps = [(b[0] - a[0]).days for a, b in zip(points, points[1:])]
        interval = statistics.median(gaps)
        if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
            continue
        yearly = interval >= 300
        if len(points) < (MIN_YEARLY_PAYMENTS if yearly else MIN_PAYMENTS):
            continue
        card = all(t.kind.startswith(CARD_KIND) for t in rows)
        if rows[-1].category in CHOSEN or (card and rows[-1].category != SUBSCRIPTIONS):
            continue
        if yearly and len(points) < MIN_PAYMENTS and points[-1][1] < MIN_YEARLY_AMOUNT:
            continue
        jitter = statistics.median(abs(g - interval) for g in gaps) / interval
        if jitter > (0.1 if yearly else MAX_JITTER):
            continue
        amounts = [a for _, a in points]
        mean = statistics.mean(amounts)
        if not mean or statistics.pstdev(amounts) / mean > MAX_VARIATION:
            continue
        last_day, last = points[-1]
        if (asof - last_day).days > interval * ALIVE_FACTOR + ALIVE_SLACK:
            continue

        days, cadence, months = _cadence(interval)
        anchor = round(statistics.median(d.day for d, _ in points[-3:]))
        recent = statistics.median(amounts[-3:]) if not yearly else last
        dues = []
        nxt = last_day
        while True:
            nxt = _add_months(nxt, months, anchor) if months else nxt + dt.timedelta(days=round(days))
            if nxt > until:
                break
            dues.append(nxt)
        first = rows[0]
        out.append({
            "label": label,
            "category": first.category,
            "subcategory": first.subcategory,
            "cadence": cadence,
            "interval": round(days, 2),
            "count": len(points),
            "first": points[0][0],
            "last": last_day,
            "amount": round(recent, 2),
            "variable": statistics.pstdev(amounts[-6:]) / mean > 0.05,
            "yearly": round(recent * 12 / months if months else recent * 365.25 / days, 2),
            "monthly": round(recent / months if months else recent * 30.44 / days, 2),
            "next": dues[0] if dues else _add_months(last_day, months, anchor) if months
                    else last_day + dt.timedelta(days=round(days)),
            "dues": dues,
            "price": _price(points, days),
            "year_ago": _year_ago(points),
            "spark": [round(a, 2) for a in amounts[-24:]],
        })
    return sorted(out, key=lambda c: -c["yearly"])


def income(statement, asof: dt.date, until: dt.date | None = None) -> list[dict]:
    """Money that comes in on a rhythm -- the salary -- with its next date,
    so the month ahead reads against what will cover it."""
    groups: dict[str, list] = defaultdict(list)
    for t in analysis.income(statement):
        if t.category != "Revenus" or t.subcategory.startswith("Remboursement"):
            continue
        groups[t.label].append(t)
    until = until or asof + dt.timedelta(days=max(HORIZONS))
    out = []
    for label, rows in groups.items():
        points = _per_day(rows)
        if len(points) < MIN_PAYMENTS:
            continue
        gaps = [(b[0] - a[0]).days for a, b in zip(points, points[1:])]
        interval = statistics.median(gaps)
        if not 25 <= interval <= 35:
            continue
        if statistics.median(abs(g - interval) for g in gaps) / interval > MAX_JITTER:
            continue
        last_day = points[-1][0]
        if (asof - last_day).days > interval * ALIVE_FACTOR + ALIVE_SLACK:
            continue
        anchor = round(statistics.median(d.day for d, _ in points[-3:]))
        amount = statistics.median(a for _, a in points[-6:])
        dues, nxt = [], last_day
        while True:
            nxt = _add_months(nxt, 1, anchor)
            if nxt > until:
                break
            dues.append(nxt)
        out.append({"label": label, "amount": round(amount, 2), "dues": dues})
    return out


def calendar_ahead(bills: list[dict], pay: list[dict], start: dt.date,
                   slots: dict[str, int], shown_from: dt.date | None = None) -> dict:
    """The due dates, one row each, and what falls within each horizon
    from `start` (today). Rows from `shown_from` on (the day after the
    statement ends): a due date between the two has probably gone out
    already, the export just stops earlier -- kept, marked `pending`, out
    of the totals."""
    shown_from = shown_from or start
    rows = []
    for c in bills:
        for d in c["dues"]:
            rows.append({"day": d, "label": c["label"], "amount": c["amount"], "out": True,
                         "category": c["category"], "slot": c.get("slot", slots.get(c["category"])),
                         "cadence": c["cadence"], "variable": c["variable"]})
    for p in pay:
        for d in p["dues"]:
            rows.append({"day": d, "label": p["label"], "amount": p["amount"], "out": False,
                         "category": "Revenus", "slot": None, "cadence": "chaque mois",
                         "variable": False})
    rows = [r for r in rows if r["day"] >= shown_from]
    rows.sort(key=lambda r: (r["day"], not r["out"], -r["amount"]))
    for r in rows:
        r["pending"] = r["day"] < start
    totals = []
    for h in HORIZONS:
        until = start + dt.timedelta(days=h)
        inside = [r for r in rows if not r["pending"] and r["day"] <= until]
        totals.append({
            "days": h, "until": until,
            "out": round(sum(r["amount"] for r in inside if r["out"]), 2),
            "in": round(sum(r["amount"] for r in inside if not r["out"]), 2),
            "count": sum(1 for r in inside if r["out"]),
        })
    gone = [r for r in rows if r["pending"]]
    return {"rows": rows, "totals": totals,
            "pending": {"count": len(gone), "out": round(sum(r["amount"] for r in gone if r["out"]), 2)}}


# --- cancellation deadlines --------------------------------------------------

HEALTH = ("Santé & assurance", "Assurance maladie")
INSURANCE = ("Santé & assurance", "Autres assurances")
# A Swiss insurance contract usually renews for a year unless cancelled three
# months before its anniversary -- usually, not always: the line says so.
INSURANCE_NOTICE_MONTHS = 3


def _months_before(day: dt.date, months: int) -> dt.date:
    return _add_months(day, -months, day.day)


def deadlines(bills: list[dict], today: dt.date) -> list[dict]:
    """The dates by which a commitment can still be changed: the basic
    health insurance for next January (a date fixed by law), and each yearly
    insurance three months before it renews (a date fixed by its contract,
    so marked to check). Soonest first; past ones dropped."""
    out = []
    insured = [c for c in bills if (c["category"], c["subcategory"]) == HEALTH and c["interval"] < 60]
    if insured:
        main = max(insured, key=lambda c: c["yearly"])
        change_by = dt.date(today.year, *health.CHANGE_BY)
        if change_by >= today:
            out.append({
                "kind": "lamal", "label": main["label"], "by": change_by,
                "days": (change_by - today).days,
                "title": "Changer de caisse maladie pour le 1er janvier",
                "detail": health.CHANGE_RULE,
                "monthly": main["monthly"], "yearly": main["yearly"], "price": main["price"],
                "certain": True,
            })
    for c in bills:
        if (c["category"], c["subcategory"]) != INSURANCE or c["interval"] < 300:
            continue
        renewal = c["next"]
        by = _months_before(renewal, INSURANCE_NOTICE_MONTHS)
        if by < today:
            continue
        out.append({
            "kind": "insurance", "label": c["label"], "by": by, "days": (by - today).days,
            "title": f"Résilier ou renégocier {c['label']}",
            "detail": (f"Prélevée {c['cadence']}, la prochaine fois vers le "
                       f"{renewal.strftime('%d.%m.%Y')} : un contrat se résilie d'habitude "
                       f"{INSURANCE_NOTICE_MONTHS} mois avant son échéance. À vérifier sur la police."),
            "monthly": c["monthly"], "yearly": c["yearly"], "price": c["price"],
            "certain": False,
        })
    return sorted(out, key=lambda d: d["by"])


def summary(bills: list[dict]) -> dict:
    """What the commitments weigh together, and what moved."""
    rises = [c for c in bills if c["price"] and c["price"]["delta"] > 0]
    falls = [c for c in bills if c["price"] and c["price"]["delta"] < 0]
    return {
        "count": len(bills),
        "yearly": round(sum(c["yearly"] for c in bills), 2),
        "monthly": round(sum(c["monthly"] for c in bills), 2),
        "rises": len(rises),
        "rises_yearly": round(sum(c["price"]["yearly_delta"] for c in rises), 2),
        "falls": len(falls),
    }
