"""The files the app hands out: the transactions of a view, the analysis
tables, the year-end figures for the tax return.

Each one is built by the same functions as the screen it comes from, so the
file holds exactly what was shown -- the filter, the order, the year.
"""

from __future__ import annotations

import datetime as dt

from flask import Response, abort, redirect, request

from ... import crypto as crypto_module
from ... import export as export_module
from ... import finpension as finpension_module
from ... import ibkr as ibkr_module
from .. import periods
from .common import _filtered, _sorted, bp, store

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file(payload: bytes, mime: str, name: str) -> Response:
    return Response(payload, mimetype=mime, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Content-Length": str(len(payload)),
    })


@bp.route("/export.<fmt>")
def export(fmt: str):
    """The current view -- window and filters included. Through `_filtered`
    and `_sorted`, the table's own two functions: every row of the filter,
    not the page on screen, in the order it was sorted."""
    if fmt not in ("csv", "xlsx"):
        abort(404)
    data = store()
    low, high = data.bounds
    period = periods.resolve(request.args, low, high)
    window = data.window(period["start"], period["end"])
    rows = _sorted(_filtered(window, request.args), request.args)
    if fmt == "csv":
        # Flask appends the charset; spelling it out doubles it.
        payload, mime = export_module.to_csv(rows), "text/csv"
    else:
        payload = export_module.to_xlsx(
            rows, export_module.sheet_name(period["start"], period["end"]))
        mime = XLSX
    return _file(payload, mime, export_module.filename(period["start"], period["end"], fmt))


@bp.route("/analyse/export.<fmt>")
def analysis_export(fmt: str):
    """The analysis tables, in the year on screen; the drilled category
    does not reach the file, the file is the analysis."""
    from ..api.analyse import analysis_data
    if fmt not in ("csv", "xlsx"):
        abort(404)
    data = analysis_data(request.args)
    if not data.get("profile"):
        return redirect("/analyse")
    if fmt == "csv":
        payload = export_module.to_analysis_csv(data["profile"], data["categories"])
        mime = "text/csv"
    else:
        payload = export_module.to_analysis_xlsx(data["profile"], data["categories"])
        mime = XLSX
    return _file(payload, mime, f"pms-analyse.{fmt}")


@bp.route("/epargne/impots.xlsx")
def tax_export():
    """The savings' year-end table as a workbook, one sheet per 31 December --
    what the tax return is filled from in March. The same `fiscal.year_end`
    dicts the page shows, whatever the window: a year-end is a date."""
    from ..api.savings import tax_years
    data = store()
    ibkr = ibkr_module.load(data.path.with_name("ibkr.json"))
    if not ibkr or data.empty:
        abort(404)
    ibkr["flows"] = ibkr_module.flows(ibkr, data.statement.transactions)
    finpension = finpension_module.load(data.path.with_name("finpension.json"))
    crypto = crypto_module.load(data.path.with_name("crypto.json"))
    crypto = crypto if crypto and crypto.get("daily_series") else None
    years = tax_years(data.statement, ibkr, finpension, crypto, dt.date.today())
    if not years:
        abort(404)
    return _file(export_module.to_tax_xlsx(years), XLSX, "pms-impots.xlsx")


@bp.route("/impots/<int:year>.xlsx")
def tax_return_export(year: int):
    """The `/impots` page for one year as a workbook: each rubric with its
    rule and estimate, then the lines behind it -- what the return is filled
    from, with the certificates beside it."""
    from ..api.taxes import tax_data
    data = tax_data({"year": year, "net": request.args.get("net")})
    if data.get("empty") or data["year"] != year:
        abort(404)
    return _file(export_module.to_return_xlsx(data), XLSX, f"pms-declaration-{year}.xlsx")
