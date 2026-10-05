"""The dashboard: one window, every panel, and the budget form that lives
in its monthly panel.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from urllib.parse import parse_qsl, urlsplit

from flask import Response, abort, redirect, render_template, request, url_for
from werkzeug.datastructures import ImmutableMultiDict

from ... import analysis, buckets
from ... import budgets as budgets_module
from ... import finpension as finpension_module
from ... import ibkr as ibkr_module
from ... import plans as plans_module
from ... import review as review_module
from ...analysis import chf
from ...categories import UNCATEGORISED
from .. import charts, periods
from .. import news as news_module
from .common import (
    BUCKET_FILL,
    COMPACT_PAGE_SIZE,
    PERFS,
    SCALES,
    SPLITS,
    STACKS,
    bp,
    focus_mode,
    perf_mode,
    scale_mode,
    shares_mode,
    smooth_mode,
    split_mode,
    stack_mode,
    store,
)
from .savings import (
    POCKETS,
    SavingsBook,
    _attribution,
    _benchmark_return,
    _benchmarks,
    _evolution_rows,
    _level,
    _fees,
    _indexed_rows,
    _mwr_rows,
    _pocket_rows,
    _risk_table,
    _savings_parts,
    _split_series,
    _stale_notes,
)
from .transactions import _transactions


def _delta(current: float, previous: float) -> dict | None:
    """Signed change against the comparison window, as a share."""
    if not previous:
        return None
    change = (current - previous) / previous * 100
    return {"pct": change, "up": change > 0, "previous": previous}


def _kpis(window, previous) -> list[dict]:
    spending_rows = analysis.spending(window)
    spend = sum(abs(t.amount_chf) for t in spending_rows)
    earn = sum(t.amount_chf for t in analysis.income(window))
    prev_spend = sum(abs(t.amount_chf) for t in analysis.spending(previous))
    prev_earn = sum(t.amount_chf for t in analysis.income(previous))

    days = max((window.period_end - window.period_start).days + 1, 1)
    prev_days = max((previous.period_end - previous.period_start).days + 1, 1)

    closing = next((a.closing_balance for a in window.accounts
                    if a.currency == "CHF"), 0.0)

    return [
        {"label": "Dépensé", "value": chf(spend, 0), "unit": "CHF",
         "delta": _delta(spend, prev_spend), "good_when_down": True},
        {"label": "Encaissé", "value": chf(earn, 0), "unit": "CHF",
         "delta": _delta(earn, prev_earn), "good_when_down": False},
        {"label": "Net", "value": ("+" if earn - spend >= 0 else "") + chf(earn - spend, 0),
         "unit": "CHF", "delta": None, "good_when_down": False,
         "positive": earn - spend >= 0},
        {"label": "Par jour", "value": chf(spend / days, 0), "unit": "CHF",
         "delta": _delta(spend / days, prev_spend / prev_days), "good_when_down": True,
         # The mean is dragged up by rent and tax days; the median says what an
         # ordinary day costs. Showing only one of them tells half the story.
         "note": "médiane " + chf(
             analysis.median_daily(spending_rows, window.period_start,
                                   window.period_end), 0) + " CHF"},
        {"label": "Solde en fin de période", "value": chf(closing, 0), "unit": "CHF",
         "delta": None, "good_when_down": False},
    ]


def _controls_context(args) -> dict:
    """What the period controls need: the window, its neighbours, the grain
    and stack switches. No aggregation -- so a swap can refresh the controls
    without paying for a whole dashboard a second time."""
    low, high = store().bounds
    period = periods.resolve(args, low, high)
    return {
        "period": period,
        "neighbours": periods.neighbours(period["start"], period["end"],
                                         low, high),
        "bounds": {"low": low, "high": high},
        "stack": stack_mode(args),
        "grains": [{"id": g, "label": analysis.GRAIN_LABELS[g],
                    "active": g == period["grain"]}
                   for g in analysis.GRAINS],
    }


def _context(args, form_errors=None, form_values=None) -> dict:
    """The dashboard, window and all. `form_errors` / `form_values` carry a
    form that failed validation: the error summary and the per-field state
    (red border, message, kept value) are rendered from them, so a failed
    POST re-renders the same page instead of flashing and forgetting."""
    data = store()
    low, high = data.bounds
    controls = _controls_context(args)
    period = controls["period"]

    window = data.window(period["start"], period["end"])
    prev_start, prev_end = analysis.previous_window(period["start"], period["end"])
    previous = data.window(prev_start, prev_end)

    spend = analysis.spending(window)
    categories = analysis.by_category(spend)
    slots, legend = charts.colour_map(categories)
    for row in categories:
        row["slot"] = slots.get(row["category"], slots[charts.OTHER])

    rows = analysis.timeseries(window, period["grain"],
                               period["start"], period["end"])
    drill, drill_hint = charts.drill_target(rows, period["grain"])

    # Panels that need a minimum span to say anything. Showing a "seasonality"
    # chart for a three-week window would be noise dressed as a finding, so each
    # one declares the window it needs and is simply absent otherwise.
    days = period["days"]
    years_spanned = period["end"].year - period["start"].year + 1
    custodian = analysis.custodian_costs(window)
    fixed = analysis.fixed_vs_variable(window) if days >= 60 else None
    # Same window as the commitments themselves: the reference date is the end
    # of what is on screen, so the panel answers "as of the period shown", not
    # "as of some other date the page never mentions".
    missing = analysis.missing_commitments(window) if days >= 60 else []
    geo = analysis.by_country(spend)
    daily = analysis.daily_totals(spend)

    # Who was paying, and when that changed. One payer says nothing a KPI does
    # not already say, so the panel needs at least two.
    sources = analysis.income_sources(window)
    named, tail = sources[:analysis.INCOME_SLOTS], sources[analysis.INCOME_SLOTS:]
    income_fills = {row["label"]: f"var(--s{i})" for i, row in enumerate(named)}
    income_fills[analysis.OTHER] = f"var(--s{analysis.INCOME_SLOTS})"
    income_rows = (analysis.income_timeline(window, period["grain"],
                                            period["start"], period["end"])
                   if len(sources) >= 2 and days >= 90 else [])

    # The table mirrors the band rather than listing all 22 counterparties: past
    # the named payers it is refunds and the odd reimbursement, and twenty rows
    # of noise would bury the four that tell the story. The folded row still
    # says how many and how much, so nothing is hidden -- only summarised.
    income_table = [{**row, "fill": income_fills[row["label"]]} for row in named]
    if tail:
        income_table.append({
            "label": f"{analysis.OTHER} ({len(tail)} payeurs)",
            "fill": income_fills[analysis.OTHER],
            "amount": sum(r["amount"] for r in tail),
            "share": sum(r["share"] for r in tail),
            "count": sum(r["count"] for r in tail),
            "first": min(r["first"] for r in tail),
            "last": max(r["last"] for r in tail),
            "folded": True,
        })

    panels = {
        "balance": bool(window.transactions),
        "highlights": days >= 14 and len(spend) >= 10,
        "fixed": fixed is not None and len(fixed["months"]) >= 2,
        "missing": bool(missing),
        "income": bool(income_rows),
        "calendar": days >= 45,
        "years": years_spanned >= 2,
        "season": days >= 300,
        "country": bool(geo["rows"]),
        "custodian": custodian["count"] > 0,
    }

    # The brokerage snapshot is read fresh on every request, like the plan.
    # The panel answers "what was my savings worth at the end of the period
    # on screen": the Swissquote balance as of the window's end, the
    # brokerage NAV as of the same date (the snapshot's last point when the
    # window reaches the present), and whatever is declared (the 3a, later).
    ibkr = ibkr_module.load(data.path.with_name("ibkr.json"))
    finpension = finpension_module.load(data.path.with_name("finpension.json"))
    panels["ibkr"] = bool(ibkr)
    ibkr_chart = {}
    if ibkr:
        ibkr["flows"] = ibkr_module.flows(ibkr, data.statement.transactions)
        start, end = period["start"], period["end"]
        # One book for the whole section: every value and every franc that
        # moved, by day -- the headline, the pocket table, the curve and the
        # risk table all read it, so none of them can disagree on a deposit.
        book = SavingsBook(data.statement, ibkr, finpension)
        values = {pocket: book.value(pocket, end) for pocket in POCKETS}
        swiss_at_end, nav_at_end = values["swissquote"], values["ibkr"]
        finp_value = values["finpension"]
        ibkr["swissquote_chf"] = round(swiss_at_end, 2)
        ibkr["nav_chf"] = round(nav_at_end, 2)
        ibkr["finpension"] = finpension
        ibkr["finp_chf"] = round(finp_value, 2)
        ibkr["finp_as_of"] = (periods.parse_date(finpension.get("value_as_of"))
                              if finpension else None)
        ibkr["captured_on"] = periods.parse_date((ibkr.get("captured_at") or "")[:10])
        ibkr["total"] = round(values["total"]
                              + sum(a["value"] for a in ibkr["other_accounts"]), 2)
        ibkr["stale"] = _stale_notes(ibkr, finpension, end)
        focus = focus_mode(args)
        ibkr["focus"] = focus
        ibkr["perf"] = perf_mode(args)
        ibkr["parts"] = _savings_parts(ibkr, swiss_at_end, finpension,
                                       finp_value, split_mode(args), focus)
        fees = _fees(custodian["total_chf"], custodian["count"], ibkr,
                     finpension, values, start, end)
        ibkr["fees"] = fees
        ibkr["pockets"] = _pocket_rows(book, fees, start, end)
        ibkr["hero"] = next(r for r in ibkr["pockets"] if r["pocket"] == focus)
        benchmarks = _benchmarks(ibkr, finpension)
        ibkr["risk"] = _risk_table(book, start, end, benchmarks)
        ibkr["attribution"] = _attribution(ibkr, book, start, end)
        # The headline's comparison: each index over the same window.
        ibkr["bench"] = []
        for name, series in benchmarks.items():
            rate, first = _benchmark_return(series, start, end)
            if rate is not None:
                ibkr["bench"].append({"name": name, "rate": rate,
                                      "since": first if first > start else None})

        ibkr["evolution"] = _evolution_rows(data.statement, ibkr, finpension,
                                            start, end, period["grain"])
        spec = _split_series(split_mode(args), finpension, focus)
        plotted = ibkr["evolution"]
        if scale_mode(args) == "index":
            # Base 100: sizes give way to performance, deposits taken out --
            # a 10'000 CHF brokerage and a 40'000 CHF current account on one
            # axis said nothing about which one did better. The TWR/MWR
            # switch picks which performance; in francs it has nothing to
            # change, a value is a value.
            # The reference indices ride along, dashed: an index has no
            # flows, so TWR and MWR rebase it the same way.
            plotted = [dict(row) for row in plotted]
            # Only next to the accounts: a breakdown view uses every hue
            # already, and its parts are not investments to compare.
            compared = benchmarks if split_mode(args) == "account" else {}
            for i, (name, series) in enumerate(compared.items()):
                key = f"bench_{i}"
                for row in plotted:
                    row[key] = _level(series, row["date"]) \
                        if series[0][0] <= row["date"] else None
                spec = [*spec, {"key": key, "name": name, "dash": True,
                                "slot": (6, 4, 7, 5)[i % 4]}]
            rebase = _mwr_rows if perf_mode(args) == "mwr" else _indexed_rows
            plotted = rebase(plotted, [s["key"] for s in spec], book)
        ibkr_chart = charts.evolution_chart(plotted, scale_mode(args), focus,
                                            spec)

    # Months × categories, as bars: one row per category, one little bar per
    # month. A table of numbers is not how you find out "how much goes to
    # food this month" at a glance; a row of bars is. Two whole months are
    # the least it can say anything about.
    m_rows = analysis.monthly(window)
    panels["monthly"] = len(m_rows) >= 2
    monthly_keys = [r["month"] for r in m_rows]
    # One hue per category, folded past the validated eight -- same rule as
    # the timeline, so the 8th category keeps its hue there too.
    m_slots = [c["category"] for c in categories][:charts.MAX_SLOTS - 1]

    def _month_bars(values: list[float]) -> list[dict]:
        peak = max(values) or 0.0
        return [{
            "key": key,
            "label": plans_module.month_label(key),
            "amount": round(v, 2),
            # Scaled to the category's own busiest month: the point is the
            # shape of the year (the December spike), not comparing heights
            # across categories.
            "h": round(100 * v / peak, 1) if peak else 0.0,
        } for key, v in zip(monthly_keys, values)]

    monthly = []
    for name in m_slots:
        values = [row["categories"].get(name, 0.0) for row in m_rows]
        monthly.append({
            "name": name,
            "slot": next(c["slot"] for c in categories
                         if c["category"] == name),
            "total": round(sum(values), 2),
            "median": round(statistics.median(values), 2),
            "bars": _month_bars(values),
        })
    others = [sum(v for c, v in row["categories"].items()
                  if c not in m_slots) for row in m_rows]
    if sum(others):
        monthly.append({
            "name": charts.OTHER,
            "slot": len(m_slots),
            "total": round(sum(others), 2),
            "median": round(statistics.median(others), 2),
            "bars": _month_bars(others),
        })

    # What changed this month -- only when the window is one calendar month,
    # the month in progress included: elsewhere "this month" has no meaning.
    start, end = period["start"], period["end"]
    month_end = analysis.bucket_bounds(start, "month")[1]
    one_month = start.day == 1 and (end == month_end
                                    or (end == high and end < month_end))
    review = (review_module.month_review(data.statement, start, end)
              if one_month else None)
    panels["review"] = review is not None

    # A statement that just arrived: said until its month is on screen.
    fresh = news_module.news(data.sources, high)
    if fresh and (fresh["start"], fresh["end"]) == (start, end):
        fresh = None

    # The bucket bar over time, unfolded on demand. Read from the whole
    # ledger, so a rolling sum can reach back before the window; whole
    # months only, so it needs two of them inside the window.
    share_base = shares_mode(args)
    smooth = smooth_mode(args)
    base = share_base or buckets.DEFAULT_SHARE_BASE
    share_rows = buckets.shares_by_month(data.statement, period["start"],
                                         period["end"], base, smooth)
    shares_chart = (charts.shares_chart(share_rows, buckets.share_names(base),
                                        BUCKET_FILL, base, smooth,
                                        buckets.TARGET)
                    if len(share_rows) >= 2 else {})
    panels["shares"] = bool(shares_chart.get("lines"))
    shares = {
        "open": share_base is not None,
        "base": base, "smooth": smooth, "rows": share_rows,
        "names": [line["name"] for line in shares_chart.get("lines", [])],
        "bases": [{"id": key, "label": label.capitalize(), "active": key == base}
                  for key, label in buckets.SHARE_BASES.items()],
        "smoothings": [{"months": m, "label": "Brut" if m == 1 else f"{m} mois",
                        "active": m == smooth} for m in buckets.SMOOTHING],
    }

    # Declared monthly goals, read against each row's median month.
    budgets = budgets_module.Budgets.load(data.path.with_name("budgets.json"))
    for row in monthly:
        budget = budgets.amounts.get(row["name"])
        row["budget"] = budget
        row["gauge_pct"] = (round(row["median"] / budget * 100, 1)
                            if budget else None)

    # The right rail mirrors the page: same gates as the panels, so a link
    # never points at a section that is absent.
    # G64: the Sommaire links mirror the headings they jump to, so a user who
    # follows one lands exactly where it was announced. The rail truncates
    # visually (ellipsis) but the accessible name stays the full heading.
    toc = [
        ("p-review", "Revue du mois"),
        ("p-shares", "Évolution des parts"),
        ("p-balance", "Évolution du solde"),
        ("p-ibkr", "Épargne"),
        ("p-highlights", "Faits marquants"),
        ("p-income", "D'où vient l'argent"),
        ("p-missing", "Engagements sans passage récent"),
        ("p-fixed", "Socle contraint et dépenses choisies"),
        ("p-monthly", "Dépenses par mois"),
        ("p-calendar", "Calendrier des dépenses"),
        ("p-years", "Cumul des dépenses"),
        ("p-profiles", "Par jour de semaine"),
        ("p-country", "Dépenses par carte, par pays"),
        ("p-custodian", "Ce que le custodian a prélevé"),
        ("txPanel", "Transactions"),
    ]
    shown = {"p-review": panels["review"], "p-shares": panels["shares"],
             "p-balance": panels["balance"], "p-ibkr": bool(ibkr),
             "p-highlights": panels["highlights"],
             "p-income": panels["income"], "p-missing": panels["missing"],
             "p-fixed": panels["fixed"], "p-monthly": panels["monthly"],
             "p-calendar": panels["calendar"], "p-years": panels["years"],
             "p-profiles": True,
             "p-country": panels["season"] and panels["country"],
             "p-custodian": panels["custodian"], "txPanel": True}
    toc = [{"id": item_id, "label": label}
           for item_id, label in toc if shown[item_id]]

    balance = charts.balance_chart(window) if panels["balance"] else {}
    years = (charts.year_chart(analysis.year_cumulative(spend))
             if panels["years"] else {})

    # Only the crosshair needs data client-side; everything else is server-drawn.
    crosshair_data = {}
    if balance.get("series"):
        crosshair_data["balance"] = {"series": balance["series"],
                                     "geom": balance["geom"],
                                     "dates": balance["dates"]}
    if years.get("series"):
        crosshair_data["years"] = {"series": years["series"],
                                   "geom": years["geom"]}
    if ibkr_chart.get("series"):
        crosshair_data["ibkr"] = {"series": ibkr_chart["series"],
                                  "geom": ibkr_chart["geom"],
                                  "labels": ibkr_chart["labels"],
                                  "unit": ibkr_chart["unit"]}
    if shares_chart.get("series"):
        crosshair_data["shares"] = {"series": shares_chart["series"],
                                    "geom": shares_chart["geom"],
                                    "labels": shares_chart["labels"]}
    if panels["calendar"]:
        # The calendar's tooltips and its lazy twin table, once, keyed by day
        # -- instead of a title, a JSON row list and a hint on every cell.
        crosshair_data["calendar"] = {
            day.isoformat(): [round(v["amount"], 2), v["count"]]
            for day, v in sorted(daily.items())}

    stack = stack_mode(args)
    if stack == "bucket":
        fills = dict(BUCKET_FILL)
        present = [name for name in buckets.ORDER
                   if any(r["buckets"].get(name) for r in rows)]
        stack_legend = [{"name": name, "fill": BUCKET_FILL[name]}
                        for name in present]
    else:
        fills = {name: f"var(--s{slot})" for name, slot in slots.items()}
        stack_legend = [{"name": l["name"], "fill": f"var(--s{l['slot']})"}
                        for l in legend]

    timeline_chart = charts.timeline(rows, fills, period["grain"], drill,
                                     STACKS[stack]["source"])
    if timeline_chart.get("bands"):
        crosshair_data["timeline"] = {
            "width": timeline_chart["width"],
            "plot": timeline_chart["plot"],
            "bands": timeline_chart["bands"],
        }

    return {
        **controls,
        "window": window,
        "chart_data_json": json.dumps(crosshair_data, separators=(",", ":")),
        "previous": {"start": prev_start, "end": prev_end,
                     "exists": bool(previous.transactions)},
        "kpis": _kpis(window, previous),
        "categories": categories,
        "category_bars": charts.category_bars(categories),
        "legend": legend,
        "buckets": buckets.summarise(window),
        "bucket_fill": BUCKET_FILL,
        "shares": shares,
        "review": review,
        "news": fresh,
        # The calendar's twin table, rendered server-side only when asked for
        # (the no-JavaScript path); app.js builds it from #chartData otherwise.
        "calendar_table": args.get("table") == "calendar",
        "timeline": timeline_chart,
        "stack": stack,
        "stack_legend": stack_legend,
        "stacks": [{"id": key, "label": spec["label"], "aria": spec["aria"],
                    "active": key == stack}
                   for key, spec in STACKS.items()],
        "drill_hint": drill_hint,
        "day_strip": charts.day_strip(
            analysis.timeseries(window, "day", period["start"], period["end"]),
            period["start"], period["end"]),
        "series": rows,
        "custodian": custodian,
        "top_merchants": analysis.top_merchants(spend, limit=12),

        # --- the analytical panels, each scoped to the window ----------------
        "panels": panels,
        "toc": toc,
        "finpension": finpension,
        "split": split_mode(args),
        "splits": [{"id": key, "label": spec["label"], "aria": spec["aria"],
                    "active": key == split_mode(args)}
                   for key, spec in SPLITS.items()],
        "scale": scale_mode(args),
        "perfs": [{"id": key, "label": spec["label"], "aria": spec["aria"],
                   "active": key == perf_mode(args)}
                  for key, spec in PERFS.items()],
        # The savings section's pocket picker: a labelled control, not the
        # value boxes that used to be clickable without saying so.
        "focuses": [{"id": key, "label": label, "active": key == focus_mode(args)}
                    for key, label in (("total", "Tout"), ("swissquote", "Swissquote"),
                                       ("ibkr", "IBKR"), ("finpension", "3a"))],
        "scales": [{"id": key, "label": spec["label"], "aria": spec["aria"],
                    "active": key == scale_mode(args)}
                   for key, spec in SCALES.items()],
        "focus": focus_mode(args),
        "monthly": monthly,
        "fixed": fixed,
        "missing": missing,
        "income_sources": income_table,
        "income_payers": len(sources),
        "geo": geo,
        "highlights": (analysis.highlights(window, custodian)
                       if panels["highlights"] else []),
        "ibkr": ibkr,
        "charts": {
            "income": (charts.income_band(income_rows, income_fills)
                       if panels["income"] else {}),
            "balance": balance,
            "ibkr": ibkr_chart,
            "weekday": charts.weekday_chart(analysis.weekday_profile(spend)),
            "calendar": (charts.calendar_chart(daily, period["start"], period["end"])
                         if panels["calendar"] else {}),
            "fixed": charts.fixed_chart(fixed) if panels["fixed"] else {},
            "country": charts.country_chart(geo) if panels["country"] else {},
            "years": years,
            "shares": shares_chart,
            "season": (charts.season_chart(analysis.seasonality(spend))
                       if panels["season"] else {}),
            "custodian": (charts.custodian_chart(custodian["conversions"])
                          if panels["custodian"] else {}),
        },
        "uncategorised": sum(abs(t.amount_chf) for t in spend
                             if t.category == UNCATEGORISED),
        "gaps": data.gaps,
        "sources": data.sources,
        "form_errors": form_errors or {},
        "form_values": form_values or {},
        **_transactions(window, period, args, COMPACT_PAGE_SIZE),
    }


@bp.route("/")
def dashboard():
    if store().empty:
        return render_template("empty.html.j2",
                               ledger=str(store().path)), 200
    if request.args.get("fragment") == "controls":
        # The swap refreshes the period bar after <main>: it used to fetch the
        # whole page for it, a second full dashboard build per click.
        return render_template("partials/controls_fragment.html.j2",
                               **_controls_context(request.args))
    context = _context(request.args)
    template = ("partials/main.html.j2" if request.args.get("fragment")
                else "dashboard.html.j2")
    return render_template(template, **context)


@bp.route("/day/<iso>")
def day(iso: str):
    """Every movement of one day, in statement order."""
    try:
        target = dt.date.fromisoformat(iso)
    except ValueError:
        abort(404)

    data = store()
    window = data.window(target, target)
    if not window.transactions:
        return redirect(url_for("dashboard.dashboard",
                                **{"from": iso, "to": iso, "grain": "day"}))

    spend = analysis.spending(window)
    return render_template(
        "day.html.j2",
        date=target,
        rows=sorted(window.transactions, key=lambda t: t.seq),
        spending=sum(abs(t.amount_chf) for t in spend),
        income=sum(t.amount_chf for t in analysis.income(window)),
        categories=analysis.by_category(spend),
        neighbours={
            "prev": target - dt.timedelta(days=1),
            "next": target + dt.timedelta(days=1),
        },
        bounds=data.bounds,
    )


def _dashboard_rerender(errors: dict[str, str], values: dict[str, str]) -> Response:
    """Re-render the dashboard carrying a failed form's state.

    The POST lands with an empty query string, but the page the user filled
    the form on is the Referer -- the re-render must show that same window,
    or the error turns up on one the user never asked to see.
    """
    if store().empty:
        return redirect(url_for("dashboard.dashboard"))
    args = request.args
    referrer = request.referrer or ""
    if referrer:
        split = urlsplit(referrer)
        if split.path == url_for("dashboard.dashboard"):
            args = ImmutableMultiDict(parse_qsl(split.query))
    return render_template("dashboard.html.j2",
                           **_context(args, errors, values))


@bp.route("/budgets", methods=["POST"])
def budgets_edit():
    """Declare or remove a monthly budget -- plain forms, no JavaScript.

    A budget that fails to parse re-renders the dashboard with the error,
    like the plan forms: a silent no-op would have the user type the same
    amount again into a field that never said what it wanted.
    """
    store_ = budgets_module.Budgets.load(store().path.with_name("budgets.json"))
    action = request.form.get("action") or ""
    category = (request.form.get("category") or "").strip()
    amount_text = (request.form.get("amount") or "").strip()

    errors: dict[str, str] = {}
    if action == "delete":
        store_.remove(category)
    elif action == "add" and category:
        try:
            amount = float(amount_text) if amount_text else 0.0
        except ValueError:
            errors["budget-amount"] = "Utilisez le point décimal, pas la virgule."
        else:
            if amount <= 0:
                errors["budget-amount"] = "Montant invalide."
            else:
                store_.set_budget(category, amount)

    if errors:
        return _dashboard_rerender(errors, {"budget-amount": amount_text})
    store_.save()
    return redirect(request.referrer or url_for("dashboard.dashboard"))
