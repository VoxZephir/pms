"""IBKR without the connector: the Flex Web Service.

The connector needs a Claude Code session, and it signs out: the savings
went stale whenever nobody ran `/epargne`. A Flex Query is a report the
account holder defines once in the IBKR portal; the Flex Web Service serves
it to whoever holds the query's token, from a script. `python -m pms --ibkr`
fetches it and folds it into `data/ibkr.json` the way a capture does --
appending only what is newer than the snapshot:

* the broker's NAV per day (section "Net Asset Value (NAV) in Base") -> `nav`;
* the positions and cash at the statement's end -> `positions`, `cash`,
  `account`; the position's price -> `nav_daily` (every day's, when the
  query has "Prior Period Positions"), which the fund / dollar split reads;
* deposits, dividends, withholding tax and interest ("Cash Transactions"),
  commissions ("Trades") -> the journal the transaction-history export
  started, after its last day: the flows stay the broker's own record.

The token and the query id live in `data/ibkr_flex.json`, git-ignored;
`data/ibkr_flex.example.json` shows the shape and `docs/epargne.md` how to
set the query up. The token is never printed and never put in an error.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SEND = ("https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/"
        "SendRequest?t={token}&q={query}&v=3")
# "Statement generation in progress", "too many requests", "server busy":
# worth waiting for. Anything else (expired token, unknown query) is not.
RETRY = {"1009", "1018", "1019", "1021"}
WITHHOLDING = "impôt à la source US"


class FlexError(Exception):
    """A Flex statement that could not be had -- the message is safe to print."""


def _http(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "pms/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def _call(http, url: str) -> str:
    try:
        return http(url)
    except OSError as exc:
        # urllib's errors carry a status or a socket reason, never the URL --
        # the reason alone, to keep the token out of any message.
        raise FlexError(f"service Flex injoignable ({getattr(exc, 'reason', None) or type(exc).__name__})") from None


def _status(text: str) -> tuple[str, str, str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise FlexError("réponse du service Flex illisible") from None
    return (root.findtext("Status") or "", root.findtext("ErrorCode") or "",
            root.findtext("ErrorMessage") or "")


def download(token: str, query_id: str, http=_http, wait=time.sleep,
             tries: int = 12) -> str:
    """The statement's XML: request it, then fetch it once it is generated."""
    quoted = urllib.parse.quote(str(token), safe="")
    reply = _call(http, SEND.format(token=quoted, query=urllib.parse.quote(str(query_id), safe="")))
    status, code, message = _status(reply)
    if status != "Success":
        raise FlexError(f"requête refusée par IBKR ({code} : {message})")
    root = ET.fromstring(reply)
    reference = root.findtext("ReferenceCode") or ""
    url = root.findtext("Url") or ""
    if not reference or not url.startswith("https://"):
        raise FlexError("réponse du service Flex incomplète")
    for attempt in range(tries):
        text = _call(http, f"{url}?t={quoted}&q={urllib.parse.quote(reference, safe='')}&v=3")
        if "<FlexQueryResponse" in text:
            return text
        status, code, message = _status(text)
        if code not in RETRY:
            raise FlexError(f"relevé refusé par IBKR ({code} : {message})")
        wait(min(5 * (attempt + 1), 20))
    raise FlexError("relevé Flex toujours en préparation, réessayer dans quelques minutes")


def _date(text: str | None) -> dt.date | None:
    """'20251001', '2025-10-01', '20251001;153000' -> a date."""
    digits = re.sub(r"\D", "", (text or "")[:10])[:8]
    try:
        return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def _num(text: str | None) -> float | None:
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _detail(element) -> bool:
    """One row per event: the detail rows, not their summaries."""
    return element.get("levelOfDetail") in (None, "", "DETAIL", "EXECUTION")


def parse(xml_text: str) -> dict:
    """What the statement says, in the snapshot's terms (CHF, dated)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise FlexError("relevé Flex illisible") from None
    statement = root.find(".//FlexStatement")
    if statement is None:
        raise FlexError("le relevé Flex ne contient aucun compte")
    info = statement.find(".//AccountInformation")
    base = (info.get("currency") if info is not None else None) or "CHF"

    rates: dict[str, tuple[dt.date, float]] = {}
    for e in statement.iter("ConversionRate"):
        day, rate = _date(e.get("reportDate")), _num(e.get("rate"))
        if e.get("toCurrency") == base and day and rate:
            if e.get("fromCurrency") not in rates or day >= rates[e.get("fromCurrency")][0]:
                rates[e.get("fromCurrency")] = (day, rate)

    def to_base(currency: str | None, row_rate: float | None = None) -> float | None:
        if not currency or currency == base:
            return 1.0
        return row_rate or (rates.get(currency) or (None, None))[1]

    nav = sorted({(day, round(total, 2)) for e in statement.iter("EquitySummaryByReportDateInBase")
                  if (day := _date(e.get("reportDate"))) and (total := _num(e.get("total"))) is not None})

    positions, holding_shares, holding_currency = [], {}, {}
    # A query broken out by day repeats the positions for every date: the
    # holdings are the last day's.
    open_rows = [e for e in statement.iter("OpenPosition")
                 if e.get("levelOfDetail") in (None, "", "SUMMARY")]
    last_day = max((d for e in open_rows if (d := _date(e.get("reportDate")))), default=None)
    for e in open_rows:
        if last_day and _date(e.get("reportDate")) not in (None, last_day):
            continue
        symbol, quantity = e.get("symbol") or "", _num(e.get("position"))
        if not symbol or not quantity:
            continue
        rate = to_base(e.get("currency"), _num(e.get("fxRateToBase")))
        value = _num(e.get("positionValue")) or 0.0
        pnl = _num(e.get("fifoPnlUnrealized")) or 0.0
        positions.append({
            "name": symbol, "currency": e.get("currency") or base, "quantity": quantity,
            "market_price": _num(e.get("markPrice")),
            "market_value": round(value, 2),
            "market_value_chf": round(value * rate, 2) if rate else None,
            "unrealized_pnl": round(pnl, 2),
            "unrealized_pnl_chf": round(pnl * rate, 2) if rate else None,
            "unrealized_pnl_pct": round(pnl / (value - pnl) * 100, 2) if value - pnl else None,
        })
        holding_shares[symbol] = quantity
        holding_currency[symbol] = e.get("currency") or base

    cash, base_cash = [], None
    for e in statement.iter("CashReportCurrency"):
        currency, amount = e.get("currency"), _num(e.get("endingCash"))
        if amount is None or not currency:
            continue
        if currency == "BASE_SUMMARY":
            base_cash = round(amount, 2)
        else:
            cash.append({"currency": currency, "amount": round(amount, 2)})

    flows, income, costs = [], [], []
    withheld: dict[tuple, float] = {}
    for e in statement.iter("CashTransaction"):
        if not _detail(e):
            continue
        day = _date(e.get("dateTime") or e.get("reportDate") or e.get("settleDate"))
        amount, rate = _num(e.get("amount")), to_base(e.get("currency"), _num(e.get("fxRateToBase")))
        if not day or amount is None or not rate:
            continue
        chf = round(amount * rate, 2)
        kind, symbol = e.get("type") or "", e.get("symbol") or ""
        if kind == "Deposits/Withdrawals":
            flows.append((day, chf))
        elif kind in ("Dividends", "Payment In Lieu Of Dividends"):
            income.append({"date": day, "kind": "dividende", "label": symbol, "amount_chf": chf})
        elif kind == "Withholding Tax":
            withheld[(day, symbol)] = withheld.get((day, symbol), 0.0) - chf
        elif "Interest" in kind:
            income.append({"date": day, "kind": "intérêts", "label": "intérêts", "amount_chf": chf})
        elif kind in ("Other Fees", "Commission Adjustments") and chf:
            costs.append({"date": day, "kind": "frais", "label": e.get("description") or kind,
                          "amount_chf": round(-chf, 2)})
    for (day, symbol), amount in withheld.items():
        if amount > 0.005:
            costs.append({"date": day, "kind": WITHHOLDING,
                          "label": f"Retenue sur dividende {symbol}", "amount_chf": round(amount, 2)})

    for e in statement.iter("Trade"):
        if not _detail(e):
            continue
        commission = _num(e.get("ibCommission"))
        day = _date(e.get("tradeDate") or e.get("dateTime"))
        if not commission or not day:
            continue
        currency = e.get("ibCommissionCurrency") or e.get("currency")
        rate = to_base(currency, _num(e.get("fxRateToBase")) if currency == e.get("currency") else None)
        if not rate:
            continue
        quantity, symbol = abs(_num(e.get("quantity")) or 0.0), e.get("symbol") or ""
        if e.get("assetCategory") == "CASH":
            kind, label = "commission de change", f"Conversion {symbol} {quantity:,.2f}".replace(",", "’")
        else:
            buying = (e.get("buySell") or "").upper().startswith("BUY")
            kind = "commission d'achat" if buying else "commission de vente"
            label = f"{'Achat' if buying else 'Vente'} {quantity:g} {symbol}"
        costs.append({"date": day, "kind": kind, "label": label,
                      "amount_chf": round(-commission * rate, 2)})

    end = _date(statement.get("toDate")) or (nav[-1][0] if nav else None)
    # The fund / dollar split reads the price of the one fund held: every
    # day's where the query has prior-period positions, the closing mark.
    main = max(positions, key=lambda p: p["market_value_chf"] or 0.0)["name"] if positions else None
    prices = {}
    for e in statement.iter("PriorPeriodPosition"):
        day, price = _date(e.get("date")), _num(e.get("price"))
        if e.get("symbol") == main and day and price:
            prices[day] = price
    for p in positions:
        if p["name"] == main and end and p["market_price"]:
            prices[end] = p["market_price"]
    usd = (rates.get("USD") or (None, None))[1] or next(
        (_num(e.get("fxRateToBase")) for e in statement.iter("OpenPosition")
         if e.get("currency") == "USD" and _num(e.get("fxRateToBase"))), None)
    return {
        "base": base, "start": _date(statement.get("fromDate")), "end": end,
        "generated": statement.get("whenGenerated") or "",
        "nav": nav, "positions": positions, "cash": cash, "base_cash": base_cash,
        # Whether the query has the section at all: an account that holds no
        # fund has none, a query without the section says nothing.
        "has_positions": statement.find(".//OpenPositions") is not None,
        "fx_usd": usd, "prices": sorted(prices.items()),
        "flows": sorted(flows), "income": sorted(income, key=lambda e: e["date"]),
        "costs": sorted(costs, key=lambda c: c["date"]),
        "holding": ({"date": end, "shares": holding_shares, "currency": holding_currency,
                     "cash": {c["currency"]: c["amount"] for c in cash if c["amount"]}}
                    if end else None),
    }


def _captured_at(generated: str) -> str:
    """'20261008;101530' -> '2026-10-08T10:15:30'."""
    digits = re.sub(r"\D", "", generated)
    if len(digits) >= 14:
        return (f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}T"
                f"{digits[8:10]}:{digits[10:12]}:{digits[12:14]}")
    return dt.datetime.now().isoformat(timespec="seconds")


def fold(parsed: dict, ibkr_path: Path) -> dict:
    """Fold one statement into the snapshot: the capture's append-only merge
    for the NAV, the prices, the positions and the costs; the journal
    extended after its last day for the flows, the income and the holdings.
    Returns what changed."""
    from . import snapshots
    ibkr_path = Path(ibkr_path)
    raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
    if not parsed["nav"]:
        raise FlexError("le relevé Flex n'a pas de NAV : cocher la section "
                        "« Net Asset Value (NAV) in Base » dans la requête")
    account = dict(raw.get("account") or {})
    account["net_liquidation"] = parsed["nav"][-1][1]
    if parsed["base_cash"] is not None:
        account["total_cash"] = parsed["base_cash"]
    capture = {
        "captured_at": _captured_at(parsed["generated"]),
        "account": account,
        "nav": [[d.isoformat(), v] for d, v in parsed["nav"]],
        "nav_daily": [[d.isoformat(), p] for d, p in parsed["prices"]],
        "positions": parsed["positions"],
        "costs": [{**c, "date": c["date"].isoformat()} for c in parsed["costs"]],
    }
    if parsed["cash"]:
        capture["cash"] = parsed["cash"]
    if parsed["fx_usd"]:
        capture["fx_chf_per_usd"] = parsed["fx_usd"]
    report = snapshots.merge({"ibkr": capture}, ibkr_path,
                             ibkr_path.with_name("finpension.json"))["ibkr"]

    raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
    if parsed["has_positions"]:
        # A fund sold is gone: kept, its last value would still count in the
        # composition. The merge only ever adds or updates.
        held = {p["name"] for p in parsed["positions"]}
        report["sold"] = [p["name"] for p in raw.get("positions", []) if p["name"] not in held]
        raw["positions"] = [p for p in raw.get("positions", []) if p["name"] in held]
    journal = raw.get("journal")
    report["journal"] = None
    if journal:
        # Only what the journal does not hold yet: an overlapping statement
        # (the last 30 days, run daily) must not count a deposit twice.
        last = journal.get("last") or ""
        flows = [[d.isoformat(), a] for d, a in parsed["flows"] if d.isoformat() > last]
        income = [{**e, "date": e["date"].isoformat()} for e in parsed["income"]
                  if e["date"].isoformat() > last]
        journal.setdefault("flows", []).extend(flows)
        journal.setdefault("income", []).extend(income)
        holding = parsed["holding"]
        if holding and holding["date"].isoformat() > last:
            journal.setdefault("positions", []).append({**holding, "date": holding["date"].isoformat()})
        start = parsed["start"]
        # A statement that starts after the journal ends leaves days nobody
        # read: their deposits are missing, and the panel would call them
        # returns. Said, not guessed.
        gap = (start and last and start > dt.date.fromisoformat(last) + dt.timedelta(days=1))
        if parsed["end"] and parsed["end"].isoformat() > last:
            journal["last"] = parsed["end"].isoformat()
        report["journal"] = {"flows": len(flows), "income": len(income),
                             "gap": [last, start.isoformat()] if gap else None}
    ibkr_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def load_config(path: Path) -> tuple[str, str]:
    path = Path(path)
    if not path.exists():
        raise FlexError(f"pas configuré : {path.name} absent (modèle : "
                        f"data/ibkr_flex.example.json, marche à suivre : docs/epargne.md)")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        token, query = str(raw["token"]).strip(), str(raw["query_id"]).strip()
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        raise FlexError(f"{path.name} illisible : il faut \"token\" et \"query_id\"") from None
    if not token or not query or token.startswith("<"):
        raise FlexError(f"{path.name} : jeton ou numéro de requête manquant")
    return token, query


def refresh(config_path: Path, ibkr_path: Path, http=_http, wait=time.sleep) -> dict:
    """Download, read and fold the statement; the report says what moved."""
    if not Path(ibkr_path).exists():
        raise FlexError("snapshot absent : data/ibkr.json")
    token, query = load_config(config_path)
    parsed = parse(download(token, query, http=http, wait=wait))
    report = fold(parsed, ibkr_path)
    report["end"] = parsed["end"]
    report["value"] = parsed["nav"][-1][1]
    return report
