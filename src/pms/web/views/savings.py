"""The savings panel's arithmetic: Swissquote + IBKR + 3a, split, charted
and measured. Pure functions over the store and the snapshots -- no routes.
"""

from __future__ import annotations

import bisect
import datetime as dt

from ... import analysis
from ... import finpension as finpension_module
from ... import ibkr as ibkr_module

# How far a snapshot may lag the date on screen before the panel says so.
# A week: a weekend plus a bank holiday leaves four days without a price,
# never seven. Past that, the figure shown is an old one carried forward.
STALE_DAYS = 7


def _stale_notes(ibkr: dict, finpension: dict | None,
                 end: dt.date) -> list[str]:
    """Which pocket shows a figure older than the window's end, and since when.

    Both snapshots carry their last known value forward to any later date,
    so a stale one reads exactly like a current one: on 22.09 the 3a showed
    its 8 August value labelled "au 21.09", and nothing on the page said so.
    Measured against the window's end rather than the wall clock: an old
    window is not stale, and a ledger that is itself behind is its own topic.
    """
    notes = []
    last_nav = ibkr_module.nav_series(ibkr)[-1][0]
    if (end - last_nav).days > STALE_DAYS:
        notes.append(f"IBKR : chiffres arrêtés au {last_nav:%d.%m.%Y}, "
                     f"{(end - last_nav).days} jours avant le {end:%d.%m.%Y}")
    if finpension:
        # The 3a moves with its proxies after the last reading; it is frozen
        # only once both the reading and the proxies stop.
        known = [day for day, _ in finpension["yearly"]]
        if finpension.get("value_as_of"):
            known.append(dt.date.fromisoformat(finpension["value_as_of"]))
        proxies = [series[-1][0]
                   for series in finpension["proxy_series"].values() if series]
        if proxies:
            known.append(min(proxies))
        frozen = max(known) if known else None
        if frozen and (end - frozen).days > STALE_DAYS:
            notes.append(f"3a : valeur figée au {frozen:%d.%m.%Y}, "
                         f"{(end - frozen).days} jours avant le {end:%d.%m.%Y}")
    return notes


# How much of the brokerage NAV each curve key carries (see _evolution_row):
# a deposit raises those keys by that share, and must not read as a return.
_IBKR_SHARE = {"ibkr": 1.0, "usd": 1.0, "rss": 1.0, "ibkr_usd": 1.0,
               "total": 1.0, "actions": 0.5, "mf": 0.5,
               "ibkr_actions": 0.5, "ibkr_mf": 0.5}


def _ibkr_share(key: str, ibkr: dict) -> float:
    if key in _IBKR_SHARE:
        return _IBKR_SHARE[key]
    for prefix in ("ibkr_geo_", "geo_"):
        if key.startswith(prefix):
            region = key[len(prefix):]
            return sum((p.get("geography") or {}).get(region, 0)
                       for p in ibkr["positions"]) / 100
    return 0.0


# The curve keys that carry the Swissquote balance, and so its flows.
_SWISS_KEYS = ("swiss", "cash", "total", "chf")

# The reference indices: the 3a's own proxies, captured daily since August
# 2024 -- what a world ETF and the Swiss market did, in francs. Price
# indices: their dividends are not in them, and the panel says so.
BENCHMARKS = {"URTHxCHF": "MSCI World (CHF)", "SMI": "SMI"}


def _benchmarks(ibkr: dict, finpension: dict | None) -> dict[str, list]:
    """Name -> date-sorted (date, level), the proxies plus any index
    captured into the IBKR snapshot."""
    out = {}
    proxies = (finpension or {}).get("proxy_series") or {}
    for key, name in BENCHMARKS.items():
        if proxies.get(key):
            out[name] = sorted(proxies[key])
    out.update(ibkr.get("benchmarks") or {})
    return out


def _level(series: list, day: dt.date) -> float | None:
    i = bisect.bisect_right(series, (day, float("inf")))
    return series[i - 1][1] if i else None


def _holding_at(ibkr: dict, day: dt.date) -> dict | None:
    state = None
    for h in ibkr.get("holdings") or []:
        if h["date"] <= day:
            state = h
    return state


def _fund_price(ibkr: dict, symbol: str, day: dt.date) -> float | None:
    """The fund's close in its own currency: the daily capture where it
    exists, the weekly series (stamped Monday, closing Friday) before."""
    daily = ibkr.get("price_daily") or []
    if daily and day >= daily[0][0]:
        return _level(daily, day)
    weekly = (ibkr.get("prices") or {}).get(symbol) or []
    i = bisect.bisect_right(weekly, (day - dt.timedelta(days=4), float("inf")))
    return weekly[i - 1][1] if i else None


def _usd_chf(ibkr: dict, symbol: str, day: dt.date) -> float | None:
    """USD.CHF on `day`. Where the broker's daily NAV exists it is implied
    by it -- NAV = shares × price × rate + cash, the one unknown being the
    rate -- so no daily currency series has to be captured (or copied by
    hand, which slipped a week the one time it was tried). Before, the
    weekly series captured for the rebuild."""
    exact_from = ibkr.get("exact_from")
    if exact_from and day >= exact_from:
        state = _holding_at(ibkr, day)
        price = _fund_price(ibkr, symbol, day)
        nav = ibkr_module.nav_at(ibkr, day)
        if state and price:
            usd = sum(q * price for s, q in state["shares"].items()
                      if state["currency"].get(s, "USD") == "USD")
            usd += state["cash"].get("USD", 0.0)
            chf = state["cash"].get("CHF", 0.0)
            if usd > 0:
                return (nav - chf) / usd
        return None
    weekly = (ibkr.get("prices") or {}).get("USD.CHF") or []
    i = bisect.bisect_right(weekly, (day - dt.timedelta(days=4), float("inf")))
    return weekly[i - 1][1] if i else None


def _attribution(ibkr: dict, book: "SavingsBook", start: dt.date,
                 end: dt.date) -> dict | None:
    """The brokerage's franc return split into what the fund did in dollars
    and what the dollar did against the franc; the rest -- dividends, cash,
    fees, the timing of a deposit -- closes the gap, so the three compound
    exactly to the return shown: (1 + fund)(1 + fx)(1 + rest) = 1 + TWR.

    Only for a single dollar fund (RSST since July 2024); a mixed or
    unpriced holding gives no split rather than an invented one.
    """
    first = start
    if book.ibkr_start and first < book.ibkr_start:
        first = book.ibkr_start
    state = _holding_at(ibkr, end)
    if not state or len(state["shares"]) != 1:
        return None
    symbol = next(iter(state["shares"]))
    p0, p1 = _fund_price(ibkr, symbol, first), _fund_price(ibkr, symbol, end)
    f0, f1 = _usd_chf(ibkr, symbol, first), _usd_chf(ibkr, symbol, end)
    total = book.twr("ibkr", first, end)
    if not (p0 and p1 and f0 and f1) or total is None:
        return None
    fund, fx = p1 / p0 - 1, f1 / f0 - 1
    rest = (1 + total) / ((1 + fund) * (1 + fx)) - 1
    return {"fund_name": symbol, "fund": fund, "fx": fx, "rest": rest,
            "total": total, "since": first if first > start else None}


def _benchmark_return(series: list, start: dt.date,
                      end: dt.date) -> tuple[float | None, dt.date | None]:
    """The index's change over [start, end], from its first point when it
    starts later -- and that first date, so the panel can say so."""
    if not series or end < series[0][0]:
        return None, None
    first = max(start, series[0][0])
    a, b = _level(series, first), _level(series, end)
    return (b / a - 1 if a and b else None), first

POCKETS = ("total", "swissquote", "ibkr", "finpension")
POCKET_NAMES = {"total": "Épargne totale", "swissquote": "Swissquote",
                "ibkr": "IBKR", "finpension": "3a finpension"}

# Under a year, an annual rate is an extrapolation: one good month printed
# as +136 %/an. GIPS forbids it for that reason; so does this panel.
MIN_DAYS_ANNUALIZED = 365


class SavingsBook:
    """Every pocket's value and every franc that entered or left it, by day.

    One source for the whole section -- the headline, the pocket table, the
    base-100 curve and the risk table -- so no two parts of the panel can
    disagree on what a deposit is. The rules, each learnt the hard way:

    * a transfer from Swissquote to IBKR leaves one pocket and enters the
      other: a flow out of Swissquote, a flow into IBKR, nothing for the
      total (24.09.2026: +34 % for September before this);
    * IBKR is worth nothing before its first NAV point, and its opening value
      is money arriving -- funded from outside the ledger, it read as a gain
      in the total (148 in base 100 instead of 124);
    * a 3a deposit is a flow into the 3a (23.05.2024 for the first one).
    """

    def __init__(self, statement, ibkr: dict, finpension: dict | None):
        self.statement, self.ibkr, self.finpension = statement, ibkr, finpension
        self._ledger: dict[dt.date, float] = {}
        for txn in statement.transactions:
            self._ledger[txn.date] = self._ledger.get(txn.date, 0.0) + txn.amount_chf
        series = ibkr_module.nav_series(ibkr)
        self.ibkr_start = series[0][0] if series else None
        self._ibkr: dict[dt.date, float] = {}
        for day, amount in [*(series[:1]), *ibkr.get("flows", [])]:
            self._ibkr[day] = self._ibkr.get(day, 0.0) + amount
        self._finp: dict[dt.date, float] = {}
        for day, amount in (finpension or {}).get("deposit_entries", []):
            self._finp[day] = self._finp.get(day, 0.0) + amount
        self._values: dict[tuple[str, dt.date], float] = {}
        self._cumulative: dict[str, tuple[list, list]] = {}

    # --- values -----------------------------------------------------------
    def value(self, pocket: str, day: dt.date) -> float:
        key = (pocket, day)
        if key not in self._values:
            if pocket == "swissquote":
                v = analysis.balance_at(self.statement, day)
            elif pocket == "ibkr":
                v = (ibkr_module.nav_at(self.ibkr, day)
                     if self.ibkr_start and day >= self.ibkr_start else 0.0)
            elif pocket == "finpension":
                v = (finpension_module.value_at(self.finpension, day)
                     if self.finpension else None) or 0.0
            else:
                v = sum(self.value(p, day) for p in POCKETS[1:])
            self._values[key] = v
        return self._values[key]

    # --- flows ------------------------------------------------------------
    def _books(self, pocket: str) -> list[dict]:
        return {"swissquote": [self._ledger], "ibkr": [self._ibkr],
                "finpension": [self._finp],
                "total": [self._ledger, self._ibkr, self._finp]}[pocket]

    def flows(self, pocket: str, after: dt.date,
              until: dt.date) -> list[tuple[dt.date, float]]:
        """Money into (+) or out of (-) the pocket in (after, until]."""
        by_day: dict[dt.date, float] = {}
        for book in self._books(pocket):
            for day, amount in book.items():
                if after < day <= until:
                    by_day[day] = by_day.get(day, 0.0) + amount
        return sorted(by_day.items())

    def flow(self, pocket: str, after: dt.date, until: dt.date) -> float:
        """The net of `flows`, from running sums: the daily index asks for
        every day of the window, and a scan per day cost seconds."""
        if pocket not in self._cumulative:
            merged: dict[dt.date, float] = {}
            for book in self._books(pocket):
                for day, amount in book.items():
                    merged[day] = merged.get(day, 0.0) + amount
            days = sorted(merged)
            running, total = [], 0.0
            for day in days:
                total += merged[day]
                running.append(total)
            self._cumulative[pocket] = (days, running)
        days, running = self._cumulative[pocket]

        def upto(day):
            i = bisect.bisect_right(days, day)
            return running[i - 1] if i else 0.0
        return upto(until) - upto(after)

    def ledger_flows(self, after, until):
        return sorted((d, a) for d, a in self._ledger.items() if after < d <= until)

    def ibkr_flows(self, after, until):
        return sorted((d, a) for d, a in self._ibkr.items() if after < d <= until)

    # --- returns ----------------------------------------------------------
    def index(self, pocket: str, start: dt.date, end: dt.date) -> list:
        """The daily time-weighted index from 100, `v1 / (v0 + flow)`:
        what 100 francs left alone in the pocket would have become."""
        out, level = [(start, 100.0)], 100.0
        prev = self.value(pocket, start)
        day = start
        while day < end:
            nxt = day + dt.timedelta(days=1)
            value = self.value(pocket, nxt)
            base = prev + self.flow(pocket, day, nxt)
            if base > 0 and value > 0:
                level *= value / base
            out.append((nxt, level))
            prev, day = value, nxt
        return out

    def twr(self, pocket: str, start: dt.date, end: dt.date) -> float | None:
        if end <= start:
            return None
        return self.index(pocket, start, end)[-1][1] / 100 - 1

    def mwr(self, pocket: str, start: dt.date, end: dt.date) -> float | None:
        """For the period, flows at their dates. A pocket that does not exist
        yet at the start (IBKR before August 2025) starts when it does."""
        if pocket == "ibkr" and self.ibkr_start and start < self.ibkr_start:
            start = self.ibkr_start
        return analysis.money_weighted(
            self.value(pocket, start), self.value(pocket, end),
            self.flows(pocket, start, end), start, end)

    def summary(self, pocket: str, start: dt.date, end: dt.date) -> dict:
        """Where the pocket was, where it is, and why: the money put in
        against what the money did."""
        first, last = self.value(pocket, start), self.value(pocket, end)
        put_in = self.flow(pocket, start, end)
        twr = self.twr(pocket, start, end) if pocket != "swissquote" else None
        mwr = self.mwr(pocket, start, end) if pocket != "swissquote" else None
        days = (end - start).days
        # Days counted inclusively: 01.10 to 30.09 is a year, not 364 days.
        yearly = days + 1 >= MIN_DAYS_ANNUALIZED

        # Next to a one-year figure, its annual rate is the same number
        # rounded differently (+39.2 % and "+39.4 % par an") -- noise. The
        # headline only gives it for windows clearly longer than a year.
        longer = days + 1 > MIN_DAYS_ANNUALIZED + 7

        def annual(rate):
            return ((1 + rate) ** (365.25 / days) - 1
                    if rate is not None and yearly and longer and rate > -1
                    else None)

        return {"pocket": pocket, "name": POCKET_NAMES[pocket],
                "start_value": round(first, 2), "value": round(last, 2),
                "change": round(last - first, 2), "put_in": round(put_in, 2),
                "gain": round(last - first - put_in, 2),
                "twr": twr, "mwr": mwr,
                "twr_annual": annual(twr), "mwr_annual": annual(mwr)}


def _key_flows_dated(key: str, book: SavingsBook, after: dt.date,
                     until: dt.date) -> list[tuple[dt.date, float]]:
    """The flows of one curve key: the ledger's for the keys that carry the
    Swissquote balance, the brokerage's in the share of the NAV the key
    holds. The same book as the pockets, so the curve, the table and the
    headline remove the same money."""
    by_day: dict[dt.date, float] = {}
    if key in _SWISS_KEYS:
        for day, amount in book.ledger_flows(after, until):
            by_day[day] = by_day.get(day, 0.0) + amount
    share = _ibkr_share(key, book.ibkr)
    if share:
        for day, amount in book.ibkr_flows(after, until):
            by_day[day] = by_day.get(day, 0.0) + share * amount
    return sorted(by_day.items())


def _key_flow(key: str, book: SavingsBook, after: dt.date,
              until: dt.date) -> float:
    return sum(amount for _, amount in _key_flows_dated(key, book, after, until))


def _mwr_rows(rows: list[dict], keys: list[str], book: SavingsBook) -> list[dict]:
    """The money-weighted twin of `_indexed_rows`: each point is 100 times
    one plus the MWR from the line's first point to that date, the flows at
    their own dates. Not a chained index -- an MWR does not chain -- but the
    question "what had my money returned by then", asked at every point."""
    out = [dict(row) for row in rows]
    for key in keys:
        first = None
        for row in out:
            value = row.get(key)
            if value is None:
                continue
            if first is None:
                first = (row["date"], value)
                row[key] = 100.0
                continue
            flows = _key_flows_dated(key, book, first[0], row["date"])
            rate = analysis.money_weighted(first[1], value, flows,
                                           first[0], row["date"])
            row[key] = round(100 * (1 + rate), 2) if rate is not None else None
    return out


def _indexed_rows(rows: list[dict], keys: list[str],
                  book: SavingsBook) -> list[dict]:
    """The curve rebased to 100, each line from its own first point, flows
    taken out: what 100 francs left alone would have become, `v1 / (v0 +
    flow)`, so a deposit is a step in the CHF curve and nothing in this one."""
    out = [dict(row) for row in rows]
    for key in keys:
        level = prev_value = prev_day = None
        for row in out:
            value = row.get(key)
            if value is None:
                continue
            if level is None:
                level = 100.0
            else:
                base = prev_value + _key_flow(key, book, prev_day, row["date"])
                if base > 0 and value > 0:
                    level *= value / base
            prev_value, prev_day = value, row["date"]
            row[key] = round(level, 2)
    return out


def _fees(custodian_total: float, custodian_count: int, ibkr: dict,
          finpension: dict | None, values: dict, start: dt.date,
          end: dt.date) -> dict:
    """What each pocket cost over the window, keyed by pocket.

    Swissquote: the FX markup and negative interest of the custodian
    section, the same figure. IBKR: commissions and the spread of its
    automatic conversions, as captured from its trades -- the record starts
    where the connector's history does, and the row says so. The 3a: the
    quarterly flat-rate fee of its journal. Fund costs (TER) are inside the
    prices of all three and on no statement; they are not here.
    """
    fees = {"swissquote": {
        "amount": round(custodian_total, 2),
        "detail": (f"marge de change sur {custodian_count} conversion"
                   f"{'s' if custodian_count > 1 else ''}"
                   if custodian_count else "aucune conversion"),
        "items": []}}

    costs = [c for c in ibkr.get("costs", []) if start <= c["date"] <= end]
    detail = (", ".join(sorted({c["kind"] for c in costs}))
              if costs else "aucune opération")
    known_from = ibkr.get("costs_known_from")
    if known_from and start < known_from:
        detail += f" · connus depuis le {known_from:%d.%m.%Y}"
    fees["ibkr"] = {"amount": round(sum(c["amount_chf"] for c in costs), 2),
                    "detail": detail,
                    "items": [{"date": c["date"], "label": c["label"],
                               "amount": c["amount_chf"]} for c in costs]}

    if finpension:
        entries = [(d, a) for d, a in finpension.get("fee_entries", [])
                   if start <= d <= end]
        fees["finpension"] = {
            "amount": round(sum(a for _, a in entries), 2),
            "detail": (f"{len(entries)} frais administratif"
                       f"{'s' if len(entries) > 1 else ''} forfaitaire"
                       f"{'s' if len(entries) > 1 else ''}"
                       if entries else "aucun prélèvement"),
            "items": [{"date": d, "label": "Frais administratif forfaitaire",
                       "amount": a} for d, a in entries]}
    for pocket, row in fees.items():
        value = values.get(pocket)
        row["pct"] = round(row["amount"] / value * 100, 3) if value else None
    fees["total"] = {"amount": round(sum(f["amount"] for f in fees.values()), 2),
                     "detail": "", "items": []}
    total_value = values.get("total")
    fees["total"]["pct"] = (round(fees["total"]["amount"] / total_value * 100, 3)
                            if total_value else None)
    return fees


def _pocket_rows(book: SavingsBook, fees: dict, start: dt.date,
                 end: dt.date) -> list[dict]:
    """One row per pocket, then the total: the comparison the panel exists
    for, in one table -- what each holds, what was put in, what it made,
    how it performed, what it cost."""
    rows = []
    pockets = [p for p in ("swissquote", "ibkr", "finpension")
               if p != "finpension" or book.finpension]
    total = book.value("total", end)
    for pocket in (*pockets, "total"):
        row = book.summary(pocket, start, end)
        row["share"] = row["value"] / total * 100 if total else None
        row["fees"] = fees.get(pocket)
        rows.append(row)
    return rows


def _risk_table(book: SavingsBook, start: dt.date, end: dt.date,
                benchmarks: dict | None = None) -> dict | None:
    """Risk and return, one column per invested pocket and the total.

    Measured on the daily index (calendar days, annualized by the sampling
    rate) from the window's first day. The monthly version this replaces
    started at the end of the first month -- October missing -- and saw
    11 points a year: on IBKR over 01.10.2025-30.09.2026 it printed 30.8 %
    for a 39.4 % year, a −4.2 % drawdown for a −8.9 % one, a 13.6 % vol for
    21.9 %. Annual rates are left out under a year.
    """
    days = (end - start).days
    if days < 28:
        return None
    # A pocket younger than the window is measured from its first day, and
    # the header says so: over the full history the IBKR column starts in
    # August 2025, after the April 2025 tariff crash its fund went through
    # (RSST −25 % close to close) -- a −8.85 % drawdown read as the fund's
    # own looked wrong until the start date was on screen.
    ibkr_label = "IBKR"
    if book.ibkr_start and start < book.ibkr_start:
        ibkr_label = f"IBKR (depuis le {book.ibkr_start:%d.%m.%Y})"
    columns = [("ibkr", ibkr_label)]
    if book.finpension:
        columns.append(("finpension", "3a (estimé)"))
    columns.append(("total", "Épargne totale"))
    yearly = days + 1 >= MIN_DAYS_ANNUALIZED
    stats = {}
    for pocket, _ in columns:
        first = start
        if pocket == "ibkr" and book.ibkr_start and start < book.ibkr_start:
            first = book.ibkr_start
        series = book.index(pocket, first, end)
        values = [v for _, v in series]
        years = (end - first).days / 365.25
        stats[pocket] = analysis.risk_stats(
            values, years, periods_per_year=365.25) if years > 0 else {}
        stats[pocket]["mwr"] = book.mwr(pocket, first, end)
        stats[pocket]["years"] = years

    # The reference indices, measured exactly like the pockets: the same
    # daily index, the same window -- an index has no flows, so its MWR is
    # its TWR. One that starts later says from when, like a young pocket.
    for name, series in (benchmarks or {}).items():
        if not series or end <= series[0][0]:
            continue
        first = max(start, series[0][0])
        base = _level(series, first)
        if not base:
            continue
        values, day = [], first
        while day <= end:
            values.append(100 * _level(series, day) / base)
            day += dt.timedelta(days=1)
        years = (end - first).days / 365.25
        key = f"bench:{name}"
        label = name + (f" (depuis le {first:%d.%m.%Y})" if first > start else "")
        columns.append((key, label))
        stats[key] = analysis.risk_stats(values, years, periods_per_year=365.25) \
            if years > 0 and len(values) > 2 else {}
        stats[key]["mwr"] = values[-1] / 100 - 1
        stats[key]["years"] = years

    def pct(v):
        return f"{v * 100:.2f} %" if v is not None else "—"

    def annual_pct(pocket, field):
        s = stats[pocket]
        if not yearly or not s:
            return "—"
        if field == "mwr":
            rate = s.get("mwr")
            return pct((1 + rate) ** (1 / s["years"]) - 1) \
                if rate is not None and rate > -1 and s["years"] > 0 else "—"
        return pct(s.get(field))

    def num(v):
        return f"{v:.2f}" if v is not None else "—"

    spec = [
        ("Rendement sur la période (TWR)", "pct", "cumulative",
         "ce qu'auraient donné 100 francs laissés tels quels, versements retirés"),
        ("Rendement annualisé (TWR)", "annual", "cagr",
         "le même, ramené à un an — seulement sur un an ou plus"),
        ("Rendement annualisé (MWR)", "annual", "mwr",
         "le rendement de l'argent effectivement placé, chaque versement pondéré par sa durée"),
        ("Volatilité annualisée", "pct", "vol",
         "l'amplitude des variations quotidiennes, ramenée à un an"),
        ("Pire baisse (max drawdown)", "pct", "max_dd",
         "la plus forte chute depuis un sommet, sur la période"),
        ("Durée de la pire baisse", "days", "longest_dd",
         "le plus long passage sous un sommet précédent, en jours"),
        ("Ulcer index", "pct", "ulcer",
         "profondeur et durée des baisses combinées — plus bas, plus confortable"),
        ("Sharpe", "ratio", "sharpe",
         "rendement annuel au-delà du taux sans risque (0,5 %), par unité de volatilité"),
        ("Sortino", "ratio", "sortino",
         "comme Sharpe, en ne comptant que les baisses"),
        ("Calmar", "ratio", "calmar",
         "rendement annuel divisé par la pire baisse"),
    ]
    rows = []
    for label, kind, field, why in spec:
        cells = []
        for pocket, _ in columns:
            s = stats[pocket]
            if not s:
                text = "—"
            elif kind == "pct":
                text = pct(s.get(field))
            elif kind == "annual":
                text = annual_pct(pocket, field)
            elif kind == "days":
                text = f"{s[field]} j" if s.get(field) is not None else "—"
            else:
                text = num(s.get(field)) if yearly else "—"
            cells.append({"text": text})
        rows.append({"label": label, "why": why, "cells": cells})
    return {"columns": [name for _, name in columns], "rows": rows,
            "benchmark_columns": [i for i, (key, _) in enumerate(columns)
                                  if key.startswith("bench:")],
            "points": days + 1, "yearly": yearly,
            "cash_share": (book.value("swissquote", end) / book.value("total", end)
                           if book.value("total", end) else None)}


def _split_series(split: str, finpension: dict | None,
                  focus: str = "total") -> list[dict]:
    """The plot's lines for the chosen breakdown -- the same parts as the
    bar, so the curve and the split never disagree. Slots stay within the
    eight validated hues; the total rides on top.

    A focus names a pocket, and the breakdown applies *to that pocket*:
    clicking IBKR then "Monnaie" decomposes the brokerage (USD equity +
    CHF cash), not the whole portfolio. The pocket's own currency is a
    single line (the 3a is all CHF); Swissquote is cash whatever the view.
    """
    def part(key: str, name: str, slot: int) -> dict:
        return {"key": key, "name": name, "slot": slot}

    if focus == "ibkr":
        if split == "currency":
            spec = [part("ibkr_usd", "USD", 2), part("ibkr_chf", "CHF", 0)]
        elif split == "asset":
            spec = [part("ibkr_actions", "Actions", 2),
                    part("ibkr_mf", "Trend-Following", 3),
                    part("ibkr_cash", "Cash", 0)]
        elif split == "fund":
            spec = [part("rss", "RSST", 2), part("ibkr_cash", "Cash", 0)]
        elif split == "geo":
            spec = [part("ibkr_geo_États-Unis", "États-Unis", 2),
                    part("ibkr_cash", "Cash", 0)]
        else:
            spec = [part("ibkr", "IBKR", 2)]
    elif focus == "finpension":
        if split == "currency":
            spec = [part("finp", "CHF", 3)]
        elif split == "asset":
            spec = [part("finp_actions", "Actions", 2),
                    part("finp_cash", "Cash", 0)]
        elif split == "fund":
            spec = [part("finp_cash", "Cash", 0)]
            for isin, holding in (finpension["holdings"].items()
                                  if finpension else []):
                spec.append(part(f"fund_{isin}",
                                 holding.get("short") or holding["name"],
                                 len(spec) + 1))
        elif split == "geo":
            spec = [part("finp_cash", "Cash", 0),
                    part("finp_geo_États-Unis", "États-Unis", 2),
                    part("finp_geo_Europe (hors CH)", "Europe", 3),
                    part("finp_geo_Japon", "Japon", 4),
                    part("finp_geo_Suisse", "Suisse", 5),
                    part("finp_geo_Émergents", "Émergents", 6),
                    part("finp_geo_Autres", "Autres", 7)]
        else:
            spec = [part("finp", "3a finpension", 3)]
    elif focus == "swissquote":
        spec = [part("swiss", "Swissquote", 0)]
    elif split == "currency":
        spec = [part("chf", "CHF", 0), part("usd", "USD", 2)]
    elif split == "asset":
        spec = [part("cash", "Cash", 0), part("actions", "Actions", 2),
                part("mf", "Trend-Following", 3)]
    elif split == "fund":
        spec = [part("cash", "Cash", 0), part("rss", "RSST", 2)]
        for isin, holding in (finpension["holdings"].items()
                              if finpension else []):
            spec.append(part(f"fund_{isin}",
                             holding.get("short") or holding["name"],
                             len(spec) + 1))
    elif split == "geo":
        spec = [part("cash", "Cash", 0), part("geo_États-Unis", "États-Unis", 2),
                part("geo_Europe (hors CH)", "Europe", 3),
                part("geo_Japon", "Japon", 4), part("geo_Suisse", "Suisse", 5),
                part("geo_Émergents", "Émergents", 6),
                part("geo_Autres", "Autres", 7)]
    else:
        spec = [part("swiss", "Swissquote", 0), part("ibkr", "IBKR", 2),
                part("finp", "3a finpension", 3)]
    # The whole-portfolio line rides on top only in the total view; a
    # focused pocket shows its own breakdown alone.
    if focus == "total":
        spec.append(part("total", "Épargne totale", 1))
    return spec


def _savings_parts(ibkr: dict, swiss: float, finpension: dict | None,
                   finp_value: float, split: str,
                   focus: str = "total") -> list[dict]:
    """The savings split for the bar, one of three views of the same money.

    By account (the default), by currency, or by asset class. A focus
    decomposes the focused pocket only -- IBKR is USD equity + CHF cash,
    the 3a its funds -- and the bar fills to the pocket, not to the whole
    portfolio. Whatever the view cannot classify -- a declared account
    with no currency -- folds into "Autres", so the bar always fills.
    """
    finp = finp_value
    nav = ibkr["nav_chf"]
    chf_cash = sum(c["amount"] for c in ibkr["cash"]
                   if c["currency"] == "CHF")
    usd_cash = sum(c["amount"] for c in ibkr["cash"]
                   if c["currency"] != "CHF")
    usd_cash_chf = usd_cash * ibkr["fx_rate"] if usd_cash and ibkr["fx_rate"] \
        else 0.0
    total_cash = chf_cash + usd_cash_chf
    holdings = (finpension["holdings"].values() if finpension else [])
    fund_weight = sum(h["shares"] * h.get("price", 0.0) for h in holdings)
    finp_cash_amt = finpension.get("cash", 0.0) if finpension else 0.0
    fund_total = fund_weight + finp_cash_amt
    cash_share = finp_cash_amt / fund_total if fund_total else 0.0
    # The whole-portfolio cash pool for the total views: Swissquote, the
    # brokerage cash (converted), and the 3a's cash balance.
    cash = swiss + usd_cash_chf + finp_cash_amt

    if focus == "ibkr":
        if split == "currency":
            # The pocket is USD-denominated except its CHF cash; the USD
            # cash (118 USD) sits inside the NAV, so it is in the USD part.
            parts = [("USD", round(nav - chf_cash, 2)),
                     ("CHF", round(chf_cash, 2))]
        elif split == "asset":
            parts = [("Cash", round(total_cash, 2))]
            for position in ibkr["positions"]:
                split_pct = position.get("asset_split")
                if split_pct:
                    total_pct = sum(split_pct.values()) or 100.0
                    for cls, pct in split_pct.items():
                        parts.append(({"MF": "Trend-Following"}.get(cls, cls),
                                      round(position["value"] * pct / total_pct,
                                            2)))
                else:
                    parts.append((position["asset_class"],
                                  round(position["value"], 2)))
        elif split == "fund":
            parts = [("Cash", round(total_cash, 2))]
            for position in ibkr["positions"]:
                parts.append((position["name"], round(position["value"], 2)))
        elif split == "geo":
            parts = [("Cash", round(total_cash, 2))]
            for position in ibkr["positions"]:
                for name, pct in (position.get("geography") or {}).items():
                    parts.append((name,
                                  round(position["value"] * pct / 100, 2)))
        else:
            parts = [("IBKR", round(nav, 2))]
    elif focus == "finpension":
        if split == "currency":
            parts = [("CHF", round(finp, 2))]
        else:
            parts = [("Cash", round(finp * cash_share, 2))]
            if split == "asset":
                classes: dict[str, float] = {}
                for holding in holdings:
                    weight = holding["shares"] * holding.get("price", 0.0)
                    classes[holding["class"]] = classes.get(holding["class"],
                                                            0.0) + weight
                for name, value in classes.items():
                    parts.append((name, round(finp * value / fund_weight, 2)
                                  if fund_weight else 0.0))
            elif split == "fund":
                for holding in holdings:
                    weight = holding["shares"] * holding.get("price", 0.0)
                    parts.append((holding.get("short") or holding["name"],
                                  round(finp * weight / fund_weight, 2)
                                  if fund_weight else 0.0))
            elif split == "geo":
                regions: dict[str, float] = {}
                for holding in holdings:
                    weight = holding["shares"] * holding.get("price", 0.0)
                    geo = holding.get("geography") or {"Autres": 100}
                    for name, pct in geo.items():
                        name = "Émergents" if name in ("Chine", "Inde", "Taïwan") \
                            else name
                        regions[name] = regions.get(name, 0.0) \
                            + weight * pct / 100
                for name, value in sorted(regions.items(),
                                          key=lambda kv: -kv[1]):
                    parts.append((name, round(finp * value / fund_weight, 2)
                                  if fund_weight else 0.0))
            else:
                parts = [("3a finpension", round(finp, 2))]
    elif focus == "swissquote":
        # A current account is one currency and one asset class -- whatever
        # the view, the box fills with the balance.
        parts = [("CHF" if split == "currency" else "Cash", round(swiss, 2))]
    elif split == "currency":
        parts = [("CHF", round(swiss + finp
                               + sum(c["amount"] for c in ibkr["cash"]
                                     if c["currency"] == "CHF"), 2))]
        usd = sum(p["value_currency"] for p in ibkr["positions"]
                  if p["currency"] == "USD")
        usd += sum(c["amount"] for c in ibkr["cash"]
                   if c["currency"] == "USD")
        if usd and ibkr["fx_rate"]:
            parts.append(("USD", round(usd * ibkr["fx_rate"], 2)))
    elif split == "asset":
        # Economic exposure, not instrument: RSST is the S&P 500 (with a
        # managed-futures overlay), and the 3a is equity index funds. The
        # 3a's value is split across its holdings' classes by their last
        # printed prices -- proportions only, the total stays the captured
        # one.
        parts = [("Cash", round(cash, 2))]

        classes: dict[str, float] = {}
        for position in ibkr["positions"]:
            split = position.get("asset_split")
            if split:
                # A stacked fund declares its exposure explicitly -- RSST
                # is 100 % S&P 500 + 100 % managed futures, so its value
                # goes half to Actions, half to Trend-Following.
                total_pct = sum(split.values()) or 100.0
                for cls, pct in split.items():
                    classes[cls] = classes.get(cls, 0.0) \
                        + position["value"] * pct / total_pct
            else:
                classes[position["asset_class"]] = \
                    classes.get(position["asset_class"], 0.0) \
                    + position["value"]
        if finp:
            total_weight = sum(h["shares"] * h.get("price", 0.0)
                               for h in finpension["holdings"].values())
            if total_weight:
                for holding in finpension["holdings"].values():
                    weight = holding["shares"] * holding.get("price", 0.0)
                    classes[holding["class"]] = \
                        classes.get(holding["class"], 0.0) \
                        + finp * weight / total_weight
            else:
                classes["Autres"] = classes.get("Autres", 0.0) + finp
        labels = {"MF": "Trend-Following"}
        for name in ("Actions", "Obligations", "MF"):
            if classes.get(name):
                parts.append((labels.get(name, name),
                              round(classes[name], 2)))
        if classes.get("Autres"):
            parts.append(("Autres", round(classes["Autres"], 2)))
    elif split == "geo":
        # Geographic exposure -- declared per holding (the RSST position
        # and each 3a fund), approximations of the tracked indices.
        regions: dict[str, float] = {}
        for position in ibkr["positions"]:
            for name, pct in (position.get("geography") or {}).items():
                regions[name] = regions.get(name, 0.0) \
                    + position["value"] * pct / 100
        if finp:
            total_weight = sum(h["shares"] * h.get("price", 0.0)
                               for h in finpension["holdings"].values())
            if total_weight:
                for holding in finpension["holdings"].values():
                    weight = holding["shares"] * holding.get("price", 0.0)
                    geo = holding.get("geography") or {"Autres": 100}
                    for name, pct in geo.items():
                        name = "Émergents" if name in ("Chine", "Inde", "Taïwan") \
                            else name
                        regions[name] = regions.get(name, 0.0) \
                            + finp * weight / total_weight * pct / 100
        parts = [("Cash", round(cash, 2))]
        for name, value in sorted(regions.items(), key=lambda kv: -kv[1]):
            parts.append((name, round(value, 2)))
    elif split == "fund":
        parts = [("Cash", round(cash, 2))]
        for position in ibkr["positions"]:
            parts.append((position["name"], round(position["value"], 2)))
        if finp:
            total_weight = sum(h["shares"] * h.get("price", 0.0)
                               for h in finpension["holdings"].values())
            if total_weight:
                for holding in finpension["holdings"].values():
                    weight = holding["shares"] * holding.get("price", 0.0)
                    parts.append((
                        holding.get("short") or holding["name"],
                        round(finp * weight / total_weight, 2)))
    else:
        parts = [("Swissquote", round(swiss, 2)),
                 ("IBKR", round(ibkr["nav_chf"], 2))]
        for account in ibkr["other_accounts"]:
            parts.append((account["name"], account["value"]))
        if finp:
            parts.append(("3a finpension", round(finp, 2)))

    pocket_value = {"ibkr": nav, "finpension": finp, "swissquote": swiss} \
        .get(focus, ibkr["total"])
    accounted = sum(value for _, value in parts)
    if accounted < pocket_value - 0.01:
        parts.append(("Autres", round(pocket_value - accounted, 2)))
    return [{"name": name, "value": value} for name, value in parts]


def _evolution_row(statement, ibkr: dict, finpension: dict | None,
                   point_day: dt.date) -> dict:
    """The savings picture at one date: the Swissquote balance, the
    brokerage NAV and the 3a as of that day, their sum, and every
    breakdown key (the 3a is None before its first known value, the
    brokerage before its first NAV point -- the series stops where the
    data stops). The breakdown views are linear combinations of the base
    series; the proportions come from the captured holdings (3a fund
    weights, cash share) and the declared splits (RSST 50/50). Shared by
    the curve (one point per grain bucket) and the stats table (one point
    per month end), so the two never disagree."""
    swiss = analysis.balance_at(statement, point_day)
    ibkr_series = ibkr_module.nav_series(ibkr)
    ibkr_start = ibkr_series[0][0] if ibkr_series else None
    nav = ibkr_module.nav_at(ibkr, point_day) \
        if ibkr_start and point_day >= ibkr_start else None
    finp_raw = (finpension_module.value_at(finpension, point_day)
                if finpension else None)
    finp = finp_raw or 0.0
    nav0 = nav or 0.0

    cash_chf = sum(c["amount"] for c in ibkr["cash"] if c["currency"] == "CHF")
    usd_cash_chf = sum(c["amount"] for c in ibkr["cash"]
                       if c["currency"] != "CHF") * ibkr["fx_rate"]
    ibkr_cash_total = cash_chf + usd_cash_chf
    finp_cash = finpension.get("cash", 0.0) if finpension else 0.0
    fund_weight = sum(h["shares"] * h.get("price", 0.0)
                      for h in (finpension["holdings"].values()
                                if finpension else []))
    fund_total = fund_weight + finp_cash
    fund_share = fund_weight / fund_total if fund_total else 0.0
    cash_share = finp_cash / fund_total if fund_total else 0.0

    row = {
        "date": point_day, "swiss": round(swiss, 2),
        "ibkr": round(nav, 2) if nav is not None else None,
        "finp": round(finp_raw, 2) if finp_raw else None,
        "total": round(swiss + nav0 + finp, 2),
        # breakdown views of the same money. The IBKR cash is inside
        # the NAV series, so it is not added again.
        "chf": round(swiss + finp + cash_chf, 2),
        "usd": round(nav, 2) if nav is not None else None,
        "cash": round(swiss + finp * cash_share, 2),
        "actions": round(nav0 * 0.5 + finp * fund_share, 2),
        "mf": round(nav * 0.5, 2) if nav is not None else None,
        "rss": round(nav, 2) if nav is not None else None,
        # The focused pocket's own breakdown: the breakdown views
        # of the bar and the curve when a box is clicked. IBKR is
        # USD-denominated except its CHF cash; the 3a is all CHF.
        "ibkr_usd": round((nav or 0.0) - cash_chf, 2)
        if nav is not None else None,
        "ibkr_chf": round(cash_chf, 2) if nav is not None else None,
        "ibkr_cash": round(ibkr_cash_total, 2)
        if nav is not None else None,
        "ibkr_actions": round(nav0 * 0.5, 2)
        if nav is not None else None,
        "ibkr_mf": round(nav * 0.5, 2) if nav is not None else None,
        "finp_cash": round(finp * cash_share, 2) if finp_raw else None,
        "finp_actions": round(finp * fund_share, 2)
        if finp_raw else None,
    }
    for isin, holding in (finpension["holdings"].items()
                          if finpension else []):
        weight = (holding["shares"] * holding.get("price", 0.0)
                  / fund_weight) if fund_weight else 0.0
        row[f"fund_{isin}"] = round(finp * weight, 2)
        geo = holding.get("geography") or {"Autres": 100}
        for region, pct in geo.items():
            region = "Émergents" if region in ("Chine", "Inde", "Taïwan") \
                else region
            row[f"geo_{region}"] = round(
                row.get(f"geo_{region}", 0.0) + finp * weight * pct / 100,
                2)
            row[f"finp_geo_{region}"] = round(
                row.get(f"finp_geo_{region}", 0.0)
                + finp * weight * pct / 100, 2)
    for position in ibkr["positions"]:
        for region, pct in (position.get("geography") or {}).items():
            row[f"geo_{region}"] = round(
                row.get(f"geo_{region}", 0.0) + nav0 * pct / 100, 2)
            if nav is not None:
                row[f"ibkr_geo_{region}"] = round(
                    row.get(f"ibkr_geo_{region}", 0.0)
                    + nav0 * pct / 100, 2)
    return row


def _evolution_rows(statement, ibkr: dict, finpension: dict | None,
                    start: dt.date, end: dt.date, grain: str) -> list[dict]:
    """One point per calendar bucket inside [start, end], clamped to the
    window -- the same buckets the rest of the app uses, so the curve
    follows the chosen grain (daily for a month, monthly for a year).
    Under two points, the chart stays absent -- the KPIs remain."""
    rows = []
    seen: set[dt.date] = set()
    day = start
    while day <= end:
        bucket_end = analysis.bucket_bounds(day, grain)[1]
        point_day = min(bucket_end, end)
        if point_day not in seen:
            seen.add(point_day)
            rows.append(_evolution_row(statement, ibkr, finpension, point_day))
        day = bucket_end + dt.timedelta(days=1)
    return rows
