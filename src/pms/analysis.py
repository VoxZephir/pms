"""Aggregations powering the dashboard.

Two modelling decisions drive everything here.

1. **Forex transfers are internal, not spending.** Every EUR/USD card payment is
   funded by an automatic CHF -> EUR/USD conversion carrying the same reference
   as its own leg. Counting both the CHF leg and the foreign purchase would
   double-count. So both conversion legs are excluded from spending, and each
   foreign purchase is converted to CHF instead (see `_fx_index`). Both foreign
   accounts open and close at exactly 0.00, which is what makes this sound: the
   sum of the CHF legs *is* the CHF cost of all foreign spending.

2. **The custodian's cost is the gap between the printed rate and the rate
   actually applied.** Each conversion prints "Taux de change: 1 CHF = X EUR"
   and, separately, the CHF amount actually debited. Those two disagree by a
   very stable ~0.97%: that difference is Swissquote's FX markup, and it is the
   only cost the bank charges on this account.
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
from bisect import bisect_left, bisect_right
from collections import defaultdict

from .models import AccountSummary, Statement, Transaction

FX_KINDS = ("Transfert automatisé", "Transfert Forex manuel")

# What a folded tail is called, wherever one is folded -- categories past the
# eighth colour slot, payers past the seventh. One name, because it means the
# same thing in both places and the reader should not have to check.
OTHER = "Autres"


def chf(value: float, decimals: int = 2) -> str:
    """Swiss number formatting: 12'345.67 (apostrophe as thousands separator)."""
    return f"{value:,.{decimals}f}".replace(",", "’")


def is_fx_leg(txn: Transaction) -> bool:
    """True for either side of an internal currency conversion."""
    return txn.kind.startswith(FX_KINDS)


def _fx_index(statement: Statement) -> dict[str, tuple[list[dt.date], list[float]]]:
    """Per currency, the effective CHF-per-unit rate of each conversion, by date.

    Built from the foreign leg, which carries both the credited foreign amount
    and the CHF actually debited ("Montant: 763.86 CHF").
    """
    points: dict[str, list[tuple[dt.date, float]]] = defaultdict(list)
    for txn in statement.transactions:
        if not is_fx_leg(txn) or txn.currency == "CHF":
            continue
        if not txn.fx_counter_amount or not txn.amount:
            continue
        points[txn.currency].append((txn.date, txn.fx_counter_amount / abs(txn.amount)))

    index: dict[str, tuple[list[dt.date], list[float]]] = {}
    for currency, series in points.items():
        series.sort()
        index[currency] = ([d for d, _ in series], [r for _, r in series])
    return index


def to_chf(txn: Transaction, index: dict[str, tuple[list[dt.date], list[float]]]) -> float:
    """Signed amount expressed in CHF, using the conversion nearest in time."""
    if txn.currency == "CHF":
        return txn.amount
    dates, rates = index.get(txn.currency, ([], []))
    if not dates:
        return txn.amount
    pos = bisect_left(dates, txn.date)
    candidates = [p for p in (pos - 1, pos) if 0 <= p < len(dates)]
    best = min(candidates, key=lambda p: abs((dates[p] - txn.date).days))
    return txn.amount * rates[best]


def annotate_chf(statement: Statement) -> None:
    """Attach `amount_chf` to every transaction.

    Picking the nearest conversion leaves a small residual (~0.5 CHF on this
    statement), because a day's purchases are funded by one conversion at one
    rate. Since each foreign account opens and closes at 0.00, the exact CHF
    cost of that currency's spending is known: it is the sum of the CHF legs.
    So the per-transaction estimates are scaled to hit that total, which makes
    "opening + income - spending == closing" tie out to the centime.
    """
    index = _fx_index(statement)
    for txn in statement.transactions:
        txn.amount_chf = to_chf(txn, index)

    for currency in index:
        legs = [t for t in statement.transactions
                if t.currency == currency and is_fx_leg(t)]
        purchases = [t for t in statement.transactions
                     if t.currency == currency and not is_fx_leg(t)]
        target = -sum(t.fx_counter_amount or 0.0 for t in legs)
        estimate = sum(t.amount_chf for t in purchases)
        if estimate and target:
            factor = target / estimate
            for txn in purchases:
                txn.amount_chf *= factor


def spending(statement: Statement) -> list[Transaction]:
    """Outgoing money that represents real spending (conversions excluded)."""
    return [t for t in statement.transactions if t.amount_chf < 0 and not is_fx_leg(t)]


def income(statement: Statement) -> list[Transaction]:
    return [t for t in statement.transactions if t.amount_chf > 0 and not is_fx_leg(t)]


def xirr(cashflows: list[tuple[dt.date, float]]) -> float | None:
    """The annual rate that brings the cashflows' value to zero.

    Investor's sign: money put in is negative, money taken out (and the
    value left at the end) positive. Bisection rather than Newton: the
    derivative can vanish on the flows of a current account, and a rate
    found slowly beats one that diverges. None when the flows cannot have
    a rate (all one sign) or it lies outside -99 % .. +1000 % a year.
    """
    flows = [(day, amount) for day, amount in cashflows if amount]
    if not flows or all(a > 0 for _, a in flows) or all(a < 0 for _, a in flows):
        return None
    first = min(day for day, _ in flows)

    def npv(rate: float) -> float:
        return sum(amount / (1 + rate) ** ((day - first).days / 365.25)
                   for day, amount in flows)

    low, high = -0.99, 10.0
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        return None
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7 or high - low < 1e-10:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def money_weighted(start_value: float, end_value: float,
                   flows: list[tuple[dt.date, float]], start: dt.date,
                   end: dt.date) -> float | None:
    """The money-weighted return over [start, end], *for the period* (not
    annualized), next to a TWR that is also for the period.

    `flows` are deposits into the pocket (+) and withdrawals (-), dated
    within (start, end]. A deposit just before a rise weighs more than one
    just before a fall -- that is the whole difference with the TWR, which
    the panel shows side by side.
    """
    if start_value <= 0 or end <= start:
        return None
    cash = [(start, -start_value)] + [(day, -amount) for day, amount in flows
                                      if start < day <= end] + [(end, end_value)]
    rate = xirr(cash)
    if rate is None:
        return None
    return (1 + rate) ** ((end - start).days / 365.25) - 1


def risk_stats(values: list[float], years: float,
               risk_free: float = 0.005,
               periods_per_year: float = 12) -> dict:
    """testfolio-style risk and return summary from a value series.

    `values` is a series of month-spaced levels; the return stats are
    annualized from the monthly changes, the drawdowns from the levels
    themselves. `years` is the span of the series for the CAGR; the
    risk-free rate is the dated assumption behind the Sharpe (0.5 %,
    checked 2026 -- rates move).
    """
    if len(values) < 3:
        return {}
    returns = [values[i] / values[i - 1] - 1
               for i in range(1, len(values)) if values[i - 1] > 0]
    if not returns:
        return {}

    vol = statistics.stdev(returns) * (periods_per_year ** 0.5) \
        if len(returns) > 1 else 0.0
    cagr = (values[-1] / values[0]) ** (1 / years) - 1 if years > 0 else 0.0

    peak = values[0]
    drawdowns = []
    longest = current = 0
    for value in values:
        if value > peak:
            peak = value
        dd = (value - peak) / peak
        drawdowns.append(dd)
        current = current + 1 if dd < 0 else 0
        longest = max(longest, current)
    underwater = [d for d in drawdowns if d < 0]

    downside = [r for r in returns if r < 0]
    down_vol = statistics.stdev(downside) * (periods_per_year ** 0.5) \
        if len(downside) > 1 else 0.0

    return {
        "final": values[-1],
        "cumulative": values[-1] / values[0] - 1,
        "cagr": cagr,
        "vol": vol,
        "sharpe": (cagr - risk_free) / vol if vol else None,
        "sortino": (cagr - risk_free) / down_vol if down_vol else None,
        "max_dd": min(drawdowns),
        "avg_dd": (sum(underwater) / len(underwater)) if underwater else 0.0,
        "longest_dd": longest,
        "ulcer": (sum(d * d for d in drawdowns) / len(drawdowns)) ** 0.5,
        "calmar": (cagr / abs(min(drawdowns))) if min(drawdowns) else None,
    }


def balance_at(statement: Statement, day: dt.date) -> float:
    """The CHF running balance on (or just before) `day`, from the printed chain.

    Indexed once per statement and bisected: the savings section asks for
    every day of the window, and a scan of 2'400 rows per day made a
    two-year daily curve cost seconds.
    """
    rows = statement.transactions
    cached = getattr(statement, "_balance_index", None)
    if cached is None or cached[0] is not rows or cached[1] != len(rows):
        chf = [(t.date, t.balance) for t in rows
               if t.currency == "CHF" and t.balance is not None]
        ordered = all(a[0] <= b[0] for a, b in zip(chf, chf[1:]))
        cached = (rows, len(rows), [d for d, _ in chf], [b for _, b in chf],
                  ordered)
        try:
            statement._balance_index = cached
        except AttributeError:  # a frozen or slotted statement: no cache
            pass
    _, _, dates, balances, ordered = cached
    if not balances:
        return 0.0
    if not ordered:
        # Out-of-order rows keep the old meaning: the last one, in list
        # order, dated on or before the day.
        best = None
        for when, balance in zip(dates, balances):
            if when <= day:
                best = balance
        return balances[0] if best is None else best
    i = bisect_right(dates, day)
    return balances[i - 1] if i else balances[0]


# --- custodian ------------------------------------------------------------

# What the same conversion would cost elsewhere: published rates, checked on
# 02.08.2026. FX markups move, so date the figure and re-check before quoting
# it -- an undated number ages badly.
REFERENCE_FX_AS_OF = "02.08.2026"
REFERENCE_FX_MARKUP = [
    {"name": "Wise", "rate": 0.41,
     "note": "frais publiés sur les conversions CHF"},
    {"name": "neon", "rate": 1.5,
     "note": "plan gratuit"},
    {"name": "Revolut", "rate": 0.0,
     "note": "plan standard, dans le forfait"},
]


def custodian_costs(statement: Statement) -> dict:
    """Break down every franc Swissquote kept, and how it was charged."""
    conversions = []
    for txn in statement.transactions:
        if not is_fx_leg(txn) or txn.currency == "CHF" or not txn.fx_rate:
            continue
        foreign = abs(txn.amount)
        charged = txn.fx_counter_amount or 0.0
        reference = foreign / txn.fx_rate  # value at the rate the statement prints
        markup = charged - reference
        conversions.append({
            "date": txn.date,
            "reference": txn.reference,
            "currency": txn.currency,
            "foreign_amount": foreign,
            "printed_rate": txn.fx_rate,
            "charged_chf": charged,
            "reference_chf": reference,
            "markup_chf": markup,
            "markup_pct": (markup / reference * 100) if reference else 0.0,
            "manual": "manuel" in txn.kind,
        })
    conversions.sort(key=lambda c: c["date"])

    by_currency: dict[str, dict] = {}
    for conv in conversions:
        bucket = by_currency.setdefault(conv["currency"], {
            "currency": conv["currency"], "count": 0,
            "volume_chf": 0.0, "markup_chf": 0.0,
        })
        bucket["count"] += 1
        bucket["volume_chf"] += conv["charged_chf"]
        bucket["markup_chf"] += conv["markup_chf"]
    for bucket in by_currency.values():
        base = bucket["volume_chf"] - bucket["markup_chf"]
        bucket["markup_pct"] = (bucket["markup_chf"] / base * 100) if base else 0.0

    # Negative balance interest, charged in the foreign currency.
    interest = [t for t in statement.transactions
                if t.kind.startswith("Intérêts") and t.amount_chf < 0]
    interest_total = -sum(t.amount_chf for t in interest)

    # Anything the bank billed explicitly (none on this account -- worth stating).
    explicit_fees = [t for t in statement.transactions if t.fee]
    explicit_total = sum(abs(t.fee) for t in explicit_fees)

    markup_total = sum(c["markup_chf"] for c in conversions)
    volume = sum(c["charged_chf"] for c in conversions)
    pcts = [c["markup_pct"] for c in conversions if c["foreign_amount"] > 5]

    # The same volume through an alternative, in the same convention as
    # `effective_pct` (markup over the pre-markup value).
    base = volume - markup_total
    references = [{
        **ref,
        "would_cost": round(base * ref["rate"] / 100, 2),
        "saved": round(markup_total - base * ref["rate"] / 100, 2),
    } for ref in REFERENCE_FX_MARKUP]

    return {
        "conversions": conversions,
        "by_currency": sorted(by_currency.values(), key=lambda b: -b["markup_chf"]),
        "count": len(conversions),
        "volume_chf": volume,
        "markup_chf": markup_total,
        "interest_chf": interest_total,
        "explicit_fees_chf": explicit_total,
        "explicit_fee_count": len(explicit_fees),
        "references": references,
        "references_as_of": REFERENCE_FX_AS_OF,
        "total_chf": markup_total + interest_total + explicit_total,
        "median_markup_pct": statistics.median(pcts) if pcts else 0.0,
        "effective_pct": (markup_total / (volume - markup_total) * 100) if volume else 0.0,
        "largest": max(conversions, key=lambda c: c["markup_chf"]) if conversions else None,
    }


# --- category & time aggregations -----------------------------------------

def by_category(transactions: list[Transaction]) -> list[dict]:
    """Totals per category, each with its subcategories and top merchants."""
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        groups[txn.category].append(txn)

    total = sum(abs(t.amount_chf) for t in transactions) or 1.0
    out = []
    for category, rows in groups.items():
        amount = sum(abs(t.amount_chf) for t in rows)

        subs: dict[str, list[Transaction]] = defaultdict(list)
        merchants: dict[str, list[float]] = defaultdict(list)
        for txn in rows:
            subs[txn.subcategory or "—"].append(txn)
            merchants[txn.label].append(abs(txn.amount_chf))

        out.append({
            "category": category,
            "amount": amount,
            "count": len(rows),
            "share": amount / total * 100,
            "average": amount / len(rows),
            "subcategories": sorted(
                ({"name": name,
                  "amount": sum(abs(t.amount_chf) for t in items),
                  "count": len(items)} for name, items in subs.items()),
                key=lambda s: -s["amount"],
            ),
            "top_merchants": sorted(
                ({"name": name, "amount": sum(values), "count": len(values)}
                 for name, values in merchants.items()),
                key=lambda m: -m["amount"],
            )[:8],
        })
    return sorted(out, key=lambda c: -c["amount"])


def monthly(statement: Statement) -> list[dict]:
    """Income, spending and net per calendar month, plus per-category splits."""
    spend = spending(statement)
    earn = income(statement)

    months: dict[str, dict] = {}

    def bucket(key: str) -> dict:
        return months.setdefault(key, {
            "month": key, "spending": 0.0, "income": 0.0,
            "categories": defaultdict(float), "count": 0,
        })

    for txn in spend:
        row = bucket(txn.date.strftime("%Y-%m"))
        row["spending"] += abs(txn.amount_chf)
        row["categories"][txn.category] += abs(txn.amount_chf)
        row["count"] += 1
    for txn in earn:
        bucket(txn.date.strftime("%Y-%m"))["income"] += txn.amount_chf

    out = []
    for key in sorted(months):
        row = months[key]
        row["categories"] = dict(row["categories"])
        row["net"] = row["income"] - row["spending"]
        out.append(row)
    return out


def top_merchants(transactions: list[Transaction], limit: int = 20) -> list[dict]:
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        groups[txn.label].append(txn)

    rows = []
    for name, items in groups.items():
        values = [abs(t.amount_chf) for t in items]
        amount = sum(values)

        # Merging a brand's branches can pull in the odd outlier -- a Coop
        # petrol station among the supermarkets. Report the category that
        # carries the money, not whichever row happened to come first.
        weights: dict[str, float] = defaultdict(float)
        for txn in items:
            weights[txn.category] += abs(txn.amount_chf)
        dominant = max(weights, key=weights.get)

        rows.append({
            "name": name,
            "amount": amount,
            "count": len(items),
            "average": amount / len(items),
            # Next to the mean because the two disagree wherever it matters: one
            # 900 CHF shop at a merchant otherwise visited for 20 CHF pulls the
            # average up to something nobody ever paid. The median says what a
            # visit there usually costs.
            "median": statistics.median(values),
            "category": dominant,
            "categories": len(weights),
            "category_share": weights[dominant] / amount * 100 if amount else 100.0,
            # Only worth mentioning when the split is real. A Coop petrol stop
            # among 434 grocery runs rounds to 100% -- saying "2 categories"
            # there states something false.
            "mixed": len(weights) > 1
                     and (weights[dominant] / amount * 100 if amount else 100.0) < 95.0,
            "first": min(t.date for t in items),
            "last": max(t.date for t in items),
        })
    return sorted(rows, key=lambda r: -r["amount"])[:limit]


def weekday_profile(transactions: list[Transaction]) -> list[dict]:
    names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    totals = [0.0] * 7
    counts = [0] * 7
    for txn in transactions:
        totals[txn.date.weekday()] += abs(txn.amount_chf)
        counts[txn.date.weekday()] += 1
    return [{"day": names[i], "amount": totals[i], "count": counts[i]} for i in range(7)]


# --- period slicing ---------------------------------------------------------

# Grains, coarse to fine. Drilling into a bucket moves one step down this list.
GRAINS = ["year", "month", "week", "day"]
GRAIN_LABELS = {"year": "Année", "month": "Mois", "week": "Semaine", "day": "Jour"}


def finer_grain(grain: str) -> str | None:
    """The next level down, or None at the bottom."""
    index = GRAINS.index(grain)
    return GRAINS[index + 1] if index + 1 < len(GRAINS) else None


def slice_period(statement: Statement, start: dt.date | None,
                 end: dt.date | None) -> Statement:
    """A view of the statement restricted to a date window.

    The transactions are the *same objects*, already annotated with `amount_chf`,
    `category` and `bucket`. That matters: `annotate_chf` scales foreign amounts
    against each currency's full set of conversions, so it has to run once over
    everything. Re-running it on a slice would rescale against a partial set and
    silently produce different numbers for the same transaction.
    """
    rows = statement.transactions
    if start:
        rows = [t for t in rows if t.date >= start]
    if end:
        rows = [t for t in rows if t.date <= end]

    accounts = []
    for currency in sorted({t.currency for t in rows}):
        series = [t for t in rows if t.currency == currency]
        with_balance = [t for t in series if t.balance is not None]
        opening = ((with_balance[0].balance - with_balance[0].amount)
                   if with_balance else 0.0)
        accounts.append(AccountSummary(
            currency=currency,
            opening_balance=round(opening, 2),
            closing_balance=with_balance[-1].balance if with_balance else 0.0,
            credit_total=round(sum(t.amount for t in series if t.amount > 0), 2),
            debit_total=round(-sum(t.amount for t in series if t.amount < 0), 2),
        ))

    return Statement(
        holder=statement.holder,
        iban=statement.iban,
        client_number=statement.client_number,
        period_start=start or (rows[0].date if rows else statement.period_start),
        period_end=end or (rows[-1].date if rows else statement.period_end),
        generated_on=statement.generated_on,
        reference_currency=statement.reference_currency,
        reference_currency_label=statement.reference_currency_label,
        accounts=accounts,
        transactions=rows,
    )


def bucket_bounds(day: dt.date, grain: str) -> tuple[dt.date, dt.date]:
    """The calendar bucket a date belongs to, as (first day, last day)."""
    if grain == "day":
        return day, day
    if grain == "week":
        monday = day - dt.timedelta(days=day.weekday())
        return monday, monday + dt.timedelta(days=6)
    if grain == "month":
        first = day.replace(day=1)
        following = (first + dt.timedelta(days=32)).replace(day=1)
        return first, following - dt.timedelta(days=1)
    return day.replace(month=1, day=1), day.replace(month=12, day=31)


def bucket_key(day: dt.date, grain: str) -> str:
    if grain == "day":
        return day.isoformat()
    if grain == "week":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}"
    if grain == "month":
        return day.strftime("%Y-%m")
    return str(day.year)


MONTH_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
               "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def bucket_label(start: dt.date, grain: str) -> str:
    if grain == "day":
        return f"{start.day} {MONTH_SHORT[start.month - 1]}"
    if grain == "week":
        _, week, _ = start.isocalendar()
        return f"s{week:02d} · {start.day} {MONTH_SHORT[start.month - 1]}"
    if grain == "month":
        return f"{MONTH_SHORT[start.month - 1]} {start.year % 100:02d}"
    return str(start.year)


def _step(day: dt.date, grain: str) -> dt.date:
    """The first day of the next bucket."""
    _, last = bucket_bounds(day, grain)
    return last + dt.timedelta(days=1)


def timeseries(statement: Statement, grain: str,
               start: dt.date | None = None,
               end: dt.date | None = None) -> list[dict]:
    """Spending and income per calendar bucket, with no gaps.

    Empty buckets are emitted too. A month with no spending is information --
    dropping it would silently compress the axis and misdraw the shape.
    """
    spend = spending(statement)
    earn = income(statement)
    if not spend and not earn:
        return []

    first = start or min(t.date for t in spend + earn)
    last = end or max(t.date for t in spend + earn)

    rows: dict[str, dict] = {}
    cursor, _ = bucket_bounds(first, grain)
    while cursor <= last:
        low, high = bucket_bounds(cursor, grain)
        rows[bucket_key(cursor, grain)] = {
            "key": bucket_key(cursor, grain),
            "label": bucket_label(low, grain),
            "start": max(low, first),
            "end": min(high, last),
            "spending": 0.0,
            "income": 0.0,
            "count": 0,
            "categories": defaultdict(float),
            # The same money split the other way. Both breakdowns are computed
            # here rather than one of them being derived later, because they
            # partition an identical set of rows: whichever one is drawn, the
            # column height is the same number.
            "buckets": defaultdict(float),
        }
        cursor = _step(cursor, grain)

    for txn in spend:
        row = rows.get(bucket_key(txn.date, grain))
        if row is None:
            continue
        row["spending"] += abs(txn.amount_chf)
        row["categories"][txn.category] += abs(txn.amount_chf)
        row["buckets"][txn.bucket or "Non classé"] += abs(txn.amount_chf)
        row["count"] += 1
    for txn in earn:
        row = rows.get(bucket_key(txn.date, grain))
        if row is not None:
            row["income"] += txn.amount_chf

    out = []
    for key in sorted(rows):
        row = rows[key]
        row["categories"] = dict(row["categories"])
        row["buckets"] = dict(row["buckets"])
        row["net"] = row["income"] - row["spending"]
        out.append(row)
    return out


def suggest_grain(start: dt.date, end: dt.date) -> str:
    """Pick a readable grain for a window: aim for roughly 10-60 buckets."""
    days = (end - start).days + 1
    if days <= 45:
        return "day"
    if days <= 200:
        return "week"
    if days <= 1200:
        return "month"
    return "year"


def previous_window(start: dt.date, end: dt.date) -> tuple[dt.date, dt.date]:
    """The equally long window immediately before this one, for comparison."""
    span = (end - start).days + 1
    return start - dt.timedelta(days=span), start - dt.timedelta(days=1)


# --- geography -------------------------------------------------------------

# Card terminals append the country to the address line; bank transfers carry an
# IBAN instead and so have no country at all. Any geography view therefore has
# to be scoped to card payments, or it silently misattributes rent and taxes.
COUNTRY_RE = re.compile(r",\s*([^,]+)$")


def country_of(txn: Transaction) -> str | None:
    match = COUNTRY_RE.search(txn.location or "")
    if not match:
        return None
    country = match.group(1).strip()
    return country or None


def by_country(transactions: list[Transaction]) -> dict:
    """Card spending per country, plus what share of it left Switzerland."""
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    located = 0.0
    unlocated = 0.0

    for txn in transactions:
        country = country_of(txn)
        if country is None:
            unlocated += abs(txn.amount_chf)
            continue
        totals[country] += abs(txn.amount_chf)
        counts[country] += 1
        located += abs(txn.amount_chf)

    rows = sorted(
        ({"country": name, "amount": amount, "count": counts[name],
          "share": amount / located * 100 if located else 0.0}
         for name, amount in totals.items()),
        key=lambda r: -r["amount"],
    )
    abroad = sum(r["amount"] for r in rows if r["country"] != "Suisse")
    return {
        "rows": rows,
        "located": located,
        "unlocated": unlocated,
        "abroad": abroad,
        "abroad_share": abroad / located * 100 if located else 0.0,
        "countries": len(rows),
    }


# --- fixed vs variable -----------------------------------------------------

# Commitments that are fixed by contract, whatever the merchant history says.
STRUCTURAL_SUBCATEGORIES = {
    ("Logement", "Loyer / régie"),
    ("Logement", "Énergie"),
    ("Logement", "Redevance TV"),
    ("Santé & assurance", "Assurance maladie"),
    ("Santé & assurance", "Autres assurances"),
    ("Télécom & abonnements", "Téléphonie & internet"),
}

RECURRING_MIN_MONTHS = 6
RECURRING_MAX_VARIATION = 0.6


def recurring_labels(transactions: list[Transaction]) -> dict[str, dict]:
    """Counterparties that behave like a subscription.

    Two signals together: billed across at least six distinct months, and with a
    stable amount (coefficient of variation under 0.6). The stability test is
    what keeps a supermarket visited every week out of the "fixed" bucket -- it
    recurs, but the amount is a choice, not a commitment.
    """
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        groups[txn.label].append(txn)

    found = {}
    for label, rows in groups.items():
        months = {t.date.strftime("%Y-%m") for t in rows}
        if len(months) < RECURRING_MIN_MONTHS:
            continue
        amounts = [abs(t.amount_chf) for t in rows]
        mean = statistics.mean(amounts)
        if not mean:
            continue
        variation = statistics.pstdev(amounts) / mean if len(amounts) > 1 else 0.0
        if variation > RECURRING_MAX_VARIATION:
            continue
        found[label] = {
            "label": label,
            "months": len(months),
            "count": len(rows),
            "total": sum(amounts),
            "average": mean,
            "variation": variation,
            "category": rows[0].category,
        }
    return found


def is_fixed(txn: Transaction, recurring: dict[str, dict]) -> bool:
    if (txn.category, txn.subcategory) in STRUCTURAL_SUBCATEGORIES:
        return True
    return txn.label in recurring


def fixed_vs_variable(statement: Statement) -> dict:
    """The monthly floor -- what a month costs before any discretionary choice."""
    spend = spending(statement)
    recurring = recurring_labels(spend)

    months: dict[str, dict] = {}
    for txn in spend:
        key = txn.date.strftime("%Y-%m")
        row = months.setdefault(key, {"month": key, "fixed": 0.0, "variable": 0.0})
        row["fixed" if is_fixed(txn, recurring) else "variable"] += abs(txn.amount_chf)

    series = [months[k] for k in sorted(months)]
    full = [m for m in series if m["fixed"] + m["variable"] > 0]
    complete = full[1:-1] if len(full) > 2 else full  # drop partial first/last months

    fixed_total = sum(m["fixed"] for m in series)
    variable_total = sum(m["variable"] for m in series)
    total = fixed_total + variable_total or 1.0

    detail = sorted(
        ({**info, "structural": False} for info in recurring.values()),
        key=lambda r: -r["total"],
    )
    for txn in spend:
        if (txn.category, txn.subcategory) in STRUCTURAL_SUBCATEGORIES \
                and txn.label not in recurring:
            match = next((d for d in detail if d["label"] == txn.label), None)
            if match is None:
                detail.append({
                    "label": txn.label, "months": 0, "count": 0, "total": 0.0,
                    "average": 0.0, "variation": 0.0,
                    "category": txn.category, "structural": True,
                })
                match = detail[-1]
            match["total"] += abs(txn.amount_chf)
            match["count"] += 1
    detail.sort(key=lambda r: -r["total"])

    return {
        "months": series,
        "fixed_total": fixed_total,
        "variable_total": variable_total,
        "fixed_share": fixed_total / total * 100,
        "monthly_floor": (statistics.median([m["fixed"] for m in complete])
                          if complete else 0.0),
        "monthly_variable": (statistics.median([m["variable"] for m in complete])
                             if complete else 0.0),
        "commitments": detail[:14],
        "commitment_count": len(detail),
    }


# --- who was paying, and when ----------------------------------------------

# Eight validated hues, minus one kept for the tail. The same rule the category
# palette follows, for the same reason: a ninth colour would not be legible.
INCOME_SLOTS = 7


def income_sources(statement: Statement) -> list[dict]:
    """Every payer, ranked by what they paid, with the span they cover.

    This is the fact the app never stated. The statement records a change of
    employer -- one payer stops, a gap opens, a benefits office pays once, a new
    employer starts -- and nothing on the dashboard showed it, because the
    yearly cumulative traces spending only and the timeline reduces income to a
    single marker line.
    """
    earn = income(statement)
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for txn in earn:
        groups[txn.label].append(txn)

    total = sum(t.amount_chf for t in earn) or 1.0
    rows = []
    for label, items in groups.items():
        amount = sum(t.amount_chf for t in items)
        days = sorted({t.date for t in items})
        rows.append({
            "label": label,
            "amount": amount,
            "share": amount / total * 100,
            "count": len(items),
            "first": days[0],
            "last": days[-1],
            "months": len({d.strftime("%Y-%m") for d in days}),
        })
    return sorted(rows, key=lambda r: -r["amount"])


def income_timeline(statement: Statement, grain: str,
                    start: dt.date | None = None,
                    end: dt.date | None = None) -> list[dict]:
    """Per bucket, how that period's income split between payers.

    Empty buckets are emitted with a total of 0 rather than dropped: a month
    with no income at all is the single most informative thing this series has
    to say, and skipping it would close the gap it exists to show.

    The tail folds into `Autres` past `INCOME_SLOTS` payers, ranked over the
    whole window rather than per bucket -- otherwise a payer would change colour
    from one column to the next.
    """
    earn = income(statement)
    if not earn:
        return []

    ranked = [r["label"] for r in income_sources(statement)][:INCOME_SLOTS]
    named = set(ranked)

    first = start or min(t.date for t in earn)
    last = end or max(t.date for t in earn)

    rows: dict[str, dict] = {}
    cursor, _ = bucket_bounds(first, grain)
    while cursor <= last:
        low, high = bucket_bounds(cursor, grain)
        rows[bucket_key(cursor, grain)] = {
            "key": bucket_key(cursor, grain),
            "label": bucket_label(low, grain),
            "start": max(low, first),
            "end": min(high, last),
            "total": 0.0,
            "sources": defaultdict(float),
        }
        cursor = _step(cursor, grain)

    for txn in earn:
        row = rows.get(bucket_key(txn.date, grain))
        if row is None:
            continue
        row["total"] += txn.amount_chf
        row["sources"][txn.label if txn.label in named else OTHER] \
            += txn.amount_chf

    out = []
    for key in sorted(rows):
        row = rows[key]
        row["sources"] = dict(row["sources"])
        out.append(row)
    return out


# --- commitments that stopped coming ---------------------------------------

# How far past its own rhythm a commitment has to be before it is worth saying
# anything. A monthly bill has to be 45 days silent, which is late enough that
# it is not just the bank being slow.
LATE_FACTOR = 1.5

# Past this, "late" is the wrong word: a subscription silent for three times its
# interval was almost certainly cancelled, and calling that a missing payment
# every month would train you to ignore the panel.
ENDED_FACTOR = 3.0

# The last days of a statement are always incomplete -- an export cuts wherever
# it cuts. So on top of the ratio, a commitment must be a clear week past due,
# which stops a weekly one from being flagged for a statement four days stale.
LATE_MIN_SLACK_DAYS = 7

# Two intervals cannot be told apart from a rhythm; three payments is the least
# that establishes one.
LATE_MIN_PAYMENTS = 3

# `recurring_labels` tests that the *amount* is stable, which is the right test
# for the monthly floor but not for this: a canteen visited nearly every working
# day passes it, and telling someone their lunch is overdue is how a panel earns
# its way into being ignored. Two more conditions, both about timing:
#
#   * billed no more often than roughly monthly. Under that it is a habit, not a
#     direct debit -- and a habit has no due date to miss;
#   * evenly spaced. Rent lands every 30 days give or take one; a restaurant
#     visited "regularly" swings by 40% or more. Measured as the median
#     deviation of the gaps against the median gap, so one late month does not
#     disqualify an otherwise metronomic commitment.
LATE_MIN_INTERVAL_DAYS = 20
LATE_MAX_JITTER = 0.25


def missing_commitments(statement: Statement,
                        asof: dt.date | None = None) -> list[dict]:
    """Recurring commitments whose next payment never turned up.

    `fixed_vs_variable` already knows which counterparties behave like a
    subscription; this asks the one question it never answered -- when each was
    last seen, against how often it usually comes round. Everything here is read
    off the same rows, so a commitment can only be reported late if the app was
    already calling it recurring.

    The rhythm is the *median* gap between payments, not the mean: one missed
    month would otherwise stretch the expected interval and hide the very thing
    being looked for.

    Ordered by what is at stake rather than by how late it is -- a rent that has
    not gone out matters more than a 9.90 subscription two months silent -- with
    the ones that look cancelled pushed to the end.
    """
    spend = spending(statement)
    recurring = recurring_labels(spend)
    reference = asof or statement.period_end

    by_label: dict[str, list[Transaction]] = defaultdict(list)
    for txn in spend:
        if txn.label in recurring:
            by_label[txn.label].append(txn)

    out = []
    for label, rows in by_label.items():
        days = sorted({t.date for t in rows})
        if len(days) < LATE_MIN_PAYMENTS:
            continue
        steps = [(b - a).days for a, b in zip(days, days[1:])]
        interval = statistics.median(steps)
        if interval < LATE_MIN_INTERVAL_DAYS:
            continue
        jitter = statistics.median([abs(s - interval) for s in steps]) / interval
        if jitter > LATE_MAX_JITTER:
            continue

        gap = (reference - days[-1]).days
        if gap < interval * LATE_FACTOR or gap - interval < LATE_MIN_SLACK_DAYS:
            continue

        info = recurring[label]
        out.append({
            "label": label,
            "category": info["category"],
            "average": info["average"],
            "count": info["count"],
            "interval": interval,
            "jitter": jitter,
            "last": days[-1],
            "expected": days[-1] + dt.timedelta(days=round(interval)),
            "gap": gap,
            "ratio": gap / interval,
            "ended": gap >= interval * ENDED_FACTOR,
        })

    return sorted(out, key=lambda r: (r["ended"], -r["average"]))


# --- calendar & seasonality -------------------------------------------------

def daily_totals(transactions: list[Transaction]) -> dict[dt.date, dict]:
    days: dict[dt.date, dict] = {}
    for txn in transactions:
        row = days.setdefault(txn.date, {"amount": 0.0, "count": 0})
        row["amount"] += abs(txn.amount_chf)
        row["count"] += 1
    return days


def median_daily(transactions: list[Transaction],
                 start: dt.date, end: dt.date) -> float:
    """The typical day's spending.

    Counted over *every* day of the window, including the ones with no
    movement -- the same denominator the mean uses. Dropping the empty days
    would make the two numbers answer different questions while sitting side
    by side, which is the sort of comparison that quietly misleads.

    Worth showing next to the mean because they diverge sharply here: a rent
    payment and a tax bill pull the average well above what an ordinary day
    actually costs.
    """
    span = (end - start).days + 1
    if span <= 0:
        return 0.0
    days = daily_totals(transactions)
    values = [days.get(start + dt.timedelta(days=i), {}).get("amount", 0.0)
              for i in range(span)]
    return statistics.median(values)


def most_frequent_amount(transactions: list[Transaction]) -> dict | None:
    """The payment you make more often than any other.

    Deliberately computed on individual payments, not on daily totals. The mode
    of a day's total is 0.00 -- the days you spent nothing -- and with 586
    distinct totals over 731 days that distribution is near-continuous anyway,
    so its mode is an artefact rather than a fact about spending. One payment
    repeated 107 times is a fact.
    """
    counts: dict[float, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        counts[round(abs(txn.amount_chf), 2)].append(txn)
    if not counts:
        return None

    amount, rows = max(counts.items(), key=lambda kv: (len(kv[1]), kv[0]))
    if len(rows) < 3:
        return None  # nothing repeats often enough to be worth calling a habit

    who: dict[str, int] = defaultdict(int)
    for txn in rows:
        who[txn.label] += 1
    label, hits = max(who.items(), key=lambda kv: kv[1])
    return {"amount": amount, "count": len(rows),
            "label": label, "label_count": hits,
            "share": hits / len(rows) * 100}


def year_cumulative(transactions: list[Transaction]) -> list[dict]:
    """Cumulative spend by day-of-year, one series per calendar year."""
    per_year: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for txn in transactions:
        per_year[txn.date.year][txn.date.timetuple().tm_yday] += abs(txn.amount_chf)

    series = []
    for year in sorted(per_year):
        running = 0.0
        points = []
        for day in sorted(per_year[year]):
            running += per_year[year][day]
            points.append((day, running))
        series.append({
            "year": year,
            "points": points,
            "total": running,
            "first_day": points[0][0] if points else 0,
            "last_day": points[-1][0] if points else 0,
        })
    return series


def seasonality(transactions: list[Transaction]) -> list[dict]:
    """Average spend per calendar month, across however many years are held."""
    per_month: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for txn in transactions:
        per_month[txn.date.month][txn.date.year] += abs(txn.amount_chf)

    rows = []
    for month in range(1, 13):
        years = per_month.get(month, {})
        values = list(years.values())
        rows.append({
            "month": month,
            "average": statistics.mean(values) if values else 0.0,
            "years": len(values),
            "values": {y: v for y, v in sorted(years.items())},
        })
    return rows


def highlights(statement: Statement, custodian: dict) -> list[dict]:
    """Notable facts, each with a headline figure and an explanation."""
    spend = spending(statement)
    earn = income(statement)
    months = monthly(statement)
    cats = by_category(spend)

    total_spend = sum(abs(t.amount_chf) for t in spend)
    total_income = sum(t.amount_chf for t in earn)
    days = max((statement.period_end - statement.period_start).days, 1)
    full_months = [m for m in months if m["count"] > 5]

    items: list[dict] = []

    biggest = max(spend, key=lambda t: abs(t.amount_chf))
    items.append({
        "icon": "\U0001F4B8", "label": "Plus grosse dépense",
        "value": f"{chf(abs(biggest.amount_chf))} CHF",
        "detail": f"{biggest.label} — {biggest.date:%d.%m.%Y} ({biggest.category})",
    })

    merchants = top_merchants(spend, limit=1)
    if merchants:
        top = merchants[0]
        items.append({
            "icon": "\U0001F3C6", "label": "Premier bénéficiaire",
            "value": f"{chf(top['amount'])} CHF",
            "detail": f"{top['name']} — {top['count']} paiements, "
                      f"{chf(top['average'])} CHF en moyenne",
        })

    items.append({
        "icon": "\U0001F4C5", "label": "Dépense moyenne par jour",
        "value": f"{chf(total_spend / days)} CHF",
        "detail": f"sur {days} jours et {len(spend)} transactions",
    })

    if full_months:
        peak = max(full_months, key=lambda m: m["spending"])
        quiet = min(full_months, key=lambda m: m["spending"])
        items.append({
            "icon": "\U0001F4C8", "label": "Mois le plus cher",
            "value": f"{chf(peak['spending'])} CHF",
            "detail": f"{peak['month']} — contre {chf(quiet['spending'], 0)} CHF "
                      f"le mois le plus sobre ({quiet['month']})",
        })

    savings = (total_income - total_spend) / total_income * 100 if total_income else 0
    items.append({
        "icon": "\U0001F4B0", "label": "Taux d'épargne",
        "value": f"{savings:.1f} %",
        "detail": f"{chf(total_income, 0)} CHF encaissés, "
                  f"{chf(total_spend, 0)} CHF dépensés",
    })

    if cats:
        first = cats[0]
        items.append({
            "icon": "\U0001F3AF", "label": "Premier poste de dépense",
            "value": f"{first['share']:.1f} %",
            "detail": f"{first['category']} — {chf(first['amount'], 0)} CHF "
                      f"sur {first['count']} transactions",
        })

    if custodian["count"]:
        items.append({
            "icon": "\U0001F3E6", "label": "Marge de change Swissquote",
            "value": f"{chf(custodian['markup_chf'])} CHF",
            "detail": f"{custodian['effective_pct']:.2f} % sur "
                      f"{chf(custodian['volume_chf'], 0)} CHF convertis "
                      f"en {custodian['count']} opérations",
        })

    card = [t for t in spend if "carte" in t.kind]
    twint = [t for t in spend if t.kind == "Paiement Twint"]
    if card and twint:
        items.append({
            "icon": "\U0001F4B3", "label": "Carte contre Twint",
            "value": f"{len(card)} / {len(twint)}",
            "detail": f"{chf(sum(abs(t.amount_chf) for t in card), 0)} CHF par carte, "
                      f"{chf(sum(abs(t.amount_chf) for t in twint), 0)} CHF par Twint",
        })

    weekdays = weekday_profile(spend)
    busiest = max(weekdays, key=lambda d: d["amount"])
    items.append({
        "icon": "\U0001F5D3️", "label": "Jour le plus dépensier",
        "value": busiest["day"],
        "detail": f"{chf(busiest['amount'], 0)} CHF cumulés sur "
                  f"{busiest['count']} transactions",
    })

    frequent = most_frequent_amount(spend)
    if frequent:
        detail = f"{frequent['count']} fois"
        if frequent["share"] >= 40:
            detail += (f", dont {frequent['label_count']} chez "
                       f"{frequent['label']}")
        items.append({
            "icon": "🔁", "label": "Paiement le plus fréquent",
            "value": f"{chf(frequent['amount'])} CHF",
            "detail": detail,
        })

    small = [t for t in spend if abs(t.amount_chf) < 10]
    small_total = sum(abs(t.amount_chf) for t in small)
    items.append({
        "icon": "\U0001FA99", "label": "Micro-dépenses (< 10 CHF)",
        "value": f"{len(small)} transactions",
        "detail": f"{chf(small_total, 0)} CHF au total, soit "
                  f"{small_total / total_spend * 100:.1f} % des dépenses",
    })

    return items
