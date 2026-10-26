"""Revolut's crypto statement -> a savings pocket (`data/crypto.json`).

What the export is, measured on a real one (fr-ch):

* **The quantities lost their decimal point.** 0.01234567 ETH prints
  "1,234,567", 12.345678 USDT "12,345,678": the significant digits, leading
  and trailing zeros dropped, grouped by three. A trade also prints its
  price and value, so its quantity is the digits scaled to the power of ten
  closest to value / price -- exact, the digits are all there. (A few rows
  are formatted properly, "12 345,6789" with a narrow space: read as is.)
* **A staking reward prints no price**, so its scale is lost. Rewards come
  at a steady rate on a known staked amount: each is scaled to the power of
  ten closest to the expected reward (staked x yield x days since the last
  one), the yield itself fitted on the rewards (`_rewards`). Regular rewards
  (SOL's, per epoch) come out clean; more dispersed ones (ETH's) can leave
  about one in seven ambiguous by a factor of ten. A quantity read in the
  Revolut app (`--crypto-qty ETH=0.5`) calibrates the total exactly.
* **The value includes the fee**: the bank account was debited the value.
* Same double-encoded UTF-8 as the account statement (`revolut._text`).

Valued with public prices, fixed at capture like the IBKR snapshot -- the
app never reads one live: Binance's daily closes in USD (full history, no
key), in francs at the ECB's rate of the day (frankfurter.app).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import re
import statistics
import urllib.request
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

from .revolut import _text

BINANCE = ("https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1d"
           "&startTime={start}&limit=1000")
FX = "https://api.frankfurter.app/{start}..{end}?from=USD&to=CHF"
STABLE = {"USDT", "USDC", "BUSD", "DAI"}  # one dollar

MONTHS = {"janv": 1, "jan": 1, "févr": 2, "fevr": 2, "feb": 2, "mars": 3, "mar": 3,
          "avr": 4, "apr": 4, "mai": 5, "may": 5, "juin": 6, "jun": 6, "juil": 7,
          "jul": 7, "août": 8, "aout": 8, "aug": 8, "sept": 9, "sep": 9, "oct": 10,
          "nov": 11, "déc": 12, "dec": 12}
IN = {"Achat": "buy", "Buy": "buy", "Réception": "in", "Receive": "in"}
OUT = {"Vente": "sell", "Sell": "sell", "Envoi": "out", "Send": "out"}
STAKE = {"Mise en staking", "Stake"}
SPACES = "   "


# --- reading -----------------------------------------------------------------

def _day(value: str) -> dt.date:
    """'3 avr. 2024, 16:22:43' (or 'Oct.', the export mixes languages)."""
    day, month, year = value.split(",")[0].replace(".", "").split()
    return dt.date(int(year), MONTHS[month.lower()], int(day))


def _money(value: str) -> tuple[float | None, str]:
    if not value:
        return None, ""
    currency = ("CHF" if "CHF" in value else "EUR" if "€" in value
                else "GBP" if "£" in value else "USD" if "$" in value else "")
    number = re.sub(r"[^\d,\-]", "", value).replace(",", ".")
    return (float(number) if number else None), currency


def _proper(raw: str) -> bool:
    """Formatted with its decimal point (the narrow-space thousands)."""
    return any(c in raw for c in SPACES) or bool(
        re.fullmatch(r"\d+,\d+", raw) and not re.fullmatch(r"\d{1,3}(,\d{3})+", raw))


def _digits(raw: str) -> int:
    return int(re.sub(r"\D", "", raw) or 0)


def _scaled(digits: int, target: float) -> float:
    """`digits` times the power of ten closest to `target` (in ratio)."""
    return min((digits / 10 ** k for k in range(-6, 22)),
               key=lambda q: abs(math.log10(q / target)))


def _quantity(raw: str, estimate: float | None) -> float | None:
    raw = raw.strip()
    if _proper(raw):
        return float(raw.translate({ord(c): None for c in SPACES}).replace(",", "."))
    digits = _digits(raw)
    return _scaled(digits, estimate) if digits and estimate else None


def parse(path: str | Path) -> list[dict]:
    """One dict per row: symbol, kind, day, quantity (None if unknowable),
    the raw digits, price, value and fee in their currency."""
    rows = []
    for row in csv.DictReader(io.StringIO(_text(Path(path)), newline="")):
        kind = (row.get("Type") or "").replace(" ", " ").strip()
        price, currency = _money(row.get("Price", ""))
        value, _ = _money(row.get("Value", ""))
        fee, _ = _money(row.get("Fees", ""))
        raw = (row.get("Quantity") or "").strip()
        rows.append({
            "symbol": row["Symbol"].strip(), "kind": kind, "day": _day(row["Date"]),
            "quantity": _quantity(raw, value / price if value and price else None),
            "digits": 0 if _proper(raw) else _digits(raw),
            "price": price, "value": value, "fee": fee or 0.0, "currency": currency,
        })
    rows.sort(key=lambda r: r["day"])  # stable: same-day rows keep file order
    return rows


def _is_staking_reward(r: dict) -> bool:
    return "staking" in r["kind"].lower() and ("Récompense" in r["kind"]
                                               or "reward" in r["kind"].lower())


def _is_reward(r: dict) -> bool:
    return "Récompense" in r["kind"] or "reward" in r["kind"].lower()


# --- francs ------------------------------------------------------------------

def _rates(rows: list[dict], fallback) -> callable:
    """CHF per unit of a currency on a day.

    Revolut prices the same coin in CHF minutes after a purchase in EUR
    (the staking move): the ratio of the two prices is the day's rate. With
    no such pair, `fallback(currency, day)`.
    """
    pairs: dict[str, list[tuple[dt.date, float]]] = defaultdict(list)
    for a in rows:
        if a["currency"] in ("", "CHF") or not a["price"]:
            continue
        for b in rows:
            if (b["symbol"] == a["symbol"] and b["currency"] == "CHF" and b["price"]
                    and abs((b["day"] - a["day"]).days) <= 1):
                pairs[a["currency"]].append((a["day"], b["price"] / a["price"]))
                break

    def rate(currency: str, day: dt.date) -> float | None:
        if currency == "CHF":
            return 1.0
        near = [r for d, r in pairs.get(currency, []) if abs((d - day).days) <= 2]
        if near:
            return near[0]
        return fallback(currency, day) if fallback else None
    return rate


def ledger_rates(ledger_path: Path):
    """CHF per unit from every conversion in the ledger, nearest in time."""
    from .analysis import is_fx_leg
    from .ledger import Ledger
    points: dict[str, list[tuple[dt.date, float]]] = defaultdict(list)
    for t in Ledger.load(ledger_path).transactions.values():
        if is_fx_leg(t) and t.currency != "CHF" and t.fx_counter_amount and t.amount:
            points[t.currency].append((t.date, t.fx_counter_amount / abs(t.amount)))
    for series in points.values():
        series.sort()

    def rate(currency: str, day: dt.date) -> float | None:
        series = points.get(currency)
        if not series:
            return None
        i = bisect_left([d for d, _ in series], day)
        near = [series[j] for j in (i - 1, i) if 0 <= j < len(series)]
        return min(near, key=lambda p: abs((p[0] - day).days))[1]
    return rate


# --- staking -----------------------------------------------------------------

def _rewards(rows: list[dict], symbol: str, target: float | None = None) -> dict:
    """Each staking reward of `symbol` with its decimal point restored.

    Expected reward = staked x yield x days since the previous reward; each
    reward takes the power of ten closest to it, and the yield is refitted
    as the median of what that implies, until it settles. `target` -- the
    total read in the app -- rescales them all to match it.
    """
    staked_moves = [(r["day"], r["quantity"]) for r in rows
                    if r["symbol"] == symbol and r["kind"] in STAKE and r["quantity"]]
    rewards = [r for r in rows if r["symbol"] == symbol and _is_staking_reward(r)
               and (r["digits"] or r["quantity"])]
    if not rewards or not staked_moves:
        return {"days": [], "quantities": [], "yield": None, "ambiguous": 0}

    def staked(day, earned):
        return sum(q for d, q in staked_moves if d <= day) + earned

    rate, quantities, ratios = 0.03, [], []
    for _ in range(8):
        quantities, ratios, earned, previous = [], [], 0.0, None
        for r in rewards:
            gap = max((r["day"] - previous).days, 1) if previous else 1
            previous = r["day"]
            base = staked(r["day"], earned)
            if base <= 0:
                quantities.append(0.0)
                continue
            q = r["quantity"] if not r["digits"] else _scaled(r["digits"], base * rate * gap / 365)
            quantities.append(q)
            ratios.append(q / (base * gap / 365))
            earned += q
        fitted = statistics.median(ratios) if ratios else rate
        if abs(fitted - rate) < 1e-6:
            break
        rate = fitted
    ambiguous = sum(1 for x in ratios if abs(math.log10(x / rate)) > 0.4)
    if target is not None and sum(quantities) > 0:
        factor = max(target, 0.0) / sum(quantities)
        quantities = [q * factor for q in quantities]
    return {"days": [r["day"] for r in rewards], "quantities": quantities,
            "yield": rate, "ambiguous": ambiguous}


# --- the pocket --------------------------------------------------------------

def ledger(rows: list[dict], fallback=None, actual: dict | None = None,
           until: dt.date | None = None) -> dict:
    """Quantities day by day, the money in and out, fees, and the rewards.

    Flows, in francs, from the pocket's point of view: a purchase or a coin
    received is money in, a sale or a send money out. Rewards are return,
    never flows. `actual` -- {symbol: (day, quantity)} read in the app --
    calibrates the staking rewards so the quantity on that day matches.
    """
    rate = _rates(rows, fallback)
    events: list[tuple[dt.date, str, float]] = []  # (day, symbol, +/- quantity)
    flows: dict[dt.date, float] = defaultdict(float)
    fees: list[tuple[dt.date, float, str]] = []
    cost: dict[str, float] = defaultdict(float)
    held: dict[str, float] = defaultdict(float)
    sent = []
    for r in rows:
        kind, sym = IN.get(r["kind"]) or OUT.get(r["kind"]), r["symbol"]
        if _is_reward(r) and not _is_staking_reward(r) and r["quantity"]:
            events.append((r["day"], sym, r["quantity"]))  # a gift, read as is
            held[sym] += r["quantity"]
        if kind is None or r["quantity"] is None:
            continue
        fx = rate(r["currency"], r["day"]) or 0.0
        value = (r["value"] or 0.0) * fx
        if r["fee"]:
            fees.append((r["day"], round(r["fee"] * fx, 2), f"{sym} · {r['kind'].lower()}"))
        if kind in ("buy", "in"):
            events.append((r["day"], sym, r["quantity"]))
            flows[r["day"]] += value
            cost[sym] += value
            held[sym] += r["quantity"]
            continue
        # Out: Revolut takes the fee of a send in the coin itself.
        fee_q = r["fee"] / r["price"] if kind == "out" and r["price"] else 0.0
        gone = r["quantity"] + fee_q
        cost[sym] -= cost[sym] * (min(gone / held[sym], 1.0) if held[sym] else 0.0)
        held[sym] = max(held[sym] - gone, 0.0)
        events.append((r["day"], sym, -gone))
        flows[r["day"]] -= value
        if kind == "out":
            sent.append({"day": r["day"].isoformat(), "symbol": sym,
                         "quantity": round(r["quantity"], 8), "value_chf": round(value, 2),
                         "fee_chf": round(r["fee"] * fx, 2)})

    rewards = {}
    for sym in sorted({r["symbol"] for r in rows if _is_staking_reward(r)}):
        target = None
        if actual and sym in actual:
            day, quantity = actual[sym]
            bought = sum(q for d, s, q in events if s == sym and d <= day)
            target = quantity - bought
        fit = _rewards(rows, sym, target)
        for day, q in zip(fit["days"], fit["quantities"]):
            events.append((day, sym, q))
            held[sym] += q
        rewards[sym] = {"count": len(fit["days"]), "quantity": round(sum(fit["quantities"]), 10),
                        "yield": round(fit["yield"], 4) if fit["yield"] else None,
                        "ambiguous": fit["ambiguous"], "calibrated": target is not None}
    unread = {r["symbol"] for r in rows
              if _is_reward(r) and not _is_staking_reward(r) and r["quantity"] is None}
    return {"events": sorted(events), "flows": sorted(flows.items()), "fees": fees,
            "cost": {s: round(c, 2) for s, c in cost.items() if held.get(s, 0) > 1e-9},
            "held": {s: q for s, q in held.items() if q > 1e-12},
            "sent": sent, "rewards": rewards, "unread": sorted(unread)}


# --- prices ------------------------------------------------------------------

def _get(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "pms"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def fetch_market(symbols, start: dt.date, end: dt.date) -> dict[str, list]:
    """{symbol: [(day, CHF price)]} -- Binance closes in USD, ECB USD->CHF."""
    fx_raw = _get(FX.format(start=(start - dt.timedelta(days=7)).isoformat(),
                            end=end.isoformat()))["rates"]
    fx = sorted((dt.date.fromisoformat(d), r["CHF"]) for d, r in fx_raw.items())
    fx_days = [d for d, _ in fx]

    def usd_chf(day):
        i = bisect_right(fx_days, day)
        return fx[i - 1][1] if i else fx[0][1]

    market = {}
    for sym in sorted(set(symbols)):
        closes = []
        if sym in STABLE:
            day = start
            while day <= end:
                closes.append((day, 1.0))
                day += dt.timedelta(days=1)
        else:
            cursor = int(dt.datetime(start.year, start.month, start.day).timestamp() * 1000)
            while True:
                try:
                    batch = _get(BINANCE.format(symbol=sym, start=cursor))
                except OSError:
                    break  # not listed on Binance: no value, said so
                if not batch:
                    break
                closes += [(dt.datetime.utcfromtimestamp(k[0] / 1000).date(), float(k[4]))
                           for k in batch]
                if len(batch) < 1000:
                    break
                cursor = batch[-1][0] + 86_400_000
        if closes:
            market[sym] = [(d, round(p * usd_chf(d), 10)) for d, p in closes]
    return market


def _price(series: list, day: dt.date) -> float | None:
    if not series:
        return None
    i = bisect_right([d for d, _ in series], day)
    return series[i - 1][1] if i else None


# --- the snapshot ------------------------------------------------------------

def capture(statement: Path, out: Path, ledger_path: Path | None = None,
            market: dict | None = None, actual: dict | None = None,
            until: dt.date | None = None) -> dict:
    """Read the statement, price it day by day, write the snapshot.

    `actual` -- {symbol: (day, quantity)} -- is kept in the snapshot, so a
    later capture without it stays calibrated.
    """
    out = Path(out)
    previous = load(out) or {}
    if actual is None and previous.get("calibration"):
        actual = {s: (dt.date.fromisoformat(d), q)
                  for s, (d, q) in previous["calibration"].items()}
    rows = parse(statement)
    fallback = ledger_rates(ledger_path) if ledger_path and Path(ledger_path).exists() else None
    book = ledger(rows, fallback, actual)
    first = min(r["day"] for r in rows)
    until = until or dt.date.today()
    symbols = {s for _, s, _ in book["events"]}
    market = fetch_market(symbols, first, until) if market is None else market

    daily = []
    day, i, held = first, 0, defaultdict(float)
    events = book["events"]
    while day <= until:
        while i < len(events) and events[i][0] <= day:
            held[events[i][1]] += events[i][2]
            i += 1
        value = sum(q * (_price(market.get(s), day) or 0.0)
                    for s, q in held.items() if q > 1e-12)
        daily.append([day.isoformat(), round(value, 2)])
        day += dt.timedelta(days=1)

    positions = []
    for sym, qty in sorted(book["held"].items()):
        price = _price(market.get(sym), until)
        positions.append({"symbol": sym, "quantity": round(qty, 10), "price_chf": price,
                          "value_chf": round(qty * price, 2) if price is not None else None,
                          "cost_chf": book["cost"].get(sym, 0.0),
                          "rewards": book["rewards"].get(sym)})
    snapshot = {
        "captured_at": dt.datetime.now().isoformat(timespec="seconds"),
        "as_of": until.isoformat(),
        "source": f"{Path(statement).name} · cours Binance (USD) × BCE (USD/CHF)",
        "positions": positions,
        "value_chf": round(sum(p["value_chf"] or 0 for p in positions), 2),
        "cost_chf": round(sum(p["cost_chf"] for p in positions), 2),
        "daily": daily,
        "flows": [[d.isoformat(), round(a, 2)] for d, a in book["flows"]],
        "fees": [[d.isoformat(), a, label] for d, a, label in book["fees"]],
        "sent": book["sent"],
        "rewards": book["rewards"],
        "unread": book["unread"],
        "calibration": ({s: [d.isoformat(), q] for s, (d, q) in actual.items()}
                        if actual else {}),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    return snapshot


def load(path: Path) -> dict | None:
    """The snapshot, its series as dates. None if absent or unreadable."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    raw["daily_series"] = [(dt.date.fromisoformat(d), v) for d, v in raw.get("daily", [])]
    raw["flow_entries"] = [(dt.date.fromisoformat(d), a) for d, a in raw.get("flows", [])]
    raw["fee_entries"] = [(dt.date.fromisoformat(d), a, label)
                          for d, a, label in raw.get("fees", [])]
    return raw


def value_at(snapshot: dict | None, day: dt.date) -> float:
    """The pocket's value on `day`: nothing before its first purchase, the
    last captured value after the capture."""
    series = (snapshot or {}).get("daily_series") or []
    if not series or day < series[0][0]:
        return 0.0
    i = bisect_right([d for d, _ in series], day)
    return series[i - 1][1]
