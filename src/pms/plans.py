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
from .models import Statement

VERSION = 1

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
DESTINATION_LABELS = {
    SPENT: "dépense",
    SHELTERED: "virement 3a (hors impôt sur la fortune)",
    TAXABLE: "virement placement (imposable)",
}

# The cadence of a planned series of transfers, in months, and its label.
CONTRIBUTION_EVERY = {"month": 1, "quarter": 3, "semester": 6, "year": 12}
CONTRIBUTION_LABELS = {"month": "chaque mois", "quarter": "chaque trimestre",
                       "semester": "chaque semestre", "year": "chaque année"}

#: Named parameter sets the user can recall. The built-ins are examples of
#: shape, not advice: the app proposes, and applying one is the user declaring
#: the values -- the same standing as a confirmed seasonal suggestion. Keys are
#: stable English identifiers, labels the French UI copy. Vol stays None
#: (measured) everywhere: dispersion is an observation on the user's own
#: pockets, not a hypothesis to template. A scenario may also carry `months`,
#: the horizon its shape is about -- applying it sets the view length too.
BUILTIN_SCENARIOS: dict[str, dict] = {
    "constant-growth": {"label": "Croissance constante",
                        "rate_segments": [(12, 0.04)], "vol": None},
    # The lost decade in CHF, measured on the real path (S&P 500 total return
    # x USDCHF, pic 2000-09-07 -> creux 2009-03-09 -> recouvrement 2014-12-19):
    # -11.8 %/an pendant 102 mois est le CAGR qui mène au creux de -65.6 %, et
    # +20.3 %/an pendant 69 mois celui qui en revient. Un scénario qui perd
    # 2 % deux ans puis gagne 3 % huit ans serait une décennie qui gagne.
    # Une fois l'épisode fini, le rendement retombe à la moyenne historique
    # longue en CHF (3.9 %/an, mesurée 1999-2018, épisode compris) -- c'est ce
    # qui s'applique ensuite, au lieu du taux de recouvrement porté à vie.
    "lost-decade": {"label": "Décennie perdue — S&P 500 en CHF",
                    "rate_segments": [(102, -0.1180), (69, 0.2027),
                                      (300, 0.0389)],
                    "vol": None, "months": 180},
    "rebound": {"label": "Rebond après crise",
                "rate_segments": [(12, -0.10), (108, 0.06)], "vol": None},
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


def closing_chf(statement: Statement) -> float:
    """What the account actually holds: the CHF closing balance."""
    return next((a.closing_balance for a in statement.accounts
                 if a.currency == "CHF"), 0.0)


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

    @classmethod
    def load(cls, path: Path | str) -> "Plan":
        plan = cls(path)
        if not plan.path.exists():
            return plan
        try:
            raw = json.loads(plan.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return plan

        income = raw.get("income")
        if isinstance(income, dict) and income.get("amount"):
            try:
                plan.income = float(income["amount"])
            except (TypeError, ValueError):
                pass

        for entry in raw.get("one_offs", []):
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
            plan.one_offs.append({
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

        for pair in raw.get("rate_segments", []):
            try:
                months, rate = pair
                months = int(months)
                rate = float(rate)
            except (TypeError, ValueError):
                continue
            if months >= 1 and -100 <= rate <= 100:
                plan.rate_segments.append((months, rate))

        rate = raw.get("rate")
        if rate is not None:
            try:
                plan.rate = float(rate)
            except (TypeError, ValueError):
                pass
        if plan.rate_segments:
            # The first segment is the closest single-number reading of the
            # schedule; the segments themselves stay canonical.
            plan.rate = plan.rate_segments[0][1]

        vol = raw.get("vol")
        if vol is not None:
            try:
                vol = float(vol)
            except (TypeError, ValueError):
                vol = None
            # A volatility outside [0, 100] % would silently invert or explode
            # the band. A hand edit that wrote one is demoted to the measured
            # fallback, never echoed into the chart.
            plan.vol = vol if vol is not None and 0 <= vol <= 1.0 else None

        for name, spec in (raw.get("scenarios") or {}).items():
            if not isinstance(spec, dict) or not str(name).strip():
                continue
            segments: list[tuple[int, float]] = []
            for pair in spec.get("rate_segments", []):
                try:
                    months, rate = pair
                    months = int(months)
                    rate = float(rate)
                except (TypeError, ValueError):
                    continue
                if months >= 1 and -100 <= rate <= 100:
                    segments.append((months, rate))
            scenario_vol = spec.get("vol")
            if scenario_vol is not None:
                try:
                    scenario_vol = float(scenario_vol)
                except (TypeError, ValueError):
                    scenario_vol = None
                if scenario_vol is not None and not 0 <= scenario_vol <= 1.0:
                    scenario_vol = None
            try:
                months = int(spec.get("months") or 0)
            except (TypeError, ValueError):
                months = 0
            plan.scenarios[str(name)] = {"rate_segments": segments,
                                         "vol": scenario_vol,
                                         "months": months if months >= 1 else 0}

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
            plan.contributions.append({"pocket": pocket, "amount": amount,
                                       "every": every, "months": months,
                                       "start": start})

        for pair in raw.get("ignored_seasonal", []):
            try:
                category, month = pair
                plan.ignored.append((str(category), int(month)))
            except (TypeError, ValueError):
                continue
        return plan

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": VERSION,
            "income": {"amount": self.income} if self.income is not None else None,
            # `rate` stays written so an older checkout reading the file
            # compounds at the first segment's rate -- a real number the user
            # typed -- rather than at nothing.
            "rate": (self.rate_segments[0][1] if self.rate_segments
                     else self.rate),
            "rate_segments": [[m, r] for m, r in self.rate_segments],
            "vol": self.vol,
            "scenarios": {name: {"rate_segments": [[m, r] for m, r in
                                                    s["rate_segments"]],
                                 "vol": s["vol"],
                                 "months": s.get("months", 0)}
                          for name, s in self.scenarios.items()},
            "contributions": self.contributions,
            "one_offs": self.one_offs,
            "ignored_seasonal": [[c, m] for c, m in self.ignored],
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
                         months: int, start: str = "") -> None:
        self.contributions.append({"pocket": pocket, "amount": amount,
                                   "every": every, "months": months,
                                   "start": start})

    def remove_contribution(self, pocket: str, amount: float, every: str,
                            months: int, start: str) -> bool:
        """Remove every series equal to the declared one. A series has no
        natural key beyond its full content; two identical ones are
        indistinguishable, so all matches go."""
        wanted = {"pocket": pocket, "amount": amount, "every": every,
                  "months": months, "start": start}
        before = len(self.contributions)
        self.contributions = [c for c in self.contributions if c != wanted]
        return len(self.contributions) < before

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
        return (self.income is None and not self.one_offs
                and not self.ignored and self.rate is None
                and not self.rate_segments and self.vol is None
                and not self.contributions)


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
        total = row["spending"]
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
        total = row["spending"]
        for s in seasonal:
            if s["month"] != cal:
                continue
            carried = row["categories"].get(s["category"], 0.0)
            total -= min(s["amount"], carried)
        raw[(year_no, cal)] = row["spending"]
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

    base = baseline(statement)
    suggestions = seasonal_one_offs(statement)
    as_of = statement.period_end
    first = _add_months(as_of, 1)

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
    keys = [month_key(_add_months(first, i)) for i in range(months_ahead)]
    if partial:
        keys.insert(0, month_key(as_of))

    month_start = as_of.replace(day=1)
    spent_so_far = sum(abs(t.amount_chf) for t in analysis.spending(statement)
                       if t.date >= month_start)
    earned_so_far = sum(t.amount_chf for t in analysis.income(statement)
                        if t.date >= month_start)
    spent_by_category: dict[str, float] = defaultdict(float)
    for txn in analysis.spending(statement):
        if txn.date >= month_start:
            spent_by_category[txn.category] += abs(txn.amount_chf)

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
        declared_labels = {e["label"] for e in plan.one_offs if e["month"] == key}
        seasonal_shadows = {(e["seasonal"]["category"], e["seasonal"]["month"])
                            for e in plan.one_offs if e.get("seasonal")}
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
        # The horizon the caller asked for -- the page copy reads it back, so
        # the subtitle and the curve never drift apart from what was asked.
        "months": months_ahead,
        "rows": rows,
        "low": low,
    }


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
    if rate_schedule:
        def monthly_at(row: int) -> float:
            declared = rate_at(rate_schedule, row)
            return (1.0 + declared) ** (1 / 12) - 1 if declared is not None else 0.0
    else:
        monthly = (1.0 + rate) ** (1 / 12) - 1 if rate else 0.0
        monthly_at = lambda row: monthly  # noqa: E731

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
