"""The 3a ceiling, the wealth on 31.12, and the cash as months of needs."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from pms import fiscal
from pms.models import Transaction
from pms.web.views.savings import _reserve

D = dt.date


def _txn(day, amount, balance, currency="CHF", account="", subcategory="",
         bucket="", seq=0):
    return Transaction(date=day, reference=str(hash((day, amount, account)) % 10**9),
                       currency=currency, amount=amount, value_date=day,
                       balance=balance, kind="Paiement", amount_chf=amount,
                       subcategory=subcategory, bucket=bucket, account=account, seq=seq)


FINPENSION = {"deposit_entries": [(D(2024, 5, 10), 7056.0)], "last": "2026-07-01"}


def test_the_ceiling_is_the_published_one_or_says_it_is_not():
    assert fiscal.ceiling(2026) == (7258.0, True)
    assert fiscal.ceiling(2024) == (7056.0, True)
    assert fiscal.ceiling(2031) == (7258.0, False)


def test_3a_deposits_come_from_the_journal_then_from_the_ledger():
    """A transfer the journal already holds is not counted twice; one sent
    after it ends is in the bank statement first."""
    rows = [_txn(D(2024, 5, 9), -7056.0, 0.0, subcategory="Prévoyance 3a"),
            _txn(D(2026, 9, 30), -2000.0, 0.0, subcategory="Prévoyance 3a")]
    assert [a for _, a, _ in fiscal.deposits_3a(FINPENSION, rows, 2024)] == [7056.0]
    assert fiscal.deposits_3a(FINPENSION, rows, 2026) == [
        (D(2026, 9, 30), 2000.0, "relevé bancaire")]


def test_what_is_left_before_31_12_and_the_gaps_since_2025():
    rows = [_txn(D(2026, 9, 30), -2000.0, 0.0, subcategory="Prévoyance 3a")]
    p3 = fiscal.pillar3a(FINPENSION, rows, 2026, D(2026, 10, 8))
    assert p3["paid"] == 2000.0 and p3["left"] == 5258.0
    assert p3["days_left"] == 84
    # 2024 was paid in full; 2025 not at all -- and only gaps from 2025 count.
    assert p3["gaps"] == [{"year": 2025, "amount": 7258.0}]
    past = fiscal.pillar3a(FINPENSION, rows, 2024, D(2026, 10, 8))
    assert past["left"] == 0.0 and past["days_left"] is None and past["gaps"] == []


def test_the_wealth_on_31_12_account_by_account():
    rows = [
        _txn(D(2025, 1, 1), 1000.0, 1000.0),
        _txn(D(2025, 12, 31), -100.0, 900.0, seq=1),
        _txn(D(2026, 1, 2), -50.0, 850.0),          # the next year: not in it
        _txn(D(2025, 6, 1), 80.0, 80.0, currency="EUR", account="revolut"),
        # First seen in 2026, but it held its opening balance on 31.12.
        _txn(D(2026, 2, 1), -10.0, 140.0, account="revolut"),
    ]
    statement = SimpleNamespace(transactions=rows)
    ibkr = {"nav": [(D(2025, 1, 1), 5000.0), (D(2025, 12, 31), 5500.0)],
            "nav_daily": [], "positions": [], "flows": [],
            "holdings": [{"date": D(2025, 3, 1), "shares": {"FUND": 10.0},
                          "currency": {"FUND": "USD"}, "cash": {"CHF": 4.5}}],
            "income": [{"date": D(2025, 6, 30), "kind": "dividende", "amount_chf": 12.0},
                       {"date": D(2024, 6, 30), "kind": "dividende", "amount_chf": 99.0}],
            "costs": [{"date": D(2025, 6, 30), "kind": fiscal.WITHHOLDING,
                       "label": "", "amount_chf": 1.8}]}
    year = fiscal.year_end(statement, ibkr, None, None, 2025)
    by_name = {r["name"]: r for r in year["rows"]}
    assert by_name["Swissquote (CHF)"]["value"] == 900.0
    assert "Revolut (EUR)" in by_name           # no rate known: listed, unvalued
    assert by_name["Revolut (CHF)"]["value"] == 150.0
    assert by_name["IBKR"]["value"] == 5500.0
    assert "10 FUND" in by_name["IBKR"]["detail"] and "4.50 CHF" in by_name["IBKR"]["detail"]
    assert year["dividends"] == 12.0 and year["withheld"] == 1.8
    assert year["taxable"] == 6550.0


def test_the_year_still_running_is_estimated_at_the_statement_s_last_day():
    rows = [_txn(D(2025, 12, 1), 1000.0, 1000.0),
            _txn(D(2026, 3, 1), -200.0, 800.0),
            _txn(D(2026, 10, 7), -100.0, 700.0)]
    statement = SimpleNamespace(transactions=rows)
    # Not today: the balances stop at the statement's last day.
    assert fiscal.year_to_date(rows, D(2026, 10, 13)) == D(2026, 10, 7)
    assert fiscal.year_to_date(rows, D(2027, 1, 5)) is None     # 2026 is closed now
    ibkr = {"nav": [(D(2026, 1, 1), 5000.0), (D(2026, 10, 7), 5400.0),
                    (D(2026, 10, 12), 9999.0)],
            "nav_daily": [], "positions": [], "flows": [], "holdings": [],
            "income": [{"date": D(2026, 6, 30), "kind": "dividende", "amount_chf": 12.0},
                       {"date": D(2026, 10, 9), "kind": "dividende", "amount_chf": 50.0}],
            "costs": []}
    year = fiscal.year_end(statement, ibkr, None, None, 2026, D(2026, 10, 7))
    assert year["partial"] and year["day"] == D(2026, 10, 7)
    assert year["taxable"] == 700.0 + 5400.0       # IBKR at the same day, not after
    assert year["dividends"] == 12.0                 # what came after is not counted
    assert year["ceiling_3a"] == 7258.0
    assert not fiscal.year_end(statement, ibkr, None, None, 2025)["partial"]


def test_year_ends_are_the_31_decembers_past_and_banks_come_first():
    rows = [_txn(D(2024, 7, 30), 1.0, 1.0)]
    assert fiscal.year_ends(rows, D(2026, 10, 8)) == [2024, 2025]
    table = fiscal.table([
        {"rows": [{"name": "A (CHF)", "kind": "bank"}, {"name": "IBKR", "kind": "broker"}]},
        {"rows": [{"name": "A (CHF)", "kind": "bank"}, {"name": "IBKR", "kind": "broker"},
                  {"name": "B (CHF)", "kind": "bank"}]}])
    assert [r["name"] for r in table["rows"]] == ["A (CHF)", "B (CHF)", "IBKR"]
    assert table["rows"][1]["cells"][0] is None    # B did not exist yet


def test_the_reserve_counts_months_of_needs():
    """The needs of whole months, as a mean (taxes are needs, paid in a
    few months); past six months, the rest is named."""
    rows = [_txn(D(2026, 1, 1), 50000.0, 50000.0)]
    for month in range(1, 10):
        rows.append(_txn(D(2026, month, 5), -1000.0, 0.0, bucket="Need"))
    rows.append(_txn(D(2026, 4, 20), -3000.0, 0.0, bucket="Need"))   # the tax bill
    rows.append(_txn(D(2026, 5, 6), -9999.0, 0.0, bucket="Want"))    # not a need
    statement = SimpleNamespace(transactions=rows)
    reserve = _reserve(statement, 24000.0, D(2026, 10, 8))
    assert reserve["basis"] == 9                       # January to September
    assert reserve["monthly"] == pytest.approx(12000 / 9, abs=0.01)
    assert reserve["months"] == pytest.approx(24000 / (12000 / 9))
    assert reserve["excess"] == pytest.approx(24000 - 6 * 12000 / 9, abs=0.01)
    # Two months of history say nothing.
    assert _reserve(statement, 24000.0, D(2026, 3, 10)) is None
