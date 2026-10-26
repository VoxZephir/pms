"""Need / Want / Save over time: the shares, their base, their smoothing."""

from __future__ import annotations

import copy
import datetime as dt

import pytest

from pms import analysis, buckets
from pms.categories import classify_all
from pms.models import Statement, Transaction


@pytest.fixture(scope="module")
def ledger(statement):
    """The made-up statement, classified and bucketed like the store does."""
    whole = copy.deepcopy(statement)
    classify_all(whole.transactions)
    analysis.annotate_chf(whole)
    buckets.annotate(whole.transactions)
    return whole


def _month(year: int, month: int, income: float, need: float,
           want: float = 0.0) -> list[Transaction]:
    """One month of hand-made movements: a salary, a need, a want."""
    day = dt.date(year, month, 10)
    rows = []
    for i, (amount, category) in enumerate(((income, "Revenus"),
                                            (-need, "Logement"),
                                            (-want, "Shopping"))):
        if not amount:
            continue
        txn = Transaction(date=day, reference=f"{year}{month:02d}{i}",
                          currency="CHF", amount=amount, value_date=day,
                          balance=None, kind="Paiement", seq=i)
        txn.category, txn.amount_chf = category, amount
        rows.append(txn)
    buckets.annotate(rows)
    return rows


def _statement(*months: list[Transaction]) -> Statement:
    rows = [t for month in months for t in month]
    first = rows[0].date.replace(day=1)
    last = analysis.bucket_bounds(rows[-1].date, "month")[1]
    return Statement(holder="", iban="", period_start=first, period_end=last,
                     generated_on=None, reference_currency="CHF", accounts=[],
                     transactions=rows)


def test_income_shares_make_one_hundred(ledger):
    rows = buckets.shares_by_month(ledger, ledger.period_start,
                                   ledger.period_end, "income")
    assert len(rows) > 12
    for row in rows:
        if row["raw"][buckets.NEED] is not None:
            assert sum(row["raw"].values()) == pytest.approx(100)


def test_spending_shares_make_one_hundred_and_have_no_save(ledger):
    rows = buckets.shares_by_month(ledger, ledger.period_start,
                                   ledger.period_end, "spending", smooth=3)
    for row in rows:
        assert buckets.SAVE not in row["raw"]
        for shares in (row["raw"], row["smooth"]):
            if shares[buckets.NEED] is not None:
                assert sum(shares.values()) == pytest.approx(100)
                assert all(0 <= v <= 100 for v in shares.values())


def test_only_whole_months_are_read(ledger):
    """The statement starts on 30 July and stops on 30 July: neither July is
    whole, and a partial month swings for reasons that are not the reader's."""
    rows = buckets.shares_by_month(ledger, ledger.period_start,
                                   ledger.period_end)
    assert rows[0]["key"] == "2024-08" and rows[-1]["key"] == "2026-06"
    for row in rows:
        assert (row["start"], row["end"]) == \
            analysis.bucket_bounds(row["start"], "month")


def test_smoothing_is_a_ratio_of_sums_not_a_mean_of_ratios():
    """Month one earned almost nothing: its 200 % would weigh as much as a
    salary month in a mean. In a ratio of sums it weighs what it earned."""
    statement = _statement(_month(2025, 1, 100, 200),
                           _month(2025, 2, 1000, 100),
                           _month(2025, 3, 1000, 100))
    rows = buckets.shares_by_month(statement, statement.period_start,
                                   statement.period_end, "income", smooth=3)
    need = rows[-1]["smooth"][buckets.NEED]
    assert need == pytest.approx(400 / 2100 * 100)
    mean_of_ratios = (200 + 10 + 10) / 3
    assert abs(need - mean_of_ratios) > 50


def test_a_smoothed_series_starts_once_its_window_is_full(ledger):
    rows = buckets.shares_by_month(ledger, ledger.period_start,
                                   ledger.period_end, "income", smooth=12)
    assert all(r["smooth"][buckets.NEED] is None for r in rows[:11])
    assert all(r["smooth"][buckets.NEED] is not None for r in rows[11:])


def test_the_rolling_sum_reaches_back_before_the_window(ledger):
    """Zooming into 2026 must not throw away the months that feed its first
    smoothed point -- the ledger has them."""
    rows = buckets.shares_by_month(ledger, dt.date(2026, 1, 1),
                                   dt.date(2026, 6, 30), "income", smooth=6)
    assert rows[0]["key"] == "2026-01"
    assert rows[0]["smooth"][buckets.NEED] is not None


def test_a_month_without_income_has_no_income_shares():
    statement = _statement(_month(2025, 1, 0, 300, 50),
                           _month(2025, 2, 1000, 300))
    income = buckets.shares_by_month(statement, statement.period_start,
                                     statement.period_end, "income")
    spending = buckets.shares_by_month(statement, statement.period_start,
                                       statement.period_end, "spending")
    assert all(v is None for v in income[0]["raw"].values())
    assert spending[0]["raw"][buckets.NEED] == pytest.approx(300 / 350 * 100)


def test_save_goes_negative_when_a_month_spends_more_than_it_earned():
    statement = _statement(_month(2025, 1, 1000, 1500),
                           _month(2025, 2, 1000, 300))
    rows = buckets.shares_by_month(statement, statement.period_start,
                                   statement.period_end, "income")
    assert rows[0]["raw"][buckets.SAVE] == pytest.approx(-50)
    assert rows[1]["raw"][buckets.SAVE] == pytest.approx(70)


# --- the panel's summary -------------------------------------------------------

def test_a_month_that_earned_more_than_it_spent_reads_in_shares_of_income():
    summary = buckets.summarise(_statement(_month(2025, 1, 1000, 300, 100)))
    shares = {r["name"]: r["share"] for r in summary["rows"]}
    assert summary["basis"] == "income" and summary["overspend"] == 0
    assert shares[buckets.NEED] == pytest.approx(30)
    assert shares[buckets.SAVE] == pytest.approx(60)   # the 600 left unspent
    assert sum(shares.values()) == pytest.approx(100)


def test_a_month_that_spent_more_than_it_earned_reads_in_shares_of_spending():
    """The salary not in yet: 50 earned, 2'300 spent. In shares of income that
    printed 3'600 % and a Save of -4'500 %, true and useless."""
    summary = buckets.summarise(_statement(_month(2025, 1, 50, 1800, 500)))
    shares = {r["name"]: r["share"] for r in summary["rows"]}
    assert summary["basis"] == "spend"
    assert summary["base"] == pytest.approx(2300)
    assert summary["overspend"] == pytest.approx(2250)
    assert shares[buckets.NEED] == pytest.approx(1800 / 2300 * 100)
    assert shares[buckets.SAVE] == 0 and summary["residual"] == 0
    assert all(0 <= v <= 100 for v in shares.values())
    assert sum(shares.values()) == pytest.approx(100)
    # No hollow "unspent" half when nothing was left over.
    save = next(r for r in summary["rows"] if r["name"] == buckets.SAVE)
    assert not any(p["hollow"] for p in save["parts"])


def test_the_highlights_drop_what_one_window_cannot_say():
    """A savings rate of -4'500 % and the dearest month of a single month."""
    statement = _statement(_month(2025, 1, 50, 1800, 500))
    custodian = {"count": 0}
    labels = [h["label"] for h in analysis.highlights(statement, custodian)]
    assert "Taux d'épargne" not in labels
    assert "Mois le plus cher" not in labels
