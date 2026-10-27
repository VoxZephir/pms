"""The savings: what the money outside the spending is worth, how each
pocket did, and the figures the tax return asks for.

One `SavingsBook` per request, as on the old panel: the headline, the pocket
table, the curve and the risk table all read it, so none of them can
disagree on a deposit (`views/savings.py`, `docs/epargne.md`).
"""

from __future__ import annotations

import datetime as dt

from flask import request

from ... import allocation as allocation_module
from ... import analysis
from ... import benchmarks as benchmarks_module
from ... import crypto as crypto_module
from ... import finpension as finpension_module
from ... import fiscal
from ... import holdings as holdings_module
from ... import ibkr as ibkr_module
from .. import periods
from ..views.common import (
    PERFS, RATES, SCALES, SPLITS, bench_mode, focus_mode, perf_mode, rate_mode, titres_mode,
    scale_mode, split_mode,
)
from ..views.savings import (
    POCKETS, SavingsBook, _attribution, _benchmark_return, _benchmarks, _evolution_rows,
    _fees, _indexed_rows, _level, _mwr_rows, _pocket_rows, _reserve, _risk_table,
    STATS_MODES, _savings_parts, _split_series, _stale_benchmarks, _stale_notes, annualize,
    stats_mode,
)
from ..views.savings_reads import readings
from . import api, payload, store
from .shell import period_of

# What the panel reads from the brokerage snapshot; the rest of it (daily
# NAV series, raw journal) is the book's business, not the browser's.
SHIPPED = ("captured_at", "positions", "other_accounts", "opened", "reconstructed_until",
           "journal_source", "account", "currency")


def tax_years(statement, ibkr, finpension, crypto, today: dt.date,
              closed: int | None = None) -> list[dict]:
    """The last `closed` 31 Decembers, then the year still running as of the
    statement's last day -- an estimate of the next return, filed a year on."""
    years = fiscal.year_ends(statement.transactions, today)
    out = [fiscal.year_end(statement, ibkr, finpension, crypto, year)
           for year in years[-closed if closed else 0:]]
    day = fiscal.year_to_date(statement.transactions, today)
    if day:
        out.append(fiscal.year_end(statement, ibkr, finpension, crypto, day.year, day))
    return out


@api.route("/api/savings")
def savings():
    data = store()
    if data.empty:
        return payload({"empty": True})
    args = request.args
    period = period_of(args)
    start, end = period["start"], period["end"]

    titres = titres_mode(args)
    loaded = savings_book(data, titres)
    if loaded is None:
        return payload({"period": period, "available": False})
    book, ibkr, finpension = loaded
    values = {pocket: book.value(pocket, end) for pocket in POCKETS}
    custodian = analysis.custodian_costs(data.window(start, end))

    focus = focus_mode(args)
    if (focus == "crypto" and not book.crypto) or (focus == "titres" and not book.securities):
        focus = "total"
    split, scale, perf, rate = split_mode(args), scale_mode(args), perf_mode(args), rate_mode(args)

    # The helpers read these off the snapshot itself, as the old panel set them.
    ibkr["swissquote_chf"] = round(values["swissquote"], 2)
    ibkr["nav_chf"] = round(values["ibkr"], 2)
    ibkr["finp_chf"] = round(values["finpension"], 2)
    ibkr["finpension"] = finpension
    ibkr["focus"], ibkr["perf"], ibkr["rate"] = focus, perf, rate

    out: dict = {k: ibkr.get(k) for k in SHIPPED}
    out["period"] = period
    out["available"] = True
    out["focus"], out["split"], out["scale"], out["perf"], out["rate"] = focus, split, scale, perf, rate
    out["swissquote_chf"] = ibkr["swissquote_chf"]
    out["nav_chf"] = ibkr["nav_chf"]
    out["finp_chf"] = ibkr["finp_chf"]
    out["finpension"] = ({k: finpension.get(k) for k in
                          ("value", "value_as_of", "deposits", "fees", "first")}
                         if finpension else None)
    out["finp_as_of"] = periods.parse_date(finpension.get("value_as_of")) if finpension else None
    out["captured_on"] = periods.parse_date((ibkr.get("captured_at") or "")[:10])
    ibkr["total"] = round(values["total"] + sum(a["value"] for a in ibkr.get("other_accounts", [])), 2)
    out["total"] = ibkr["total"]
    out["stale"] = _stale_notes(ibkr, finpension, end, book.crypto)
    out["parts"] = _savings_parts(ibkr, values["swissquote"], finpension, values["finpension"],
                                  split, focus, book.crypto, values["crypto"], values["titres"],
                                  titres_each=[(h["name"], holdings_module.value_on([h], end))
                                               for h in book.securities
                                               if end >= holdings_module.start(h)],
                                  titres_other=holdings_module.value_on(
                                      [h for h in book.securities
                                       if holdings_module.kind_of(h) == holdings_module.OTHER], end),
                                  titres_name=book.name("titres"))
    fees = _fees(custodian["total_chf"], custodian["count"], ibkr, finpension, values,
                 start, end, book.crypto)
    out["fees"] = fees
    out["pockets"] = _pocket_rows(book, fees, start, end)
    out["hero"] = next(r for r in out["pockets"] if r["pocket"] == focus)
    out["reads"] = readings(book, start, end)
    out["crypto"] = _crypto_summary(book.crypto)
    today = dt.date.today()
    out["reserve"] = _reserve(data.statement, values["swissquote"], end)
    out["pillar3a"] = (fiscal.pillar3a(finpension, data.statement.transactions, end.year, today)
                       if finpension else None)

    targets = allocation_module.Allocation.load(data.path.with_name("allocation.json")).targets
    # The other goods (a watch) are no class of the portfolio: left out of
    # the allocation, which is about what is invested.
    others = holdings_module.value_on([h for h in book.securities
                                       if holdings_module.kind_of(h) == holdings_module.OTHER], end)
    by_class = [p for p in _savings_parts(ibkr, values["swissquote"], finpension, values["finpension"],
                                          "asset", "total", book.crypto, values["crypto"], values["titres"],
                                          titres_in_actions=True, titres_other=others)
                if p["name"] != "Autres biens"]
    total_by_class = sum(p["value"] for p in by_class) or 1.0
    exposure = allocation_module.exposure(by_class, allocation_module.leverage(ibkr["positions"]))
    out["allocation"] = {
        "classes": allocation_module.CLASSES, "targets": targets,
        "current": {p["name"]: p["value"] / total_by_class * 100 for p in by_class},
        "drift": allocation_module.drift(by_class, targets),
        "exposure": exposure,
    }
    out["tax"] = fiscal.table(tax_years(data.statement, ibkr, finpension, book.crypto, today, closed=3))

    offered = benchmarks_module.available(data.path.with_name("benchmarks.json"), finpension)
    picked = bench_mode(args)
    benchmarks = _benchmarks(ibkr, finpension, offered, picked)
    out["stale"] += _stale_benchmarks(benchmarks, end)
    out["bench_options"] = [
        {"key": key, "name": benchmarks_module.label(key), "on": key in picked,
         "available": key in offered, "source": offered[key]["source"] if key in offered else ""}
        for key in benchmarks_module.KEYS]
    described = {entry["name"]: entry for entry in offered.values()}
    out["risk"] = _risk_table(book, start, end, benchmarks, stats_mode(args, start, end))
    out["attribution"] = _attribution(ibkr, book, start, end)
    out["bench"] = []
    for name, series in benchmarks.items():
        r, first = _benchmark_return(series, start, end)
        if r is not None:
            entry = described.get(name, {})
            out["bench"].append({"name": name, "rate": r, "rate_pa": annualize(r, (end - first).days),
                                 "since": first if first > start else None,
                                 "source": entry.get("source", "indice de prix"),
                                 "total_return": entry.get("total_return", False)})

    # The curve: the rows the old chart was drawn from, one line per part of
    # the chosen breakdown; in base 100 the indices ride along, dashed.
    rows = _evolution_rows(data.statement, ibkr, finpension, start, end, period["grain"], book.crypto,
                           book.securities)
    spec = _split_series(split, finpension, focus, bool(book.crypto), book.securities)
    out["invested"] = _invested(book, [r["date"] for r in rows], focus)
    if scale == "index":
        rows = [dict(row) for row in rows]
        compared = benchmarks if split == "account" else {}
        free = [s for s in (6, 4, 7, 5) if s not in {p["slot"] for p in spec}]
        for i, (name, series) in enumerate(compared.items()):
            key = f"bench_{i}"
            for row in rows:
                row[key] = _level(series, row["date"]) if series[0][0] <= row["date"] else None
            spec = [*spec, {"key": key, "name": name, "dash": True,
                            "slot": free[i % len(free)] if free else 6}]
        rebase = _mwr_rows if perf == "mwr" else _indexed_rows
        rows = rebase(rows, [s["key"] for s in spec], book)
    out["evolution"] = {
        "spec": spec,
        "rows": [{"date": r["date"], **{s["key"]: r.get(s["key"]) for s in spec}} for r in rows],
        "unit": "" if scale == "index" else "CHF",
    }

    out["options"] = {
        "splits": [{"id": k, "label": v["label"]} for k, v in SPLITS.items()],
        "scales": [{"id": k, "label": v["label"], "title": v["aria"]} for k, v in SCALES.items()],
        "perfs": [{"id": k, "label": v["label"], "title": v["aria"]} for k, v in PERFS.items()],
        "rates": [{"id": k, "label": v["label"], "title": v["aria"]} for k, v in RATES.items()],
        "stats": [{"id": k, "label": v["label"], "title": v["aria"]} for k, v in STATS_MODES.items()],
        "focuses": [{"id": k, "label": label} for k, label in
                    (("total", "Tout"), ("swissquote", "Swissquote"), ("ibkr", "IBKR"),
                     ("finpension", "3a"), ("crypto", "Crypto"), ("titres", "Titres"))
                    if (k != "crypto" or book.crypto) and (k != "titres" or book.securities)],
    }
    # The unlisted shares, and whether they are counted: the page offers the
    # switch only when some are declared.
    declared = holdings_module.load(data.path.with_name("holdings.json"))
    out["titres"] = {"declared": len(declared), "counted": titres,
                     "name": holdings_module.pocket_name(declared),
                     "value": holdings_module.value_on(declared, end) if declared else 0.0}
    return payload(out)


def _invested(book, dates: list, focus: str) -> dict | None:
    """What was put into the portfolio, and what it is worth, at each point
    of the curve: the money entered since each pocket opened (cumulated from
    its very first flow, not from the window's start) against its value.
    The gap is the gain. The portfolio is the invested pockets -- IBKR, the
    3a, the crypto; the Swissquote cash has no "deposits" that would mean
    anything here (a salary is not an investment). A pocket chosen above
    is shown alone."""
    pockets = (["ibkr", "finpension"] + (["crypto"] if book.crypto else [])
               + (["titres"] if book.securities else []))
    if focus in pockets:
        pockets = [focus]
    if not dates:
        return None
    origin = dt.date(1900, 1, 1)
    rows = []
    for day in dates:
        put = sum(book.flow(p, origin, day) for p in pockets)
        worth = sum(book.value(p, day) for p in pockets)
        rows.append({"date": day, "contributed": round(put, 2), "value": round(worth, 2)})
    if not any(r["value"] or r["contributed"] for r in rows):
        return None
    last = rows[-1]
    return {"rows": rows, "pockets": pockets,
            "contributed": last["contributed"], "value": last["value"],
            "gain": round(last["value"] - last["contributed"], 2),
            "gain_pct": round((last["value"] / last["contributed"] - 1) * 100, 1)
            if last["contributed"] > 0 else None}


def savings_book(data, titres: bool = True):
    """(book, IBKR snapshot, 3a snapshot) from the files next to the ledger,
    or None without an IBKR snapshot -- the page and the assistant read the
    same pockets. `titres` counts the unlisted shares declared on the tax
    page (`?titres=0` leaves them out)."""
    ibkr = ibkr_module.load(data.path.with_name("ibkr.json"))
    if not ibkr:
        return None
    finpension = finpension_module.load(data.path.with_name("finpension.json"))
    ibkr["flows"] = ibkr_module.flows(ibkr, data.statement.transactions)
    crypto = crypto_module.load(data.path.with_name("crypto.json"))
    securities = holdings_module.load(data.path.with_name("holdings.json")) if titres else []
    return SavingsBook(data.statement, ibkr, finpension, crypto, securities), ibkr, finpension


def pocket_summaries(data, start, end, focus: str = "total") -> list[dict] | None:
    """Each pocket over the window, then the total (`SavingsBook.summary`);
    only the pocket chosen, when one is."""
    loaded = savings_book(data)
    if loaded is None:
        return None
    book = loaded[0]
    pockets = book.pockets()
    chosen = [focus] if focus in pockets else [*pockets, "total"]
    return [book.summary(p, book.start_of(p, start) if p in ("crypto", "titres") else start, end)
            for p in chosen]


@api.route("/api/allocation", methods=["POST"])
def allocation_edit():
    """Declare the target split by asset class, or clear it. A split that
    does not add up is refused with the reason."""
    body = request.get_json(silent=True) or {}
    store_ = allocation_module.Allocation.load(store().path.with_name("allocation.json"))
    if body.get("action") == "clear":
        store_.targets = {}
    else:
        typed = {name: str((body.get("targets") or {}).get(name, "") or "")
                 for name in allocation_module.CLASSES}
        targets, error = allocation_module.validate(typed)
        if error:
            return payload({"error": error}), 400
        store_.targets = targets
    store_.save()
    return payload({"targets": store_.targets})


def _crypto_summary(crypto: dict | None) -> dict | None:
    """The coin-by-coin table: what the pocket row adds up."""
    if not crypto:
        return None
    return {k: crypto.get(k) for k in
            ("as_of", "positions", "value_chf", "cost_chf", "calibration", "sent", "unread")}
