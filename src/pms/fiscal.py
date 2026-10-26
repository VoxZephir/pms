"""What the tax return asks of the savings: the 3a deduction and the wealth
on 31 December.

* **The 3a ceiling.** The deductible maximum of an employee affiliated to a
  pension fund (OPP 3, art. 7): how much of the year's has been paid in, and
  what is left -- the foundation must have *received* it by 31.12, so a
  transfer sent on the 30th is late. A year left short is a gap: from 2025
  on it can be bought back within ten years (OPP 3, art. 7a), once the year
  of the buyback is itself paid in full.
* **The wealth on 31.12.** Each account's balance or value that day, as the
  wealth section of the return lists them, and what the brokerage paid in
  the year (dividends, interest, US tax withheld -- reclaimable through the
  return). The 3a is outside taxable wealth until withdrawn: shown apart,
  with the year's deposits, which are the deduction.

Not the official figures: the tax authority values securities and foreign
currency at its own year-end rates (the ESTV price list). These are the
broker's NAV, market closes and the app's exchange rates -- close to them,
and the panel says so.
"""

from __future__ import annotations

import datetime as dt

from . import analysis
from . import crypto as crypto_module
from . import finpension as finpension_module
from . import ibkr as ibkr_module

# The "small" 3a maximum, CHF: an employee with a pension fund. Reset with
# the AVS pensions, every two years; a year past the table carries the last
# known amount, and says it is not the published one.
PILLAR3A_CEILING = {2021: 6883, 2022: 6883, 2023: 7056, 2024: 7056,
                    2025: 7258, 2026: 7258}
# The first year whose gap can be bought back (OPP 3, art. 7a).
BUYBACK_FROM = 2025
SUBCATEGORY_3A = "Prévoyance 3a"
WITHHOLDING = "impôt à la source US"
# How the return names the accounts: the primary bank is the one whose IBAN
# names the ledger.
ACCOUNT_NAMES = {"": "Swissquote"}


def ceiling(year: int) -> tuple[float, bool]:
    """The year's maximum, and whether it is the published figure."""
    if year in PILLAR3A_CEILING:
        return float(PILLAR3A_CEILING[year]), True
    known = [y for y in PILLAR3A_CEILING if y <= year] or [min(PILLAR3A_CEILING)]
    return float(PILLAR3A_CEILING[max(known)]), False


def _journal_end(finpension: dict | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat((finpension or {}).get("last") or "")
    except ValueError:
        return None


def deposits_3a(finpension: dict | None, transactions,
                year: int) -> list[tuple[dt.date, float, str]]:
    """The year's 3a deposits: the foundation's journal, then the transfers
    to it in the ledger dated after the journal ends -- a deposit sent last
    week is in the bank statement long before a regenerated journal."""
    out = [(day, amount, "journal finpension")
           for day, amount in (finpension or {}).get("deposit_entries", [])
           if day.year == year and amount > 0]
    journal_end = _journal_end(finpension)
    for t in transactions:
        if (t.subcategory == SUBCATEGORY_3A and t.amount_chf < 0 and t.date.year == year
                and (journal_end is None or t.date > journal_end)):
            out.append((t.date, round(-t.amount_chf, 2), "relevé bancaire"))
    return sorted(out)


def pillar3a(finpension: dict | None, transactions, year: int,
             today: dt.date) -> dict:
    """The year's ceiling against what was paid in, and the gaps since 2025."""
    top, published = ceiling(year)
    deposits = deposits_3a(finpension, transactions, year)
    paid = sum(amount for _, amount, _ in deposits)
    deadline = dt.date(year, 12, 31)
    gaps = []
    for earlier in range(BUYBACK_FROM, year):
        missing = ceiling(earlier)[0] - sum(
            amount for _, amount, _ in deposits_3a(finpension, transactions, earlier))
        if missing >= 0.5:
            gaps.append({"year": earlier, "amount": round(missing, 2)})
    return {"year": year, "ceiling": top, "published": published,
            "paid": round(paid, 2), "left": round(max(top - paid, 0.0), 2),
            "deposits": deposits, "deadline": deadline,
            "days_left": (deadline - today).days if today <= deadline else None,
            "gaps": gaps}


def year_ends(transactions, today: dt.date) -> list[int]:
    """The 31 Decembers past, from the ledger's first year."""
    if not transactions:
        return []
    first = min(t.date for t in transactions)
    return [y for y in range(first.year, today.year) if dt.date(y, 12, 31) >= first]


def year_to_date(transactions, today: dt.date) -> dt.date | None:
    """The day the year still running can be estimated at: the statement's
    last, when it falls in that year. Not today -- the bank balances stop
    there, and an IBKR value five days later would add two different dates."""
    if not transactions:
        return None
    last = max(t.date for t in transactions)
    return last if last.year == today.year else None


def _balances(transactions, day: dt.date) -> dict[tuple[str, str], float]:
    """Each (account, currency) chain's printed balance at the end of `day`."""
    last: dict[tuple[str, str], float] = {}
    rows = sorted((t for t in transactions if t.date <= day and t.balance is not None),
                  key=lambda t: (t.date, t.seq))
    for t in rows:
        last[(t.account, t.currency)] = t.balance
    # A chain whose first row in the ledger comes later still held its
    # opening balance that day -- the same backfill `analysis.cash_points`
    # makes. Nothing to declare if that opening is zero.
    later = sorted((t for t in transactions if t.date > day and t.balance is not None
                    and (t.account, t.currency) not in last),
                   key=lambda t: (t.date, t.seq))
    for t in later:
        key = (t.account, t.currency)
        if key not in last:
            last[key] = round(t.balance - t.amount, 2)
    return {key: balance for key, balance in last.items()
            if key in {(t.account, t.currency) for t in rows} or abs(balance) >= 0.005}


def _holding(ibkr: dict, day: dt.date) -> str:
    state = None
    for h in ibkr.get("holdings") or []:
        if h["date"] <= day:
            state = h
    if not state:
        return ""
    shares = [f"{q:,.4g} {s}".replace(",", "’")
              for s, q in sorted(state["shares"].items()) if abs(q) > 1e-6]
    cash = [f"{a:,.2f} {c}".replace(",", "’")
            for c, a in sorted(state["cash"].items()) if abs(a) >= 0.005]
    return " · ".join([*shares, *(["liquidités " + ", ".join(cash)] if cash else [])])


def table(years: list[dict]) -> dict:
    """The year-ends side by side: one row per account that existed in any
    of them, a blank where it did not yet."""
    names: list[str] = []
    for year in years:
        names += [r["name"] for r in year["rows"] if r["name"] not in names]
    # Bank accounts first, then the brokerage and the coins: an account
    # opened in a later year still sits with the other accounts.
    kind = {r["name"]: r["kind"] for year in years for r in year["rows"]}
    names.sort(key=lambda name: ("bank", "broker", "crypto").index(kind[name]))
    rows = [{"name": name,
             "cells": [next((r for r in year["rows"] if r["name"] == name), None)
                       for year in years]}
            for name in names]
    return {"years": years, "rows": rows}


def year_end(statement, ibkr: dict | None, finpension: dict | None,
             crypto: dict | None, year: int, day: dt.date | None = None) -> dict:
    """The wealth on 31.12 of `year`, account by account, and the year's
    brokerage income -- the figures the return asks for. With `day`, the
    year still running as of that day: an estimate, `partial`, its income
    and 3a deposits so far."""
    partial = day is not None and day < dt.date(year, 12, 31)
    day = day if partial else dt.date(year, 12, 31)
    rate = analysis.fx_rate(statement)
    rows = []
    for (account, currency), balance in sorted(_balances(statement.transactions, day).items()):
        r = 1.0 if currency == "CHF" else rate(currency, day)
        name = ACCOUNT_NAMES.get(account, account.capitalize())
        rows.append({"name": f"{name} ({currency})", "kind": "bank",
                     "detail": (f"{balance:,.2f} {currency} × {r:.4f}".replace(",", "’")
                                if currency != "CHF" and r and balance else ""),
                     "value": round(balance * r, 2) if r else None})
    series = ibkr_module.nav_series(ibkr) if ibkr else []
    if series and series[0][0] <= day:
        rows.append({"name": "IBKR", "kind": "broker", "detail": _holding(ibkr, day),
                     "value": round(ibkr_module.nav_at(ibkr, day), 2)})
    coins = crypto_module.value_at(crypto, day) if crypto else 0.0
    if coins >= 0.5:
        rows.append({"name": "Crypto (Revolut)", "kind": "crypto",
                     "detail": "cours Binance × BCE",
                     "value": round(coins, 2)})
    income = [e for e in (ibkr or {}).get("income", [])
              if e["date"].year == year and e["date"] <= day]
    withheld = [c for c in (ibkr or {}).get("costs", [])
                if c["date"].year == year and c["date"] <= day and c["kind"] == WITHHOLDING]
    finp_value = (finpension_module.value_at(finpension, day) if finpension else None)
    return {
        "year": year, "day": day, "partial": partial, "rows": rows,
        "ceiling_3a": ceiling(year)[0],
        "taxable": round(sum(r["value"] or 0.0 for r in rows), 2),
        "dividends": round(sum(e["amount_chf"] for e in income
                               if e["kind"] == "dividende"), 2),
        "interest": round(sum(e["amount_chf"] for e in income
                              if e["kind"] != "dividende"), 2),
        "withheld": round(sum(c["amount_chf"] for c in withheld), 2),
        "pillar3a_value": round(finp_value, 2) if finp_value else None,
        "pillar3a_paid": round(sum(a for d, a, _ in
                                   deposits_3a(finpension, statement.transactions, year)
                                   if d <= day), 2)
        if finpension else None,
    }
