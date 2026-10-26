"""The year in review, for `/bilan` (`docs/bilan.md`): a year told in a dozen
findings -- what came in and went out, the dearest month and why, where the
money went more and less than the year before, the shops of the year, the
countries, the quietest stretch. Each finding is computed here; the page lays
them out.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from . import analysis, projects, twint, upcoming
from .review import CARD_KIND

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
# A year is told once it holds this many months of the statement.
MIN_MONTHS = 3
SAVED = "Épargne & investissement"


def years(statement) -> list[dict]:
    """The years the statement covers enough of, newest first."""
    out = []
    for year in sorted({t.date.year for t in statement.transactions}, reverse=True):
        start = max(dt.date(year, 1, 1), statement.period_start)
        end = min(dt.date(year, 12, 31), statement.period_end)
        months = len({(t.date.month) for t in statement.transactions if t.date.year == year})
        if months >= MIN_MONTHS:
            out.append({"year": year, "start": start, "end": end, "months": months,
                        "whole": start == dt.date(year, 1, 1) and end == dt.date(year, 12, 31)})
    return out


def _spend(statement, year: int):
    return [t for t in analysis.spending(statement) if t.date.year == year and t.category != SAVED]


def _income(statement, year: int):
    # Pay and other income; a friend paying back a share is not earned.
    return [t for t in analysis.income(statement) if t.date.year == year and t.category == "Revenus"
            and not t.subcategory.startswith("Remboursement")]


def review(statement, year: int, slots: dict[str, int]) -> dict:
    spend = _spend(statement, year)
    earn = _income(statement, year)
    spent = sum(-t.amount_chf for t in spend)
    earned = sum(t.amount_chf for t in earn)
    saved_in = sum(-t.amount_chf for t in analysis.spending(statement)
                   if t.date.year == year and t.category == SAVED)
    before_spend = _spend(statement, year - 1)
    before_spent = sum(-t.amount_chf for t in before_spend)
    had_before = bool(before_spend)

    # Months: the dearest and the cheapest whole ones, and what made the
    # dearest dear -- the category furthest above its own ordinary month.
    per_month: dict[int, float] = defaultdict(float)
    per_cat_month: dict[tuple[str, int], float] = defaultdict(float)
    for t in spend:
        per_month[t.date.month] += -t.amount_chf
        per_cat_month[(t.category, t.date.month)] += -t.amount_chf
    covered = sorted(per_month)
    dear = max(covered, key=lambda m: per_month[m]) if covered else None
    cheap = min(covered, key=lambda m: per_month[m]) if covered else None
    why = None
    if dear is not None and len(covered) >= 3:
        def ordinary(cat):
            values = sorted(per_cat_month.get((cat, m), 0.0) for m in covered if m != dear)
            return values[len(values) // 2] if values else 0.0
        cats = {c for c, m in per_cat_month if m == dear}
        top = max(cats, key=lambda c: per_cat_month[(c, dear)] - ordinary(c))
        why = {"category": top, "amount": round(per_cat_month[(top, dear)], 2),
               "ordinary": round(ordinary(top), 2)}

    # Categories against the year before: the largest rise and fall.
    cats_now: dict[str, float] = defaultdict(float)
    cats_before: dict[str, float] = defaultdict(float)
    for t in spend:
        cats_now[t.category] += -t.amount_chf
    for t in before_spend:
        cats_before[t.category] += -t.amount_chf
    # A part year against a whole one: compared month for month.
    scale = (len({t.date.month for t in before_spend}) / len(covered)) if had_before and covered else 1.0
    moves = sorted(((c, cats_now.get(c, 0.0) * scale - cats_before.get(c, 0.0))
                    for c in set(cats_now) | set(cats_before)), key=lambda kv: kv[1])
    rise = moves[-1] if had_before and moves and moves[-1][1] > 0 else None
    fall = moves[0] if had_before and moves and moves[0][1] < 0 else None

    # The shops: the most visited, the one that took the most.
    visits = Counter(t.label for t in spend if t.kind.startswith(CARD_KIND))
    # The shop that took the most: among what is chosen at the till, not the
    # bills (an insurer is not a shop).
    takings: dict[str, float] = defaultdict(float)
    for t in spend:
        if t.category in upcoming.CHOSEN:
            takings[t.label] += -t.amount_chf
    regular = visits.most_common(1)[0] if visits else None
    biggest_shop = max(takings.items(), key=lambda kv: kv[1]) if takings else None
    single = max(spend, key=lambda t: -t.amount_chf, default=None)
    seen_before = {t.label for t in analysis.spending(statement) if t.date.year < year}
    new_shops = len({t.label for t in spend if t.label and t.label not in seen_before}) if seen_before else None

    # Abroad: days paying on site per country -- a meal, a room, groceries;
    # a website billing from abroad is not a visit.
    abroad: dict[str, set] = defaultdict(set)
    for t in spend:
        if t.kind.startswith(CARD_KIND) and projects._on_site(t):
            country = analysis.country_of(t)
            if country and country != twint.HOME and not country.isdigit():
                abroad[country].add(t.date)
    # The trips: the stays abroad that prove presence, as `/projets` reads them.
    stays = [s for s in projects.suggestions(statement, set()) if s["start"].year == year]

    # The rhythm: the busiest weekday, the longest run without a card payment.
    by_day = Counter(t.date.weekday() for t in spend if t.kind.startswith(CARD_KIND))
    card_days = sorted({t.date for t in spend if t.kind.startswith(CARD_KIND)})
    quiet = (0, None, None)
    for a, b in zip(card_days, card_days[1:]):
        gap = (b - a).days - 1
        if gap > quiet[0]:
            quiet = (gap, a + dt.timedelta(days=1), b - dt.timedelta(days=1))

    def mlabel(m):
        return MONTHS[m - 1] if m else None

    return {
        "year": year,
        "spent": round(spent, 2), "earned": round(earned, 2), "kept": round(earned - spent, 2),
        "saved_in": round(saved_in, 2),
        "rate": (earned - spent) / earned * 100 if earned else None,
        "before": {"spent": round(before_spent, 2), "change": (spent * scale / before_spent - 1) * 100
                   if had_before and before_spent else None} if had_before else None,
        "count": len(spend),
        "dear": {"month": mlabel(dear), "amount": round(per_month[dear], 2), "why": why} if dear else None,
        "cheap": {"month": mlabel(cheap), "amount": round(per_month[cheap], 2)} if cheap else None,
        "months": [{"month": mlabel(m), "amount": round(per_month[m], 2)} for m in covered],
        "rise": {"category": rise[0], "amount": round(rise[1], 2), "slot": slots.get(rise[0])} if rise else None,
        "fall": {"category": fall[0], "amount": round(fall[1], 2), "slot": slots.get(fall[0])} if fall else None,
        "categories": [{"category": c, "amount": round(a, 2), "share": a / spent * 100 if spent else 0.0,
                        "slot": slots.get(c)} for c, a in sorted(cats_now.items(), key=lambda kv: -kv[1])[:6]],
        "regular": {"label": regular[0], "visits": regular[1]} if regular else None,
        "biggest_shop": {"label": biggest_shop[0], "amount": round(biggest_shop[1], 2)} if biggest_shop else None,
        "single": {"label": single.label, "amount": round(-single.amount_chf, 2), "date": single.date,
                   "category": single.category} if single else None,
        "new_shops": new_shops,
        "countries": [{"country": c, "days": len(d)} for c, d in sorted(abroad.items(), key=lambda kv: -len(kv[1]))],
        "stays": [{"name": s["name"], "start": s["start"], "end": s["end"], "net": s["net"]}
                  for s in sorted(stays, key=lambda s: s["start"])],
        "weekday": WEEKDAYS[by_day.most_common(1)[0][0]] if by_day else None,
        "quiet": {"days": quiet[0], "start": quiet[1], "end": quiet[2]} if quiet[0] >= 2 else None,
    }
