"""The ledger against Switzerland, for `/analyse` (`docs/analyse.md`, « Contre
la Suisse »): one's own inflation against the consumer price index, and the
spending of a month against the average Swiss household.

The public figures are copied here with their source and the date they were
read: the app asks no third party at run time. They were read from the OFS
releases; check them against the linked tables before quoting them -- and
update them with each release (the index monthly, the budget survey yearly).
"""

from __future__ import annotations

from . import analysis, lookback, upcoming

# Swiss consumer price index (OFS, LIK/IPC): change against the same month a
# year before, %. Read 19.10.2026 (September 2026 released 01.10.2026).
CPI_SOURCE = "OFS, indice des prix à la consommation"
CPI_URL = "https://www.bfs.admin.ch/bfs/fr/home/statistiques/prix/indice-prix-consommation.html"
CPI_YEARLY = {2015: -1.1, 2016: -0.4, 2017: 0.5, 2018: 0.9, 2019: 0.4, 2020: -0.7,
              2021: 0.6, 2022: 2.8, 2023: 2.1, 2024: 1.1, 2025: 0.2}
CPI_MONTHLY = {
    "2025-01": 0.4, "2025-02": 0.3, "2025-03": 0.3, "2025-04": 0.0, "2025-05": -0.1, "2025-06": 0.1,
    "2025-07": 0.2, "2025-08": 0.2, "2025-09": 0.2, "2025-10": 0.1, "2025-11": 0.0, "2025-12": 0.1,
    "2026-01": 0.1, "2026-02": 0.1, "2026-03": 0.3, "2026-04": 0.6, "2026-05": 0.6, "2026-06": 0.5,
    "2026-07": 0.4, "2026-08": 0.8, "2026-09": 1.0,
}

# Household budget survey 2023 (OFS, HABE/EBM, published 17.11.2025): the
# average Swiss household, 2.07 persons, CHF a month.
HOUSEHOLD_SOURCE = "OFS, enquête sur le budget des ménages 2023"
HOUSEHOLD_URL = ("https://www.bfs.admin.ch/bfs/fr/home/statistiques/situation-economique-sociale-population/"
                 "revenus-consommation-et-fortune/budget-des-menages.html")
HOUSEHOLD_SIZE = 2.07
# Each ledger category against the survey groups that cover the same money.
# A category with no fair counterpart (shopping mixes clothing, furniture and
# electronics; P2P and Twints are not consumption) is left out, not forced.
HOUSEHOLD = [
    {"label": "Logement et énergie", "survey": 1449, "categories": ["Logement"]},
    {"label": "Transports", "survey": 744, "categories": ["Transport"]},
    {"label": "Alimentation", "survey": 638, "categories": ["Alimentation"]},
    {"label": "Restaurants et hôtels", "survey": 558, "categories": ["Restaurants & bars"],
     "subcategories": [("Loisirs & voyages", "Hébergement")]},
    {"label": "Loisirs et culture", "survey": 488, "categories": ["Loisirs & voyages"],
     "exclude": [("Loisirs & voyages", "Hébergement")]},
    # Health: care (236) plus the basic insurance premium (689), which the
    # survey counts among compulsory expenses and the ledger with health.
    {"label": "Santé, primes LAMal comprises", "survey": 236 + 689, "categories": ["Santé & assurance"],
     "exclude": [("Santé & assurance", "Autres assurances")]},
    {"label": "Communications", "survey": 162, "subcategories": [("Télécom & abonnements", "Téléphonie & internet")]},
]


# A tax bill follows the income, a savings transfer a decision: neither is a price.
NOT_PRICES = {"Impôts", "Épargne & investissement"}


def inflation(statement, fetched: dict | None = None) -> dict | None:
    """One's own price rise: the fixed-price commitments (rent, premiums,
    subscriptions) paid now against the same a year before, weighted by what
    each costs a year. A bill that varies (electricity) has no price to
    compare and stays out; the everyday shopping too -- the receipts are not
    on the statement, only their totals."""
    end = statement.period_end
    rows = []
    for c in upcoming.commitments(statement, end):
        if c["variable"] or not c["year_ago"] or c["category"] in NOT_PRICES:
            continue
        factor = c["yearly"] / c["amount"] if c["amount"] else 0.0
        rows.append({"label": c["label"], "category": c["category"], "subcategory": c["subcategory"],
                     "before": c["year_ago"], "now": c["amount"],
                     "yearly_before": round(c["year_ago"] * factor, 2), "yearly_now": c["yearly"],
                     "pct": (c["amount"] - c["year_ago"]) / c["year_ago"] * 100})
    before = sum(r["yearly_before"] for r in rows)
    if len(rows) < 2 or not before:
        return None
    now = sum(r["yearly_now"] for r in rows)
    for r in rows:
        r["contribution"] = (r["yearly_now"] - r["yearly_before"]) / before * 100
    # The months held here, extended and corrected by the last refresh
    # (`cpi.py`), which only keeps a series that agrees with these.
    monthly = {**CPI_MONTHLY, **((fetched or {}).get("monthly") or {})}
    shown = {m: v for m, v in monthly.items() if m >= "2025-01"}
    month = f"{end:%Y-%m}"
    cpi_month = max((m for m in monthly if m <= month), default=None)
    return {
        "pct": (now / before - 1) * 100, "yearly_before": round(before, 2), "yearly_now": round(now, 2),
        "delta": round(now - before, 2), "count": len(rows),
        "rows": sorted(rows, key=lambda r: -abs(r["contribution"])),
        "cpi": {"month": cpi_month, "pct": monthly.get(cpi_month) if cpi_month else None,
                "yearly": [{"year": y, "pct": v} for y, v in sorted(CPI_YEARLY.items())],
                "monthly": [{"month": m, "pct": v} for m, v in sorted(shown.items())],
                "latest": max(monthly),
                "source": (fetched or {}).get("source") or CPI_SOURCE,
                "url": (fetched or {}).get("url") or CPI_URL,
                "fetched": (fetched or {}).get("fetched")},
    }


def households(statement) -> dict | None:
    """The average month of the last twelve whole ones, group by group,
    against the average Swiss household and against it per person -- a
    person living alone spends more than a head of a couple (rent and
    subscriptions do not split), so the truth sits between the two."""
    months = lookback.whole_months(statement)[-12:]
    if len(months) < 6:
        return None
    keys = set(months)
    spend = [t for t in analysis.spending(statement) if f"{t.date:%Y-%m}" in keys]
    rows = []
    for group in HOUSEHOLD:
        cats = set(group.get("categories", []))
        subs = set(group.get("subcategories", []))
        out = set(group.get("exclude", []))
        total = sum(-t.amount_chf for t in spend
                    if (t.category in cats or (t.category, t.subcategory) in subs)
                    and (t.category, t.subcategory) not in out)
        mine = total / len(months)
        per_person = group["survey"] / HOUSEHOLD_SIZE
        rows.append({"label": group["label"], "mine": round(mine, 2), "household": float(group["survey"]),
                     "person": round(per_person, 2),
                     "vs_person": (mine / per_person - 1) * 100 if per_person else None})
    return {"months": len(months), "first": months[0], "last": months[-1], "rows": rows,
            "size": HOUSEHOLD_SIZE, "source": HOUSEHOLD_SOURCE, "url": HOUSEHOLD_URL}
