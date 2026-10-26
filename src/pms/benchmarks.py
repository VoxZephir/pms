"""Reference indices to compare the savings with (`data/benchmarks.json`).

A catalogue of public indices, captured in francs by `--benchmarks` -- fixed
at capture like every snapshot here, the app never reads one live. Yahoo
Finance's daily closes (no key), converted at the ECB's rate of the day
(frankfurter.app).

**Dividends reinvested.** A price index leaves them out: against the user's
accumulating funds, the MSCI World read ~1.8 % a year low, the SMI ~3 % --
a comparison that flattered every pocket. Each entry is therefore read as
a total return, from whichever instrument gives one cleanly:

* a total-return index where Yahoo publishes it (S&P 500: ^SP500TR);
* an accumulating ETF, whose close already holds the dividends (Euro Stoxx
  50: SXRT.DE);
* a distributing ETF's dividend-adjusted close (`adjclose`): URTH, QQQ,
  EEM, and for the SMI the UBS ETF -- the iShares one (CSSMI.SW) was
  rejected, Yahoo lists each of its dividends twice (+19.6 % for 2025
  instead of ~17.5 %);
* gold and the coins pay nothing: their price is their return.

An ETF return is net of its fees (0.1-0.6 % a year), which is what an
investor gets anyway.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from bisect import bisect_right
from pathlib import Path

YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={start}"
         "&period2={end}&interval=1d&events=div%7Csplit")
FX = "https://api.frankfurter.app/{start}..{end}?from={currency}&to=CHF"

# key, name on screen, Yahoo ticker, quote currency, what is read.
CATALOGUE = [
    ("msci_world", "MSCI World", "URTH", "USD", "iShares MSCI World ETF, dividendes réinvestis"),
    ("sp500", "S&P 500", "^SP500TR", "USD", "S&P 500 Total Return"),
    ("nasdaq100", "Nasdaq 100", "QQQ", "USD", "Invesco QQQ, dividendes réinvestis"),
    ("smi", "SMI", "SMICHA.SW", "CHF", "UBS ETF SMI, dividendes réinvestis"),
    ("eurostoxx50", "Euro Stoxx 50", "SXRT.DE", "EUR", "iShares Core Euro Stoxx 50 (capitalisant)"),
    ("emerging", "Marchés émergents", "EEM", "USD", "iShares MSCI Emerging Markets, dividendes réinvestis"),
    ("gold", "Or", "GC=F", "USD", "once d'or (contrat à terme), sans dividende"),
    ("bitcoin", "Bitcoin", "BTC-USD", "USD", "cours, sans dividende"),
    ("ethereum", "Ethereum", "ETH-USD", "USD", "cours, sans dividende"),
]
KEYS = [key for key, *_ in CATALOGUE]
DEFAULT = ("msci_world", "smi")
# What a capture reads; a snapshot without it predates the switch and holds
# price indices.
BASIS = "total_return"

# The 3a proxies that stand for a catalogue entry when it is not captured --
# price series (the 3a estimate needs prices), so only a fallback.
PROXIES = {"msci_world": "URTHxCHF", "smi": "SMI"}

# Where the 3a's proxies are kept current without the IBKR connector: its
# estimate between two readings follows them (`finpension.value_at`).
# Prices, as the series they extend. Checked against the IBKR captures over
# September 2026: the SMI and EEM closes are the same numbers, URTH × Yahoo's
# USD/CHF close within 0.05 % (the ECB's 16:00 fixing was up to 0.5 % off).
PROXY_SOURCES = {"SMI": ("^SSMI", None), "URTHxCHF": ("URTH", "CHF=X"),
                 "EEM": ("EEM", None)}


def _entry(key: str) -> tuple:
    return next(c for c in CATALOGUE if c[0] == key)


def label(key: str) -> str:
    """'S&P 500 (CHF)': converted series say so, the SMI needs not."""
    _, name, _, currency, _ = _entry(key)
    return name if currency == "CHF" else f"{name} (CHF)"


def source(key: str) -> str:
    """What the series is, in words: 'S&P 500 Total Return (^SP500TR)'."""
    _, _, ticker, _, what = _entry(key)
    return f"{what} ({ticker})"


def _get(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _fx(currency: str, start: dt.date, end: dt.date):
    if currency == "CHF":
        return lambda day: 1.0
    raw = _get(FX.format(start=(start - dt.timedelta(days=7)).isoformat(),
                         end=end.isoformat(), currency=currency))["rates"]
    points = sorted((dt.date.fromisoformat(d), r["CHF"]) for d, r in raw.items())
    days = [d for d, _ in points]

    def rate(day):
        i = bisect_right(days, day)
        return points[i - 1][1] if i else points[0][1]
    return rate


def levels(result: dict) -> list[tuple[int, float]]:
    """(timestamp, level) from one Yahoo chart result: the dividend-adjusted
    close where Yahoo gives one, the close otherwise (an index, a coin).
    Back-adjusted, so only ratios mean anything -- which is all a return is."""
    indicators = result["indicators"]
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    closes = adjusted or indicators["quote"][0]["close"]
    return [(ts, close) for ts, close in zip(result["timestamp"], closes)
            if close is not None]


def _chart(ticker: str, start: dt.date, end: dt.date) -> dict:
    stamp = lambda d: int(dt.datetime(d.year, d.month, d.day).timestamp())  # noqa: E731
    raw = _get(YAHOO.format(ticker=urllib.parse.quote(ticker, safe=""),
                            start=stamp(start), end=stamp(end + dt.timedelta(days=1))))
    return raw["chart"]["result"][0]


def _day(ts: int) -> dt.date:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()


def fetch(key: str, start: dt.date, end: dt.date) -> list[list]:
    """[[iso day, level in CHF]] for one catalogue entry."""
    _, _, ticker, currency, _ = _entry(key)
    rate = _fx(currency, start, end)
    return [[_day(ts).isoformat(), round(close * rate(_day(ts)), 6)]
            for ts, close in levels(_chart(ticker, start, end))]


def proxies(start: dt.date, end: dt.date | None = None, chart=_chart) -> dict[str, list]:
    """The 3a's proxy series from `start`: {"SMI": [[iso day, level]], ...},
    in the units of the IBKR captures they extend (plain closes)."""
    end = end or dt.date.today()

    def closes(ticker):
        result = chart(ticker, start, end)
        return {_day(ts): close for ts, close
                in zip(result["timestamp"], result["indicators"]["quote"][0]["close"])
                if close is not None}
    out = {}
    for name, (ticker, currency) in PROXY_SOURCES.items():
        prices = closes(ticker)
        if currency:
            rate = closes(currency)
            prices = {day: p * rate[day] for day, p in prices.items() if day in rate}
        out[name] = [[day.isoformat(), round(v, 4)] for day, v in sorted(prices.items())]
    return out


def capture(out: Path, start: dt.date, end: dt.date | None = None,
            fetcher=fetch) -> dict:
    """Every catalogue entry from `start`, written to `out`. An index that
    fails to download keeps its previous series rather than vanishing --
    and its previous basis with it, so a price series is never relabelled."""
    end = end or dt.date.today()
    raw = load_raw(out) or {}
    previous = raw.get("series", {})
    previous_basis = raw.get("bases") or {key: raw.get("basis", "price") for key in previous}
    series, bases, failed = {}, {}, []
    for key in KEYS:
        try:
            series[key] = fetcher(key, start, end)
            bases[key] = BASIS
        except (OSError, KeyError, ValueError, TypeError):
            failed.append(key)
            if key in previous:
                series[key] = previous[key]
                bases[key] = previous_basis.get(key, "price")
    snapshot = {"captured_at": dt.datetime.now().isoformat(timespec="seconds"),
                "source": "Yahoo Finance (clôtures ajustées des dividendes) × BCE (change)",
                "series": series, "bases": bases, "failed": failed}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return snapshot


def load_raw(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def available(snapshot_path: Path | None, finpension: dict | None) -> dict[str, dict]:
    """key -> {"name", "series": [(date, level)], "total_return", "source"},
    in catalogue order: the captured catalogue, dividends reinvested; the 3a
    proxy (a price series) only where the catalogue entry is missing or was
    captured before the switch to total returns."""
    raw = (load_raw(snapshot_path) if snapshot_path else None) or {}
    captured = raw.get("series", {})
    bases = raw.get("bases") or {key: raw.get("basis", "price") for key in captured}
    proxies = (finpension or {}).get("proxy_series") or {}
    out = {}
    for key in KEYS:
        total_return = bases.get(key) == BASIS and bool(captured.get(key))
        proxy = proxies.get(PROXIES.get(key, ""))
        if total_return:
            series = [(dt.date.fromisoformat(d), v) for d, v in captured[key]]
            what = source(key)
        elif proxy:
            series = sorted((d if isinstance(d, dt.date) else dt.date.fromisoformat(d), v)
                            for d, v in proxy)
            what = "indice de prix du 3a, dividendes non compris"
        elif captured.get(key):
            series = [(dt.date.fromisoformat(d), v) for d, v in captured[key]]
            what = "indice de prix, dividendes non compris (--benchmarks pour recapturer)"
        else:
            continue
        out[key] = {"name": label(key), "series": series,
                    "total_return": total_return, "source": what}
    return out
