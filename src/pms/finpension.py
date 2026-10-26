"""The 3a account at finpension: a transaction journal and yearly reports.

The second statement the app knows, after Swissquote. The journal CSV and
the performance PDFs live in `inbox/finpension/`, and this module turns
them into a captured snapshot -- `data/finpension.json`, gitignored like
the IBKR one -- that the savings panel reads. The journal has no current
value in it (the cash balance only), so the value comes from the newest
performance report.
"""

from __future__ import annotations

import bisect
import csv
import datetime as dt
import json
import re
from pathlib import Path


def _num(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value.replace("'", "").replace(" ", "").strip())


def parse_journal(path: Path | str) -> dict:
    """The transaction CSV: deposits, trades, dividends, fees, and the
    running cash balance -- summarized, with the raw entries kept."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))

    entries = []
    for row in rows:
        if not (row.get("Date") or "").strip():
            continue
        entries.append({
            "date": dt.date.fromisoformat(row["Date"].strip()),
            "category": (row.get("Category") or "").strip(),
            "asset": (row.get("Asset Name") or "").strip(),
            "isin": (row.get("ISIN") or "").strip(),
            "shares": _num(row.get("Number of Shares")),
            "price": _num(row.get("Asset Price in CHF")),
            "cash_flow": _num(row.get("Cash Flow")) or 0.0,
            "balance": _num(row.get("Balance")),
        })
    entries.sort(key=lambda e: e["date"])
    if not entries:
        return {"entries": [], "deposits": 0.0, "dividends": 0.0,
                "interests": 0.0, "fees": 0.0, "first": None, "last": None}

    deposits = sum(e["cash_flow"] for e in entries if e["category"] == "Deposit")
    dividends = sum(e["cash_flow"] for e in entries if e["category"] == "Dividend")
    interests = sum(e["cash_flow"] for e in entries if e["category"] == "Interests")
    fee_rows = [e for e in entries
                if e["category"] == "Flat-rate administrative fee"]
    fee_entries = [(e["date"], round(-e["cash_flow"], 2)) for e in fee_rows]
    # The total from the unrounded flows: summing the rounded entries
    # drifted by two centimes from the journal's own figure.
    fees = -sum(e["cash_flow"] for e in fee_rows)

    deposit_entries = [[e["date"].isoformat(), round(e["cash_flow"], 2)]
                       for e in entries if e["category"] == "Deposit"]

    by_year: dict[int, float] = {}
    for entry in entries:
        if entry["category"] == "Deposit":
            by_year[entry["date"].year] = by_year.get(entry["date"].year, 0.0) \
                + entry["cash_flow"]

    return {
        "entries": entries,
        "deposits": round(deposits, 2),
        "dividends": round(dividends, 2),
        "interests": round(interests, 2),
        "fees": round(fees, 2),
        # Dated, so the savings panel can say what a window cost -- the
        # total alone answered "since the opening" whatever the period on screen.
        "fee_entries": [[day.isoformat(), amount] for day, amount in fee_entries],
        # Dated too: a deposit is money arriving in the 3a, not a return.
        "deposit_entries": deposit_entries,
        "deposits_by_year": {str(year): round(amount, 2)
                             for year, amount in sorted(by_year.items())},
        "first": entries[0]["date"].isoformat(),
        "last": entries[-1]["date"].isoformat(),
    }


PROXY_KEYS = {"SMI": "SMI", "URTH x USD.CHF": "URTHxCHF", "EEM": "EEM"}


def _normalize_series(series) -> list:
    """Proxy points to (date, level) pairs, dropping unparseable rows."""
    out = []
    for date, level in series or []:
        try:
            out.append((dt.date.fromisoformat(date), float(level)))
        except (TypeError, ValueError):
            continue
    return out


def _level_at(series: list, day: dt.date) -> float | None:
    """The level on or before `day` in a date-sorted series. Bisected: the
    savings section reconstructs the 3a for every day of the window."""
    i = bisect.bisect_right(series, (day, float("inf")))
    return series[i - 1][1] if i else None


def value_at(snapshot: dict, day: dt.date) -> float | None:
    """The value on or before `day`, or None before the first.

    Between two observed values (yearly reports, or a value read in the
    finpension app) the curve is *reconstructed* from the similar index
    funds' series stored in the snapshot: the last observed value scaled
    by the portfolio's blended proxy ratio. Without proxies it falls back
    to a staircase -- flat between observations, which is what made the
    line trail the real account by hundreds of francs mid-year.
    """
    observed = [(d, v) for d, v in snapshot["yearly"] if d <= day]
    if snapshot.get("value_as_of"):
        try:
            as_of = dt.date.fromisoformat(snapshot["value_as_of"])
        except ValueError:
            as_of = None
        if as_of and as_of <= day:
            observed.append((as_of, snapshot["value"]))
    observed.sort()
    if not observed:
        return None
    obs_date, obs_value = observed[-1]
    if obs_date == day:
        return obs_value

    series_map = snapshot.get("proxy_series") or {}
    if not series_map:
        return obs_value
    weights = []
    for isin, holding in snapshot["holdings"].items():
        series = series_map.get(PROXY_KEYS.get(snapshot.get("proxies", {}).get(isin, "")))
        weight = holding["shares"] * holding.get("price", 0.0)
        if weight <= 0 or not series:
            continue
        base = _level_at(series, obs_date)
        now = _level_at(series, day)
        if not base or not now or base <= 0:
            continue
        weights.append((weight, now / base))
    if not weights:
        return obs_value
    total = sum(w for w, _ in weights)
    return round(obs_value * sum(w * ratio for w, ratio in weights) / total, 2)


def fund_class(name: str) -> str:
    """The economic exposure of a fund, from its name.

    The savings split sorts by asset class, not by instrument: an index
    fund is not an "ETF" class, it is the equity market it tracks. Named
    after the holdings, so a name is never silently misplaced.
    """
    lowered = name.lower()
    if "money market" in lowered or "cash" in lowered:
        return "Cash"
    if "bond" in lowered or "obligation" in lowered:
        return "Obligations"
    if "equit" in lowered:
        return "Actions"
    return "Autres"


def holdings(journal: dict) -> dict[str, dict]:
    """Net shares per ISIN from the journal: buys minus sells.

    The journal is a cash-flow log -- its "Balance" column is the cash, not
    the account value. The current value is the cash plus these holdings at
    today's prices. Each holding keeps its last printed price, name and
    asset class, so the savings split can weigh classes without fetching
    prices.
    """
    net: dict[str, dict] = {}
    for entry in journal["entries"]:
        if entry["category"] not in ("Buy", "Sell") or not entry["shares"]:
            continue
        holding = net.setdefault(entry["isin"], {
            "shares": 0.0, "price": 0.0, "name": entry["asset"],
            "class": fund_class(entry["asset"]),
        })
        holding["shares"] += entry["shares"]
        if entry["price"]:
            holding["price"] = entry["price"]
    return {isin: {**holding, "shares": round(holding["shares"], 6)}
            for isin, holding in net.items()
            if abs(holding["shares"]) > 1e-9}


def _deposits(raw: dict) -> list[tuple[dt.date, float]]:
    """Dated deposits; a snapshot older than the dated list only has yearly
    totals, placed on the first known value of that year (the first year's
    deposit is the opening one)."""
    entries = _normalize_series(raw.get("deposit_entries"))
    if entries:
        return sorted(entries)
    out = []
    yearly = sorted(_normalize_series(raw.get("yearly")))
    for year, amount in (raw.get("deposits_by_year") or {}).items():
        day = next((d for d, _ in yearly if d.year == int(year)),
                   dt.date(int(year), 1, 1))
        out.append((day, float(amount)))
    return sorted(out)


def load(path: Path | str) -> dict | None:
    """Normalize a captured snapshot, or None when absent or unreadable."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        value = float(raw["value"])
        deposits = float(raw.get("deposits") or 0.0)
        dividends = float(raw.get("dividends") or 0.0)
        fees = float(raw.get("fees") or 0.0)
        yearly = [(dt.date.fromisoformat(d), float(v))
                  for d, v in raw.get("yearly", [])]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return None
    yearly.sort()
    return {
        "captured_at": raw.get("captured_at") or "",
        "value": round(value, 2),
        "value_as_of": raw.get("value_as_of") or "",
        "value_method": raw.get("value_method") or "",
        "deposits": round(deposits, 2),
        "dividends": round(dividends, 2),
        "fees": round(fees, 2),
        "holdings": raw.get("holdings") or {},
        "cash": round(float(raw.get("cash") or 0.0), 2),
        "proxies": raw.get("proxies") or {},
        "proxy_series": {name: sorted(_normalize_series(series)) for name, series
                         in (raw.get("proxy_series") or {}).items()},
        "first": raw.get("first") or "",
        "last": raw.get("last") or "",
        "fee_entries": _normalize_series(raw.get("fee_entries")),
        "deposit_entries": _deposits(raw),
        "yearly": yearly,
        "gains": round(value - deposits, 2),
    }


def observe(path: Path | str, value: float, day: dt.date) -> dict:
    """Record a value read in the finpension app on `day`.

    `value_at()` anchors every date on the latest observation on or before
    it, and `value` / `value_as_of` hold only the newest one. So the reading
    being replaced must first join `yearly`: overwrite it and every day since
    the previous entry re-anchors on an older one -- done by hand the first
    time, a whole month re-anchored on the month before and the curve jumped
    overnight. A reading older than the current one is only an
    observation; it never replaces the newest.
    """
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    yearly = {d: v for d, v in raw.get("yearly", [])}
    when = day.isoformat()
    current = raw.get("value_as_of") or ""
    if when < current:
        yearly[when] = round(value, 2)
    else:
        if current and current != when and raw.get("value") is not None:
            yearly.setdefault(current, float(raw["value"]))
        raw["value"] = round(value, 2)
        raw["value_as_of"] = when
        note = f"le {day.strftime('%d.%m.%Y')} : {value:.2f}"
        method = raw.get("value_method") or ""
        if note not in method:
            raw["value_method"] = (f"{method}, {note}" if method
                                   else f"relevé dans l'app finpension : {note}")
    raw["yearly"] = sorted([d, v] for d, v in yearly.items())
    raw["captured_at"] = dt.date.today().isoformat()
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw


def regenerate(journal_path: Path | str, reports_dir: Path | str,
               snapshot_path: Path | str) -> dict:
    """Rebuild `data/finpension.json` from the freshly dropped documents.

    The journal summary always comes from the CSV; the value comes from the
    newest performance report -- unless the snapshot already carries a more
    recent reconstruction (a session-captured value with current prices),
    which is kept. The captured proxy series survive the rebuild the same
    way: they are session captures, not documents. That is the update flow
    for "new documents": drop them in `inbox/finpension/`, run
    `python -m pms --finpension`.
    """
    journal = parse_journal(journal_path)
    reports = sorted(Path(reports_dir).glob("rapport_de_performance_*.pdf")) \
        if Path(reports_dir).exists() else []
    report = reports[-1] if reports else None

    value, as_of = None, ""
    if report:
        value = parse_report_value(report)
        year = re.search(r"(\d{4})", report.name)
        if value is not None and year:
            as_of = f"{year.group(1)}-12-31"

    existing = load(snapshot_path) or {}
    if existing.get("value_as_of", "") > as_of:
        value, as_of = existing["value"], existing["value_as_of"]

    snapshot = {
        "captured_at": dt.date.today().isoformat(),
        "value": value if value is not None else existing.get("value", 0.0),
        "value_as_of": as_of or existing.get("value_as_of", ""),
        "value_method": existing.get("value_method", ""),
        "deposits": journal["deposits"],
        "dividends": journal["dividends"],
        "interests": journal["interests"],
        "fees": journal["fees"],
        "fee_entries": journal.get("fee_entries", []),
        "deposit_entries": journal.get("deposit_entries", []),
        "deposits_by_year": journal["deposits_by_year"],
        # The journal gives shares and prices; the geography and the short
        # name were declared by hand and are in no document. Rebuilding from
        # the journal alone wiped them -- and the geographic split with
        # them -- on every `--finpension` until 02.10.2026.
        "holdings": {isin: {**{k: v for k, v in
                               (existing.get("holdings") or {}).get(isin, {}).items()
                               if k in ("geography", "short")},
                            **holding}
                     for isin, holding in holdings(journal).items()},
        "cash": (journal["entries"][-1]["balance"]
                 if journal["entries"] else 0.0),
        "first": journal["first"],
        "last": journal["last"],
        "yearly": [[d.isoformat(), v] for d, v in existing.get("yearly", [])],
        "proxy_series": {name: [[d.isoformat(), v] for d, v in series]
                         for name, series
                         in (existing.get("proxy_series") or {}).items()},
        "proxies": existing.get("proxies") or {},
    }
    path = Path(snapshot_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return snapshot


def parse_report_value(path: Path | str) -> float | None:
    """The portfolio value from a performance report, as of its date.

    The overview page (the one headed "Rendement") reads "Portfolio 1
    <id> <début> <rendement> <depuis le début> <valeur>" -- the value is
    the last amount on that page. The cover also mentions the portfolio
    id, so a page with "Portfolio 1" alone is not enough.
    """
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:3]:
            text = page.extract_text() or ""
            if "Rendement" not in text:
                continue
            numbers = re.findall(r"[\d'’]+\.\d{2}", text)
            if numbers:
                return float(numbers[-1].replace("'", "").replace("’", ""))
    return None
