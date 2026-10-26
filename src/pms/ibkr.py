"""The money outside the statement: the Interactive Brokers account.

The ledger only knows the Swissquote account; the brokerage (and the 3a)
is exactly what the `Save` bucket misses. IBKR exposes *states*, not a
journal -- equity, cash, positions and a NAV curve -- through its MCP
connector, which is attached to a Claude Code session, not to this app.
So the app reads a captured snapshot, `data/ibkr.json`, gitignored like
the other personal data: frozen at capture time, a snapshot has the same
standing as a bank statement. It is never a live read.
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import re
from pathlib import Path

# How the statement prints a transfer to (or from) the brokerage. The first
# one ended "the cash never moved, MWR = TWR": a NAV that jumps by a
# deposit is not a return.
LEDGER_PAYEE = re.compile(r"interactive\s+brokers", re.IGNORECASE)


def load(path: Path | str) -> dict | None:
    """Normalize a captured snapshot, or None when absent or unreadable.

    Missing, corrupt, or empty is not fatal -- the app runs without the
    panel, exactly like an empty overrides file.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    try:
        equity = float(raw["account"]["net_liquidation"])
        nav = [(dt.date.fromisoformat(d), float(v))
               for d, v in raw.get("nav", [])]
    except (KeyError, TypeError, ValueError):
        return None
    if not nav:
        return None
    nav.sort()

    # Before the broker's daily NAV (`nav_exact_from`), the value is rebuilt
    # from the exported transaction history -- holdings and cash, week by
    # week, at the weekly closes captured in `prices` (ibkr_history.rebuild;
    # a few hundredths of a percent off the broker's own figure where both
    # exist). It replaces the few monthly points captured before, which were
    # a day off and missed everything older than the connector's one year --
    # the April 2025 crash included.
    journal = raw.get("journal") or {}
    prices = raw.get("prices") or {}
    reconstructed_until = None
    try:
        exact_from = dt.date.fromisoformat(raw.get("nav_exact_from") or "")
    except ValueError:
        exact_from = None
    if journal.get("positions") and prices and exact_from:
        from . import ibkr_history
        rebuilt = ibkr_history.rebuild(journal["positions"], prices, exact_from)
        if rebuilt:
            nav = rebuilt + [p for p in nav if p[0] >= exact_from]
            reconstructed_until = exact_from

    positions = []
    for pos in raw.get("positions", []):
        try:
            currency_value = float(pos["market_value"])
            positions.append({
                "name": str(pos["name"]),
                "currency": str(pos.get("currency", "")),
                # The snapshot carries a CHF figure when available (the base
                # currency at capture time); fall back to the own-currency
                # value rather than refusing the whole file.
                "value": float(pos.get("market_value_chf") or currency_value),
                "value_currency": currency_value,
                "pnl": float(pos.get("unrealized_pnl_chf")
                             or pos.get("unrealized_pnl") or 0.0),
                "pnl_currency": float(pos.get("unrealized_pnl") or 0.0),
                "pnl_pct": float(pos.get("unrealized_pnl_pct") or 0.0),
                "asset_class": str(pos.get("asset_class") or "Autres"),
                "asset_split": pos.get("asset_split"),
                "geography": pos.get("geography"),
                # Gross exposure multiple: a return-stacked fund is
                # 100 % equities + 100 % managed futures on every franc --
                # ~2x notional, the extra sleeve funded by collateral and
                # futures. Displayed as a fact; the split still shows where
                # the *value* sits.
                "exposure": float(pos.get("exposure") or 1.0),
            })
        except (KeyError, TypeError, ValueError):
            continue

    performance = raw.get("performance") or {}
    try:
        ytd = float(performance.get("ytd_pct") or 0.0)
        one_year = float(performance.get("one_year_pct") or 0.0)
    except (TypeError, ValueError):
        ytd = one_year = 0.0

    # Declared savings outside both the statement and the brokerage -- the
    # 3a, for instance. A number the owner types in, like the plan's income.
    others = []
    for entry in raw.get("other_accounts", []):
        try:
            others.append({
                "name": str(entry["name"]),
                "value": round(float(entry["value"]), 2),
            })
        except (KeyError, TypeError, ValueError):
            continue

    # Per-currency cash and the capture-time rate, for the currency and
    # asset-class breakdowns of the savings panel.
    cash = []
    for entry in raw.get("cash", []):
        try:
            cash.append({"currency": str(entry["currency"]),
                         "amount": round(float(entry["amount"]), 2)})
        except (KeyError, TypeError, ValueError):
            continue
    try:
        fx_rate = float(raw.get("fx_chf_per_usd") or 0.0)
    except (TypeError, ValueError):
        fx_rate = 0.0

    # The daily capture is the position's share price, not the account NAV
    # (the performance API only prints month-end points). Scale it onto the
    # monthly NAVs: the series agrees with the bank's figure at every anchor,
    # and the days in between follow the fund's own moves -- the same anchor
    # trick the 3a reconstruction uses. A corrupt daily block only degrades
    # to the monthly curve; it never refuses the whole snapshot.
    nav_daily = []
    try:
        raw_daily = [(dt.date.fromisoformat(d), float(p))
                     for d, p in raw.get("nav_daily", [])]
        raw_daily.sort()
    except (TypeError, ValueError):
        raw_daily = []
    if raw_daily:
        month_i = 0
        for day, price in raw_daily:
            while month_i + 1 < len(nav) and nav[month_i + 1][0] <= day:
                month_i += 1
            anchor_day, anchor_value = nav[month_i]
            base = next((p for d, p in reversed(raw_daily) if d <= anchor_day),
                        None)
            nav_daily.append((day, round(anchor_value * price / base, 2)
                              if base and base > 0 else anchor_value))
        # Where the broker's own daily NAV exists (the connector's last year,
        # captured on 02.10.2026), it is the figure: the price scaling only fills the
        # days it lacks. The scaled curve had drifted up to 5 % from it
        # between month-end anchors that were themselves a day off.
        merged = dict(nav_daily)
        merged.update(dict(nav))
        nav_daily = sorted(merged.items())

    # Deposits that did not come from Swissquote (those are read from the
    # ledger, see `flows`): declared at capture, + in, - out. A bad row is
    # dropped, not fatal.
    declared = []
    for entry in raw.get("flows", []):
        try:
            declared.append((dt.date.fromisoformat(entry[0]), float(entry[1])))
        except (TypeError, ValueError, IndexError):
            continue

    # What the broker charged, captured from its trades (`/epargne`):
    # commissions, and the spread of the automatic conversions it books in
    # pairs. The connector's history does not reach the account's opening,
    # so `costs_known_from` says where the record starts.
    costs = []
    for entry in raw.get("costs", []):
        try:
            costs.append({"date": dt.date.fromisoformat(entry["date"]),
                          "kind": str(entry.get("kind") or ""),
                          "label": str(entry.get("label") or ""),
                          "amount_chf": float(entry["amount_chf"])})
        except (KeyError, TypeError, ValueError):
            continue
    try:
        costs_from = dt.date.fromisoformat(raw.get("costs_known_from") or "")
    except ValueError:
        costs_from = None

    # What the brokerage paid, from the transaction history: dividends and
    # interest, by the broker's date -- the year's income the tax return
    # asks for (`fiscal.py`).
    income = []
    for entry in journal.get("income", []):
        try:
            income.append({"date": dt.date.fromisoformat(entry["date"]),
                           "kind": str(entry.get("kind") or ""),
                           "amount_chf": float(entry["amount_chf"])})
        except (KeyError, TypeError, ValueError):
            continue

    journal_flows = []
    for entry in journal.get("flows", []):
        try:
            journal_flows.append((dt.date.fromisoformat(entry[0]), float(entry[1])))
        except (TypeError, ValueError, IndexError):
            continue
    try:
        opened = dt.date.fromisoformat(journal.get("first") or "")
    except ValueError:
        opened = None

    # Reference indices captured for comparison (`/epargne`), by display
    # name: {"S&P 500 (CHF)": [[date, level], ...]}. The 3a's proxies (MSCI
    # World in CHF, SMI) are added by the savings panel from its snapshot.
    benchmarks = {}
    for name, points in (raw.get("benchmarks") or {}).items():
        try:
            series = sorted((dt.date.fromisoformat(d), float(v)) for d, v in points)
        except (TypeError, ValueError):
            continue
        if series:
            benchmarks[str(name)] = series

    # Kept raw for the performance attribution (fund vs currency): the
    # fund's own price in dollars, daily where captured, weekly before; the
    # weekly USD.CHF; and the holdings and cash day by day from the journal.
    raw_prices = {}
    for symbol, points in prices.items():
        try:
            raw_prices[symbol] = sorted((dt.date.fromisoformat(d), float(v))
                                        for d, v in points)
        except (TypeError, ValueError):
            continue
    holdings = []
    for p in journal.get("positions", []):
        try:
            holdings.append({"date": dt.date.fromisoformat(p["date"]),
                             "shares": p.get("shares") or {},
                             "currency": p.get("currency") or {},
                             "cash": p.get("cash") or {}})
        except (KeyError, TypeError, ValueError):
            continue

    return {
        "captured_at": raw.get("captured_at") or "",
        "benchmarks": benchmarks,
        "price_daily": raw_daily,
        "prices": raw_prices,
        "holdings": holdings,
        "exact_from": exact_from,
        "declared_flows": sorted(declared),
        "journal_flows": sorted(journal_flows),
        "journal_source": journal.get("source") or "",
        "opened": opened,
        "reconstructed_until": reconstructed_until,
        "costs": sorted(costs, key=lambda c: c["date"]),
        "costs_known_from": costs_from,
        "income": sorted(income, key=lambda e: e["date"]),
        "base_currency": raw.get("base_currency") or "CHF",
        "equity": round(equity, 2),
        "cash": cash,
        "fx_rate": fx_rate,
        "other_accounts": others,
        "positions": positions,
        "performance": {
            "measure": performance.get("measure") or "TWR",
            "ytd_pct": ytd,
            "one_year_pct": one_year,
            "inception": performance.get("inception") or "",
        },
        "nav": nav,
        "nav_daily": nav_daily,
    }


def nav_series(ibkr: dict) -> list:
    """The densest captured NAV series: daily when the snapshot carries one,
    the monthly curve otherwise."""
    return ibkr.get("nav_daily") or ibkr["nav"]


def flows(ibkr: dict, transactions) -> list[tuple[dt.date, float]]:
    """Money into (+) or out of (-) the brokerage, by date.

    A Swissquote transfer to Interactive Brokers is a deposit seen from the
    other side, so the ledger is the source: nothing to capture, and every
    future statement brings its own. Deposits from elsewhere are declared in
    the snapshot (`flows`) -- `/epargne` flags a NAV jump the price does not
    explain.
    """
    if ibkr.get("journal_flows"):
        # The broker's own record wins: every deposit and withdrawal since
        # the opening, where the ledger only sees those after its own start --
        # and reading both would count each transfer twice.
        raw_flows = list(ibkr["journal_flows"])
    else:
        raw_flows = [(t.date, -t.amount_chf) for t in transactions
                     if LEDGER_PAYEE.search(
                         f"{t.kind} | {t.merchant} | {' '.join(t.detail or [])}")]
    raw_flows += list(ibkr.get("declared_flows", []))
    return sorted(_snap(ibkr, raw_flows))


def _snap(ibkr: dict, flows_: list) -> list:
    """Date each flow on the NAV point that shows it.

    The broker can book a deposit the day before Swissquote debits it and
    the NAV moves; a withdrawal shows in the weekly rebuild of the next
    day. A flow dated a day
    before its NAV point reads as a one-day crash and a next-day jump -- a
    fake −20 % in the drawdown. Each flow goes to the first NAV point on or
    after its date, or the one after that if that is where the value moves
    by about its amount.
    """
    series = nav_series(ibkr)
    days = [d for d, _ in series]
    values = dict(series)
    out = []
    for when, amount in flows_:
        if days and when < days[0]:
            # Before the first value point, a flow is already inside it: the
            # early deposits are part of what the account held at that point.
            # Moved onto that point, they read as the whole account deposited then.
            continue
        i = bisect.bisect_left(days, when)
        if i >= len(days):
            out.append((when, amount))
            continue
        def miss(j, amount=amount):
            change = values[days[j]] - values[days[j - 1]] if j else values[days[j]]
            return abs(change - amount)
        best = min(range(i, min(i + 2, len(days))), key=miss)
        out.append((days[best], amount))
    return out


def twr(ibkr: dict, flows_: list, start: dt.date, end: dt.date) -> float | None:
    """Time-weighted return over [start, end], deposits taken out.

    Chained point to point along the NAV series; a deposit dated in an
    interval joins the base at its start, `v1 / (v0 + flow)`. That is IBKR's
    own convention: on a deposit day it gives exactly the broker's figure,
    where `(v1 - flow) / v0` drifts from it. Without flows it
    reduces to `end / start`, which is what the app showed before there were
    any.
    """
    prev = nav_at(ibkr, start)
    if not prev:
        return None
    prev_day, factor = start, 1.0
    for day, value in nav_series(ibkr):
        if day <= start or day > end:
            continue
        flow = sum(amount for when, amount in flows_ if prev_day < when <= day)
        base = prev + flow
        if base > 0:
            factor *= value / base
        prev, prev_day = value, day
    return factor - 1


def nav_at(ibkr: dict, day: dt.date) -> float:
    """The NAV on (or just before) `day`, from the captured series; the first
    point before the series starts. Bisected: the savings section asks for
    every day of the window."""
    series = nav_series(ibkr)
    dates = ibkr.get("_nav_dates")
    if dates is None or ibkr.get("_nav_dates_of") is not series:
        dates = [d for d, _ in series]
        ibkr["_nav_dates"], ibkr["_nav_dates_of"] = dates, series
    i = bisect.bisect_right(dates, day)
    return series[i - 1][1] if i else series[0][1]
