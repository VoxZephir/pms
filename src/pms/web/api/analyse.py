"""The backward-looking analysis: the ordinary month, category by category.

No window, like the forecast: the seasonality that survives two years is the
finding, and the baseline is defined on the whole ledger -- a windowed strip
would give a different number for the same month. Shared with the export, so
the file and the screen cannot disagree."""

from __future__ import annotations

import datetime as dt

from flask import request

from ... import analysis, cpi, lookback, swiss
from ... import plans as plans_module
from ..palette import colour_map
from . import api, payload, store

#: The profile's modes: the median across the observed years (the default),
#: or one observed year, so a rise from one year to the next shows raw
#: instead of being flattened into a median.
DEFAULT_ANALYSIS_YEAR = "median"


def year_mode(args) -> str:
    """Which year the profile shows -- validated against what is observed
    in `analysis_data`, never echoed raw. A year is four digits: a longer
    run would blow up `int()` before the fallback ever ran."""
    raw = (args.get("year") or "").strip()
    return raw if raw.isdigit() and len(raw) <= 4 else DEFAULT_ANALYSIS_YEAR


def analysis_data(args) -> dict:
    data = store()
    if data.empty:
        return {"empty": True}
    base = plans_module.baseline(data.statement)
    profile = plans_module.monthly_profile(data.statement)
    observed = sorted({y for p in profile for y in p["years"]}, reverse=True)

    year = year_mode(args)
    if year != DEFAULT_ANALYSIS_YEAR and int(year) not in observed:
        year = DEFAULT_ANALYSIS_YEAR
    shown = (profile if year == DEFAULT_ANALYSIS_YEAR
             else plans_module.monthly_profile(data.statement, year=int(year)))

    categories = plans_module.category_profile(data.statement)
    for c in categories:
        c["peak_month_label"] = plans_module.MONTH_NAMES[c["peak_month"] - 1].capitalize()
        if c["seasonal"]:
            c["seasonal"]["month_label"] = plans_module.MONTH_NAMES[
                c["seasonal"]["month"] - 1].capitalize()

    monthly = analysis.monthly(data.statement)
    whole = lookback.whole_months(data.statement)
    change = lookback.year_change(data.statement, monthly, whole)
    seasonal = {c["category"] for c in categories if c["seasonal"]}
    lines = lookback.category_lines(monthly, whole, categories, seasonal)
    for c in categories:
        c.update(lines.get(c["category"], {}))
    # One hue per category for the whole page, by median spend as the table
    # lists them. The tail gets none (`null`, drawn neutral): five rows in the
    # same hue as "Autres" read as one category.
    slots, _ = colour_map(categories)
    for c in categories:
        c["slot"] = slots.get(c["category"])

    # The drill: one category's real monthly series, in the year on screen.
    # A `?year=2025&cat=X` URL must not silently mix three years.
    cat = (args.get("cat") or "").strip()
    if cat not in {c["category"] for c in categories}:
        cat = ""
    drill = None
    if cat:
        months = monthly
        if year != DEFAULT_ANALYSIS_YEAR:
            months = [r for r in months if r["month"].startswith(f"{int(year)}-")]
        rows = [{"key": r["month"],
                 "label": analysis.bucket_label(dt.date.fromisoformat(r["month"] + "-01"), "month"),
                 "amount": round(r["categories"].get(cat, 0.0), 2)} for r in months]
        drill = {"category": cat,
                 "rows": [r for r in rows if r["amount"] > 0],
                 "median": next((c["median"] for c in categories if c["category"] == cat), 0.0),
                 **lookback.category_detail(data.statement, monthly, whole, cat)}

    return {
        "as_of": data.statement.period_end,
        "baseline": base,
        # Two observed calendar months are the least it says anything about.
        "profile": shown if len(shown) >= 2 else [],
        "year": year,
        "years": [{"id": DEFAULT_ANALYSIS_YEAR, "label": "Médiane"}]
                 + [{"id": str(y), "label": str(y)} for y in observed],
        "categories": categories,
        "drill": drill,
        "headline": lookback.headline(monthly, whole, change),
        "change": change,
        "rhythm": lookback.rhythm(data.statement, whole),
        "weekdays": lookback.weekdays(data.statement, whole),
        "whole_months": len(whole),
        # Against Switzerland: one's own prices against the index, one's
        # month against the average household (`swiss.py`).
        "inflation": swiss.inflation(data.statement, cpi.load(data.path.with_name("cpi.json"))),
        "households": swiss.households(data.statement),
    }


@api.route("/api/analyse")
def analyse():
    return payload(analysis_data(request.args))
