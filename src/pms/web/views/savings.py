"""The savings panel's arithmetic: Swissquote + IBKR + 3a, split, charted
and measured. Pure functions over the store and the snapshots -- no routes.
"""

from __future__ import annotations

import bisect
import datetime as dt

from ... import analysis
from ... import benchmarks as benchmarks_module
from ...buckets import NEED
from ... import crypto as crypto_module
from ... import finpension as finpension_module
from ... import holdings as holdings_module
from ... import ibkr as ibkr_module

# How far a snapshot may lag the date on screen before the panel says so.
# A week: a weekend plus a bank holiday leaves four days without a price,
# never seven. Past that, the figure shown is an old one carried forward.
STALE_DAYS = 7


def _stale_notes(ibkr: dict, finpension: dict | None,
                 end: dt.date, crypto: dict | None = None) -> list[str]:
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
    if crypto and crypto.get("daily_series"):
        last = crypto["daily_series"][-1][0]
        if (end - last).days > STALE_DAYS:
            notes.append(f"Crypto : cours arrêtés au {last:%d.%m.%Y}, "
                         f"{(end - last).days} jours avant le {end:%d.%m.%Y} "
                         f"(python -m pms --crypto)")
    return notes


def _stale_benchmarks(benchmarks: dict[str, list], end: dt.date) -> list[str]:
    """The picked indices that stop more than a week before the window's end:
    the headline compares a pocket's return to date with an index's return
    to its last capture -- a fortnight short, the comparison is off by it."""
    behind = [(series[-1][0], name) for name, series in benchmarks.items()
              if series and (end - series[-1][0]).days > STALE_DAYS]
    if not behind:
        return []
    last = min(day for day, _ in behind)
    return [f"Repères ({', '.join(name for _, name in behind)}) : cours arrêtés au "
            f"{last:%d.%m.%Y}, {(end - last).days} jours avant le {end:%d.%m.%Y} "
            f"(python -m pms --benchmarks)"]


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
# The keys that carry the crypto pocket: priced in dollars, no region.
_CRYPTO_KEYS = ("crypto", "total", "usd", "geo_Autres")

def _benchmarks(ibkr: dict, finpension: dict | None,
                available: dict | None = None,
                selected=benchmarks_module.DEFAULT) -> dict[str, list]:
    """Name -> date-sorted (date, level) for the indices picked: the public
    catalogue, dividends reinvested (`benchmarks.py`), the 3a's own price
    proxies where it is not captured, plus any index captured into the IBKR
    snapshot. A price series is marked as such on the panel."""
    if available is None:
        available = benchmarks_module.available(None, finpension)
    out = {available[key]["name"]: available[key]["series"]
           for key in selected if key in available}
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

    Only for a single dollar fund; a mixed or
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

POCKETS = ("total", "swissquote", "ibkr", "finpension", "crypto", "titres")
POCKET_NAMES = {"titres": "Titres non cotés", "total": "Épargne totale", "swissquote": "Swissquote",
                "ibkr": "IBKR", "finpension": "3a finpension",
                "crypto": "Crypto (Revolut)"}

# Under a year, an annual rate is an extrapolation: one good month printed
# as over +100 %/an. GIPS forbids it for that reason; so does this panel.
MIN_DAYS_ANNUALIZED = 365


class SavingsBook:
    """Every pocket's value and every franc that entered or left it, by day.

    One source for the whole section -- the headline, the pocket table, the
    base-100 curve and the risk table -- so no two parts of the panel can
    disagree on what a deposit is. The rules, each learnt the hard way:

    * a transfer from Swissquote to IBKR leaves one pocket and enters the
      other: a flow out of Swissquote, a flow into IBKR, nothing for the
      total (the first such transfer read as a month of tens of percent
      before this);
    * IBKR is worth nothing before its first NAV point, and its opening value
      is money arriving -- funded from outside the ledger, it read as a gain
      in the total (far too high in base 100);
    * a 3a deposit is a flow into the 3a;
    * a crypto purchase is a flow into the crypto pocket, and out of the
      cash it was paid from -- Revolut's euros, which the cash therefore
      counts (`analysis.cash_points`); a staking reward is return.
    """

    def __init__(self, statement, ibkr: dict, finpension: dict | None,
                 crypto: dict | None = None, securities: list[dict] | None = None):
        self.statement, self.ibkr, self.finpension = statement, ibkr, finpension
        # Unlisted shares declared on the tax page (`holdings.py`), when the
        # page counts them: their yearly tax value, their dividends as
        # their return.
        self.securities = securities or []
        self._titres = holdings_module.pocket_flows(statement, self.securities)
        self.titres_start = min((holdings_module.start(h) for h in self.securities), default=None)
        self.crypto = crypto if crypto and crypto.get("daily_series") else None
        self.crypto_start = self.crypto["daily_series"][0][0] if self.crypto else None
        self._crypto: dict[dt.date, float] = {}
        for day, amount in (self.crypto or {}).get("flow_entries", []):
            self._crypto[day] = self._crypto.get(day, 0.0) + amount
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

    def pockets(self) -> list[str]:
        """The pockets this book holds, in the page's order -- one list for
        every part of the page."""
        return [p for p in ("swissquote", "ibkr", "finpension", "crypto", "titres")
                if (p != "finpension" or self.finpension) and (p != "crypto" or self.crypto)
                and (p != "titres" or self.securities)]

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
            elif pocket == "crypto":
                v = crypto_module.value_at(self.crypto, day)
            elif pocket == "titres":
                v = holdings_module.value_on(self.securities, day)
            else:
                v = sum(self.value(p, day) for p in POCKETS[1:])
            self._values[key] = v
        return self._values[key]

    # --- flows ------------------------------------------------------------
    def _books(self, pocket: str) -> list[dict]:
        return {"swissquote": [self._ledger], "ibkr": [self._ibkr],
                "finpension": [self._finp], "crypto": [self._crypto], "titres": [self._titres],
                "total": [self._ledger, self._ibkr, self._finp, self._crypto, self._titres]}[pocket]

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

    def crypto_flows(self, after, until):
        return sorted((d, a) for d, a in self._crypto.items() if after < d <= until)

    def start_of(self, pocket: str, start: dt.date) -> dt.date:
        """Where a pocket's own measure starts: a pocket younger than the
        window (IBKR's NAV, the first crypto purchase) starts when it does."""
        first = {"ibkr": self.ibkr_start, "crypto": self.crypto_start,
                 "titres": self.titres_start}.get(pocket)
        return first if first and start < first else start

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
        yet at the start (IBKR before its first NAV point) starts when it does."""
        start = self.start_of(pocket, start)
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
        # rounded differently (two figures a few tenths apart) -- noise. The
        # headline only gives it for windows clearly longer than a year.
        longer = days + 1 > MIN_DAYS_ANNUALIZED + 7

        def annual(rate):
            return ((1 + rate) ** (365.25 / days) - 1
                    if rate is not None and yearly and longer and rate > -1
                    else None)

        # The "par an" view (`?rate=annual`) asks for the annual rate itself,
        # from a year on -- over the pocket's own life: a pocket younger than
        # the window has not had the window's years to earn its return.
        own = (end - self.start_of(pocket, start)).days
        return {"pocket": pocket, "name": POCKET_NAMES[pocket],
                "start_value": round(first, 2), "value": round(last, 2),
                "change": round(last - first, 2), "put_in": round(put_in, 2),
                "gain": round(last - first - put_in, 2),
                "twr": twr, "mwr": mwr,
                "twr_annual": annual(twr), "mwr_annual": annual(mwr),
                "twr_pa": annualize(twr, own), "mwr_pa": annualize(mwr, own)}


def annualize(rate: float | None, days: int) -> float | None:
    """A return over `days` as a rate per year; None under a year (see
    MIN_DAYS_ANNUALIZED) or for a total loss."""
    if rate is None or rate <= -1 or days <= 0 or days + 1 < MIN_DAYS_ANNUALIZED:
        return None
    return (1 + rate) ** (365.25 / days) - 1


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
    if key in _CRYPTO_KEYS:
        for day, amount in book.crypto_flows(after, until):
            by_day[day] = by_day.get(day, 0.0) + amount
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
          end: dt.date, crypto: dict | None = None) -> dict:
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
    if crypto:
        entries = [(d, a, label) for d, a, label in crypto.get("fee_entries", [])
                   if start <= d <= end]
        fees["crypto"] = {
            "amount": round(sum(a for _, a, _ in entries), 2),
            "detail": (f"{len(entries)} frais de transaction Revolut"
                       if entries else "aucune transaction"),
            "items": [{"date": d, "label": label, "amount": a}
                      for d, a, label in entries]}
    for pocket, row in fees.items():
        value = values.get(pocket)
        row["pct"] = round(row["amount"] / value * 100, 3) if value else None
    fees["total"] = {"amount": round(sum(f["amount"] for f in fees.values()), 2),
                     "detail": "", "items": []}
    total_value = values.get("total")
    fees["total"]["pct"] = (round(fees["total"]["amount"] / total_value * 100, 3)
                            if total_value else None)
    return fees


def _timing(book: SavingsBook, pocket: str, start: dt.date, end: dt.date,
            row: dict) -> dict:
    """What the dates of the deposits did -- the "flow luck": MWR − TWR.

    TWR is what the investments did whatever was put in when; MWR what the
    money actually there did. The gap is the timing alone: positive, the
    deposits arrived before the rises; negative, before the falls. In
    francs: the gain made, less what the TWR would have made on the same
    average capital (modified Dietz -- the capital the contribution column
    divides by), so the two read the same way.
    """
    twr, mwr = row.get("twr"), row.get("mwr")
    if twr is None or mwr is None:
        return {"timing": None, "timing_pa": None, "timing_chf": None}
    days = (end - start).days
    capital = book.value(pocket, start) + sum(
        amount * (end - day).days / days
        for day, amount in book.flows(pocket, start, end)) if days > 0 else 0.0
    pa = (row["mwr_pa"] - row["twr_pa"]
          if row.get("mwr_pa") is not None and row.get("twr_pa") is not None else None)
    return {"timing": mwr - twr, "timing_pa": pa,
            "timing_chf": round(row["gain"] - twr * capital, 2) if capital > 0 else None}


def _pocket_rows(book: SavingsBook, fees: dict, start: dt.date,
                 end: dt.date) -> list[dict]:
    """One row per pocket, then the total: the comparison the panel exists
    for, in one table -- what each holds, what was put in, what it made,
    how it performed, what it cost."""
    rows = []
    pockets = book.pockets()
    total = book.value("total", end)
    # Performance contribution: each pocket's gain over the total's average
    # invested capital (modified Dietz -- the opening value plus each flow
    # weighted by the share of the window it was there). The pockets' points
    # add up to the total's return; cash, earning nothing, contributes ~0
    # and shows what it costs as dilution.
    days = (end - start).days
    capital = book.value("total", start) + sum(
        amount * (end - day).days / days
        for day, amount in book.flows("total", start, end)) if days > 0 else 0.0
    for pocket in (*pockets, "total"):
        first = book.start_of(pocket, start) if pocket in ("crypto", "titres") else start
        row = book.summary(pocket, first, end)
        row["share"] = row["value"] / total * 100 if total else None
        row["fees"] = fees.get(pocket)
        row["contribution"] = row["gain"] / capital if capital > 0 else None
        row.update(_timing(book, pocket, first, end, row))
        rows.append(row)
    if capital > 0:
        rows[-1]["contribution"] = sum(r["contribution"] for r in rows[:-1])
    return rows


# The usual emergency-fund yardstick, in months of needs.
RESERVE_MONTHS = (3, 6)


def _reserve(statement, cash: float, end: dt.date) -> dict | None:
    """How many months of needs the current accounts hold.

    Needs per month: the Need bucket over the twelve whole months before the
    window's end (its own month too when the window ends on its last day),
    as a mean -- taxes and yearly premiums are needs, paid in a few months,
    and a median would leave them out. Fewer than three months of history
    say nothing. Past six months, the rest of the cash earns nothing: the
    panel names that amount, it is the one a pocket comparison dilutes.
    """
    last = end if (end + dt.timedelta(days=1)).day == 1 else end.replace(day=1) - dt.timedelta(days=1)
    months = []
    cursor = last.replace(day=1)
    for _ in range(12):
        months.append((cursor.year, cursor.month))
        cursor = (cursor - dt.timedelta(days=1)).replace(day=1)
    first_day = min((t.date for t in statement.transactions), default=None)
    if first_day is None:
        return None
    # A month the ledger only half covers would read as cheap: whole ones only.
    covered = [m for m in months if dt.date(m[0], m[1], 1) >= first_day.replace(day=1)
               and not (m == (first_day.year, first_day.month) and first_day.day > 1)]
    if len(covered) < 3:
        return None
    wanted = set(covered)
    need = sum(-t.amount_chf for t in analysis.spending(statement)
               if t.bucket == NEED and (t.date.year, t.date.month) in wanted)
    monthly = need / len(covered)
    if monthly <= 0:
        return None
    low, high = RESERVE_MONTHS
    return {"months": cash / monthly, "monthly": round(monthly, 2),
            "basis": len(covered), "low": low, "high": high,
            "excess": round(cash - high * monthly, 2) if cash > high * monthly else 0.0,
            "short": round(low * monthly - cash, 2) if cash < low * monthly else 0.0}


STATS_MODES = {
    "annual": {"label": "Annualisé", "aria": "taux et ratios ramenés à un an"},
    "period": {"label": "Sur la période", "aria": "taux et ratios sur la fenêtre affichée, sans extrapolation"},
}


def stats_mode(args, start: dt.date, end: dt.date) -> str:
    """`?stats=annual|period`; absent, annual from a year on and the period
    below -- so a short window shows figures without extrapolating them."""
    mode = (args.get("stats") or "").strip()
    if mode in STATS_MODES:
        return mode
    return "annual" if (end - start).days + 1 >= MIN_DAYS_ANNUALIZED else "period"


def _risk_table(book: SavingsBook, start: dt.date, end: dt.date,
                benchmarks: dict | None = None, mode: str = "annual") -> dict | None:
    """Risk and return, one column per invested pocket and the total.

    Measured on the daily index (calendar days, annualized by the sampling
    rate) from the window's first day. The monthly version this replaces
    started at the end of the first month -- that month missing -- and saw
    11 points a year: on IBKR over a year it understated the return by about
    a quarter, the drawdown by half and the volatility by about 40 %.

    `mode` "annual" scales rates and ratios to a year -- under a year that
    extrapolates, and the table says so (`extrapolated`); "period" gives
    them over the window itself, scaled to nothing.
    """
    days = (end - start).days
    if days < 28:
        return None
    # A pocket younger than the window is measured from its first day, and
    # the header says so: over the full history the IBKR column can start
    # after a crash its fund went through -- a shallow drawdown read as the
    # fund's own looked wrong until the start date was on screen.
    ibkr_label = "IBKR"
    if book.ibkr_start and start < book.ibkr_start:
        ibkr_label = f"IBKR (depuis le {book.ibkr_start:%d.%m.%Y})"
    columns = [("ibkr", ibkr_label)]
    if book.finpension:
        columns.append(("finpension", "3a (estimé)"))
    if book.crypto:
        label = "Crypto"
        if start < book.crypto_start:
            label += f" (depuis le {book.crypto_start:%d.%m.%Y})"
        columns.append(("crypto", label))
    columns.append(("total", "Épargne totale"))
    yearly = days + 1 >= MIN_DAYS_ANNUALIZED
    stats = {}
    for pocket, _ in columns:
        first = book.start_of(pocket, start)
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

    def num(v):
        return f"{v:.2f}" if v is not None else "—"

    def value(s, field):
        """One measure of one column, in the chosen mode."""
        if field == "cumulative" or field in ("max_dd", "longest_dd", "ulcer"):
            return s.get(field)
        if field == "mwr":
            rate = s.get("mwr")
            if mode == "period" or rate is None:
                return rate
            return (1 + rate) ** (1 / s["years"]) - 1 \
                if rate > -1 and s["years"] > 0 else None
        if mode == "period":
            return s.get("period", {}).get(field)
        return s.get(field)

    period = mode == "period"
    ratio_base = "rendement de la période" if period else "rendement annuel"
    spec = [
        ("Rendement sur la période (TWR)", "pct", "cumulative",
         "ce qu'auraient donné 100 francs laissés tels quels, versements retirés"),
        *([] if period else [("Rendement annualisé (TWR)", "pct", "cagr", "le même, ramené à un an")]),
        ("Rendement sur la période (MWR)" if period else "Rendement annualisé (MWR)", "pct", "mwr",
         "le rendement de l'argent effectivement placé, chaque versement pondéré par sa durée"),
        ("Volatilité sur la période" if period else "Volatilité annualisée", "pct", "vol",
         "l'amplitude des variations quotidiennes, "
         + ("cumulée sur la période" if period else "ramenée à un an")),
        ("Pire baisse (max drawdown)", "pct", "max_dd",
         "la plus forte chute depuis un sommet, sur la période"),
        ("Durée de la pire baisse", "days", "longest_dd",
         "le plus long passage sous un sommet précédent, en jours"),
        ("Ulcer index", "pct", "ulcer",
         "profondeur et durée des baisses combinées — plus bas, plus confortable"),
        ("Sharpe", "ratio", "sharpe",
         f"{ratio_base} au-delà du taux sans risque (0,5 % par an), par unité de volatilité"),
        ("Sortino", "ratio", "sortino",
         "comme Sharpe, en ne comptant que les baisses"),
        ("Calmar", "ratio", "calmar",
         f"{ratio_base} divisé par la pire baisse"),
        ("UPI (Martin)", "ratio", "upi",
         f"{ratio_base} au-delà du taux sans risque, par unité d'ulcer index : "
         "ce que rapporte chaque unité d'inconfort des baisses"),
    ]
    rows = []
    for label, kind, field, why in spec:
        cells = []
        for pocket, _ in columns:
            s = stats[pocket]
            v = value(s, field) if s else None
            if kind == "pct":
                text = pct(v)
            elif kind == "days":
                text = f"{v} j" if v is not None else "—"
            else:
                text = num(v)
            cells.append({"text": text})
        rows.append({"label": label, "why": why, "cells": cells})
    return {"columns": [name for _, name in columns], "rows": rows,
            "benchmark_columns": [i for i, (key, _) in enumerate(columns)
                                  if key.startswith("bench:")],
            "points": days + 1, "yearly": yearly, "mode": mode,
            "extrapolated": mode == "annual" and not yearly,
            "cash_share": (book.value("swissquote", end) / book.value("total", end)
                           if book.value("total", end) else None)}


def _split_series(split: str, finpension: dict | None,
                  focus: str = "total", crypto: bool = False,
                  titres: list[dict] | bool = False) -> list[dict]:
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
    elif focus == "crypto":
        spec = [part("crypto", "Crypto (Revolut)", 5)]
    elif focus == "titres":
        # Several declared (a share, a watch): a line each, in hues the
        # other pockets leave free.
        held = titres if isinstance(titres, list) else []
        if len(held) > 1:
            free = (4, 6, 7, 5, 2, 3, 0)
            spec = [part(f"titre_{h['id']}", h["name"], free[i % len(free)])
                    for i, h in enumerate(held)]
        else:
            spec = [part("titres", "Titres non cotés", 4)]
    elif split == "currency":
        spec = [part("chf", "CHF", 0), part("usd", "USD", 2)]
    elif split == "asset":
        spec = [part("cash", "Cash", 0), part("actions", "Actions", 2),
                part("mf", "Trend-Following", 3)]
        if crypto:
            spec.append(part("crypto", "Crypto", 5))
        # Equity too, but a line of their own: folded into "Actions" they
        # were there and nowhere to be seen.
        if titres:
            spec.append(part("titres", "Titres non cotés", 4))
    elif split == "fund":
        spec = [part("cash", "Cash", 0), part("rss", "RSST", 2)]
        for isin, holding in (finpension["holdings"].items()
                              if finpension else []):
            spec.append(part(f"fund_{isin}",
                             holding.get("short") or holding["name"],
                             len(spec) + 1))
        if crypto and len(spec) < 7:
            spec.append(part("crypto", "Crypto", len(spec) + 1))
    elif split == "geo":
        spec = [part("cash", "Cash", 0), part("geo_États-Unis", "États-Unis", 2),
                part("geo_Europe (hors CH)", "Europe", 3),
                part("geo_Japon", "Japon", 4), part("geo_Suisse", "Suisse", 5),
                part("geo_Émergents", "Émergents", 6),
                part("geo_Autres", "Autres", 7)]
    else:
        spec = [part("swiss", "Swissquote", 0), part("ibkr", "IBKR", 2),
                part("finp", "3a finpension", 3)]
        if crypto:
            spec.append(part("crypto", "Crypto (Revolut)", 5))
        if titres:
            spec.append(part("titres", "Titres non cotés", 4))
    # The whole-portfolio line rides on top only in the total view; a
    # focused pocket shows its own breakdown alone.
    if focus == "total":
        spec.append(part("total", "Épargne totale", 1))
    return spec


def _savings_parts(ibkr: dict, swiss: float, finpension: dict | None,
                   finp_value: float, split: str,
                   focus: str = "total", crypto: dict | None = None,
                   crypto_value: float = 0.0, titres_value: float = 0.0,
                   titres_in_actions: bool = False,
                   titres_each: list[tuple[str, float]] | None = None) -> list[dict]:
    """The savings split for the bar, one of three views of the same money.

    By account (the default), by currency, or by asset class. A focus
    decomposes the focused pocket only -- IBKR is USD equity + CHF cash,
    the 3a its funds -- and the bar fills to the pocket, not to the whole
    portfolio. Whatever the view cannot classify -- a declared account
    with no currency -- folds into "Autres", so the bar always fills.

    By asset class, unlisted shares are a part of their own, as on the
    curve. The allocation asks `titres_in_actions`: its targets name
    classes, and a part no target names is aimed at zero -- it would
    propose selling a share nobody can sell.
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
    elif focus == "titres":
        parts = ([(name, round(value, 2)) for name, value in titres_each]
                 if titres_each and len(titres_each) > 1
                 else [("Titres non cotés", round(titres_value, 2))])
    elif focus == "crypto":
        # One coin per part, in the proportions of the last capture.
        held = [(p["symbol"], p["value_chf"] or 0.0)
                for p in (crypto or {}).get("positions", [])]
        weight = sum(v for _, v in held)
        parts = [(sym, round(crypto_value * v / weight, 2))
                 for sym, v in sorted(held, key=lambda kv: -kv[1])
                 if weight and crypto_value * v / weight >= 0.5]
    elif split == "currency":
        parts = [("CHF", round(swiss + finp + titres_value
                               + sum(c["amount"] for c in ibkr["cash"]
                                     if c["currency"] == "CHF"), 2))]
        usd = sum(p["value_currency"] for p in ibkr["positions"]
                  if p["currency"] == "USD")
        usd += sum(c["amount"] for c in ibkr["cash"]
                   if c["currency"] == "USD")
        usd_chf = usd * ibkr["fx_rate"] if usd and ibkr["fx_rate"] else 0.0
        if usd_chf or crypto_value:
            parts.append(("USD", round(usd_chf + crypto_value, 2)))
    elif split == "asset":
        # Economic exposure, not instrument: a stacked fund is equities (with
        # a managed-futures overlay), and the 3a is index funds. The
        # 3a's value is split across its holdings' classes by their last
        # printed prices -- proportions only, the total stays the captured
        # one.
        parts = [("Cash", round(cash, 2))]

        classes: dict[str, float] = {}
        for position in ibkr["positions"]:
            split = position.get("asset_split")
            if split:
                # A stacked fund declares its exposure explicitly -- e.g.
                # 100 % equities + 100 % managed futures, so its value
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
        if titres_value and titres_in_actions:
            classes["Actions"] = classes.get("Actions", 0.0) + titres_value
        labels = {"MF": "Trend-Following"}
        for name in ("Actions", "Obligations", "MF"):
            if classes.get(name):
                parts.append((labels.get(name, name),
                              round(classes[name], 2)))
        if titres_value and not titres_in_actions:
            parts.append(("Titres non cotés", round(titres_value, 2)))
        if crypto_value:
            parts.append(("Crypto", round(crypto_value, 2)))
        if classes.get("Autres"):
            parts.append(("Autres", round(classes["Autres"], 2)))
    elif split == "geo":
        # Geographic exposure -- declared per holding (each IBKR position
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
        if titres_value:
            regions["Suisse"] = regions.get("Suisse", 0.0) + titres_value
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
        if crypto_value:
            parts.append(("Crypto", round(crypto_value, 2)))
        if titres_value:
            parts.append(("Titres non cotés", round(titres_value, 2)))
    else:
        parts = [("Swissquote", round(swiss, 2)),
                 ("IBKR", round(ibkr["nav_chf"], 2))]
        for account in ibkr["other_accounts"]:
            parts.append((account["name"], account["value"]))
        if finp:
            parts.append(("3a finpension", round(finp, 2)))
        if crypto_value:
            parts.append(("Crypto (Revolut)", round(crypto_value, 2)))
        if titres_value:
            parts.append(("Titres non cotés", round(titres_value, 2)))

    pocket_value = {"ibkr": nav, "finpension": finp, "swissquote": swiss,
                    "crypto": crypto_value, "titres": titres_value}.get(focus, ibkr["total"])
    accounted = sum(value for _, value in parts)
    # Under half a franc, "Autres 0" says nothing: rounding, dust coins.
    if accounted < pocket_value - 0.5:
        parts.append(("Autres", round(pocket_value - accounted, 2)))
    return [{"name": name, "value": value} for name, value in parts]


def _evolution_row(statement, ibkr: dict, finpension: dict | None,
                   point_day: dt.date, crypto: dict | None = None,
                   securities: list[dict] | None = None) -> dict:
    """The savings picture at one date: the Swissquote balance, the
    brokerage NAV and the 3a as of that day, their sum, and every
    breakdown key (the 3a is None before its first known value, the
    brokerage before its first NAV point -- the series stops where the
    data stops). The breakdown views are linear combinations of the base
    series; the proportions come from the captured holdings (3a fund
    weights, cash share) and the declared splits (a stacked fund 50/50). Shared by
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
    coins = crypto_module.value_at(crypto, point_day) if crypto else 0.0
    started = bool(crypto and crypto.get("daily_series")
                   and point_day >= crypto["daily_series"][0][0])
    # Unlisted shares at their declared value: a Swiss company's equity.
    owned = [h for h in securities or [] if point_day >= holdings_module.start(h)]
    titres = holdings_module.value_on(owned, point_day) if owned else 0.0
    # Each one too, for the pocket's own breakdown: a share, a watch.
    each = {f"titre_{h['id']}": (holdings_module.value_on([h], point_day)
                                 if h in owned else None)
            for h in securities or []}

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
        "total": round(swiss + nav0 + finp + coins + titres, 2),
        "crypto": round(coins, 2) if started else None,
        "titres": round(titres, 2) if owned else None,
        **each,
        # breakdown views of the same money. The IBKR cash is inside
        # the NAV series, so it is not added again.
        "chf": round(swiss + finp + cash_chf + titres, 2),
        "usd": (round(nav0 + coins, 2)
                if nav is not None or started else None),
        "cash": round(swiss + finp * cash_share, 2),
        # Listed equity only: the unlisted shares are their own line ("titres").
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
    if coins:
        row["geo_Autres"] = round(row.get("geo_Autres", 0.0) + coins, 2)
    if titres:
        row["geo_Suisse"] = round(row.get("geo_Suisse", 0.0) + titres, 2)
    return row


def _evolution_rows(statement, ibkr: dict, finpension: dict | None,
                    start: dt.date, end: dt.date, grain: str,
                    crypto: dict | None = None,
                    securities: list[dict] | None = None) -> list[dict]:
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
            rows.append(_evolution_row(statement, ibkr, finpension, point_day,
                                       crypto, securities))
        day = bucket_end + dt.timedelta(days=1)
    return rows
