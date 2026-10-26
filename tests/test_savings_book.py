"""SavingsBook: one book of values and flows behind the whole savings section.

Small invented accounts, so every figure can be checked by hand.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from pms.models import Transaction
from pms.web.views.savings import SavingsBook, _pocket_rows, _risk_table

D = dt.date


def _txn(day, kind, amount, balance):
    return Transaction(date=day, reference=str(hash((day, kind)) % 10**9),
                       currency="CHF", amount=amount, value_date=day,
                       balance=balance, kind=kind, amount_chf=amount)


def _book(nav, flows=(), rows=None, finpension=None):
    rows = rows if rows is not None else [
        _txn(D(2026, 9, 1), "Paiement entrant", 10000.0, 10000.0),
        # Savings moved from Swissquote to IBKR.
        _txn(D(2026, 9, 24), "Versement pour Interactive Brokers LLC", -2000.0, 8000.0),
    ]
    statement = SimpleNamespace(transactions=rows)
    ibkr = {"nav": nav, "nav_daily": [], "positions": [],
            "flows": list(flows)}
    return SavingsBook(statement, ibkr, finpension)


IBKR_NAV = [(D(2026, 9, 1), 10000.0), (D(2026, 9, 23), 10000.0),
            (D(2026, 9, 24), 12100.0), (D(2026, 9, 30), 12100.0)]


def test_a_transfer_between_pockets_is_neither_saving_nor_return():
    book = _book(IBKR_NAV, flows=[(D(2026, 9, 24), 2000.0)])
    start, end = D(2026, 9, 1), D(2026, 9, 30)
    assert book.flow("swissquote", start, end) == -2000.0
    assert book.flow("ibkr", start, end) == 2000.0
    assert book.flow("total", start, end) == 0.0
    # IBKR earned 100 on a 12'000 base: +0.8 %, not the +21 % of the ratio.
    assert book.twr("ibkr", start, end) == pytest.approx(12100 / 12000 - 1)
    # The total moved from 20'000 to 20'100 with nothing put in: +0.5 %.
    assert book.twr("total", start, end) == pytest.approx(0.005)
    summary = book.summary("total", start, end)
    assert summary["put_in"] == 0.0 and summary["gain"] == 100.0


def test_the_brokerage_opening_value_is_money_arriving():
    """IBKR was funded from outside the ledger: on a window that starts
    before it existed, its first value is a deposit, not a gain."""
    nav = [(D(2026, 9, 10), 5000.0), (D(2026, 9, 30), 5050.0)]
    book = _book(nav, rows=[_txn(D(2026, 9, 1), "Paiement entrant", 10000.0, 10000.0)])
    start, end = D(2026, 9, 1), D(2026, 9, 30)
    assert book.value("ibkr", start) == 0.0
    assert book.flow("total", start, end) == 5000.0
    assert book.twr("total", start, end) == pytest.approx(15050 / 15000 - 1)
    # Its own MWR starts when it does, not on a zero.
    assert book.mwr("ibkr", start, end) == pytest.approx(0.01, abs=1e-6)


def test_the_pockets_add_up_to_the_total():
    book = _book(IBKR_NAV, flows=[(D(2026, 9, 24), 2000.0)])
    fees = {"total": None}
    rows = _pocket_rows(book, fees, D(2026, 9, 1), D(2026, 9, 30))
    parts, total = rows[:-1], rows[-1]
    for field in ("value", "put_in", "gain", "change"):
        assert sum(r[field] for r in parts) == pytest.approx(total[field])
    assert sum(r["share"] for r in parts) == pytest.approx(100.0)
    # A current account has no return to measure.
    assert parts[0]["twr"] is None and parts[0]["mwr"] is None


def test_no_annual_rate_under_a_year():
    """One good month printed as +136 % a year; GIPS forbids it, so does
    the panel -- and 01.10 to 30.09 counts as a year, not 364 days."""
    nav = [(D(2025, 10, 1), 10000.0), (D(2026, 9, 30), 11000.0)]
    rows = [_txn(D(2025, 10, 1), "Paiement entrant", 100.0, 100.0)]
    book = _book(nav, rows=rows)
    month = _risk_table(book, D(2026, 9, 1), D(2026, 9, 30))
    assert month["yearly"] is False
    year = _risk_table(book, D(2025, 10, 1), D(2026, 9, 30))
    assert year["yearly"] is True
    cagr = next(r for r in year["rows"] if r["label"].startswith("Rendement annualisé (TWR)"))
    assert cagr["cells"][0]["text"] != "—"
    # Starts at the window's first day: the whole year is in it.
    cumulative = next(r for r in year["rows"] if r["label"].startswith("Rendement sur"))
    assert cumulative["cells"][0]["text"] == "10.00 %"


def test_a_short_window_reads_over_the_period_or_extrapolated_on_request():
    """Under a year the table no longer goes blank: by default every ratio
    is given over the window itself, and the annual view, when asked for,
    is given too but flagged as an extrapolation."""
    from pms import analysis
    from pms.web.views.savings import stats_mode
    nav = [(D(2026, 3, 1), 10000.0), (D(2026, 5, 1), 9000.0), (D(2026, 6, 1), 9500.0),
           (D(2026, 7, 1), 9200.0), (D(2026, 9, 30), 11000.0)]
    book = _book(nav, rows=[_txn(D(2026, 3, 1), "Paiement entrant", 100.0, 100.0)])
    start, end = D(2026, 3, 1), D(2026, 9, 30)
    assert stats_mode({}, start, end) == "period"
    assert stats_mode({}, D(2025, 10, 1), end) == "annual"
    assert stats_mode({"stats": "annual"}, start, end) == "annual"

    period = _risk_table(book, start, end, mode="period")
    assert period["extrapolated"] is False
    labels = [r["label"] for r in period["rows"]]
    assert "Rendement annualisé (TWR)" not in labels
    for name in ("Sharpe", "Sortino", "Calmar", "UPI (Martin)", "Volatilité sur la période"):
        row = next(r for r in period["rows"] if r["label"] == name)
        assert row["cells"][0]["text"] != "—", name

    annual = _risk_table(book, start, end, mode="annual")
    assert annual["extrapolated"] is True
    sharpe = next(r for r in annual["rows"] if r["label"] == "Sharpe")
    assert sharpe["cells"][0]["text"] != "—"

    # Period volatility is the daily one over the number of steps, not a year.
    values = [100.0, 101.0, 99.0, 102.0, 103.0]
    s = analysis.risk_stats(values, 4 / 365.25, periods_per_year=365.25)
    assert s["period"]["vol"] == pytest.approx(s["vol"] * (4 / 365.25) ** 0.5)
    assert s["period"]["calmar"] == pytest.approx(s["cumulative"] / abs(s["max_dd"]))


def test_benchmarks_are_measured_like_the_pockets():
    """An index in the risk table: the same daily measure, from its own
    first point when it starts later, and said so in its header."""
    from pms.web.views.savings import _benchmark_return
    book = _book(IBKR_NAV, flows=[(D(2026, 9, 24), 2000.0)])
    world = [(D(2026, 9, 5), 100.0), (D(2026, 9, 30), 103.0)]
    table = _risk_table(book, D(2026, 9, 1), D(2026, 9, 30), {"MSCI World (CHF)": world})
    assert table["columns"][-1] == "MSCI World (CHF) (depuis le 05.09.2026)"
    cumulative = next(r for r in table["rows"] if r["label"].startswith("Rendement sur"))
    assert cumulative["cells"][-1]["text"] == "3.00 %"
    rate, since = _benchmark_return(world, D(2026, 9, 1), D(2026, 9, 30))
    assert rate == pytest.approx(0.03) and since == D(2026, 9, 5)


def test_the_franc_return_splits_into_fund_and_dollar():
    """(1 + fund)(1 + fx)(1 + rest) = 1 + TWR, the dollar rate implied by
    the broker's NAV where it exists."""
    from pms.web.views.savings import _attribution
    nav = [(D(2026, 1, 1), 900.0), (D(2026, 6, 30), 990.0)]
    book = _book(nav, rows=[_txn(D(2026, 1, 1), "Paiement entrant", 1.0, 1.0)])
    ibkr = book.ibkr
    ibkr.update({
        "exact_from": D(2026, 1, 1),
        "price_daily": [(D(2026, 1, 1), 10.0), (D(2026, 6, 30), 10.0)],
        "holdings": [{"date": D(2025, 12, 1), "shares": {"FUND": 100.0},
                      "currency": {"FUND": "USD"}, "cash": {}}],
    })
    a = _attribution(ibkr, book, D(2026, 1, 1), D(2026, 6, 30))
    # The fund did nothing in dollars; the dollar rose 0.90 -> 0.99: all of
    # the +10 % in francs is the currency.
    assert a["fund"] == pytest.approx(0.0)
    assert a["fx"] == pytest.approx(0.10)
    assert (1 + a["fund"]) * (1 + a["fx"]) * (1 + a["rest"]) == pytest.approx(1 + a["total"])


def test_the_risk_table_reports_the_ulcer_performance_index():
    """UPI = (annual return - risk-free) / ulcer index, given over a year."""
    from pms import analysis
    stats = analysis.risk_stats([100.0, 90.0, 95.0, 110.0], 1.0, periods_per_year=4)
    assert stats["upi"] == pytest.approx((stats["cagr"] - 0.005) / stats["ulcer"])
    nav = [(D(2025, 10, 1), 10000.0), (D(2026, 3, 1), 9000.0), (D(2026, 9, 30), 11000.0)]
    book = _book(nav, rows=[_txn(D(2025, 10, 1), "Paiement entrant", 100.0, 100.0)])
    table = _risk_table(book, D(2025, 10, 1), D(2026, 9, 30))
    row = next(r for r in table["rows"] if r["label"].startswith("UPI"))
    assert row["cells"][0]["text"] != "—"


def test_contributions_add_up_to_the_total():
    """Each pocket's gain over the total's average capital: the points add
    up, and cash, earning nothing, adds nothing."""
    book = _book(IBKR_NAV, flows=[(D(2026, 9, 24), 2000.0)])
    rows = _pocket_rows(book, {"total": None}, D(2026, 9, 1), D(2026, 9, 30))
    parts, total = rows[:-1], rows[-1]
    assert sum(r["contribution"] for r in parts) == pytest.approx(total["contribution"])
    assert parts[0]["contribution"] == pytest.approx(0.0)
    # Nothing moved in or out of the total: its 100 francs over 20'000.
    assert total["contribution"] == pytest.approx(100 / 20000)


def test_the_timing_is_mwr_minus_twr_and_in_francs():
    """The 2'000 arrived just before IBKR's +100: the money did better than
    the investments -- a positive timing, worth the gain less what the TWR
    would have made on the same average capital."""
    book = _book(IBKR_NAV, flows=[(D(2026, 9, 24), 2000.0)])
    start, end = D(2026, 9, 1), D(2026, 9, 30)
    rows = {r["pocket"]: r for r in _pocket_rows(book, {"total": None}, start, end)}
    ibkr = rows["ibkr"]
    assert ibkr["timing"] == pytest.approx(ibkr["mwr"] - ibkr["twr"])
    assert ibkr["timing"] > 0
    capital = 10000 + 2000 * 6 / 29
    assert ibkr["timing_chf"] == pytest.approx(100 - (12100 / 12000 - 1) * capital, abs=0.01)
    # Nothing entered the total: no deposit, no timing.
    assert rows["total"]["timing"] == pytest.approx(0.0, abs=1e-4)
    assert rows["swissquote"]["timing"] is None


def test_a_rate_per_year_only_from_a_year_and_over_the_pockets_own_life():
    from pms.web.views.savings import annualize
    nav = [(D(2024, 10, 1), 10000.0), (D(2026, 9, 30), 20000.0)]
    book = _book(nav, rows=[_txn(D(2024, 10, 1), "Paiement entrant", 1.0, 1.0)])
    two_years = book.summary("ibkr", D(2024, 10, 1), D(2026, 9, 30))
    assert two_years["twr"] == pytest.approx(1.0)
    assert two_years["twr_pa"] == pytest.approx(2 ** (365.25 / 729) - 1)
    assert book.summary("ibkr", D(2026, 9, 1), D(2026, 9, 30))["twr_pa"] is None
    assert annualize(0.10, 364) == pytest.approx(0.10, abs=1e-3)  # 01.10 -> 30.09
    assert annualize(0.10, 200) is None
    assert annualize(-1.0, 800) is None
