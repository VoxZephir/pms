"""Cash-flow and wealth projection: the view switches of the forecast, the
net-worth curve's measured half, the scenario comparison, and the one
function every edit to the plan goes through (`apply_plan_action`).
`/api/previsions` serves them.
"""

from __future__ import annotations

import datetime as dt
import re

from flask import request

from ... import analysis
from ... import crypto as crypto_module
from ... import finpension as finpension_module
from ... import holdings as holdings_module
from ... import ibkr as ibkr_module
from ... import plans as plans_module
from ..palette import MAX_SLOTS
from .common import store, titres_mode
from .savings import _evolution_row

# Which side of the wealth tax the net-worth curve shows. A pillar 3a is out
# of taxable wealth until it is drawn; a bank balance and a brokerage account
# are not. Same money, two readings -- like the timeline's stack switch.
WEALTH_VIEWS = {
    "all": {"label": "Tout", "aria": "patrimoine total",
            "note": "Swissquote + IBKR + 3a"},
    "taxable": {"label": "Imposable", "aria": "patrimoine soumis à l'impôt "
                                             "sur la fortune",
                "note": "Swissquote + IBKR — ce que l'impôt sur la fortune "
                        "atteint"},
    "sheltered": {"label": "Hors impôt", "aria": "patrimoine hors impôt sur "
                                                "la fortune",
                  "note": "3a finpension — hors fortune imposable jusqu'au "
                          "retrait"},
}


DEFAULT_WEALTH_VIEW = "all"


# The projection horizon: ?months=N, clamped. The low bound is "next month"
# (a shorter view would be the balance itself); the high one is forty years --
# a long retirement view, the user's explicit ask. The default rides on
# plans.MONTHS_AHEAD so the two can never disagree about what "a forecast"
# means.
MONTHS_MIN, MONTHS_MAX = 1, 480


DEFAULT_MONTHS = plans_module.MONTHS_AHEAD


HORIZON_PRESETS = (6, 12, 24, 36, 60, 120, 240, 480)


# The y axis of the wealth curve. Log is the mode a multi-decade horizon
# needs; it applies only while every drawn value is positive, otherwise the
# chart falls back to linear and says so.
YSCALES = {"linear": "linéaire", "log": "log"}


DEFAULT_YSCALE = "linear"


def months_label(n: int) -> str:
    """The horizon in words: months below a year, years above -- '480 mois'
    would read as a phone number."""
    if n >= 12 and n % 12 == 0:
        years = n // 12
        return f"{years} an" + ("s" if years > 1 else "")
    return f"{n} mois"


def wealth_mode(args) -> str:
    """Which side of the wealth tax the net-worth curve shows -- validated."""
    mode = (args.get("wealth") or "").strip()
    return mode if mode in WEALTH_VIEWS else DEFAULT_WEALTH_VIEW


def months_ahead(args) -> int:
    """?months=N, clamped to [MONTHS_MIN, MONTHS_MAX]. Garbage falls back to
    the default -- the same split the rest of the app uses: enums fall back,
    numerics clamp."""
    raw = (args.get("months") or "").strip()
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_MONTHS
    return max(MONTHS_MIN, min(n, MONTHS_MAX))


def yscale_mode(args) -> str:
    """The wealth axis scale -- validated like the other view switches."""
    mode = (args.get("yscale") or "").strip()
    return mode if mode in YSCALES else DEFAULT_YSCALE


# --- cash-flow previsions ----------------------------------------------------

_PLAN_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _plan() -> plans_module.Plan:
    """The declared plan, next to the ledger like the overrides.

    Read fresh on every request: the file is tiny, and an edit made here
    must be visible on the next render without any cache to invalidate.
    """
    return plans_module.Plan.load(store().path.with_name("plans.json"))


#: How far back the observed half of the net-worth curve reaches. Symmetric
#: with the 12 months projected forward, so today sits in the middle and the
#: eye compares a measured year against an assumed one at the same scale.
WEALTH_LOOKBACK_MONTHS = 12


def _wealth(data, plan: plans_module.Plan, projection: dict) -> tuple[dict, int]:
    """The net-worth curve: a measured year, then an assumed one.

    The observed half is built by `_evolution_row`, the same function behind
    the savings page's curve -- unlisted shares included unless `?titres=0`,
    like there -- so the two can never disagree about what the portfolio was
    worth at a given month end. The projected half grows each pocket at its
    own barème when it has one (`Plan.own_rates`), the common one otherwise
    (`plans.project_pockets`). The volatility is measured on the pockets'
    own monthly history unless declared: the band is the account's real past
    dispersion, not a parameter someone chose.

    Returns `({}, 0)` when there is no brokerage snapshot: without the
    pockets the curve would just be the cash line already above it. The
    second element is the number of observed points.
    """
    ibkr = ibkr_module.load(data.path.with_name("ibkr.json"))
    if not ibkr:
        return {}, 0
    finpension = finpension_module.load(data.path.with_name("finpension.json"))
    crypto = crypto_module.load(data.path.with_name("crypto.json"))
    securities = (holdings_module.load(data.path.with_name("holdings.json"))
                  if titres_mode(request.args) else [])

    end = data.statement.period_end
    low = data.bounds[0]
    start = max(low, plans_module._add_months(end, -WEALTH_LOOKBACK_MONTHS))

    rows = []
    day = start
    while day <= end:
        month_end = analysis.bucket_bounds(day, "month")[1]
        point = min(month_end, end)
        rows.append(_evolution_row(data.statement, ibkr, finpension, point, crypto, securities))
        day = month_end + dt.timedelta(days=1)

    # Which parts of the picture the chosen view counts. The measured half and
    # the projected half must slice the same way, or the curve would step at
    # the join for no reason other than the filter.
    view = wealth_mode(request.args)
    include_cash = view != "sheltered"

    def seen(row: dict) -> float:
        return round(sum(row.get(k) or 0.0 for k in VIEW_POCKETS[view]), 2)

    observed = [{"total": seen(r), "label": _short_month(r["date"])} for r in rows]

    # The band describes the *invested* pockets only, so the volatility is
    # measured on them alone. Including the Swissquote balance would read a
    # salary landing as portfolio risk.
    years = max((end - start).days / 365.25, 1 / 12)
    invested_levels = [r["ibkr"] + r["finp"] + (r["crypto"] or 0.0) + (r["titres"] or 0.0)
                       for r in rows if r["ibkr"] is not None and r["finp"] is not None]
    stats = analysis.risk_stats(invested_levels, years) if len(invested_levels) >= 3 else {}
    # A declared value moves by a step once a year: its "volatility" would
    # measure the declaration, not a market.
    measured = {k: _measured_vol([r[k] for r in rows if r.get(k) is not None], years)
                for k in plans_module.POCKET_KEYS if k not in plans_module.FIXED_BY_DEFAULT}

    last = rows[-1]
    keys, invested, routes = _view_pockets(last, view, include_cash)
    # A declared volatility replaces the measured one; the page says which of
    # the two is drawing the band. Same effective number in all three views:
    # the measured value stays the combined-pockets one -- the same money
    # viewed two ways must not draw two different bands.
    vol = plan.vol if plan.vol is not None else stats.get("vol", 0.0)
    vols = {}
    for k in invested:
        own = plan.own_rates(k)
        vols[k] = (vol if own is None
                   else own["vol"] if own["vol"] is not None
                   else measured.get(k) or 0.0)
    split = plans_module.project_pockets(
        projection, invested, routes, plan.rate, plan.rate_segments,
        include_cash=include_cash, schedules=plan.schedules(), vols=vols)
    wealth = plans_module.wealth_from_pockets(projection, split, include_cash)
    wealth["rate"] = plan.rate
    wealth["rated"] = _rated(plan)
    wealth["vol"] = vol
    wealth["vol_source"] = "declared" if plan.vol is not None else "measured"
    # What the pockets measure, said beside a declared one too: the reader
    # deciding to override it sees what they override.
    wealth["vol_measured"] = stats.get("vol")
    wealth["observed"] = observed
    wealth["parts"] = _parts(rows, keys, invested, projection, plan, include_cash, split)
    # Each pocket's barème and band as the rate panel shows them.
    wealth["pockets_rates"] = [_pocket_rates(plan, k, last.get(k) or 0.0, vols.get(k), measured.get(k),
                                             projection)
                               for k in plans_module.POCKET_KEYS if last.get(k) is not None]
    # What the scenario comparison needs to project another plan the same way.
    wealth["pockets_start"], wealth["routes"] = invested, routes
    wealth["include_cash"] = include_cash
    wealth["pocket"] = {"taxable": plans_module.TAXABLE, "sheltered": plans_module.SHELTERED}.get(view)
    return wealth, len(observed)


def _measured_vol(levels: list[float], years: float) -> float | None:
    return analysis.risk_stats(levels, years).get("vol") if len(levels) >= 3 else None


def _rated(plan: plans_module.Plan) -> bool:
    """Whether any growth on the curve is declared: the common barème, or a
    pocket's own non-empty one."""
    return (plan.rate is not None or bool(plan.rate_segments)
            or any(s for s in plan.schedules().values()))


def _pocket_rates(plan: plans_module.Plan, key: str, value: float, vol: float | None,
                  measured: float | None, projection: dict) -> dict:
    """One pocket in the rate panel: its value today, whether it follows the
    common barème, the barème it grows by, per year over the horizon."""
    own = plan.own_rates(key)
    segments = own["rate_segments"] if own is not None else plan.rate_segments
    return {
        "id": key, "label": plans_module.POCKET_LABELS[key], "slot": POCKETS[key][1],
        "value": round(value, 2), "own": own is not None,
        "fixed_by_default": key in plans_module.FIXED_BY_DEFAULT,
        "rate_segments": [[m, r] for m, r in segments],
        "rate_years": plans_module.rate_years(segments, [r["key"] for r in projection["rows"]]),
        "vol": own["vol"] if own is not None else plan.vol,
        "vol_effective": vol, "vol_measured": measured,
        "growth": plans_module.growth_path(segments, projection.get("months") or len(projection["rows"]) or 1),
        "summary": plans_module.scenario_summary(segments, own["vol"] if own is not None else plan.vol),
    }


# The pockets of the net worth, in the slots the savings page gives them --
# a pocket keeps its hue from one page to the other.
POCKETS = {"swiss": ("Comptes", 0), "ibkr": ("IBKR", 2), "finp": ("3a", 3),
           "crypto": ("Crypto", 5), "titres": ("Titres non cotés", 4)}
CLASSES = {"cash": ("Cash", 0), "actions": ("Actions", 2),
           "mf": ("Trend-Following", 3), "crypto": ("Crypto", 5),
           "other": ("Non réparti", None)}
# Which classes each pocket holds, read off the savings page's own split
# (`_evolution_row`): the brokerage's keys, the 3a's, the rest whole.
POCKET_CLASSES = {"ibkr": {"actions": "ibkr_actions", "mf": "ibkr_mf"},
                  "finp": {"cash": "finp_cash", "actions": "finp_actions"}}
VIEW_POCKETS = {"all": ("swiss", "ibkr", "finp", "crypto", "titres"),
                "taxable": ("swiss", "ibkr", "crypto", "titres"), "sheltered": ("finp",)}


def _view_pockets(last: dict, view: str, include_cash: bool):
    """The pockets a view counts (the cash account aside when it holds
    none), the invested ones at today's value, and where a declared transfer
    lands among them."""
    # A pocket not held (no coins yet, no share declared) is left out,
    # unless a declared transfer may land in it.
    keys = [k for k in VIEW_POCKETS[view]
            if (k != "swiss" or include_cash)
            and (k in ("swiss", "ibkr", "finp") or last.get(k) is not None)]
    invested = {k: last.get(k) or 0.0 for k in keys if k != "swiss"}
    routes = {}
    if "ibkr" in keys:
        routes[plans_module.TAXABLE] = "ibkr"
    if "finp" in keys:
        routes[plans_module.SHELTERED] = "finp"
    return keys, invested, routes


def _mix(last: dict, pocket: str) -> dict[str, float]:
    """The share of each asset class in a pocket today."""
    if pocket == "swiss":
        return {"cash": 1.0}
    if pocket == "crypto":
        return {"crypto": 1.0}
    if pocket == "titres":
        return {"actions": 1.0}  # a Swiss company's equity, as on the savings page
    keys = POCKET_CLASSES[pocket]
    amounts = {c: last.get(k) or 0.0 for c, k in keys.items()}
    total = sum(amounts.values())
    if total <= 0:
        return {"other": 1.0}
    return {c: v / total for c, v in amounts.items() if v}


def _parts(rows: list[dict], keys: list[str], invested: dict[str, float], projection: dict,
           plan: plans_module.Plan, include_cash: bool, split: dict) -> dict:
    """The net worth by pocket and by asset class, measured then projected,
    and what each piece brings to the horizon.

    The projection is `split` (`plans.project_pockets`), the curve's own
    arithmetic split by pocket. The classes are the pockets at **today's mix**: the
    plan declares no rebalancing and no return per class, so the brokerage
    keeps its split and new money into it follows that split -- the page
    says it. A pocket worth nothing today that receives a transfer has no
    mix to follow: its money is "Non réparti", not guessed.
    """
    last = rows[-1]
    mixes = {k: _mix(last, k) for k in keys}

    def by_pocket(values: dict[str, float], cash: float | None) -> dict[str, float]:
        out = {k: round(values.get(k, 0.0), 2) for k in keys if k != "swiss"}
        if "swiss" in keys:
            out["swiss"] = round(cash or 0.0, 2)
        return out

    def by_class(pockets: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for pocket, value in pockets.items():
            for cls, share in mixes[pocket].items():
                out[cls] = out.get(cls, 0.0) + value * share
        return {k: round(v, 2) for k, v in out.items()}

    def observed_pockets(r: dict) -> dict[str, float]:
        return {k: round(r.get(k) or 0.0, 2) for k in keys}

    def observed_classes(r: dict) -> dict[str, float]:
        # Measured, not mixed: each month's own split.
        out: dict[str, float] = {}
        for pocket in keys:
            if pocket == "swiss":
                out["cash"] = out.get("cash", 0.0) + (r.get("swiss") or 0.0)
            elif pocket == "crypto":
                out["crypto"] = out.get("crypto", 0.0) + (r.get("crypto") or 0.0)
            elif pocket == "titres":
                out["actions"] = out.get("actions", 0.0) + (r.get("titres") or 0.0)
            else:
                for cls, key in POCKET_CLASSES[pocket].items():
                    out[cls] = out.get(cls, 0.0) + (r.get(key) or 0.0)
        return {k: round(v, 2) for k, v in out.items()}

    projected_pockets = [by_pocket(r["pockets"], r["cash"]) for r in split["rows"]]
    projected_classes = [by_class(p) for p in projected_pockets]
    seen_pockets = [observed_pockets(r) for r in rows]
    seen_classes = [observed_classes(r) for r in rows]

    def series(names: dict, present: list[dict]) -> list[dict]:
        used = {k for point in present for k, v in point.items() if abs(v) >= 0.5}
        return [{"key": k, "name": name, "slot": slot}
                for k, (name, slot) in names.items() if k in used]

    end_cash = projection["rows"][-1]["end"] if projection["rows"] else projection["cash"]
    table = []
    for k in keys:
        name, slot = POCKETS[k]
        if k == "swiss":
            table.append({"key": k, "name": name, "slot": slot,
                          "start": round(projection["cash"], 2),
                          "paid": round(-split["moved"], 2), "growth": 0.0,
                          "end": round(end_cash, 2)})
        elif invested[k] or split["end"].get(k):
            table.append({"key": k, "name": name, "slot": slot,
                          "start": round(invested[k], 2),
                          "paid": split["paid"].get(k, 0.0),
                          "growth": split["growth"].get(k, 0.0),
                          "end": split["end"].get(k, 0.0)})
    flows = [{**f, "label": (f"{f['label']} {POCKETS[f['pocket']][0]}"
                             if f.get("pocket") else f["label"]),
              "slot": POCKETS[f["pocket"]][1] if f.get("pocket") else None}
             for f in split["flows"]]
    return {
        "pockets": {"series": series({k: POCKETS[k] for k in keys}, seen_pockets + projected_pockets),
                    "observed": seen_pockets, "projected": projected_pockets},
        "classes": {"series": series(CLASSES, seen_classes + projected_classes),
                    "observed": seen_classes, "projected": projected_classes},
        "table": table,
        "flows": flows,
        "start": round(sum(t["start"] for t in table), 2),
        "end": round(sum(t["end"] for t in table), 2),
        "moved": split["moved"],
        "rated": _rated(plan),
        "own": sorted(k for k in invested if plan.own_rates(k) is not None),
    }


def _short_month(day: dt.date) -> str:
    """"oct. 25": the measured half's axis labels."""
    return f"{analysis.MONTH_SHORT[day.month - 1]} {day.year % 100:02d}"


def _suggestion_target(rows: list[dict], month: int) -> str | None:
    """The first projected row for a suggestion's calendar month, or None.

    The partial "reste du mois" row is skipped: it is the month that just
    happened, and confirming a "chaque mai" suggestion there would both
    double-charge a bill the ledger already carries and shadow next year's
    occurrence -- the shadow is keyed on the month number, not the year.
    """
    return next((r["key"] for r in rows
                 if plans_module.calendar_month(r["key"]) == month
                 and not r.get("partial")), None)


def _declared_one_offs(plan: plans_module.Plan) -> list[dict]:
    """The declared table's order -- precise day first, then month, then
    label, so the list reads in the order the money leaves. Shared with the
    POST so a failed amount edit re-renders onto the same row."""
    return sorted(plan.one_offs,
                  key=lambda e: (e["month"], e.get("date") or "",
                                 e["label"]))


def _compare(data, plan: plans_module.Plan, horizon: int, wealth: dict) -> list[dict]:
    """Every saved plan, projected over the same horizon and summed up the
    same way: the questions a scenario is for -- how low does the cash go,
    where does it end, how much went to the pockets, what is it all worth.

    The pockets start where they are today and grow at each scenario's own
    barème, in the wealth view on screen. The live plan joins the table
    when it carries no name, so the comparison never hides what is drawn.
    """
    # Creation order, not the alphabet: a scenario's colour must not change
    # because another one was named before it.
    entries = [(name, plan.scenario_plan(name)) for name in plan.plan_scenarios]
    if plan.active is None and not plan.empty:
        entries.append((None, plan))
    rows = []
    for index, (name, scenario) in enumerate(entries):
        projection = plans_module.project(data.statement, scenario, months_ahead=horizon)
        rows_ = projection["rows"]
        final = None
        if wealth:
            split = plans_module.project_pockets(
                projection, wealth["pockets_start"], wealth["routes"], scenario.rate,
                scenario.rate_segments, include_cash=wealth["include_cash"],
                schedules=scenario.schedules())
            final = plans_module.wealth_from_pockets(projection, split, wealth["include_cash"])["final"]
        rows.append({
            "name": name,
            # The plan on screen: the active scenario, or the unnamed live plan.
            "active": name == plan.active,
            "slot": index if index < MAX_SLOTS else None,
            "income": projection["income"],
            "spend": projection["baseline"],
            "spend_source": projection["baseline_source"],
            "low": projection["low"],
            "end": rows_[-1]["end"] if rows_ else projection["cash"],
            "moved": round(sum(o["amount"] for r in rows_ for o in r["one_offs"]
                               if o.get("transfer")), 2),
            "wealth": final["total"] if final else None,
            "rows": rows_,
        })
    # Each card says how it differs from the plan on screen: the comparison
    # is read against what is being edited, not in the abstract.
    shown = next((r for r in rows if r["active"]), None)
    for r in rows:
        if shown is None or r is shown:
            r["delta_low"] = r["delta_wealth"] = None
            continue
        r["delta_low"] = round(r["low"]["amount"] - shown["low"]["amount"], 2)
        r["delta_wealth"] = (round(r["wealth"] - shown["wealth"], 2)
                             if r["wealth"] is not None and shown["wealth"] is not None
                             else None)
    return rows


def _scenario_name(form, errors: dict, values: dict, key: str) -> str | None:
    """A plan scenario's name from the form, or None with the error set."""
    name = (form.get("name") or "").strip()
    values[key] = name
    if not name:
        errors[key] = "Le nom est requis."
    elif len(name) > 60:
        errors[key] = "Le nom est limité à 60 caractères."
    else:
        return name
    return None


def _suggestions(data, plan: plans_module.Plan, projection: dict) -> list[dict]:
    """The seasonal one-offs the history suggests and the plan has not
    decided on yet, each with the projected month it would land in."""
    all_suggestions = plans_module.seasonal_one_offs(data.statement)
    # Per target month, like the projection: last December's confirmation
    # does not confirm this December's bill.
    confirmed_shadows = {(e["seasonal"]["category"], e["seasonal"]["month"], e["month"])
                         for e in plan.one_offs if e.get("seasonal")}
    suggestions = []
    for s in all_suggestions:
        if (s["category"], s["month"]) in plan.ignored:
            continue
        # A short horizon may not reach a suggestion's calendar month: it is
        # skipped, not listed with a target that does not exist.
        target = _suggestion_target(projection["rows"], s["month"])
        if target is None:
            continue
        # An already-confirmed suggestion is not offered again: confirming
        # twice would declare the same bill twice. The same shadowing rules
        # as the projection -- by provenance, or by label in the target
        # month (the renamed confirmation).
        shadowed = ((s["category"], s["month"], target) in confirmed_shadows
                    or s["category"] in {e["label"] for e in plan.one_offs
                                         if e["month"] == target})
        if shadowed:
            continue
        s["target"] = target
        s["month_label"] = plans_module.MONTH_NAMES[s["month"] - 1].capitalize()
        suggestions.append(s)
    return suggestions


def apply_plan_action(plan: plans_module.Plan, form, horizon: int
                      ) -> tuple[dict[str, str], dict, int | None]:
    """One edit to the plan, from a form (or the JSON the new front end
    posts): `(errors, values, applied_months)`. Nothing is saved here -- the
    caller saves when `errors` is empty, and re-renders with the typed
    values otherwise. `/api/previsions` posts every edit through here."""
    action = form.get("action") or ""
    month = (form.get("month") or "").strip()
    label = (form.get("label") or "").strip()
    amount_text = (form.get("amount") or "").strip()
    # A precise day is optional: an entry may still be declared for a month
    # ("the December bill") when the day is not known yet.
    date_text = (form.get("date") or "").strip()

    errors: dict[str, str] = {}
    # The rate edits (`rate`, `rate-years`, `vol`, `scenario-apply`,
    # `scenario-save`) act on one pocket's own barème when `rate_pocket`
    # names one, on the common barème otherwise.
    target = (form.get("rate_pocket") or "").strip()
    if target and target not in plans_module.POCKET_KEYS:
        return {"rate_pocket": "Poche inconnue."}, {}, None
    own = plan.own_rates(target) if target else None
    current_segments = own["rate_segments"] if own is not None else plan.rate_segments
    current_vol = own["vol"] if own is not None else plan.vol

    def put_rates(segments, vol) -> None:
        if target:
            plan.set_pocket_rates(target, segments, vol)
        else:
            plan.set_rates(segments, vol)
    values: dict[str, str] = {}
    # Set by scenario-apply when the scenario carries a horizon: the redirect
    # then sets the view length, or a 15-year scenario would render on a
    # 12-month axis.
    applied_months: int | None = None

    if action == "delete":
        plan.remove_one_off(month, label)
    elif action == "destination":
        plan.set_destination(month, label,
                             (form.get("destination") or "").strip())
    elif action == "amount":
        # The row is addressed by (month, label), the same upsert key as the
        # other edits; the error state is keyed to the row's place in the
        # rendered table so the summary lands on this very input.
        index = next((i for i, e in enumerate(_declared_one_offs(plan), 1)
                      if e["month"] == month and e["label"] == label), None)
        if index is not None:
            values[f"amount-{index}"] = amount_text
            try:
                amount = float(amount_text) if amount_text else 0.0
            except ValueError:
                errors[f"amount-{index}"] = \
                    "Utilisez le point décimal, pas la virgule."
            else:
                if amount <= 0:
                    errors[f"amount-{index}"] = "Montant invalide."
                else:
                    plan.set_amount(month, label, amount)
    elif action == "ignore" or action == "restore":
        category = (form.get("category") or "").strip()
        try:
            month_no = int(form.get("month_no") or 0)
        except ValueError:
            month_no = 0
        if category and 1 <= month_no <= 12:
            if action == "ignore":
                plan.ignore(category, month_no)
            else:
                plan.restore(category, month_no)
    elif action == "income":
        values["plan-income"] = amount_text
        if not amount_text:
            plan.income = None
        else:
            try:
                plan.income = float(amount_text)
            except ValueError:
                errors["plan-income"] = "Utilisez le point décimal, pas la virgule."
    elif action == "spend":
        values["plan-spend"] = amount_text
        if not amount_text:
            plan.spend = None
        else:
            try:
                spend = float(amount_text)
            except ValueError:
                errors["plan-spend"] = "Utilisez le point décimal, pas la virgule."
            else:
                if spend <= 0:
                    errors["plan-spend"] = "Montant invalide."
                else:
                    plan.spend = spend
    elif action == "plan-save-as":
        # A copy of the plan shown, or of another one (`from`): that one is
        # loaded first, the shown one keeping its edits, then copied.
        name = _scenario_name(form, errors, values, "plan-new")
        base = (form.get("from") or "").strip()
        if name and name in plan.plan_scenarios:
            errors["plan-new"] = "Un scénario porte déjà ce nom."
        elif name and base and base != plan.active and base not in plan.plan_scenarios:
            errors["plan-new"] = "Le scénario de départ n'existe plus."
        elif name:
            if base and base != plan.active:
                plan.switch_scenario(base)
            plan.save_scenario_as(name)
    elif action == "plan-switch":
        name = (form.get("name") or "").strip()
        if not plan.switch_scenario(name):
            errors["plan-switch"] = "Scénario inconnu."
    elif action == "plan-rename":
        # The unnamed plan has nothing to rename: naming it is saving it.
        old = (form.get("old") or "").strip()
        name = _scenario_name(form, errors, values, "plan-rename")
        if name and name == old:
            pass
        elif name and name in plan.plan_scenarios:
            errors["plan-rename"] = "Un scénario porte déjà ce nom."
        elif name and not old:
            plan.save_scenario_as(name)
        elif name and not plan.rename_scenario(old, name):
            errors["plan-rename"] = "Scénario inconnu."
    elif action == "plan-delete":
        plan.remove_plan_scenario((form.get("name") or "").strip())
    elif action == "plan-undelete":
        if plan.undelete_scenario() is None:
            errors["plan-undelete"] = "Plus rien à rétablir : un scénario porte déjà ce nom."
    elif action == "rate":
        # One form, two parallel lists: each row posts its duration and its
        # rate, matched by position. The `remove` submit button (only the
        # clicked one is transmitted) drops that row before parsing; a row
        # with both fields blank is the trailing "add" row.
        months_list = form.getlist("months")
        rates_list = form.getlist("rates")
        remove = (form.get("remove") or "").strip()
        if remove:
            try:
                removed = int(remove)
            except ValueError:
                removed = -1
            if 0 <= removed < len(months_list):
                del months_list[removed]
                del rates_list[removed]
        segments, row_errors = plans_module.parse_rate_segments(
            months_list, rates_list)
        for i, message in row_errors.items():
            errors[f"rate-row-{i}"] = message
        values["rate-months"] = months_list
        values["rate-rates"] = rates_list
        if not errors:
            # The declared volatility is kept: editing the barème must not
            # silently clear the vol the user typed.
            put_rates(segments, current_vol)
    elif action == "rate-years":
        # One rate per calendar year of the horizon shown, in order; the
        # years are recomputed here from the same statement and horizon, so
        # a page left open across a new statement is refused, not misread.
        rates_list = form.getlist("rates")
        keys = plans_module.projection_keys(store().statement.period_end, horizon)
        years = plans_module.rate_years(current_segments, keys)
        segments, year_errors = plans_module.segments_from_years(years, rates_list)
        for i, message in year_errors.items():
            errors["rate-years" if i < 0 else f"rate-year-{i}"] = message
        values["rate-years"] = rates_list
        if not errors:
            put_rates(segments, current_vol)
    elif action == "pocket-own":
        # A pocket leaves the common barème with a copy of it, to edit.
        if not target:
            errors["rate_pocket"] = "Choisissez une poche."
        else:
            plan.set_pocket_rates(target, plan.rate_segments, plan.vol)
    elif action == "pocket-common":
        if not target:
            errors["rate_pocket"] = "Choisissez une poche."
        else:
            plan.follow_common(target)
    elif action == "scenario-apply":
        choice = (form.get("scenario") or "").strip()
        applied_months = None
        if not choice:
            errors["scenario-apply"] = "Choisissez un scénario."
        else:
            kind, _, name = choice.partition(":")
            if kind == "builtin" and name in plans_module.BUILTIN_SCENARIOS:
                spec = plans_module.BUILTIN_SCENARIOS[name]
                per_pocket = spec.get("pockets") or {}
                if target and target in per_pocket:
                    put_rates(*per_pocket[target])
                else:
                    put_rates(spec["rate_segments"], spec["vol"])
                    # On the common barème, a scenario per pocket sets every
                    # pocket it names.
                    if not target:
                        for pocket, (segments, pocket_vol) in per_pocket.items():
                            plan.set_pocket_rates(pocket, segments, pocket_vol)
                months = spec.get("months") or 0
                applied_months = months if months >= 1 else None
            elif kind == "saved" and name in plan.scenarios:
                if target:
                    spec = plan.scenarios[name]
                    put_rates(spec["rate_segments"], spec["vol"])
                    months = spec.get("months") or 0
                    applied_months = months if months >= 1 else None
                else:
                    applied_months = plan.apply_scenario(name)
            else:
                errors["scenario-apply"] = "Scénario inconnu."
    elif action == "scenario-save":
        name = (form.get("name") or "").strip()
        values["scenario-name"] = name
        if not name:
            errors["scenario-save"] = "Le nom est requis."
        elif len(name) > 60:
            errors["scenario-save"] = "Le nom est limité à 60 caractères."
        elif ":" in name:
            errors["scenario-save"] = "Le nom ne peut pas contenir « : »."
        else:
            # The snapshot is the *current live* barème -- and the horizon it
            # was read on: tweak, then save under a new name, works naturally.
            plan.set_scenario(name, current_segments, current_vol, horizon)
    elif action == "scenario-delete":
        plan.remove_scenario((form.get("name") or "").strip())
    elif action == "contrib":
        pocket = (form.get("pocket") or "").strip()
        every = (form.get("every") or "").strip()
        start = (form.get("start") or "").strip()
        # The months of the year the series is limited to; none = all year.
        in_months = form.getlist("in_months")
        if form.get("in_months_on") and not any(
                m.strip().isdigit() and 1 <= int(m) <= 12 for m in in_months):
            errors["contrib-in-months"] = "Choisissez au moins un mois."
        values["contrib-amount"] = amount_text
        values["contrib-every"] = every
        values["contrib-months"] = (form.get("months") or "").strip()
        values["contrib-start"] = start
        values["contrib-pocket"] = pocket
        if pocket not in (plans_module.SHELTERED, plans_module.TAXABLE):
            errors["contrib-pocket"] = "Choisissez une poche."
        if every not in plans_module.CONTRIBUTION_EVERY:
            errors["contrib-every"] = "Choisissez une cadence."
        try:
            months = int(form.get("months") or 0)
        except ValueError:
            months = 0
        if months < 1:
            errors["contrib-months"] = "La durée est d'au moins 1 mois."
        if start and not _PLAN_MONTH.match(start):
            errors["contrib-start"] = "Le mois de début est invalide."
        try:
            amount = float(amount_text.replace("'", "").replace(",", ".")) if amount_text else 0.0
        except ValueError:
            errors["contrib-amount"] = "Un montant en francs, par exemple 500."
        else:
            if amount <= 0:
                errors["contrib-amount"] = "Montant invalide."
        # `index` edits that series in place; without it, a new one is added.
        index_text = (form.get("index") or "").strip()
        if not errors:
            if index_text:
                try:
                    index = int(index_text)
                except ValueError:
                    index = -1
                if not plan.replace_contribution(index, pocket, amount, every, months, start,
                                                 in_months):
                    errors["contrib-amount"] = "Cette série n'existe plus : rechargez la page."
            else:
                plan.add_contribution(pocket, amount, every, months, start, in_months)
    elif action == "contrib-del":
        try:
            amount = float(form.get("amount") or 0.0)
        except ValueError:
            amount = -1.0
        try:
            months = int(form.get("months") or 0)
        except ValueError:
            months = -1
        plan.remove_contribution(
            (form.get("pocket") or "").strip(), amount,
            (form.get("every") or "").strip(), months,
            (form.get("start") or "").strip(), form.getlist("in_months"))
    elif action == "vol":
        # Typed as a percentage, stored as a fraction. Blank falls back to the
        # volatility measured on the pockets -- declared 0.0 is a flat band.
        values["plan-vol"] = amount_text
        if not amount_text:
            if target:
                put_rates(current_segments, None)
            else:
                plan.vol = None
        else:
            percent = plans_module.parse_percent(amount_text)
            if percent is None:
                errors["plan-vol"] = "Une volatilité en %, par exemple 15."
            else:
                vol = percent / 100
                if not 0 <= vol <= 1.0:
                    errors["plan-vol"] = "La volatilité est entre 0 % et 100 %."
                elif target:
                    put_rates(current_segments, vol)
                else:
                    plan.vol = vol
    elif action == "add":
        # A date is the sharper declaration and carries its own month, so it
        # wins when both are posted; the month-only path stays for the
        # suggestion forms, which know the month but not the day.
        day = plans_module.parse_day(date_text)
        if day is not None:
            month = plans_module.month_key(day)
        values["oneoff-date"] = date_text
        values["oneoff-month"] = month
        values["oneoff-label"] = label
        values["oneoff-amount"] = amount_text
        if date_text and day is None:
            errors["oneoff-date"] = "La date est invalide."
        elif not _PLAN_MONTH.match(month):
            errors["oneoff-date"] = "La date est requise."
        if not label:
            errors["oneoff-label"] = "Le libellé est requis."
        try:
            amount = float(amount_text) if amount_text else 0.0
        except ValueError:
            errors["oneoff-amount"] = "Utilisez le point décimal, pas la virgule."
        else:
            if amount <= 0:
                errors["oneoff-amount"] = "Montant invalide."
        if not errors:
            seasonal = form.get("seasonal") or ""
            pair = None
            if "|" in seasonal:
                category, month_no = seasonal.split("|", 1)
                try:
                    pair = (category, int(month_no))
                except ValueError:
                    pair = None
            transfer = form.get("destination") or ""
            iso = day.isoformat() if day else ""
            # `was_month`/`was_label` name the entry being edited: replaced
            # where it stands rather than added beside it.
            was = ((form.get("was_month") or "").strip(), (form.get("was_label") or "").strip())
            if all(was):
                if not plan.replace_one_off(was, month, label, amount, transfer=transfer, date=iso):
                    errors["oneoff-label"] = "Ce ponctuel n'existe plus : rechargez la page."
            else:
                plan.add_one_off(month, label, amount, seasonal=pair, transfer=transfer, date=iso)

    return errors, values, applied_months

