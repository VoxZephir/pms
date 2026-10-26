"""Financial independence, for `/previsions` (`docs/previsions.md`, «
L'indépendance financière »): how many years of spending the wealth already
covers, the wealth that would cover them for good at a withdrawal rate, and
when the plan reaches it -- with what a little more saving, or a little less
spending, would change.

The withdrawal rate is a convention (4 % is the one the FIRE literature
starts from; 3 to 3.5 % for a horizon longer than thirty years), chosen on
the page. The return is the one declared in the plan, never invented: with
none, the date is not given.
"""

from __future__ import annotations

from . import analysis, lookback
from . import plans as plans_module

RATES = (3.0, 3.5, 4.0)
DEFAULT_RATE = 4.0
# Past this the answer is "not in a lifetime", not a date.
MAX_MONTHS = 50 * 12
SAVED = "Épargne & investissement"
WHAT_IFS = [("save", 100.0), ("save", 500.0), ("spend", -0.10)]


def yearly_spending(statement) -> tuple[float, int]:
    """The last twelve whole months' spending, savings transfers left out
    (they are wealth moving, not spent): what independence must cover."""
    months = lookback.whole_months(statement)[-12:]
    keys = set(months)
    spent = sum(-t.amount_chf for t in analysis.spending(statement)
                if f"{t.date:%Y-%m}" in keys and t.category != SAVED)
    return (spent * 12 / len(months) if months else 0.0), len(months)


def reach(wealth: float, target: float, monthly: float, segments, rate,
          parts: list[tuple[float, list]] | None = None) -> int | None:
    """Months until `wealth`, growing at the declared rate and fed `monthly`,
    reaches `target` -- None past fifty years, or without a rate.

    `parts` are the pockets with a barème of their own, (value today,
    barème): each grows by its own, the rest of the wealth -- and what is put
    aside each month -- by the common one."""
    if wealth >= target:
        return 0
    parts = parts or []
    if rate is None and not segments and not any(s for _, s in parts):
        return None
    held = [value for value, _ in parts]
    rest = wealth - sum(held)
    for month in range(1, MAX_MONTHS + 1):
        annual = plans_module.rate_at(segments, month) if segments else rate
        rest = rest * (1 + (annual or 0.0)) ** (1 / 12) + monthly
        for i, (_, own) in enumerate(parts):
            held[i] *= (1 + (plans_module.rate_at(own, month) or 0.0)) ** (1 / 12)
        if rest + sum(held) >= target:
            return month
    return None


def independence(statement, wealth: float, income_month: float, plan, withdrawal: float,
                 parts: list[tuple[float, list]] | None = None) -> dict | None:
    spend, months = yearly_spending(statement)
    if months < 6 or spend <= 0:
        return None
    target = spend / (withdrawal / 100)
    monthly = income_month - spend / 12
    segments = list(plan.rate_segments)
    rate = plan.rate
    parts = parts or []
    declared = bool(segments) or rate is not None or any(s for _, s in parts)
    base = reach(wealth, target, monthly, segments, rate, parts)
    # Saving alone, the money earning nothing: the floor of the answer, and
    # the only one there is until a return is declared.
    flat = reach(wealth, target, monthly, [], 0.0)
    what_ifs = []
    if not declared:
        segments, rate, parts = [], 0.0, []
    for kind, value in WHAT_IFS:
        if kind == "save":
            m = reach(wealth, target, monthly + value, segments, rate, parts)
            label = f"{analysis.chf(value, 0)} CHF de plus mis de côté chaque mois"
        else:
            cut = spend * (1 + value)
            m = reach(wealth, cut / (withdrawal / 100), income_month - cut / 12, segments, rate, parts)
            label = f"{abs(value) * 100:.0f} % de dépense en moins"
        ref = base if declared else flat
        what_ifs.append({"label": label, "months": m, "wait": duration(m),
                         "sooner_label": (duration(ref - m) + " plus tôt" if ref is not None and m is not None and ref > m
                                          else "possible en moins de 50 ans" if ref is None and m is not None else None),
                         "sooner": (ref - m) if ref is not None and m is not None else None})
    return {
        "wealth": round(wealth, 2), "spend": round(spend, 2), "spend_months": months,
        "years_covered": wealth / spend, "withdrawal": withdrawal, "rates": list(RATES),
        "target": round(target, 2), "progress": min(wealth / target * 100, 100.0),
        "monthly": round(monthly, 2), "declared": declared,
        "months": base, "months_flat": flat, "what_ifs": what_ifs,
        "wait": duration(base), "wait_flat": duration(flat),
        "years_label": duration(round(wealth / spend * 12)) if wealth > 0 else "rien encore",
    }


def duration(months: int | None) -> str | None:
    """"12 ans et 3 mois", the way the page says a wait."""
    if months is None:
        return None
    if months == 0:
        return "déjà atteint"
    years, rest = divmod(months, 12)
    parts = ([f"{years} an{'s' if years > 1 else ''}"] if years else []) + ([f"{rest} mois"] if rest else [])
    return " et ".join(parts)


def withdrawal_rate(args) -> float:
    try:
        value = float(args.get("swr") or DEFAULT_RATE)
    except ValueError:
        return DEFAULT_RATE
    return value if value in RATES else DEFAULT_RATE
