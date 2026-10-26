"""The tax return, rubric by rubric (`/impots`): what the statement says for
a year, and the workbook to fill the return from (`taxes.py`)."""

from __future__ import annotations

import datetime as dt

from flask import request

from ... import crypto as crypto_module
from ... import finpension as finpension_module
from ... import health, holdings, taxes, upcoming
from ... import ibkr as ibkr_module
from . import api, payload, store


def _number(raw) -> float | None:
    try:
        value = float(str(raw or "").replace("'", "").replace("’", "").strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def holdings_path(data=None):
    return (data or store()).path.with_name("holdings.json")


def settings_path(data=None):
    return (data or store()).path.with_name("tax.json")


def tax_data(args, today: dt.date | None = None) -> dict:
    data = store()
    if data.empty:
        return {"empty": True}
    today = today or dt.date.today()
    statement = data.statement
    years = taxes.years(statement)
    try:
        year = int(args.get("year") or 0)
    except ValueError:
        year = 0
    if year not in years:
        # The return filed this spring is last year's: open on it.
        year = today.year - 1 if today.year - 1 in years else years[0]

    ibkr = ibkr_module.load(data.path.with_name("ibkr.json"))
    if ibkr:
        ibkr["flows"] = ibkr_module.flows(ibkr, statement.transactions)
    finpension = finpension_module.load(data.path.with_name("finpension.json"))
    crypto = crypto_module.load(data.path.with_name("crypto.json"))
    crypto = crypto if crypto and crypto.get("daily_series") else None
    settings = health.load_settings(data.path.with_name("health.json"))
    bills = upcoming.commitments(statement, statement.period_end)
    premium = health.detected_premium(bills)

    out = taxes.return_items(statement, year, net_income=_number(args.get("net")),
                             finpension=finpension, ibkr=ibkr, crypto=crypto,
                             franchise=settings["franchise"],
                             insurer=premium["label"] if premium else None, today=today,
                             settings=taxes.load_settings(settings_path(data)),
                             owned=holdings.load(holdings_path(data)))
    out["years"] = years
    out["franchise"] = settings
    out["holdings"] = holdings.load(holdings_path(data))
    out["cantons"] = [{"id": k, "name": v["name"]} for k, v in taxes.CANTONS.items()]
    return out


@api.route("/api/impots")
def tax_page():
    return payload(tax_data(request.args))


@api.route("/api/impots/reglages", methods=["POST"])
def tax_settings():
    """The canton the return is filed in, from which year, and whether a
    year's tax is paid the year after."""
    body = request.get_json(silent=True) or {}
    try:
        since = int(body["since"]) if body.get("since") else None
        settings = taxes.save_settings(settings_path(), str(body.get("canton") or ""), since,
                                       bool(body.get("paid_next_year")))
    except (TypeError, ValueError) as error:
        return payload({"error": str(error)}), 400
    return payload({"ok": True, "settings": settings})


@api.route("/api/impots/titres", methods=["POST"])
def tax_holdings():
    """save (holding) or delete (id) a security held outside the statement;
    each answers with the undo."""
    body = request.get_json(silent=True) or {}
    path = holdings_path()
    owned = holdings.load(path)
    before = [dict(h) for h in owned]
    try:
        if body.get("action") == "delete":
            owned = [h for h in owned if h["id"] != str(body.get("id"))]
        elif body.get("action") == "restore":
            owned = [holdings.clean(h) for h in body.get("holdings") or []]
        else:
            h = holdings.clean(body.get("holding") or {})
            owned = [x for x in owned if x["id"] != h["id"]] + [h]
    except ValueError as error:
        return payload({"error": str(error)}), 400
    holdings.save(path, owned)
    return payload({"ok": True, "undo": {"action": "restore", "holdings": before}})
