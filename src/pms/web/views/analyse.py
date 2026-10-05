"""`/analyse`: the backward-looking monthly profile and its export."""

from __future__ import annotations

import datetime as dt
import json

from flask import Response, abort, redirect, render_template, request, url_for

from ... import analysis
from ... import export as export_module
from ... import plans as plans_module
from .. import charts
from .common import bp, store

#: The analysis page's profile modes: the median across the observed years
#: (the default), or one observed year at a time, so a rise from one year to
#: the next shows raw instead of being flattened into a median.
DEFAULT_ANALYSIS_YEAR = "median"


def year_mode(args) -> str:
    """Which year the profile shows -- validated against what is actually
    observed in `_analysis_context`, never echoed raw.

    A year is four digits; a longer digit run would blow up `int()` (Python
    caps integer conversion at 4300 digits) before the fallback ever ran.
    """
    raw = (args.get("year") or "").strip()
    return raw if raw.isdigit() and len(raw) <= 4 else DEFAULT_ANALYSIS_YEAR


@bp.app_template_global()
def _analysis_export_url(fmt: str) -> str:
    """The export link carrying the year that is on screen -- the file must
    hold what the page showed, like every other export in the app."""
    params = {"fmt": fmt}
    year = year_mode(request.args)
    if year != DEFAULT_ANALYSIS_YEAR:
        params["year"] = year
    return url_for("dashboard.analysis_export", **params)


@bp.app_template_global()
def _analysis_url(**overrides) -> str:
    """The analysis page keeping the view options that are on screen.

    Same rule as `_previsions_url`: only the display keys ride along, and a
    key dropped to its default disappears from the URL. `cat=""` pops the
    drill back to the ordinary month."""
    params = {}
    year = overrides.pop("year", year_mode(request.args))
    if year != DEFAULT_ANALYSIS_YEAR:
        params["year"] = year
    cat = overrides.pop("cat", (request.args.get("cat") or "").strip())
    if cat:
        params["cat"] = cat
    params.update(overrides)
    return url_for("dashboard.analysis_page", **params)


def _analysis_context() -> dict:
    """The historical analysis: the baseline's arithmetic shown month by
    calendar month, the per-category stats, and the drilled category.

    No window, like the previsions: the seasonality that survives two years
    is the finding, and the baseline is defined on the whole ledger -- a
    windowed strip would give a different number for the same month.
    Shared by the page and the export, so the file and the screen cannot
    disagree.
    """
    data = store()
    base = plans_module.baseline(data.statement)
    profile = plans_module.monthly_profile(data.statement)
    observed_years = sorted({y for p in profile for y in p["years"]},
                            reverse=True)

    year = year_mode(request.args)
    if year != DEFAULT_ANALYSIS_YEAR and int(year) not in observed_years:
        year = DEFAULT_ANALYSIS_YEAR
    shown = (profile if year == DEFAULT_ANALYSIS_YEAR
             else plans_module.monthly_profile(data.statement, year=int(year)))
    monthly_analysis = (charts.monthly_season_chart(shown, base)
                        if len(shown) >= 2 else {})

    categories = plans_module.category_profile(data.statement)
    for c in categories:
        c["peak_month_label"] = plans_module.MONTH_NAMES[
            c["peak_month"] - 1].capitalize()
        if c["seasonal"]:
            c["seasonal"]["month_label"] = plans_module.MONTH_NAMES[
                c["seasonal"]["month"] - 1].capitalize()

    # The drill: a category clicked in the table shows its own real monthly
    # series instead of the profile. Unknown names fall back to the profile.
    cat = (request.args.get("cat") or "").strip()
    if cat not in {c["category"] for c in categories}:
        cat = ""
    category_chart = {}
    if cat:
        months = analysis.monthly(data.statement)
        if year != DEFAULT_ANALYSIS_YEAR:
            # The drill obeys the year the URL declares, like the profile:
            # a ?year=2025&cat=X URL must not silently mix three years.
            months = [r for r in months
                      if r["month"].startswith(f"{int(year)}-")]
        rows = [{"key": r["month"],
                 "label": analysis.bucket_label(
                     dt.date.fromisoformat(r["month"] + "-01"), "month"),
                 "amount": r["categories"].get(cat, 0.0)}
                for r in months]
        rows = [r for r in rows if r["amount"] > 0]
        median = next((c["median"] for c in categories
                       if c["category"] == cat), 0.0)
        category_chart = charts.category_month_chart(rows, median)

    crosshair_payload = {}
    if monthly_analysis.get("series"):
        crosshair_payload["monthly"] = {"series": monthly_analysis["series"],
                                        "geom": monthly_analysis["geom"],
                                        "labels": monthly_analysis["labels"]}
    if category_chart.get("series"):
        crosshair_payload["category"] = {"series": category_chart["series"],
                                         "geom": category_chart["geom"],
                                         "labels": category_chart["labels"]}
    return dict(
        chart_data_json=json.dumps(crosshair_payload, separators=(",", ":")),
        as_of=data.statement.period_end,
        baseline=base,
        monthly_analysis=monthly_analysis,
        monthly_profile=shown if monthly_analysis else [],
        year=year,
        year_options=(
            [{"id": DEFAULT_ANALYSIS_YEAR, "label": "Médiane",
              "active": year == DEFAULT_ANALYSIS_YEAR}]
            + [{"id": str(y), "label": str(y), "active": year == str(y)}
               for y in observed_years]),
        categories=categories,
        category=cat,
        category_chart=category_chart,
    )


def _analysis_page():
    context = _analysis_context()
    template = ("partials/analysis_main.html.j2"
                if request.args.get("fragment") else "analysis.html.j2")
    return render_template(template, **context)


@bp.route("/analyse")
def analysis_page():
    return _analysis_page()


@bp.route("/analyse/export.<fmt>")
def analysis_export(fmt: str):
    """Download the analysis tables -- the same dicts the page renders.

    A file detached from its page is a file you cannot identify three months
    later, so the name says what it holds. The year pick reaches the file
    (the same rule as the transaction export: the file holds what the screen
    showed); the drilled category does not, the file is the analysis.
    """
    if fmt not in ("csv", "xlsx"):
        abort(404)
    context = _analysis_context()
    if not context["monthly_analysis"]:
        return redirect(url_for("dashboard.analysis_page"))
    if fmt == "csv":
        payload = export_module.to_analysis_csv(
            context["monthly_profile"], context["categories"])
        mime = "text/csv"
    else:
        payload = export_module.to_analysis_xlsx(
            context["monthly_profile"], context["categories"])
        mime = ("application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet")
    return Response(payload, mimetype=mime, headers={
        "Content-Disposition": f'attachment; filename="pms-analyse.{fmt}"',
        "Content-Length": str(len(payload)),
    })
