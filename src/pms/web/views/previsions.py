"""Cash-flow and wealth projection: `/previsions`, its view switches and
its forms.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from itertools import zip_longest

from flask import redirect, render_template, request, url_for

from ... import analysis
from ... import finpension as finpension_module
from ... import ibkr as ibkr_module
from ... import plans as plans_module
from ...analysis import chf
from .. import charts
from .common import DEFAULT_SCALE, bp, scale_mode, store
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


def _wealth(data, plan: plans_module.Plan, projection: dict) -> tuple[dict, dict]:
    """The net-worth curve: a measured year, then an assumed one.

    The observed half is built by `_evolution_row`, the same function behind
    the dashboard's savings curve, so the two panels can never disagree about
    what the portfolio was worth at a given month end. The volatility handed
    to the projection is measured on the pockets' own monthly history -- the
    band is the account's real past dispersion, not a parameter someone chose.

    Returns `({}, {}, 0)` when there is no brokerage snapshot: without the
    pockets the curve would just be the cash line already above it. The third
    element is the number of observed points, which the page reads back into
    the chart's aria-label.
    """
    ibkr = ibkr_module.load(data.path.with_name("ibkr.json"))
    if not ibkr:
        return {}, {}, 0
    finpension = finpension_module.load(data.path.with_name("finpension.json"))

    end = data.statement.period_end
    low = data.bounds[0]
    start = max(low, plans_module._add_months(end, -WEALTH_LOOKBACK_MONTHS))

    rows = []
    day = start
    while day <= end:
        month_end = analysis.bucket_bounds(day, "month")[1]
        point = min(month_end, end)
        rows.append(_evolution_row(data.statement, ibkr, finpension, point))
        day = month_end + dt.timedelta(days=1)

    # Which parts of the picture the chosen view counts. The measured half and
    # the projected half must slice the same way, or the curve would step at
    # the join for no reason other than the filter.
    view = wealth_mode(request.args)

    def seen(row: dict) -> float:
        if view == "taxable":
            return round(row["swiss"] + (row["ibkr"] or 0.0), 2)
        if view == "sheltered":
            return round(row["finp"] or 0.0, 2)
        return row["total"]

    observed = [{"total": seen(r),
                 "label": charts.month_label(r["date"].strftime("%Y-%m"))}
                for r in rows]

    # The band describes the *invested* pockets only, so the volatility is
    # measured on them alone. Including the Swissquote balance would read a
    # salary landing as portfolio risk.
    invested_levels = [r["ibkr"] + r["finp"] for r in rows
                       if r["ibkr"] is not None and r["finp"] is not None]
    years = max((end - start).days / 365.25, 1 / 12)
    stats = analysis.risk_stats(invested_levels, years) \
        if len(invested_levels) >= 3 else {}

    last = rows[-1]
    if view == "taxable":
        invested = last["ibkr"] or 0.0
        pocket, include_cash = plans_module.TAXABLE, True
    elif view == "sheltered":
        invested = last["finp"] or 0.0
        pocket, include_cash = plans_module.SHELTERED, False
    else:
        invested = (last["ibkr"] or 0.0) + (last["finp"] or 0.0)
        pocket, include_cash = None, True

    # A declared volatility replaces the measured one; the page says which of
    # the two is drawing the band. Same effective number in all three views:
    # the measured value stays the combined-pockets one -- the same money
    # viewed two ways must not draw two different bands.
    vol = plan.vol if plan.vol is not None else stats.get("vol", 0.0)
    wealth = plans_module.project_wealth(
        projection, invested, plan.rate, vol,
        pocket=pocket, include_cash=include_cash,
        rate_schedule=plan.rate_segments)
    wealth["vol_source"] = "declared" if plan.vol is not None else "measured"
    return wealth, charts.wealth_chart(
        observed, wealth, scale_mode(request.args),
        yscale_mode(request.args)), len(observed)


def _previsions_url(**overrides) -> str:
    """The previsions page keeping the view options that are on screen.

    The forms post to this URL and the redirect comes back to it, so editing
    the plan leaves the reader where they were instead of snapping back to the
    default view. Only the display keys ride along -- the same rule as
    `dash_url`, for the same reason. An override wins over what is on screen,
    which is what makes the view buttons themselves: they are this URL with
    one key changed, and the default key is dropped rather than spelled out.
    """
    params = {}
    view = overrides.pop("wealth", wealth_mode(request.args))
    if view and view != DEFAULT_WEALTH_VIEW:
        params["wealth"] = view
    scale = overrides.pop("scale", scale_mode(request.args))
    if scale and scale != DEFAULT_SCALE:
        params["scale"] = scale
    months = overrides.pop("months", months_ahead(request.args))
    if months and months != DEFAULT_MONTHS:
        params["months"] = months
    yscale = overrides.pop("yscale", yscale_mode(request.args))
    if yscale and yscale != DEFAULT_YSCALE:
        params["yscale"] = yscale
    params.update(overrides)
    return url_for("dashboard.previsions", **params)


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


def _month_groups(rows: list[dict], wealth_rows: list[dict]) -> list[dict]:
    """The "Mois par mois" table folded by year, and by decade when the
    horizon spans many years -- a 40-year projection would otherwise mean
    endless scrolling. Each month row carries its wealth partner attached,
    so the pairing is by construction, never by index. Years beyond the
    first start collapsed; the near term stays in view.
    """
    # zip_longest: without a brokerage snapshot the wealth partner is None
    # and the month rows still render.
    months = [dict(r, wealth=w) for r, w in zip_longest(rows, wealth_rows)]
    years: list[dict] = []
    for m in months:
        year = m["key"][:4]
        if not years or years[-1]["year"] != year:
            years.append({"year": year, "label": year, "rows": [],
                          "open": not years})
        years[-1]["rows"].append(m)
    for y in years:
        y["income"] = round(sum(r["income"] for r in y["rows"]), 2)
        y["spend"] = round(sum(r["spend"] for r in y["rows"]), 2)
        y["start"] = y["rows"][0]["start"]
        y["end"] = y["rows"][-1]["end"]
        # Per kind, so the summary never calls a programmed series a
        # "ponctuel": the chip vocabulary is the summary's vocabulary.
        y["kinds"] = Counter(o["source"] for r in y["rows"]
                             for o in r["one_offs"])
    if len(years) <= 4:
        return years
    decades: list[dict] = []
    for y in years:
        decade = y["year"][:3] + "0"
        if not decades or decades[-1]["decade"] != decade:
            decades.append({"decade": decade, "label": f"Années {decade}",
                            "years": [], "open": not decades})
        decades[-1]["years"].append(y)
    for d in decades:
        d["income"] = round(sum(y["income"] for y in d["years"]), 2)
        d["spend"] = round(sum(y["spend"] for y in d["years"]), 2)
        d["start"] = d["years"][0]["start"]
        d["end"] = d["years"][-1]["end"]
        d["kinds"] = sum((y["kinds"] for y in d["years"]), Counter())
    return decades


def _rate_rows(plan: plans_module.Plan, form_values) -> list[dict]:
    """The rate schedule table's rows, with one trailing blank "add" row.

    A failed POST carries its typed arrays here -- the re-render must show
    what was typed, not what the plan holds. Otherwise the plan's own
    segments, in percent for the form.
    """
    if form_values and form_values.get("rate-months"):
        months = list(form_values["rate-months"])
        rates = list(form_values["rate-rates"])
        # The form always posts its trailing blank "add" row; a failed POST
        # must not grow the table by one row per attempt.
        while (months and rates
               and not (months[-1] or "").strip()
               and not (rates[-1] or "").strip()):
            months.pop()
            rates.pop()
    else:
        months = [str(m) for m, _ in plan.rate_segments]
        rates = [str(round(r * 100, 1)) for _, r in plan.rate_segments]
    rows = [{"months": m, "percent": r, "index": i}
            for i, (m, r) in enumerate(zip(months, rates))]
    rows.append({"months": "", "percent": "", "index": len(rows)})
    return rows


def _plans_page(form_errors=None, form_values=None):
    data = store()
    plan = _plan()
    horizon = months_ahead(request.args)
    projection = plans_module.project(data.statement, plan,
                                      months_ahead=horizon)

    all_suggestions = plans_module.seasonal_one_offs(data.statement)
    confirmed_shadows = {(e["seasonal"]["category"], e["seasonal"]["month"])
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
        shadowed = ((s["category"], s["month"]) in confirmed_shadows
                    or s["category"] in {e["label"] for e in plan.one_offs
                                         if e["month"] == target})
        if shadowed:
            continue
        s["target"] = target
        s["month_label"] = plans_module.MONTH_NAMES[s["month"] - 1].capitalize()
        suggestions.append(s)

    ignored = [{"category": c, "month": m,
                "label": plans_module.MONTH_NAMES[m - 1].capitalize()}
               for c, m in plan.ignored]

    chart = charts.projection_chart(projection)
    wealth, wealth_chart, wealth_observed = _wealth(data, plan, projection)

    # The baseline's own arithmetic, month by calendar month: how the KPI's
    # "dépense mensuelle de base" is made up. Two observed calendar months
    # are the least it can say anything about, like the monthly panel.
    m_profile = plans_module.monthly_profile(data.statement)
    monthly_analysis = (charts.monthly_season_chart(
        m_profile, projection["baseline"]) if len(m_profile) >= 2 else {})

    crosshair_payload = {}
    if chart.get("series"):
        crosshair_payload["projection"] = {"series": chart["series"],
                                           "geom": chart["geom"],
                                           "labels": chart["labels"]}
    if wealth_chart.get("series"):
        crosshair_payload["wealth"] = {"series": wealth_chart["series"],
                                       "geom": wealth_chart["geom"],
                                       "labels": wealth_chart["labels"]}
    if monthly_analysis.get("series"):
        crosshair_payload["monthly"] = {"series": monthly_analysis["series"],
                                        "geom": monthly_analysis["geom"],
                                        "labels": monthly_analysis["labels"]}

    context = dict(
        chart_data_json=json.dumps(crosshair_payload, separators=(",", ":")),
        projection=projection,
        chart=chart,
        monthly_analysis=monthly_analysis,
        monthly_profile=m_profile if monthly_analysis else [],
        wealth=wealth,
        wealth_chart=wealth_chart,
        wealth_view=wealth_mode(request.args),
        wealth_observed=wealth_observed,
        plan_action=_previsions_url(),
        wealth_views=[{"id": key, "label": spec["label"], "aria": spec["aria"],
                       "note": spec["note"],
                       # Built here rather than in the template: the link has to
                       # drop the key when it is the default and keep the scale
                       # and the horizon, and Jinja cannot spread two mappings
                       # into one call.
                       "url": _previsions_url(wealth=key),
                       "active": key == wealth_mode(request.args)}
                      for key, spec in WEALTH_VIEWS.items()],
        scale=scale_mode(request.args),
        months=horizon,
        horizon_presets=HORIZON_PRESETS,
        months_label=months_label,
        # The horizon GET form must not carry a months key of its own -- the
        # select's value is the only one that should reach the server.
        horizon_action=_previsions_url(months=None),
        yscale=yscale_mode(request.args),
        yscale_options=[{"id": key, "label": label,
                         "url": _previsions_url(yscale=key),
                         "active": key == yscale_mode(request.args)}
                        for key, label in YSCALES.items()],
        # The month table, folded by year (and decade on long horizons), each
        # month row carrying its wealth partner.
        month_groups=_month_groups(projection["rows"],
                                   wealth.get("rows", []) if wealth else []),
        builtin_scenarios=[{"key": key, "label": spec["label"]}
                           for key, spec in
                           plans_module.BUILTIN_SCENARIOS.items()],
        saved_scenarios=[{"name": name,
                          "summary": plans_module.scenario_summary(
                              s["rate_segments"], s["vol"], s.get("months", 0))}
                         for name, s in sorted(plan.scenarios.items(),
                                               key=lambda kv: kv[0].casefold())],
        contributions=[{
            "amount": c["amount"], "every": c["every"],
            "every_label": plans_module.CONTRIBUTION_LABELS[c["every"]],
            "months": c["months"],
            "start": c["start"],
            "start_label": (plans_module.month_label(c["start"])
                            if c["start"] else "le mois prochain"),
            "pocket": c["pocket"],
            "pocket_label": ("le 3a" if c["pocket"] == plans_module.SHELTERED
                             else "le placement"),
        } for c in plan.contributions],
        pockets=[{"id": plans_module.SHELTERED, "label": "le 3a"},
                 {"id": plans_module.TAXABLE, "label": "le placement"}],
        every_options=[{"id": key, "label": label}
                       for key, label in
                       plans_module.CONTRIBUTION_LABELS.items()],
        every_labels=plans_module.CONTRIBUTION_LABELS,
        # The page's own sections, for the left rail. The wealth card is
        # absent without a brokerage snapshot, and so is its entry -- a
        # sommaire link to nothing is worse than no link.
        toc=[{"id": "p-projection", "label": "Solde projeté"}]
        + ([{"id": "p-wealth", "label": "Patrimoine"}] if wealth_chart else [])
        + [{"id": "p-forecast", "label": "Mois par mois"}]
        + ([{"id": "p-analysis", "label": "Analyse mensuelle"}]
           if monthly_analysis else [])
        + [{"id": "p-plan", "label": "Le plan"}],
        rate_rows=_rate_rows(plan, form_values),
        # The barème fold reopens when a rate or vol POST failed -- the error
        # must not sit inside a closed details block.
        rate_form_open=any(k.startswith("rate-row-") or k == "plan-vol"
                           for k in (form_errors or {})),
        vol_declared=plan.vol,
        destinations=[{"id": key, "label": plans_module.DESTINATION_LABELS[key]}
                      for key in plans_module.DESTINATIONS],
        declared=_declared_one_offs(plan),
        suggestions=suggestions,
        ignored=ignored,
        income_declared=plan.income,
        as_of=data.statement.period_end,
        form_errors=form_errors or {},
        form_values=form_values or {},
        kpis=[
            {"label": "Cash aujourd'hui", "value": chf(projection["cash"], 0),
             "note": f"solde CHF au {data.statement.period_end.strftime('%d.%m.%Y')}"},
            {"label": "Revenu mensuel", "value": chf(projection["income"], 0),
             "note": ("déclaré dans le plan" if plan.income is not None
                      else "médiane de l'historique")},
            {"label": "Dépense mensuelle de base", "value": chf(projection["baseline"], 0),
             "note": "hors ponctuels — médiane des mois, pics saisonniers retirés"},
            {"label": "Solde le plus bas prévu", "value": chf(projection["low"]["amount"], 0),
             "note": (f"en {projection['low']['label']}"
                      if projection["low"]["key"] else
                      "aujourd'hui — le solde ne descend jamais sous ce niveau"),
             "positive": projection["low"]["amount"] >= 0},
        ],
    )
    # The fragment is <main>'s content alone -- the swap replaces <main>'s
    # innerHTML in place, exactly like the dashboard's. Same context dict,
    # so the two renders cannot drift: the parity test locks it.
    template = ("partials/previsions_main.html.j2"
                if request.args.get("fragment") else "previsions.html.j2")
    return render_template(template, **context)


def _plans_post():
    """The no-JavaScript path: the page's forms submit here, then redirect.

    Every action is a small edit to data/plans.json. A value that refuses to
    parse used to be skipped -- the page simply did not change, and the user
    typed the same thing again. Now the POST re-renders the page with the
    error stated and the typed value kept, so the field says what it wanted
    instead of swallowing the keystrokes. The app keeps no session, so the
    error state is carried in the re-render, never in a flash.
    """
    plan = _plan()
    action = request.form.get("action") or ""
    month = (request.form.get("month") or "").strip()
    label = (request.form.get("label") or "").strip()
    amount_text = (request.form.get("amount") or "").strip()
    # A precise day is optional: an entry may still be declared for a month
    # ("the December bill") when the day is not known yet.
    date_text = (request.form.get("date") or "").strip()

    errors: dict[str, str] = {}
    values: dict[str, str] = {}
    # Set by scenario-apply when the scenario carries a horizon: the redirect
    # then sets the view length, or a 15-year scenario would render on a
    # 12-month axis.
    applied_months: int | None = None

    if action == "delete":
        plan.remove_one_off(month, label)
    elif action == "destination":
        plan.set_destination(month, label,
                             (request.form.get("destination") or "").strip())
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
        category = (request.form.get("category") or "").strip()
        try:
            month_no = int(request.form.get("month_no") or 0)
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
    elif action == "rate":
        # One form, two parallel lists: each row posts its duration and its
        # rate, matched by position. The `remove` submit button (only the
        # clicked one is transmitted) drops that row before parsing; a row
        # with both fields blank is the trailing "add" row.
        months_list = request.form.getlist("months")
        rates_list = request.form.getlist("rates")
        remove = (request.form.get("remove") or "").strip()
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
            # set_rates keeps the declared volatility: editing the barème
            # must not silently clear the vol the user typed.
            plan.set_rates(segments, plan.vol)
    elif action == "scenario-apply":
        choice = (request.form.get("scenario") or "").strip()
        applied_months = None
        if not choice:
            errors["scenario-apply"] = "Choisissez un scénario."
        else:
            kind, _, name = choice.partition(":")
            if kind == "builtin" and name in plans_module.BUILTIN_SCENARIOS:
                spec = plans_module.BUILTIN_SCENARIOS[name]
                plan.set_rates(spec["rate_segments"], spec["vol"])
                months = spec.get("months") or 0
                applied_months = months if months >= 1 else None
            elif kind == "saved" and name in plan.scenarios:
                applied_months = plan.apply_scenario(name)
            else:
                errors["scenario-apply"] = "Scénario inconnu."
    elif action == "scenario-save":
        name = (request.form.get("name") or "").strip()
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
            plan.set_scenario(name, plan.rate_segments, plan.vol,
                              months_ahead(request.args))
    elif action == "scenario-delete":
        plan.remove_scenario((request.form.get("name") or "").strip())
    elif action == "contrib":
        pocket = (request.form.get("pocket") or "").strip()
        every = (request.form.get("every") or "").strip()
        start = (request.form.get("start") or "").strip()
        values["contrib-amount"] = amount_text
        values["contrib-every"] = every
        values["contrib-months"] = (request.form.get("months") or "").strip()
        values["contrib-start"] = start
        values["contrib-pocket"] = pocket
        if pocket not in (plans_module.SHELTERED, plans_module.TAXABLE):
            errors["contrib-pocket"] = "Choisissez une poche."
        if every not in plans_module.CONTRIBUTION_EVERY:
            errors["contrib-every"] = "Choisissez une cadence."
        try:
            months = int(request.form.get("months") or 0)
        except ValueError:
            months = 0
        if months < 1:
            errors["contrib-months"] = "La durée est d'au moins 1 mois."
        if start and not _PLAN_MONTH.match(start):
            errors["contrib-start"] = "Le mois de début est invalide."
        try:
            amount = float(amount_text) if amount_text else 0.0
        except ValueError:
            errors["contrib-amount"] = "Utilisez le point décimal, pas la virgule."
        else:
            if amount <= 0:
                errors["contrib-amount"] = "Montant invalide."
        if not errors:
            plan.add_contribution(pocket, amount, every, months, start)
    elif action == "contrib-del":
        try:
            amount = float(request.form.get("amount") or 0.0)
        except ValueError:
            amount = -1.0
        try:
            months = int(request.form.get("months") or 0)
        except ValueError:
            months = -1
        plan.remove_contribution(
            (request.form.get("pocket") or "").strip(), amount,
            (request.form.get("every") or "").strip(), months,
            (request.form.get("start") or "").strip())
    elif action == "vol":
        # Typed as a percentage, stored as a fraction. Blank falls back to the
        # volatility measured on the pockets -- declared 0.0 is a flat band.
        values["plan-vol"] = amount_text
        if not amount_text:
            plan.vol = None
        else:
            try:
                vol = float(amount_text) / 100
            except ValueError:
                errors["plan-vol"] = "Utilisez le point décimal, pas la virgule."
            else:
                if not 0 <= vol <= 1.0:
                    errors["plan-vol"] = "La volatilité est entre 0 % et 100 %."
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
            seasonal = request.form.get("seasonal") or ""
            pair = None
            if "|" in seasonal:
                category, month_no = seasonal.split("|", 1)
                try:
                    pair = (category, int(month_no))
                except ValueError:
                    pair = None
            plan.add_one_off(month, label, amount, seasonal=pair,
                             transfer=(request.form.get("destination") or ""),
                             date=day.isoformat() if day else "")

    if errors:
        return _plans_page(form_errors=errors, form_values=values)
    plan.save()
    if applied_months:
        return redirect(_previsions_url(months=applied_months))
    return redirect(_previsions_url())


@bp.route("/previsions", methods=["GET", "POST"])
def previsions():
    """Is there enough cash at time t? Month by month, 12 months ahead.

    The GET renders the forecast: starting cash (the CHF closing balance),
    monthly income, the usual month, and the one-offs -- declared in
    data/plans.json, or suggested by the history's own seasonal patterns.
    The POST is the no-JavaScript path for editing that plan.
    """
    if request.method == "POST":
        return _plans_post()
    return _plans_page()
