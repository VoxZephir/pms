"""The brokerage's own transaction history: the CSV IBKR exports.

The connector gives *states* and one year of daily NAV -- it made the app
believe the account opened in August 2025. The exported "Transaction
History" (`inbox/ibkr/*.csv`) goes back to the first deposit, September
2023: every deposit and withdrawal, every trade with its commission,
dividends, US withholding tax, interest. Three things come out of it:

* the flows of the whole history (the app knew one deposit of five);
* the costs since the opening, not since the connector's horizon;
* the positions and the cash day by day, from which the value of the
  account can be rebuilt with weekly prices where the broker's daily NAV
  does not reach -- the April 2025 tariff crash the account went through.

Amounts in the file are in the base currency (CHF); quantities and prices
in the instrument's own.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from pathlib import Path

DEPOSIT, WITHDRAWAL = "Deposit", "Withdrawal"
BUY, SELL = "Buy", "Sell"
FX = "Forex Trade Component"
DIVIDEND, WITHHOLDING = "Dividend", "Foreign Tax Withholding"
CREDIT_INTEREST, DEBIT_INTEREST = "Credit Interest", "Debit Interest"


def _num(value: str | None) -> float | None:
    value = (value or "").strip()
    if value in ("", "-"):
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def parse(path: Path | str) -> list[dict]:
    """The "Transaction History" rows, oldest first.

    The export is several CSV tables in one file (Statement, Summary,
    Transaction History), each with its own header row; only the last one
    is read. IBKR writes it in UTF-8 that some tools save as Latin-1, so
    both are accepted.
    """
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    header = None
    rows = []
    for record in csv.reader(io.StringIO(text)):
        if len(record) < 3 or record[0] != "Transaction History":
            continue
        if record[1] == "Header":
            header = [h.strip() for h in record[2:]]
            continue
        if record[1] != "Data" or header is None:
            continue
        cells = dict(zip(header, record[2:]))
        try:
            day = dt.date.fromisoformat(cells.get("Date", "").strip())
        except ValueError:
            continue
        rows.append({
            "date": day,
            "description": cells.get("Description", "").strip(),
            "type": cells.get("Transaction Type", "").strip(),
            "symbol": cells.get("Symbol", "").strip(),
            "quantity": _num(cells.get("Quantity")),
            "price": _num(cells.get("Price")),
            "currency": cells.get("Price Currency", "").strip(),
            "gross": _num(cells.get("Gross Amount")) or 0.0,
            "commission": _num(cells.get("Commission")) or 0.0,
            "net": _num(cells.get("Net Amount")) or 0.0,
        })
    # The file is newest first; within a day, keep the file's order reversed
    # too, so a deposit precedes the trades it funded.
    rows.reverse()
    rows.sort(key=lambda r: r["date"])
    return rows


def flows(rows: list[dict]) -> list[tuple[dt.date, float]]:
    """Deposits (+) and withdrawals (-), in CHF, by the broker's date."""
    return [(r["date"], r["net"]) for r in rows if r["type"] in (DEPOSIT, WITHDRAWAL)]


def costs(rows: list[dict]) -> list[dict]:
    """What the broker kept: commissions, the spread of its automatic
    conversions, and the US tax withheld on dividends.

    The conversions it books in pairs (FXCONV: the same dollars bought and
    sold back at two prices within the second, no commission) cost their
    net "gross" -- 2.50 CHF on 28.09.2026, exactly the spread. A lone
    conversion's gross is a currency gain or loss, not a fee, and stays out.
    """
    out = []
    # Withholding nets per dividend: DBMF's of 29.12.2023 is two charges and
    # a refund, 2.69 CHF in all -- not the 5.71 of the charges alone.
    withheld: dict[tuple, float] = {}
    for r in rows:
        if r["type"] == WITHHOLDING:
            key = (r["date"], r["symbol"])
            withheld[key] = withheld.get(key, 0.0) - r["net"]
    for (day, symbol), amount in withheld.items():
        if amount > 0.005:
            out.append({"date": day, "kind": "impôt à la source US",
                        "label": f"Retenue sur dividende {symbol}",
                        "amount_chf": round(amount, 2)})
    for r in rows:
        if r["commission"] and abs(r["commission"]) >= 0.005:
            label = r["description"]
            if r["type"] in (BUY, SELL):
                label = (f"{'Achat' if r['type'] == BUY else 'Vente'} "
                         f"{abs(r['quantity'] or 0):g} {r['symbol']}")
            elif r["type"] == FX:
                label = f"Conversion {r['symbol']} {abs(r['quantity'] or 0):,.2f}".replace(",", "’")
            out.append({"date": r["date"],
                        "kind": ("commission de change" if r["type"] == FX
                                 else "commission d'achat" if r["type"] == BUY
                                 else "commission de vente" if r["type"] == SELL
                                 else "commission"),
                        "label": label, "amount_chf": round(-r["commission"], 2)})

    # Paired conversions without commission: same day, same pair, both
    # directions, the dollars nearly netting out.
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        if r["type"] == FX and not r["commission"] and r["quantity"]:
            groups.setdefault((r["date"], r["symbol"]), []).append(r)
    for (day, pair), legs in groups.items():
        bought = sum(r["quantity"] for r in legs if r["quantity"] > 0)
        sold = -sum(r["quantity"] for r in legs if r["quantity"] < 0)
        if bought and sold and abs(bought - sold) < 0.01 * max(bought, sold):
            spread = -sum(r["gross"] for r in legs)
            if spread > 0.005:
                out.append({"date": day, "kind": "écart de change automatique",
                            "label": f"Aller-retour {pair} {max(bought, sold):,.2f}".replace(",", "’"),
                            "amount_chf": round(spread, 2)})
    return sorted(out, key=lambda c: c["date"])


def income(rows: list[dict]) -> list[dict]:
    """Dividends and interest, net of the interest the broker charged."""
    out = []
    for r in rows:
        if r["type"] == DIVIDEND:
            out.append({"date": r["date"], "kind": "dividende",
                        "label": r["symbol"], "amount_chf": round(r["net"], 2)})
        elif r["type"] in (CREDIT_INTEREST, DEBIT_INTEREST):
            out.append({"date": r["date"], "kind": "intérêts",
                        "label": "intérêts", "amount_chf": round(r["net"], 2)})
    return out


def positions(rows: list[dict]) -> list[dict]:
    """Holdings and cash after each day with activity.

    Shares per symbol (with their currency); cash per currency, from the
    native legs: a trade moves its price currency, a conversion "A.B" adds
    the quantity to A and takes quantity × price from B. Commissions,
    dividends, taxes and interest are booked in CHF, their base amount --
    the value in francs is the same, only the currency pocket differs.
    """
    shares: dict[str, float] = {}
    currency_of: dict[str, str] = {}
    cash: dict[str, float] = {"CHF": 0.0}
    out = []
    by_day: dict[dt.date, list[dict]] = {}
    for r in rows:
        by_day.setdefault(r["date"], []).append(r)
    for day in sorted(by_day):
        for r in by_day[day]:
            kind = r["type"]
            if kind in (DEPOSIT, WITHDRAWAL):
                cash["CHF"] += r["net"]
            elif kind in (BUY, SELL) and r["quantity"] and r["price"] is not None:
                shares[r["symbol"]] = shares.get(r["symbol"], 0.0) + r["quantity"]
                currency_of[r["symbol"]] = r["currency"]
                cash[r["currency"]] = cash.get(r["currency"], 0.0) \
                    - r["quantity"] * r["price"]
                cash["CHF"] += r["commission"]
            elif kind == FX and r["quantity"] and r["price"] is not None and "." in r["symbol"]:
                base, quote = r["symbol"].split(".", 1)
                cash[base] = cash.get(base, 0.0) + r["quantity"]
                cash[quote] = cash.get(quote, 0.0) - r["quantity"] * r["price"]
                cash["CHF"] += r["commission"]
            elif kind in (DIVIDEND, WITHHOLDING, CREDIT_INTEREST, DEBIT_INTEREST):
                cash["CHF"] += r["net"]
        out.append({
            "date": day,
            "shares": {s: q for s, q in shares.items() if abs(q) > 1e-9},
            "currency": dict(currency_of),
            "cash": {c: round(v, 6) for c, v in cash.items() if abs(v) > 1e-6},
        })
    return out


def journal(path: Path | str) -> dict:
    """What the snapshot keeps of the export: JSON-ready, dated."""
    rows = parse(path)
    if not rows:
        return {}

    def iso(items):
        return [{**item, "date": item["date"].isoformat()} for item in items]

    return {
        "source": Path(path).name,
        "first": rows[0]["date"].isoformat(),
        "last": rows[-1]["date"].isoformat(),
        "flows": [[d.isoformat(), round(a, 2)] for d, a in flows(rows)],
        "costs": iso(costs(rows)),
        "income": iso(income(rows)),
        "positions": [{"date": p["date"].isoformat(), "shares": p["shares"],
                       "currency": p["currency"], "cash": p["cash"]}
                      for p in positions(rows)],
    }


def rebuild(positions_: list[dict], prices: dict[str, list],
            until: dt.date) -> list[tuple[dt.date, float]]:
    """The account's value at each weekly price point before `until`.

    Weekly bars are stamped on Monday and close on Friday: a point is valued
    on that Friday, with the holdings and cash of that day, each share at
    the week's close and dollars at the week's USD.CHF close. A week holding
    an instrument without a price series is skipped rather than guessed --
    the app reads from the ledger's first day (July 2024), when the account
    held RSST alone.

    Checked against the broker's exact NAV where both exist.
    """
    fx = dict(prices.get("USD.CHF", []))
    weekly = sorted({d for series in prices.values() for d, _ in series})
    holdings = sorted(positions_, key=lambda p: p["date"])
    by_symbol = {s: dict(series) for s, series in prices.items()}
    out = []
    for monday in weekly:
        friday = dt.date.fromisoformat(monday) + dt.timedelta(days=4)
        if friday >= until or monday not in fx:
            continue
        state = None
        for p in holdings:
            if dt.date.fromisoformat(p["date"]) <= friday:
                state = p
        if state is None:
            continue
        rate = fx[monday]
        value = 0.0
        priced = True
        for symbol, shares in state["shares"].items():
            close = by_symbol.get(symbol, {}).get(monday)
            if close is None:
                priced = False
                break
            currency = state["currency"].get(symbol, "USD")
            value += shares * close * (rate if currency == "USD" else 1.0)
        if not priced:
            continue
        for currency, amount in state["cash"].items():
            value += amount * (rate if currency == "USD" else 1.0)
        out.append((friday, round(value, 2)))
    return out


def summary_cash(path: Path | str) -> float | None:
    """The "final cash" the export prints, in CHF -- a check on `positions`."""
    raw = Path(path).read_bytes().decode("utf-8-sig", errors="replace")
    for record in csv.reader(io.StringIO(raw)):
        if len(record) >= 4 and record[0] == "Summary" and "finale" in record[2]:
            return _num(record[3])
    return None
