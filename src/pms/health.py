"""The basic health insurance franchise, replayed: what each franchise would
have cost a year -- premiums plus the share of the care left to pay -- for
the care costs of each year, and which one comes out cheapest
(`docs/a-venir.md`).

The law fixes the share left to pay (the franchise, then 10 % of the rest up
to a cap) and caps the premium discount a higher franchise may give: at most
70 % of the extra risk taken. The replay assumes an insurer that grants the
whole discount -- many do, not all -- and says so; the exact premiums of
every insurer are on priminfo.admin.ch.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from . import analysis

# Adult franchises (CHF a year), the share above the franchise, its yearly
# cap, and the largest premium discount for each franc of franchise above
# the lowest (OAMal art. 93 and 95).
FRANCHISES = (300, 500, 1000, 1500, 2000, 2500)
LOWEST = FRANCHISES[0]
QUOTE_PART = 0.10
QUOTE_PART_CAP = 700.0
MAX_DISCOUNT = 0.70

# The cost axis of the chart: up to this much care a year, by this step.
AXIS_MAX = 8000
AXIS_STEP = 100

CARE = ("Santé & assurance", "Pharmacie & soins")
HEALTH = ("Santé & assurance", "Assurance maladie")


def left_to_pay(costs: float, franchise: int) -> float:
    """The share of a year's care the insured pays: the franchise first,
    then 10 % of the rest, capped."""
    costs = max(costs, 0.0)
    return min(costs, franchise) + min(QUOTE_PART * max(costs - franchise, 0.0), QUOTE_PART_CAP)


def premiums(premium_month: float, franchise: int) -> dict[int, float]:
    """Each franchise's monthly premium, from the one paid today at
    `franchise`: back to the lowest franchise's premium, then the largest
    discount the law allows for each other."""
    base = premium_month + MAX_DISCOUNT * (franchise - LOWEST) / 12
    return {f: round(max(base - MAX_DISCOUNT * (f - LOWEST) / 12, 0.0), 2) for f in FRANCHISES}


def yearly_cost(costs: float, franchise: int, premium_month: float) -> float:
    return round(12 * premium_month + left_to_pay(costs, franchise), 2)


def gross_from_paid(paid: float, franchise: int) -> tuple[float, bool]:
    """The care costs that leave `paid` to the insured at `franchise` --
    `left_to_pay` read backwards -- and whether that is exact. Past the cap
    every larger cost leaves the same share: the answer is a floor."""
    if paid <= franchise:
        return round(paid, 2), True
    above = paid - franchise
    if above >= QUOTE_PART_CAP:
        return round(franchise + QUOTE_PART_CAP / QUOTE_PART, 2), False
    return round(franchise + above / QUOTE_PART, 2), True


def care_by_year(statement, insurer: str | None, franchise: int) -> list[dict]:
    """Each year's care, as far as the statement shows it: paid to
    pharmacies and practitioners, billed by the insurer on top of the
    premium (its share of a bill it paid directly), less what it refunded.
    That is the share left to the insured; read backwards through the
    franchise, it gives the year's care costs."""
    paid: dict[int, float] = defaultdict(float)
    refunds: dict[int, float] = defaultdict(float)
    billed: dict[int, float] = defaultdict(float)
    insurer_rows: dict[int, list[float]] = defaultdict(list)
    for t in statement.transactions:
        if analysis.is_internal(t):
            continue
        key = (t.category, t.subcategory)
        if key == CARE and t.amount_chf < 0:
            paid[t.date.year] += -t.amount_chf
        elif t.category == CARE[0] and t.subcategory == "Remboursement" and t.amount_chf > 0:
            refunds[t.date.year] += t.amount_chf
        elif insurer and t.label == insurer and t.amount_chf < 0:
            insurer_rows[t.date.year].append(-t.amount_chf)
    for year, amounts in insurer_rows.items():
        # The premium is the year's most common amount; anything else the
        # insurer debits is its share of a bill.
        premium = max(set(round(a, 2) for a in amounts), key=lambda a: sum(1 for b in amounts if round(b, 2) == a))
        billed[year] = sum(a for a in amounts if abs(a - premium) > 0.01 * premium)
    first, last = statement.period_start, statement.period_end
    out = []
    for year in sorted(set(paid) | set(refunds) | set(billed)):
        start = max(dt.date(year, 1, 1), first)
        end = min(dt.date(year, 12, 31), last)
        share = max(paid[year] + billed[year] - refunds[year], 0.0)
        gross, exact = gross_from_paid(share, franchise)
        out.append({"year": year, "paid": round(paid[year], 2), "billed": round(billed[year], 2),
                    "refunds": round(refunds[year], 2), "share": round(share, 2),
                    "costs": gross, "exact": exact,
                    "whole": start == dt.date(year, 1, 1) and end == dt.date(year, 12, 31),
                    "until": end})
    return out


def detected_premium(bills: list[dict]) -> dict | None:
    """The monthly premium the ledger pays its health insurer, if one is
    paid monthly: the largest such commitment."""
    health = [c for c in bills if (c["category"], c["subcategory"]) == HEALTH and c["interval"] < 60]
    if not health:
        return None
    main = max(health, key=lambda c: c["yearly"])
    return {"label": main["label"], "monthly": main["monthly"]}


def replay(franchise: int, premium_month: float, costs: float, years: list[dict]) -> dict:
    """Every franchise at the stated care costs, the cheapest, the curve of
    yearly cost against care costs, and each observed year replayed."""
    month = premiums(premium_month, franchise)
    rows = [{"franchise": f, "premium": month[f],
             "premiums": round(12 * month[f], 2),
             "left": round(left_to_pay(costs, f), 2),
             "total": yearly_cost(costs, f, month[f])} for f in FRANCHISES]
    best = min(rows, key=lambda r: r["total"])
    current = next(r for r in rows if r["franchise"] == franchise)
    axis = list(range(0, AXIS_MAX + 1, AXIS_STEP))
    curves = [{"franchise": f, "values": [yearly_cost(x, f, month[f]) for x in axis]} for f in FRANCHISES]
    # Where the highest franchise stops being the cheaper of the two ends:
    # the care costs from which the lowest one wins.
    hi, lo = FRANCHISES[-1], LOWEST
    crossing = next((x for x in axis if yearly_cost(x, lo, month[lo]) < yearly_cost(x, hi, month[hi])), None)
    replayed = []
    for y in years:
        at = {f: yearly_cost(y["costs"], f, month[f]) for f in FRANCHISES}
        cheapest = min(at, key=at.get)
        replayed.append({**y, "best": cheapest, "saving": round(at[franchise] - at[cheapest], 2)})
    return {
        "franchise": franchise, "premium": round(premium_month, 2), "costs": round(costs, 2),
        "rows": rows, "best": best["franchise"],
        "saving": round(current["total"] - best["total"], 2),
        "axis": axis, "curves": curves, "crossing": crossing,
        "years": replayed,
        "rules": {"quote_part": QUOTE_PART * 100, "cap": QUOTE_PART_CAP, "discount": MAX_DISCOUNT * 100},
    }


# --- the declared franchise ---------------------------------------------------

# The basic insurance changes insurer for 1 January only, by a notice the
# insurer receives by 30 November (LAMal art. 7).
CHANGE_BY = (11, 30)
CHANGE_RULE = ("La résiliation doit être reçue par la caisse au plus tard le 30 novembre "
               "(envoi recommandé) ; la nouvelle caisse ne peut pas refuser l'assurance de base.")


def load_settings(path) -> dict:
    """The franchise the insured declared (`data/health.json`), or the
    lowest when none was declared yet -- marked, so the page asks."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        franchise = int(raw.get("franchise"))
    except (OSError, ValueError, TypeError, AttributeError):
        return {"franchise": LOWEST, "declared": False}
    return {"franchise": franchise if franchise in FRANCHISES else LOWEST, "declared": franchise in FRANCHISES}


def save_settings(path, franchise: int) -> None:
    if franchise not in FRANCHISES:
        raise ValueError(f"Franchise inconnue : {franchise}")
    Path(path).write_text(json.dumps({"franchise": franchise}, indent=2), encoding="utf-8")
