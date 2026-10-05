"""Need / Want / Save over time: the shares, their base, their smoothing."""

from __future__ import annotations

import copy
import datetime as dt

import pytest

from pms import analysis, buckets
from pms.categories import classify_all
from pms.models import Statement, Transaction
from pms.web import charts


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


# --- the chart -----------------------------------------------------------------

def _rows(values: list[float | None]) -> list[dict]:
    return [{"label": f"m{i}", "raw": {"Need": v}, "smooth": {"Need": v}}
            for i, v in enumerate(values)]


def test_an_extreme_month_is_drawn_on_the_edge_not_stretched_into():
    """-2500 % in one month would flatten every other month into a line."""
    chart = charts.shares_chart(_rows([55.0, -2500.0, 60.0]), ["Need"],
                                {"Need": "var(--s0)"}, "income", 1,
                                buckets.TARGET)
    assert chart["lo"] == charts.SHARE_FLOOR and chart["capped"]
    (line,) = chart["lines"]
    assert len(line["offscale"]) == 1
    assert line["offscale"][0]["y"] == chart["baseline"]
    # The tooltip still says the truth.
    assert chart["series"][0]["pts"][1][2] == -2500.0


def test_a_missing_month_breaks_the_line_instead_of_bridging_it():
    chart = charts.shares_chart(_rows([50.0, 52.0, None, 49.0, 51.0]), ["Need"],
                                {"Need": "var(--s0)"}, "income", 1,
                                buckets.TARGET)
    assert len(chart["lines"][0]["segments"]) == 2
    assert chart["series"][0]["pts"][2] is None


def test_the_spending_base_is_a_fixed_zero_to_hundred_axis_without_targets():
    chart = charts.shares_chart(_rows([55.0, 60.0]), ["Need"],
                                {"Need": "var(--s0)"}, "spending", 1,
                                buckets.TARGET)
    assert (chart["lo"], chart["hi"]) == (0.0, 100.0)
    assert chart["targets"] == []


def test_end_labels_never_sit_on_top_of_each_other():
    rows = [{"label": f"m{i}", "raw": {"Want": 9.0, "Non classé": 8.0},
             "smooth": {"Want": 9.0, "Non classé": 8.0}} for i in range(3)]
    chart = charts.shares_chart(rows, ["Want", "Non classé"],
                                {"Want": "var(--s1)", "Non classé": "var(--unsorted)"},
                                "spending", 1, buckets.TARGET)
    first, second = sorted(line["end"]["label_y"] for line in chart["lines"])
    assert second - first >= 12
