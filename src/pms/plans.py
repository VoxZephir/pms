"""Cash-flow planning: enough cash at time t for what's coming.

The ledger only knows the past. The future comes from two places, kept
apart the way the ledger and the overrides are:

* `data/plans.json` -- gitignored, declared facts: the monthly income, the
  known one-off expenses, and the seasonal patterns decided to be noise.
  A declared December insurance bill is a decision, not data, so it must
  not live in the ledger.
* the ledger itself, which *suggests* seasonal one-offs: a category whose
  spend clusters in the same calendar month, two years running, well above
  its own ordinary month. December health insurance and May taxes look
  exactly like that; rent and December groceries do not.

The projection is deliberately a small arithmetic: month by month, the
starting cash plus the income minus the usual month minus that month's
one-offs. It is an estimate, not a bank statement -- the page says so.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from collections import defaultdict
from pathlib import Path

from . import analysis
from .buckets import CATEGORY_BUCKET, SAVE
from .models import Statement

VERSION = 1


def _saved(category: str) -> bool:
    """A transfer to the 3a or the brokerage, which the ledger books as
    spending. It is not consumption: left in the baseline, a monthly transfer
    to IBKR would be charged twice -- once in the median, once as the
    declared series that already subtracts it."""
    return CATEGORY_BUCKET.get(category) == SAVE


def _consumed(row: dict) -> float:
    """A monthly row's spending without its transfers to the pockets."""
    return row["spending"] - sum(amount for category, amount in row["categories"].items()
                                 if _saved(category))

# Below this amount it is a shop bill, not a one-off worth planning around.
SEASONAL_MIN_AMOUNT = 1500.0
# A suggestion must clear the category's own ordinary month by this factor,
# otherwise rent -- paid every month -- would be flagged for December.
SEASONAL_FACTOR = 2.0

MONTHS_AHEAD = 12

MONTH_NAMES = ["janvier", "février", "mars", "avril", "mai", "juin",
               "juillet", "août", "septembre", "octobre", "novembre",
               "décembre"]

# Where a planned transfer lands. Swiss wealth tax reaches a brokerage account
# but not a pillar 3a before it is drawn, so the destination is what makes the
# taxable / sheltered split of the net-worth curve meaningful. It is declared,
# never guessed from the label -- same rule as the transfer flag it replaces.
SPENT = ""
SHELTERED = "3a"
TAXABLE = "taxable"
DESTINATIONS = (SPENT, SHELTERED, TAXABLE)

# The invested pockets a barème of its own can be given (`Plan.pocket_rates`),
# as the forecast names them. Unlisted shares are held at their declared
# value until told otherwise: a market return on a share nobody trades would
# be a number nobody chose.
POCKET_KEYS = ("ibkr", "finp", "crypto", "titres")
POCKET_LABELS = {"ibkr": "IBKR", "finp": "3a", "crypto": "Crypto", "titres": "Titres non cotés"}
FIXED_BY_DEFAULT = frozenset({"titres"})
DESTINATION_LABELS = {
    SPENT: "dépense",
    SHELTERED: "virement 3a (hors impôt sur la fortune)",
    TAXABLE: "virement placement (imposable)",
}

# The cadence of a planned series of transfers, in months, and its label.
CONTRIBUTION_EVERY = {"month": 1, "quarter": 3, "semester": 6, "year": 12}
CONTRIBUTION_LABELS = {"month": "chaque mois", "quarter": "chaque trimestre",
                       "semester": "chaque semestre", "year": "chaque année"}


def in_months_of(value) -> list[int]:
    """The calendar months a series is limited to, 1-12, sorted. Empty -- and
    all twelve, which say the same -- means the whole year. Anything else
    in the list is dropped, not guessed."""
    if isinstance(value, str):
        value = [v for v in value.replace(";", ",").split(",") if v.strip()]
    months = set()
    for v in value or []:
        try:
            m = int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= m <= 12:
            months.add(m)
    return [] if len(months) == 12 else sorted(months)


def months_phrase(months: list[int]) -> str:
    """"de mai à décembre", "en mai", "en mars, juin et septembre": the
    months of a limited series as one says them. A run that crosses the new
    year reads as one ("de novembre à février")."""
    if not months:
        return "toute l'année"
    chosen = set(months)
    # Start the reading just after a month left out, so a run across
    # December-January is not cut in two.
    first = next(m for m in range(1, 13) if m in chosen and ((m - 2) % 12) + 1 not in chosen) \
        if len(chosen) < 12 else 1
    runs: list[list[int]] = []
    for i in range(12):
        m = (first - 1 + i) % 12 + 1
        if m not in chosen:
            continue
        if runs and (runs[-1][-1] % 12) + 1 == m:
            runs[-1].append(m)
        else:
            runs.append([m])
    if len(runs) == 1 and len(runs[0]) >= 3:
        first_name = MONTH_NAMES[runs[0][0] - 1]
        # "d'avril", "d'août", "d'octobre": elided before a vowel.
        of = "d'" if first_name[0] in "aeiou" else "de "
        return f"{of}{first_name} à {MONTH_NAMES[runs[0][-1] - 1]}"
    names = [MONTH_NAMES[m - 1] for run in runs for m in run]
    if len(names) == 1:
        return f"en {names[0]}"
    return "en " + ", ".join(names[:-1]) + " et " + names[-1]

#: Named parameter sets the user can recall. The built-ins are examples of
#: shape, not advice: the app proposes, and applying one is the user declaring
#: the values -- the same standing as a confirmed seasonal suggestion. Keys are
#: stable English identifiers, labels the French UI copy. Vol stays None
#: (measured) everywhere: dispersion is an observation on the user's own
#: pockets, not a hypothesis to template. A scenario may also carry `months`,
#: the horizon its shape is about -- applying it sets the view length too.
# Shapes, not forecasts: each says what kind of market it stands for in its
# `note`, and only the lost decade is a measured path. Round numbers on
# purpose -- a decimal would read as a precision nobody has.
BUILTIN_SCENARIOS: dict[str, dict] = {
    "prudent": {"label": "Prudent",
                "note": "un portefeuille surtout obligataire, ou un compte rémunéré",
                "rate_segments": [(12, 0.02)], "vol": None},
    "constant-growth": {"label": "Croissance constante",
                        "note": "un portefeuille équilibré, sans accident",
                        "rate_segments": [(12, 0.04)], "vol": None},
    "dynamic": {"label": "Dynamique",
                "note": "surtout des actions, sur une longue période sans crise",
                "rate_segments": [(12, 0.06)], "vol": None},
    # 2022: world equities lost about a sixth in francs (MSCI World, net,
    # roughly −17 % in CHF over the calendar year), bonds fell with them.
    "bad-year": {"label": "Une mauvaise année",
                 "note": "l'ordre de grandeur de 2022 en francs, puis la croissance constante",
                 "rate_segments": [(12, -0.17), (48, 0.04)], "vol": None, "months": 60},
    "crash-slow": {"label": "Krach puis reprise lente",
                   "note": "une chute d'un tiers en un an, cinq ans pour s'en remettre",
                   "rate_segments": [(12, -0.33), (60, 0.085), (120, 0.04)],
                   "vol": None, "months": 120},
    "stagnation": {"label": "Stagnation longue",
                   "note": "dix ans sans rendement, puis un retour à la moyenne",
                   "rate_segments": [(120, 0.0), (120, 0.04)], "vol": None, "months": 240},
    "stagflation": {"label": "Stagflation",
                    "note": "trois ans de baisse lente pendant que les prix montent",
                    "rate_segments": [(36, -0.05), (84, 0.05)], "vol": None, "months": 120},
    # The lost decade in CHF, measured on the real path (S&P 500 total return
    # x USDCHF, pic 2000-09-07 -> creux 2009-03-09 -> recouvrement 2014-12-19):
    # -11.8 %/an pendant 102 mois est le CAGR qui mène au creux de -65.6 %, et
    # +20.3 %/an pendant 69 mois celui qui en revient. Un scénario qui perd
    # 2 % deux ans puis gagne 3 % huit ans serait une décennie qui gagne.
    # Une fois l'épisode fini, le rendement retombe à la moyenne historique
    # longue en CHF (3.9 %/an, mesurée 1999-2018, épisode compris) -- c'est ce
    # qui s'applique ensuite, au lieu du taux de recouvrement porté à vie.
    "lost-decade": {"label": "Décennie perdue — S&P 500 en CHF",
                    "note": "le chemin mesuré de 2000 à 2014 : −66 % au creux, puis la moyenne longue",
                    "rate_segments": [(102, -0.1180), (69, 0.2027),
                                      (300, 0.0389)],
                    "vol": None, "months": 180},
    "rebound": {"label": "Rebond après crise",
                "note": "une année à −10 %, puis neuf ans de bonne croissance",
                "rate_segments": [(12, -0.10), (108, 0.06)], "vol": None},
    # One barème per pocket, constant, nominal in francs and net of fees --
    # what each pocket can plausibly be expected to do over a long horizon,
    # not a forecast of any year:
    # - IBKR, equities with managed futures stacked on top: 8 %. The
    #   simulated long history in francs, after drag and fees, is well above
    #   this, but it covers a period that lifted both legs (rising valuations,
    #   decades of falling rates), so a forward figure sits below it.
    # - the 3a, an equity strategy: ~5 % less its fees; volatility ~14 %.
    # - crypto: no cash flow to anchor a return; a modest 5 %, a volatility of
    #   70 % (the order of the major coins' history) -- the band says the rest.
    # - unlisted shares: mostly the dividend (the 35 % withheld comes back
    #   through the tax return), which the plan's income, a monthly median,
    #   never sees as a yearly payment, plus a little revaluation of the
    #   declared tax value. 12 % in all, no volatility: nobody quotes it.
    # The common barème (4 %, 12 %) is for whatever has none of its own.
    "baseline-claude": {"label": "Baseline Claude",
                        "note": "une hypothèse par poche, plausible sur le long terme : nominale en francs, nette de frais",
                        "rate_segments": [(12, 0.04)], "vol": 0.12,
                        "pockets": {"ibkr": ([(12, 0.08)], 0.23), "finp": ([(12, 0.045)], 0.14),
                                    "crypto": ([(12, 0.05)], 0.70), "titres": ([(12, 0.12)], 0.0)}},
}


def month_key(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def calendar_month(key: str) -> int:
    return int(key.split("-")[1])


def _add_months(d: dt.date, n: int) -> dt.date:
    index = d.year * 12 + (d.month - 1) + n
    return dt.date(index // 12, index % 12 + 1, 1)


def _last_of_month(d: dt.date) -> dt.date:
    return _add_months(d, 1) - dt.timedelta(days=1)


def parse_day(value: str | None) -> dt.date | None:
    """An ISO day, or None. A one-off may carry a precise date or only its
    month -- both are declarations, the date is simply the sharper one."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _destination(value) -> str:
    """Normalise the transfer field to one of DESTINATIONS.

    It used to be a boolean, so `true` still has to mean something: it means
    "moved to a pocket, which one unsaid". Read as taxable, because that is
    the answer that keeps the total honest -- a 3a is the deliberate, declared
    case, and claiming a plain `true` is sheltered would understate the wealth
    the tax reaches.
    """
    if value is True:
        return TAXABLE
    if value in DESTINATIONS:
        return value
    return SPENT


def _amount(value) -> float | None:
    """A declared monthly figure, `{"amount": x}`, or None when absent. Zero
    reads as absent, as it always has for the income: a month of nothing
    is not a declaration anyone makes."""
    if isinstance(value, dict) and value.get("amount"):
        try:
            amount = float(value["amount"])
        except (TypeError, ValueError):
            return None
        return amount if amount > 0 else None
    return None


def _segments(pairs) -> list[tuple[int, float]]:
    """(months, rate) pairs, the malformed ones dropped."""
    out: list[tuple[int, float]] = []
    for pair in pairs or []:
        try:
            months, rate = pair
            months = int(months)
            rate = float(rate)
        except (TypeError, ValueError):
            continue
        if months >= 1 and -100 <= rate <= 100:
            out.append((months, rate))
    return out


def _vol(value) -> float | None:
    """A volatility outside [0, 100] % would silently invert or explode the
    band. A hand edit that wrote one is demoted to the measured fallback,
    never echoed into the chart."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 1.0 else None


def _detached(declarations: dict) -> "Plan":
    """A plan holding these declarations, tied to no file -- a saved
    scenario, to project or compare without touching the live one."""
    plan = Plan(Path("unused"))
    plan._restore(declarations)
    return plan


def rate_at(segments: list[tuple[int, float]], row: int) -> float | None:
    """Annual rate for the `row`-th projected month (1-based).

    The schedule is a chain of (months, rate) segments covering the first
    months of the projection in order. Once the declared periods run out the
    last declared rate carries forward -- the alternative would be to invent
    a continuation, and a one-segment schedule is exactly the legacy `rate`,
    which is what makes the migration invisible.
    """
    covered = 0
    for months, rate in segments:
        covered += months
        if row <= covered:
            return rate
    return segments[-1][1] if segments else None


def projection_keys(as_of: dt.date, months_ahead: int) -> list[str]:
    """The months `project()` lays out, in row order: the rest of the
    statement's month when it does not end on the last day, then
    `months_ahead` whole months."""
    first = _add_months(as_of, 1)
    keys = [month_key(_add_months(first, i)) for i in range(months_ahead)]
    if as_of != _last_of_month(as_of):
        keys.insert(0, month_key(as_of))
    return keys


def rate_years(segments: list[tuple[int, float]], keys: list[str]) -> list[dict]:
    """The barème read per calendar year over the projected months: each
    year, how many of its months the horizon holds, and its rate -- None
    when the year straddles two periods (`mixed`) or nothing is declared.
    What the year-by-year editor shows; past the declared periods the last
    rate carries on, so a year there reads that rate."""
    years: list[dict] = []
    for row, key in enumerate(keys, start=1):
        year = int(key[:4])
        rate = rate_at(segments, row)
        if not years or years[-1]["year"] != year:
            years.append({"year": year, "months": 0, "rate": rate, "mixed": False})
        entry = years[-1]
        entry["months"] += 1
        if entry["rate"] != rate:
            entry["mixed"] = True
    for entry in years:
        if entry["mixed"]:
            entry["rate"] = None
    return years


def parse_percent(text: str) -> float | None:
    """A rate as people type it: "5.25", "5,25", "-3", "5,25 %". None when it
    is not a number."""
    cleaned = (text or "").strip().replace("%", "").replace("\u2212", "-").replace(",", ".").replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def segments_from_years(years: list[dict], rates: list[str]
                        ) -> tuple[list[tuple[int, float]], dict[int, str]]:
    """One rate per year (`rate_years`' years, in order) into a barème:
    each year's months at its rate, neighbouring years at the same rate
    merged into one period. Errors are keyed by the year's index."""
    errors: dict[int, str] = {}
    segments: list[tuple[int, float]] = []
    if len(rates) != len(years):
        return [], {-1: "Les années ne correspondent plus à l'horizon affiché : rechargez la page."}
    for i, (entry, text) in enumerate(zip(years, rates)):
        percent = parse_percent(text)
        if percent is None:
            errors[i] = "Un taux en %, par exemple 4,5."
            continue
        if not -100 < percent <= 100:
            errors[i] = "Le taux est entre -100 % et 100 %."
            continue
        rate = round(percent / 100, 6)
        if segments and segments[-1][1] == rate:
            segments[-1] = (segments[-1][0] + entry["months"], rate)
        else:
            segments.append((entry["months"], rate))
    return (segments if not errors else []), errors


def _series(pocket: str, amount: float, every: str, months: int, start: str,
            in_months=None) -> dict:
    """A contribution series as stored. `in_months` is written only when it
    limits the year, so a whole-year series keeps its old shape."""
    entry = {"pocket": pocket, "amount": amount, "every": every,
             "months": months, "start": start}
    limited = in_months_of(in_months)
    if limited:
        entry["in_months"] = limited
    return entry


def _month_no(key: str) -> int:
    year, month = key.split("-")
    return int(year) * 12 + int(month) - 1


def _contribution_occurrences(plan: "Plan", keys: list[str],
                              first_full: int) -> dict[str, list[dict]]:
    """Which projected rows each contribution series fires on.

    Absolute month numbers keep the cadence window-independent: a quarterly
    series started in January fires in April whatever month the projection
    happens to begin on. An empty start means the first full row -- the
    partial row is the only one the ledger also covers, and charging a
    transfer there would double-count one the ledger already recorded.
    """
    out: dict[str, list[dict]] = {}
    for c in plan.contributions:
        start = c["start"] or keys[first_full]
        step = CONTRIBUTION_EVERY[c["every"]]
        start_no = _month_no(start)
        for key in keys:
            delta = _month_no(key) - start_no
            # A series limited to some months of the year skips the others,
            # on top of its cadence ("chaque mois, de mai à décembre").
            if c.get("in_months") and int(key[5:7]) not in c["in_months"]:
                continue
            if 0 <= delta < c["months"] and delta % step == 0:
                out.setdefault(key, []).append({
                    "label": ("Versement programmé (3a)"
                              if c["pocket"] == SHELTERED
                              else "Versement programmé (placement)"),
                    "amount": round(c["amount"], 2),
                    "source": "contribution",
                    "transfer": c["pocket"],
                    "date": "",
                    "every": c["every"],
                    "months": c["months"],
                })
    return out


def parse_rate_segments(months: list[str], rates: list[str]
                        ) -> tuple[list[tuple[int, float]], dict[int, str]]:
    """The rate form's two parallel lists into (months, rate) pairs.

    Pairs are matched by position. A row with both fields blank is dropped --
    that is the trailing "add" row. One blank of two is an error keyed by the
    row's index, so the summary can point at the row missing its half.
    """
    segments: list[tuple[int, float]] = []
    errors: dict[int, str] = {}
    for i, (months_text, rate_text) in enumerate(zip(months, rates)):
        months_text = (months_text or "").strip()
        rate_text = (rate_text or "").strip()
        if not months_text and not rate_text:
            continue
        if not months_text or not rate_text:
            errors[i] = "Complétez la durée et le taux."
            continue
        try:
            n = int(months_text)
        except ValueError:
            errors[i] = "La durée est un nombre de mois entier."
            continue
        if n < 1:
            errors[i] = "La durée est d'au moins 1 mois."
            continue
        try:
            percent = float(rate_text)
        except ValueError:
            errors[i] = "Utilisez le point décimal, pas la virgule."
            continue
        if not -100 <= percent <= 100:
            errors[i] = "Le taux est entre -100 % et 100 %."
            continue
        segments.append((n, percent / 100))
    return segments, errors


def month_label(key: str) -> str:
    year, month = key.split("-")
    return f"{MONTH_NAMES[int(month) - 1]} {year}"


def scenario_summary(segments, vol, months=None) -> str:
    """One line telling two saved scenarios apart, e.g. "−2 % pendant 24 mois
    puis 3 % · vol mesuré" -- and the horizon it carries, when it carries
    one, so a 15-year scenario does not read like a 12-month one."""
    if segments:
        steps = [f"{rate * 100:g} % pendant {months} mois"
                 for months, rate in segments]
        rates = " puis ".join(steps)
    else:
        rates = "aucun rendement"
    vol_part = "vol mesuré" if vol is None else f"vol {vol * 100:g} %"
    out = f"{rates} · {vol_part}"
    if months:
        years = months / 12
        out += (f" · {years:g} an{'s' if years > 1 else ''} d'horizon"
                if years >= 1 else f" · {months} mois d'horizon")
    return out


def growth_path(segments: list[tuple[int, float]], months: int,
                points: int = 60) -> dict:
    """What a barème does to one franc placed today, month by month, with
    the same compounding as the projection (`_monthly_rate`): the curve a
    scenario card draws, its low point, where it ends, and the steady annual
    rate that would end at the same place. `points` thins the curve for a
    sparkline; the low point and the end are read on every month."""
    monthly_at = _monthly_rate(None, segments or None)
    value, path = 1.0, [1.0]
    for row in range(1, months + 1):
        value *= 1.0 + monthly_at(row)
        path.append(value)
    step = max(1, months // points)
    shown = path[::step]
    if shown[-1] is not path[-1]:
        shown.append(path[-1])
    low = min(range(len(path)), key=path.__getitem__)
    end = path[-1]
    return {
        "months": months,
        "points": [round(v, 4) for v in shown],
        "end": round(end, 4),
        "low": round(path[low], 4),
        "low_month": low,
        "annual": round(end ** (12 / months) - 1, 4) if months and end > 0 else None,
    }


def closing_chf(statement: Statement) -> float:
    """What the accounts actually hold: the CHF closing balances, summed."""
    return analysis.closing_chf(statement)


# --- what the history suggests ----------------------------------------------

def seasonal_one_offs(statement: Statement) -> list[dict]:
    """Annual one-off expenses read from the ledger's own history.

    For every spending category, the observed spend is aggregated per
    (year, calendar month). A suggestion needs the same (category, month)
    to have carried a large amount in at least two different years, with a
    median above `SEASONAL_MIN_AMOUNT` and at least `SEASONAL_FACTOR` times
    the category's own ordinary month. The factor is what keeps rent and
    December groceries out of the list.
    """
    per_year: dict[tuple[str, int, int], float] = defaultdict(float)
    for txn in analysis.spending(statement):
        if _saved(txn.category):
            continue  # a yearly 3a transfer is a declaration, not a bill
        per_year[(txn.category, txn.date.year, txn.date.month)] += abs(txn.amount_chf)

    by_month: dict[tuple[str, int], list[tuple[int, float]]] = defaultdict(list)
    for (category, year, month), amount in per_year.items():
        by_month[(category, month)].append((year, amount))

    out = []
    for (category, month), pairs in by_month.items():
        years = sorted({year for year, _ in pairs})
        if len(years) < 2:
            continue
        amount = statistics.median(amount for _, amount in pairs)
        if amount < SEASONAL_MIN_AMOUNT:
            continue
        # The category's own ordinary month, *excluding* the candidate month:
        # an insurance category that only ever bills in December must not be
        # compared against its December self (no ordinary month exists, so the
        # factor test is moot and the suggestion stands).
        ordinary_values = [
            value for (other, values) in by_month.items()
            if other[0] == category and other[1] != month
            for _, value in values]
        ordinary = (statistics.median(ordinary_values)
                    if ordinary_values else 0.0)
        if ordinary and amount < SEASONAL_FACTOR * ordinary:
            continue
        out.append({
            "category": category,
            "month": month,
            "amount": round(amount, 2),
            "years": years,
        })
    return sorted(out, key=lambda s: (s["month"], -s["amount"]))


# --- the declared plan --------------------------------------------------------

class Plan:
    """What the future is expected to cost, declared in `data/plans.json`.

    Missing or corrupt is not fatal: the app falls back to the history's
    own suggestions and runs with an empty plan, like an empty overrides
    file.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.income: float | None = None
        self.one_offs: list[dict] = []
        self.ignored: list[tuple[str, int]] = []
        # Annual return assumed on the invested pockets, as a fraction. `None`
        # means undeclared, which is *not* the same as 0.0: undeclared holds
        # the pockets at their last known value and says so, while a declared
        # 0.0 is the account holder stating they expect no growth. The app
        # never picks a rate on its own -- an invented rate would be the one
        # number on the page that came from nowhere.
        self.rate: float | None = None
        # The rate can also be a chain of (months, rate) segments: x % for the
        # first y months, then z % for the next u, and so on. Empty means the
        # single `rate` above (or nothing at all); once the declared periods
        # run out, the last declared rate carries forward.
        self.rate_segments: list[tuple[int, float]] = []
        # Annualised volatility of the pockets, as a fraction. `None` means
        # undeclared, which is *not* the same as 0.0: undeclared falls back to
        # the volatility measured on the pockets' own history; a declared 0.0
        # states the account holder expects a flat band.
        self.vol: float | None = None
        # Named (rate_segments, vol) presets the user can recall. A preset is
        # not a mode: applying one copies its values into the live fields, so
        # it is a declaration like any other, editable afterwards.
        self.scenarios: dict[str, dict] = {}
        # Recurring transfers to the pockets: x CHF every month/quarter/
        # semester/year for `months` months. Declared facts, like one_offs.
        self.contributions: list[dict] = []
        # A barème and a volatility of their own for some pockets: pocket ->
        # {"rate_segments", "vol"}, or {"common": True} for a pocket fixed by
        # default that was told to follow the common barème. A pocket not
        # here follows the common one (`own_rates`).
        self.pocket_rates: dict[str, dict] = {}
        # The usual month's spend, declared. `None` is the history's own
        # baseline -- a median over the whole ledger, which lags a new rent.
        self.spend: float | None = None
        # Whole plans kept under a name: every declaration above but the
        # market presets (`scenarios`), which are shared by all of them. The
        # live fields are the active one's working copy -- an edit lands in
        # it on save, and switching stores it before loading the other.
        self.plan_scenarios: dict[str, dict] = {}
        self.active: str | None = None
        # The last plan deleted, whole, so the toast that confirms the
        # deletion can undo it. One deep: an undo, not a recycle bin.
        self.deleted: dict | None = None

    @classmethod
    def load(cls, path: Path | str) -> "Plan":
        plan = cls(path)
        if not plan.path.exists():
            return plan
        try:
            raw = json.loads(plan.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return plan
        if not isinstance(raw, dict):
            return plan

        plan._restore(raw)

        for name, spec in (raw.get("scenarios") or {}).items():
            if not isinstance(spec, dict) or not str(name).strip():
                continue
            segments = _segments(spec.get("rate_segments", []))
            scenario_vol = _vol(spec.get("vol"))
            try:
                months = int(spec.get("months") or 0)
            except (TypeError, ValueError):
                months = 0
            plan.scenarios[str(name)] = {"rate_segments": segments,
                                         "vol": scenario_vol,
                                         "months": months if months >= 1 else 0}

        for name, spec in (raw.get("plan_scenarios") or {}).items():
            if isinstance(spec, dict) and str(name).strip():
                # Kept as written, normalised through a detached load: the
                # same validation as the live fields, and what is saved is
                # what a switch would restore.
                plan.plan_scenarios[str(name)] = _detached(spec)._declarations()
        active = raw.get("active_scenario")
        plan.active = active if active in plan.plan_scenarios else None
        deleted = raw.get("deleted_scenario")
        if isinstance(deleted, dict) and str(deleted.get("name") or "").strip() \
                and isinstance(deleted.get("plan"), dict):
            plan.deleted = {"name": str(deleted["name"]).strip(),
                            "plan": _detached(deleted["plan"])._declarations()}
        return plan

    def _restore(self, raw: dict) -> None:
        """Set every declared field from a plan dict -- the file's top level,
        or a saved plan scenario. Bad entries are dropped one by one, never
        the whole file."""
        self.income = _amount(raw.get("income"))
        self.spend = _amount(raw.get("spend"))
        self.one_offs = []
        self.rate_segments = []
        self.rate = None
        self.vol = None
        self.contributions = []
        self.ignored = []
        self.pocket_rates = {}
        for pocket, entry in (raw.get("pocket_rates") or {}).items():
            if pocket not in POCKET_KEYS or not isinstance(entry, dict):
                continue
            if entry.get("common"):
                self.pocket_rates[pocket] = {"common": True}
            else:
                self.pocket_rates[pocket] = {"rate_segments": _segments(entry.get("rate_segments", [])),
                                             "vol": _vol(entry.get("vol"))}

        for entry in raw.get("one_offs", []):
            if not isinstance(entry, dict):
                continue
            day = parse_day(entry.get("date"))
            month = entry.get("month") or (month_key(day) if day else None)
            if not (month and entry.get("label")):
                continue
            try:
                amount = float(entry["amount"])
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue
            seasonal = entry.get("seasonal")
            self.one_offs.append({
                "month": month,
                # An optional precise day. Without it the entry is simply "some
                # time that month", which is all a yearly bill needs; with it,
                # the projection can tell an entry still ahead of the ledger
                # from one it has already recorded.
                "date": day.isoformat() if day else "",
                "label": entry["label"],
                "amount": amount,
                "seasonal": seasonal if isinstance(seasonal, dict) else None,
                # A transfer leaves the cash account like any other one-off,
                # but it lands in a pocket instead of being spent. The cash
                # line cannot tell the difference; net worth must -- and which
                # pocket decides whether wealth tax reaches it.
                "transfer": _destination(entry.get("transfer")),
            })

        self.rate_segments = _segments(raw.get("rate_segments", []))
        rate = raw.get("rate")
        if rate is not None:
            try:
                self.rate = float(rate)
            except (TypeError, ValueError):
                pass
        if self.rate_segments:
            # The first segment is the closest single-number reading of the
            # schedule; the segments themselves stay canonical.
            self.rate = self.rate_segments[0][1]
        self.vol = _vol(raw.get("vol"))

        for entry in raw.get("contributions", []):
            if not isinstance(entry, dict):
                continue
            pocket = entry.get("pocket")
            if pocket not in (SHELTERED, TAXABLE):
                continue  # a contribution without a destination is not one
            try:
                amount = float(entry["amount"])
            except (TypeError, ValueError, KeyError):
                continue
            if amount <= 0:
                continue
            every = entry.get("every")
            if every not in CONTRIBUTION_EVERY:
                continue
            try:
                months = int(entry["months"])
            except (TypeError, ValueError, KeyError):
                continue
            if months < 1:
                continue
            start = str(entry.get("start") or "").strip()
            if start:
                # A garbage year would crash the projection's month
                # arithmetic; a malformed month would silently move the
                # series. Both are dropped whole, like every bad entry.
                try:
                    start_year, start_month = start.split("-")
                    valid = (start_year.isdigit() and len(start_year) == 4
                             and 1 <= int(start_month) <= 12)
                except (TypeError, ValueError):
                    valid = False
                if not valid:
                    continue
            self.contributions.append(_series(pocket, amount, every, months, start,
                                              entry.get("in_months")))

        for pair in raw.get("ignored_seasonal", []):
            try:
                category, month = pair
                self.ignored.append((str(category), int(month)))
            except (TypeError, ValueError):
                continue

    def _declarations(self) -> dict:
        """The declared fields as the file writes them -- the top level, and
        each saved plan scenario."""
        return {
            "income": {"amount": self.income} if self.income is not None else None,
            "spend": {"amount": self.spend} if self.spend is not None else None,
            # `rate` stays written so an older checkout reading the file
            # compounds at the first segment's rate -- a real number the user
            # typed -- rather than at nothing.
            "rate": (self.rate_segments[0][1] if self.rate_segments
                     else self.rate),
            "rate_segments": [[m, r] for m, r in self.rate_segments],
            "vol": self.vol,
            "pocket_rates": {k: ({"common": True} if v.get("common") else
                                 {"rate_segments": [[m, r] for m, r in v["rate_segments"]],
                                  "vol": v["vol"]})
                             for k, v in self.pocket_rates.items()},
            "contributions": [dict(c) for c in self.contributions],
            "one_offs": [dict(e) for e in self.one_offs],
            "ignored_seasonal": [[c, m] for c, m in self.ignored],
        }

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.active in self.plan_scenarios:
            # The live fields are the active scenario's working copy.
            self.plan_scenarios[self.active] = self._declarations()
        payload = {
            "version": VERSION,
            **self._declarations(),
            "scenarios": {name: {"rate_segments": [[m, r] for m, r in
                                                    s["rate_segments"]],
                                 "vol": s["vol"],
                                 "months": s.get("months", 0)}
                          for name, s in self.scenarios.items()},
            "plan_scenarios": self.plan_scenarios,
            "active_scenario": self.active,
            **({"deleted_scenario": self.deleted} if self.deleted else {}),
        }
        # Write then move, so an interrupted save cannot leave a truncated file.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        temporary.replace(self.path)
        return self.path

    # --- edits -------------------------------------------------------------

    def add_one_off(self, month: str, label: str, amount: float,
                    seasonal: tuple[str, int] | None = None,
                    transfer: bool | str = False,
                    date: str = "") -> None:
        """Upsert by (month, label): re-submitting the same entry edits it.

        `date` is the optional precise day. It is what lets a one-off planned
        for the end of the current month stay in the projection while the
        ledger already covers the first week of that month.
        """
        self.one_offs = [e for e in self.one_offs
                         if not (e["month"] == month and e["label"] == label)]
        entry = {"month": month, "label": label, "amount": amount}
        if date:
            entry["date"] = date
        if seasonal is not None:
            entry["seasonal"] = {"category": seasonal[0], "month": seasonal[1]}
        destination = _destination(transfer)
        if destination:
            entry["transfer"] = destination
        self.one_offs.append(entry)

    def replace_one_off(self, was: tuple[str, str], month: str, label: str, amount: float,
                        transfer: bool | str = False, date: str = "") -> bool:
        """Edit one entry whole -- day, label, amount, destination -- in place.

        Its `seasonal` provenance stays, so a confirmed suggestion is not
        offered again for being renamed or moved. Another entry already
        holding the new (month, label) gives way, as `add_one_off` would.
        """
        index = next((i for i, e in enumerate(self.one_offs)
                      if (e["month"], e["label"]) == was), None)
        if index is None:
            return False
        entry = {"month": month, "label": label, "amount": amount}
        if date:
            entry["date"] = date
        if "seasonal" in self.one_offs[index]:
            entry["seasonal"] = self.one_offs[index]["seasonal"]
        destination = _destination(transfer)
        if destination:
            entry["transfer"] = destination
        self.one_offs[index] = entry
        self.one_offs = [e for i, e in enumerate(self.one_offs)
                         if i == index or (e["month"], e["label"]) != (month, label)]
        return True

    def set_amount(self, month: str, label: str, amount: float) -> bool:
        """Resize an existing entry, in place.

        Not delete-and-re-add: that would drop the `seasonal` provenance and
        silently un-shadow the suggestion the entry was confirming, and would
        also lose the precise `date` and the `transfer` destination. Same rule
        as set_destination.
        """
        for entry in self.one_offs:
            if entry["month"] == month and entry["label"] == label:
                entry["amount"] = amount
                return True
        return False

    def set_destination(self, month: str, label: str, destination: str) -> bool:
        """Say where an existing entry's money goes: spent, or into which
        pocket.

        Edited in place rather than by delete-and-re-add, which would lose the
        seasonal provenance and so silently un-shadow the suggestion the entry
        was confirming.
        """
        destination = _destination(destination)
        for entry in self.one_offs:
            if entry["month"] == month and entry["label"] == label:
                if destination:
                    entry["transfer"] = destination
                else:
                    entry.pop("transfer", None)
                    entry["transfer"] = SPENT
                return True
        return False

    def remove_one_off(self, month: str, label: str) -> bool:
        before = len(self.one_offs)
        self.one_offs = [e for e in self.one_offs
                         if not (e["month"] == month and e["label"] == label)]
        return len(self.one_offs) < before

    def set_rates(self, segments, vol) -> None:
        """Replace the live barème. The rate form and the scenario-apply share
        this path so the two cannot drift; `vol` demotes out-of-range values
        exactly like the file load."""
        self.rate_segments = list(segments)
        self.rate = segments[0][1] if segments else None
        self.vol = vol if vol is not None and 0 <= vol <= 1.0 else None

    def own_rates(self, pocket: str) -> dict | None:
        """The pocket's own {"rate_segments", "vol"}, or None when it follows
        the common barème. An empty barème of its own holds it at its value."""
        entry = self.pocket_rates.get(pocket)
        if entry is None:
            return {"rate_segments": [], "vol": 0.0} if pocket in FIXED_BY_DEFAULT else None
        return None if entry.get("common") else entry

    def set_pocket_rates(self, pocket: str, segments, vol) -> None:
        """Give a pocket a barème of its own; `vol` None is the volatility
        measured on that pocket."""
        self.pocket_rates[pocket] = {"rate_segments": list(segments),
                                     "vol": vol if vol is not None and 0 <= vol <= 1.0 else None}

    def follow_common(self, pocket: str) -> None:
        """Back to the common barème."""
        if pocket in FIXED_BY_DEFAULT:
            self.pocket_rates[pocket] = {"common": True}
        else:
            self.pocket_rates.pop(pocket, None)

    def schedules(self) -> dict[str, list[tuple[int, float]]]:
        """The barèmes of the pockets that have their own: what
        `project_pockets` grows them by."""
        return {k: own["rate_segments"] for k in POCKET_KEYS
                if (own := self.own_rates(k)) is not None}

    def set_scenario(self, name: str, segments, vol, months: int = 0) -> None:
        """Save the live (rate_segments, vol) pair -- and the horizon it was
        read on -- under a name. Upsert: a name already taken is overwritten,
        like add_one_off."""
        name = name.strip()
        if not name:
            return
        self.scenarios[name] = {
            "rate_segments": list(segments),
            "vol": vol if vol is not None and 0 <= vol <= 1.0 else None,
            "months": months if months >= 1 else 0}

    def remove_scenario(self, name: str) -> bool:
        if name in self.scenarios:
            del self.scenarios[name]
            return True
        return False

    def apply_scenario(self, name: str) -> int | None:
        """Copy a saved scenario into the live fields -- a declaration like
        any other. Deleting the scenario never touches what it set.

        Returns the horizon (in months) the scenario carries, or None when it
        carries none -- the caller sets the view length accordingly."""
        spec = self.scenarios.get(name)
        if spec is None:
            return None
        self.set_rates(spec["rate_segments"], spec["vol"])
        months = spec.get("months") or 0
        return months if months >= 1 else None

    def add_contribution(self, pocket: str, amount: float, every: str,
                         months: int, start: str = "", in_months=None) -> None:
        self.contributions.append(_series(pocket, amount, every, months, start, in_months))

    def replace_contribution(self, index: int, pocket: str, amount: float, every: str,
                             months: int, start: str = "", in_months=None) -> bool:
        """Edit one series in place: its position in the list stays."""
        if not 0 <= index < len(self.contributions):
            return False
        self.contributions[index] = _series(pocket, amount, every, months, start, in_months)
        return True

    def remove_contribution(self, pocket: str, amount: float, every: str,
                            months: int, start: str, in_months=None) -> bool:
        """Remove every series equal to the declared one. A series has no
        natural key beyond its full content; two identical ones are
        indistinguishable, so all matches go."""
        wanted = _series(pocket, amount, every, months, start, in_months)
        before = len(self.contributions)
        self.contributions = [c for c in self.contributions if c != wanted]
        return len(self.contributions) < before

    # --- whole-plan scenarios ---------------------------------------------

    def save_scenario_as(self, name: str) -> None:
        """Keep the live plan under a name, and make it the active one --
        "save as": the next edits go to the copy, the original stays put."""
        name = name.strip()
        if not name:
            return
        self.plan_scenarios[name] = self._declarations()
        self.active = name

    def switch_scenario(self, name: str) -> bool:
        """Make another saved plan the live one. The active one keeps the
        edits made to it: they are stored before the other is loaded."""
        if name not in self.plan_scenarios:
            return False
        if self.active in self.plan_scenarios:
            self.plan_scenarios[self.active] = self._declarations()
        self._restore(self.plan_scenarios[name])
        self.active = name
        return True

    def remove_plan_scenario(self, name: str) -> bool:
        """Forget a saved plan. Deleting the active one keeps the live
        fields as they are, unnamed -- nothing on screen changes. The plan
        is kept aside (`deleted`) until the next deletion, for the undo."""
        if name not in self.plan_scenarios:
            return False
        kept = self._declarations() if name == self.active else self.plan_scenarios[name]
        self.deleted = {"name": name, "plan": kept}
        del self.plan_scenarios[name]
        if self.active == name:
            self.active = None
        return True

    def undelete_scenario(self) -> str | None:
        """Bring back the last plan deleted, under its name -- unless another
        took that name since. Returns the name, or None."""
        if not self.deleted or self.deleted["name"] in self.plan_scenarios:
            return None
        name = self.deleted["name"]
        self.plan_scenarios[name] = self.deleted["plan"]
        self.deleted = None
        return name

    def rename_scenario(self, old: str, new: str) -> bool:
        """Give a saved plan another name; its place as the active one goes
        with it. False when `old` is unknown or `new` already taken."""
        new = new.strip()
        if old not in self.plan_scenarios or not new or new in self.plan_scenarios:
            return False
        self.plan_scenarios = {(new if k == old else k): v
                               for k, v in self.plan_scenarios.items()}
        if self.active == old:
            self.active = new
        return True

    def scenario_plan(self, name: str) -> "Plan":
        """The saved plan `name`, detached -- the live plan itself when it is
        the active one, so the comparison sees edits not yet switched away."""
        if name == self.active:
            return self
        return _detached(self.plan_scenarios[name])

    def ignore(self, category: str, month: int) -> None:
        if (category, month) not in self.ignored:
            self.ignored.append((category, month))

    def restore(self, category: str, month: int) -> None:
        self.ignored = [(c, m) for c, m in self.ignored
                        if not (c == category and m == month)]

    @property
    def empty(self) -> bool:
        # A contribution is an active declaration; a saved scenario is not --
        # it changes nothing until it is applied.
        return (self.income is None and self.spend is None and not self.one_offs
                and not self.ignored and self.rate is None
                and not self.rate_segments and self.vol is None
                and not self.contributions and not self.pocket_rates)


# --- the projection -----------------------------------------------------------

def baseline(statement: Statement) -> float:
    """What an ordinary month costs, with the seasonal spikes removed.

    Each observed month is reduced by the seasonal contributions it carries
    (December minus its insurance bill, May minus its taxes), and the
    median of the adjusted months is the baseline. Without the subtraction
    the one-off would be counted twice -- once in the median, once on its
    own line.
    """
    seasonal = seasonal_one_offs(statement)
    months = analysis.monthly(statement)

    adjusted = []
    for row in months:
        total = _consumed(row)
        for s in seasonal:
            if s["month"] != calendar_month(row["month"]):
                continue
            carried = row["categories"].get(s["category"], 0.0)
            total -= min(s["amount"], carried)
        adjusted.append(max(total, 0.0))
    return statistics.median(adjusted) if adjusted else 0.0


def _interquartile_range(values: list[float]) -> float:
    """The middle half of a month's observations, Q3 minus Q1.

    Exclusive quartiles on three or more values: the fixture's three tax
    Mays (2'900, 9'200, 11'900) split into four equal intervals place Q1
    on the ordinary month and Q3 on the last bill, so the IQR spans the
    whole range. Two values are their own range (the exclusive method
    would push Q1 below the minimum and Q3 above the maximum, reporting
    a spread wider than anything observed). Fewer than two values have
    no spread at all -- 0.0, never a guess.
    """
    if len(values) == 2:
        return abs(values[0] - values[1])
    if len(values) < 2:
        return 0.0
    try:
        q1, _, q3 = statistics.quantiles(values, n=4)
    except statistics.StatisticsError:
        return 0.0
    return q3 - q1


def monthly_profile(statement: Statement,
                    year: int | None = None) -> list[dict]:
    """`baseline()`'s arithmetic spread over the calendar, one entry per
    observed calendar month, so the page can show where the number comes
    from. Each observed (year, month) is reduced by the seasonal
    contributions it carries -- the same subtraction as `baseline()`, so
    the strip and the baseline can never disagree -- then medians are
    taken per calendar month. A month never observed is absent; a month
    with nothing seasonal to strip carries a zero `seasonal_median`.

    `year` narrows the profile to a single year: only that year's
    observations feed the medians, so each month's median is the value
    of that year, and a calendar month the year never saw is absent --
    the same honest absence as a month no year ever saw. `years` then
    carries the one year.
    """
    months = analysis.monthly(statement)
    seasonal = seasonal_one_offs(statement)

    raw: dict[tuple[int, int], float] = {}
    stripped: dict[tuple[int, int], float] = {}
    for row in months:
        year_no, cal = int(row["month"][:4]), calendar_month(row["month"])
        if year is not None and year_no != year:
            continue
        total = _consumed(row)
        for s in seasonal:
            if s["month"] != cal:
                continue
            carried = row["categories"].get(s["category"], 0.0)
            total -= min(s["amount"], carried)
        raw[(year_no, cal)] = _consumed(row)
        stripped[(year_no, cal)] = max(total, 0.0)

    profile = []
    for cal in range(1, 13):
        years = sorted({yr for (yr, month) in raw if month == cal})
        if not years:
            continue
        raw_values = [raw[(yr, cal)] for yr in years]
        stripped_values = [stripped[(yr, cal)] for yr in years]
        removed = [raw[(yr, cal)] - stripped[(yr, cal)]
                   for yr in years]
        profile.append({
            "month": cal,
            "label": MONTH_NAMES[cal - 1].capitalize(),
            "short": analysis.MONTH_SHORT[cal - 1],
            "years": years,
            "raw_median": round(statistics.median(raw_values), 2),
            "stripped_median": round(statistics.median(stripped_values), 2),
            "seasonal_median": round(statistics.median(removed), 2),
            # The spread of the month's raw values: the strip tells how
            # much of the median is an annual bill, the IQR how much the
            # month itself varies between years.
            "iqr": round(_interquartile_range(raw_values), 2),
            # The suggestions that land on this month -- the declared
            # annual bills the strip removes, with their years.
            "seasonal": [s for s in seasonal if s["month"] == cal],
        })
    return profile


def _median_trend(pairs: list[tuple[int, float]]) -> float | None:
    """The category's spend shift, as a share: the median of the second
    half of the observed months over the median of the first half.

    A log-linear annualised slope turns a level change -- a move, a new
    rent -- into an absurd +800 %/an, because it extrapolates a jump as
    if it were a monthly drift. The two halves keep a level change as
    one visible shift and let a steady drift read as a slow one; medians
    keep a noisy category from being dragged by its spikes. Six observed
    months is the least that divides into two halves worth comparing,
    and a zero base (a category that only exists since the second half)
    has no share to report.
    """
    if len(pairs) < 6:
        return None
    half = len(pairs) // 2
    first = statistics.median(amount for _, amount in pairs[:half])
    second = statistics.median(amount for _, amount in pairs[half:])
    if first <= 0:
        return None
    return round((second / first - 1) * 100, 1)


def category_profile(statement: Statement) -> list[dict]:
    """Per category: the median month, the calendar month it peaks in,
    whether the history flags it seasonal, and the trend of the monthly
    spend -- the stats that tell a regular line (rent) from an annual
    spike (insurance) from a line that is drifting. Sorted by median
    spend, so the categories that shape the baseline come first."""
    months = analysis.monthly(statement)
    seasonal = {s["category"]: s for s in seasonal_one_offs(statement)}

    by_calendar: dict[tuple[str, int], list[float]] = defaultdict(list)
    # (month number, amount) per category, in the monthly series' order.
    all_values: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for row in months:
        cal = calendar_month(row["month"])
        month_no = _month_no(row["month"])
        for category, amount in row["categories"].items():
            by_calendar[(category, cal)].append(amount)
            all_values[category].append((month_no, amount))

    out = []
    for category, pairs in all_values.items():
        values = [amount for _, amount in pairs]
        per_cal = {cal: statistics.median(vs)
                   for (cat, cal), vs in by_calendar.items()
                   if cat == category}
        peak_month, peak = max(per_cal.items(), key=lambda kv: kv[1])
        flagged = seasonal.get(category)
        # A seasonal category gets no trend: its month-to-month median mixes
        # the annual bill with the small regular months, so a rising bill
        # reads as a collapse. Its story is the seasonal chip -- and the
        # declared future lives in the previsions, not in a slope.
        out.append({
            "category": category,
            "median": round(statistics.median(values), 2),
            "peak_month": peak_month,
            "peak": round(peak, 2),
            "trend": None if flagged else _median_trend(pairs),
            "seasonal": ({"month": flagged["month"],
                          "amount": round(flagged["amount"], 2),
                          "years": flagged["years"]}
                         if flagged else None),
        })
    return sorted(out, key=lambda r: -r["median"])


def monthly_income(statement: Statement) -> float:
    """The historical month, to fall back on when nothing is declared."""
    values = [row["income"] for row in analysis.monthly(statement)]
    return statistics.median(values) if values else 0.0


def project(statement: Statement, plan: Plan | None = None,
            months_ahead: int = MONTHS_AHEAD) -> dict:
    """Cash month by month: the low point is the answer the page is for.

    Starts at the CHF closing balance -- what the account actually holds.
    Each month adds the income (declared in the plan, else the historical
    median) and subtracts the baseline spend plus that month's one-offs:
    the declared ones always, the history's suggestions unless ignored.
    A declared entry with the same label shadows its suggestion, so
    confirming a suggestion does not leave it counted twice.
    """
    plan = plan or Plan(Path("unused"))  # an empty plan: history only
    cash = closing_chf(statement)
    if plan.income is not None:
        income, income_source = plan.income, "declared"
    else:
        income = monthly_income(statement)
        income_source = "history" if income else None

    history_base = baseline(statement)
    base = plan.spend if plan.spend is not None else history_base
    suggestions = seasonal_one_offs(statement)
    as_of = statement.period_end

    # The statement almost never ends on the last of the month, and everything
    # planned for the rest of that month used to fall in the gap: the first
    # projected row was the *next* month, so a transfer declared for the 28th
    # while the ledger stops on the 7th appeared nowhere. The remainder of the
    # current month is therefore a row of its own.
    #
    # It counts only what has not happened yet, and that is measurable rather
    # than prorated: the month's usual income and spend, minus what the ledger
    # already records for that month. A salary already paid leaves nothing to
    # add; a month already over its usual spend adds no more.
    partial = as_of != _last_of_month(as_of)
    keys = projection_keys(as_of, months_ahead)

    month_start = as_of.replace(day=1)
    spent_by_category: dict[str, float] = defaultdict(float)
    for txn in analysis.spending(statement):
        if txn.date >= month_start:
            spent_by_category[txn.category] += abs(txn.amount_chf)
    # A transfer to a pocket already made this month is not part of the
    # month's usual spend either: it would eat the remaining base.
    spent_so_far = sum(v for c, v in spent_by_category.items() if not _saved(c))
    earned_so_far = sum(t.amount_chf for t in analysis.income(statement)
                        if t.date >= month_start)

    def still_ahead(entry: dict) -> bool:
        """A dated entry whose day has passed is not a forecast any more --
        the ledger already carries it, and counting it again would subtract
        the same money twice. An undated entry is kept: "some time in August"
        is still ahead as far as anything here knows."""
        day = parse_day(entry.get("date"))
        return day is None or day > as_of

    contributions_by_key = _contribution_occurrences(
        plan, keys, 1 if partial else 0)

    rows = []
    running = cash
    for index, key in enumerate(keys):
        this_partial = partial and index == 0
        start = running
        earn = max(income - earned_so_far, 0.0) if this_partial else income
        month_base = max(base - spent_so_far, 0.0) if this_partial else base

        declared_offs = []
        for e in plan.one_offs:
            if e["month"] != key or not still_ahead(e):
                continue
            amount = e["amount"]
            if this_partial and not e.get("date"):
                # An undated declaration for a month already under way is a
                # forecast of what the ledger has not recorded yet. A confirmed
                # suggestion carries its category -- and the bill may already
                # be in the ledger, which would charge it twice. Same rule as
                # the suggestion path just below.
                category = (e.get("seasonal") or {}).get("category")
                if category:
                    amount = max(amount - spent_by_category.get(category, 0.0),
                                 0.0)
                    if amount <= 0:
                        continue
            declared_offs.append({
                "label": e["label"], "amount": round(amount, 2),
                "source": "declared",
                "transfer": _destination(e.get("transfer")),
                "date": e.get("date", "")})
        one_offs = declared_offs
        # A programmed series is a declared transfer: the cash line subtracts
        # it like any other, and project_wealth credits the pocket.
        one_offs.extend(contributions_by_key.get(key, []))

        # A confirmed suggestion is a declared entry, whether it kept its
        # category name or was renamed -- either way it must not be counted
        # twice. The provenance field ties the two together.
        # Both shadows are of this month only: confirming December 2026's
        # insurance must not erase December 2027's from a longer horizon.
        declared_labels = {e["label"] for e in plan.one_offs if e["month"] == key}
        seasonal_shadows = {(e["seasonal"]["category"], e["seasonal"]["month"])
                            for e in plan.one_offs
                            if e.get("seasonal") and e["month"] == key}
        for s in suggestions:
            if s["month"] != calendar_month(key):
                continue
            if (s["category"], s["month"]) in plan.ignored:
                continue
            if s["category"] in declared_labels:
                continue  # confirmed -- already on its own line
            if (s["category"], s["month"]) in seasonal_shadows:
                continue  # confirmed under another name
            amount = s["amount"]
            if this_partial:
                # Same rule as the baseline: only what the month has left to
                # deliver. A tax bill already paid on the 3rd is in the ledger,
                # so predicting it again would charge it twice.
                amount = max(amount - spent_by_category.get(s["category"], 0.0), 0.0)
                if amount <= 0:
                    continue
            one_offs.append({"label": s["category"], "amount": round(amount, 2),
                             "source": "suggestion", "transfer": SPENT,
                             "date": ""})

        spend = month_base + sum(o["amount"] for o in one_offs)
        running = start + earn - spend
        rows.append({
            "key": key,
            "label": month_label(key),
            # The remainder of a month already under way is not a full month,
            # and the table says so rather than letting it read as one.
            "partial": this_partial,
            "start": round(start, 2),
            "income": round(earn, 2),
            "spend": round(spend, 2),
            "one_offs": one_offs,
            "end": round(running, 2),
        })

    # The low point is over the whole horizon, today included: when the
    # projection never dips below the starting cash, that cash *is* the
    # answer ("you never go below where you are now"), not the first month.
    lowest = min(rows, key=lambda r: r["end"]) if rows else None
    if lowest is not None and lowest["end"] < cash:
        low = {"amount": lowest["end"], "key": lowest["key"],
               "label": lowest["label"]}
    else:
        low = {"amount": cash, "key": None, "label": "aujourd'hui"}
    return {
        "cash": round(cash, 2),
        "income": round(income, 2),
        "income_source": income_source,
        "baseline": round(base, 2),
        "baseline_source": "declared" if plan.spend is not None else "history",
        "baseline_history": round(history_base, 2),
        # The horizon the caller asked for -- the page copy reads it back, so
        # the subtitle and the curve never drift apart from what was asked.
        "months": months_ahead,
        "rows": rows,
        "low": low,
    }


def _monthly_rate(rate: float | None, rate_schedule: list[tuple[int, float]] | None):
    """The monthly rate of the `row`-th projected month (1-based), from the
    declared barème, or the single `rate`, or nothing."""
    if rate_schedule:
        def monthly_at(row: int) -> float:
            declared = rate_at(rate_schedule, row)
            return (1.0 + declared) ** (1 / 12) - 1 if declared is not None else 0.0
        return monthly_at
    monthly = (1.0 + rate) ** (1 / 12) - 1 if rate else 0.0
    return lambda row: monthly


def project_wealth(projection: dict, invested: float,
                   rate: float | None, vol: float = 0.0,
                   pocket: str | None = None,
                   include_cash: bool = True,
                   rate_schedule: list[tuple[int, float]] | None = None) -> dict:
    """Net worth month by month: the cash projection plus the invested pockets.

    Two ingredients with very different standing, and the difference is the
    whole reason this function is separate from `project()`. The cash line is
    arithmetic over declared and observed figures. The invested line rests on
    an assumed annual return, which is a guess -- so `rate` is never invented
    here: `None` holds the pockets at their last known value, and any growth
    on the chart is a number the account holder typed.

    `vol` is the annualised volatility measured on the pockets' own history
    (`analysis.risk_stats`), not a parameter of the model. It draws a ±1σ band
    widening as √t, which is what stops a single line from reading like a
    promise. It applies to the invested part only -- cash does not fluctuate.

    A one-off marked `transfer` is the one entry the cash line gets wrong on
    its own. It leaves the account like a payment, so `project()` subtracts
    it -- but it lands in a pocket rather than being spent, so net worth must
    put it back. Without this the curve shows a cliff every time money is
    moved to the 3a, which is the same mistake as counting an FX leg as
    spending. Nothing is contributed unless it is declared: the ledger is
    never mined for an intention.

    `pocket` narrows the curve to one side of the wealth tax: `None` is the
    whole net worth, `TAXABLE` the part the tax reaches (bank and brokerage),
    `SHELTERED` the pillar 3a it does not. Only transfers heading for the
    chosen pocket are added, or the sheltered curve would grow by money that
    went to the brokerage. `include_cash` goes with it: the sheltered view
    holds no cash account, so adding the current-account balance to it would
    be plain wrong rather than merely imprecise.

    `rate_schedule` is the finer alternative to `rate`: a chain of
    (months, rate) segments applied to the projected rows in order, each
    month using the rate of the segment it falls in. It wins over `rate`
    when non-empty.

    The rate applies to `held` alone. The cash line is arithmetic on declared
    figures and never compounds -- a current account earns nothing here, and
    growing it would put invented interest into the one number on the page
    that comes straight from the bank.
    """
    monthly_at = _monthly_rate(rate, rate_schedule)
    rows = []
    held = invested
    for i, row in enumerate(projection["rows"], start=1):
        moved = sum(o["amount"] for o in row["one_offs"]
                    if o.get("transfer")
                    and (pocket is None or o.get("transfer") == pocket))
        held = held * (1.0 + monthly_at(i)) + moved
        cash_now = row["end"] if include_cash else 0.0
        sigma = vol * (i / 12) ** 0.5
        rows.append({
            "key": row["key"],
            "label": row["label"],
            "partial": row.get("partial", False),
            "cash": round(cash_now, 2),
            "invested": round(held, 2),
            "moved": round(moved, 2),
            "total": round(cash_now + held, 2),
            "low": round(cash_now + max(held * (1 - sigma), 0.0), 2),
            "high": round(cash_now + held * (1 + sigma), 2),
        })

    start = (projection["cash"] if include_cash else 0.0) + invested
    return {
        "start": round(start, 2),
        "invested": round(invested, 2),
        "rate": rate,
        "rate_schedule": rate_schedule or None,
        "vol": vol,
        "rows": rows,
        "final": rows[-1] if rows else None,
        "change": round(rows[-1]["total"] - start, 2) if rows else 0.0,
        "moved": round(sum(r["moved"] for r in rows), 2),
    }


def wealth_from_pockets(projection: dict, split: dict, include_cash: bool = True) -> dict:
    """`project_wealth`'s curve, read off `project_pockets`: what the page
    draws when each pocket may grow at its own rate. The cash is the
    projection's; the band is the split's (each pocket's own σ), the low
    side floored at no invested value at all."""
    rows = []
    start_invested = sum(split["start"].values())
    for row in split["rows"]:
        cash_now = row["cash"] if include_cash else 0.0
        held = sum(row["pockets"].values())
        rows.append({
            "key": row["key"], "label": row["label"], "partial": row["partial"],
            "cash": round(cash_now, 2), "invested": round(held, 2), "moved": row["moved"],
            "total": round(cash_now + held, 2),
            "low": round(cash_now + max(held - row["spread"], 0.0), 2),
            "high": round(cash_now + held + row["spread"], 2),
        })
    start = (projection["cash"] if include_cash else 0.0) + start_invested
    return {
        "start": round(start, 2), "invested": round(start_invested, 2), "rows": rows,
        "final": rows[-1] if rows else None,
        "change": round(rows[-1]["total"] - start, 2) if rows else 0.0,
        "moved": round(sum(r["moved"] for r in rows), 2),
    }


def project_pockets(projection: dict, pockets: dict[str, float],
                    routes: dict[str, str], rate: float | None,
                    rate_schedule: list[tuple[int, float]] | None = None,
                    include_cash: bool = True,
                    schedules: dict[str, list[tuple[int, float]]] | None = None,
                    vols: dict[str, float] | None = None) -> dict:
    """`project_wealth`, pocket by pocket, and where the change comes from.

    Same arithmetic, split: each invested pocket compounds at the declared
    rate (the plan has one rate, not one per pocket -- the page says so) and
    receives the declared transfers routed to it (`routes`: destination ->
    pocket, a 3a transfer to the 3a). Since the growth is linear in the
    holdings, the pockets add up to `project_wealth`'s `invested`, to the
    centime -- the test holds them to it. A transfer to a destination with no
    pocket here (the 3a, in the taxable view) leaves the picture: the cash
    pays it and nothing receives it.

    `flows` explains the move from today's total to the horizon's: the
    income, the usual spending, the one-offs spent, the transfers that leave
    the view, and each pocket's growth. They add up to the change exactly;
    the transfers between the cash and a pocket of the view cancel, and are
    reported apart (`moved`).

    `schedules` gives some pockets a barème of their own (an empty one holds
    the pocket at its value); the others follow `rate` / `rate_schedule`.
    `vols` is each pocket's volatility: the band of a row is the sum of each
    pocket's ±1σ -- the pockets taken as moving together, the prudent
    reading, and exactly `project_wealth`'s band when they share one vol.
    """
    common_at = _monthly_rate(rate, rate_schedule)
    own_at = {k: _monthly_rate(None, s or None) for k, s in (schedules or {}).items()}
    vols = vols or {}
    held = dict(pockets)
    paid = {k: 0.0 for k in held}
    growth = {k: 0.0 for k in held}
    income = base = spent = left = 0.0
    rows = []
    for i, row in enumerate(projection["rows"], start=1):
        for key in held:
            gain = held[key] * own_at.get(key, common_at)(i)
            growth[key] += gain
            held[key] += gain
        moved = 0.0
        for o in row["one_offs"]:
            target = routes.get(o.get("transfer") or "")
            if not o.get("transfer"):
                spent += o["amount"]
            elif target is None:
                left += o["amount"]
            else:
                held.setdefault(target, 0.0)
                paid.setdefault(target, 0.0)
                growth.setdefault(target, 0.0)
                held[target] += o["amount"]
                paid[target] += o["amount"]
                moved += o["amount"]
        income += row["income"]
        base += row["spend"] - sum(o["amount"] for o in row["one_offs"])
        spread = sum(max(v, 0.0) * vols.get(k, 0.0) for k, v in held.items()) * (i / 12) ** 0.5
        rows.append({"key": row["key"], "label": row["label"],
                     "partial": row.get("partial", False),
                     "cash": round(row["end"], 2) if include_cash else None,
                     "pockets": {k: round(v, 2) for k, v in held.items()},
                     "moved": round(moved, 2), "spread": spread})

    flows = []
    if include_cash:
        flows += [{"key": "income", "label": "Revenus", "amount": round(income, 2)},
                  {"key": "base", "label": "Dépense courante", "amount": round(-base, 2)},
                  {"key": "spent", "label": "Ponctuels", "amount": round(-spent, 2)}]
        if left:
            flows.append({"key": "left", "label": "Versé hors de cette vue",
                          "amount": round(-left, 2)})
    else:
        flows += [{"key": f"paid:{k}", "pocket": k, "label": "Versements",
                   "amount": round(v, 2)} for k, v in paid.items() if v]
    flows += [{"key": f"growth:{k}", "pocket": k, "label": "Rendement",
               "amount": round(v, 2)} for k, v in growth.items() if v]
    return {
        "rows": rows,
        "start": {k: round(v, 2) for k, v in pockets.items()},
        "end": {k: round(v, 2) for k, v in held.items()},
        "paid": {k: round(v, 2) for k, v in paid.items()},
        "growth": {k: round(v, 2) for k, v in growth.items()},
        "flows": flows,
        "moved": round(sum(paid.values()), 2) if include_cash else 0.0,
    }
