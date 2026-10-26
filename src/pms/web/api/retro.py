"""The year in review (`/bilan`): `retro.review` for the year asked, the
previous one when none is."""

from __future__ import annotations

import datetime as dt

from flask import request

from ... import analysis, retro
from ..palette import colour_map
from . import api, payload, store


@api.route("/api/bilan")
def retro_page():
    data = store()
    if data.empty:
        return payload({"empty": True})
    statement = data.statement
    years = retro.years(statement)
    if not years:
        return payload({"empty": True, "reason": "Le relevé couvre moins de trois mois d'une même année."})
    try:
        year = int(request.args.get("year") or 0)
    except ValueError:
        year = 0
    known = [y["year"] for y in years]
    if year not in known:
        # The last whole year, or the latest one.
        last = dt.date.today().year - 1
        year = last if last in known else known[0]
    slots, _ = colour_map(analysis.by_category([t for t in analysis.spending(statement) if t.date.year == year]))
    return payload({"years": years, "chosen": next(y for y in years if y["year"] == year),
                    **retro.review(statement, year, slots)})
