"""The monthly review: what it flags, and above all what it does not."""

from __future__ import annotations

import copy
import datetime as dt

import pytest
from webhelpers import api

from pms import analysis, buckets, review
from pms.categories import classify_all
from pms.models import Statement, Transaction


@pytest.fixture(scope="module")
def ledger(statement):
    whole = copy.deepcopy(statement)
    classify_all(whole.transactions)
    analysis.annotate_chf(whole)
    buckets.annotate(whole.transactions)
    return whole


def _month(ledger, year: int, month: int) -> dict | None:
    first = dt.date(year, month, 1)
    return review.month_review(ledger, first, analysis.bucket_bounds(first, "month")[1])


def _every_month(ledger):
    first = dt.date(2024, 11, 1)
    while first < dt.date(2026, 7, 1):
        found = _month(ledger, first.year, first.month)
        assert found is not None
        yield found
        first = analysis.bucket_bounds(first, "month")[1] + dt.timedelta(days=1)


def test_a_premium_that_rises_in_january_is_flagged(ledger):
    (change,) = [p for p in _month(ledger, 2026, 1)["prices"]
                 if p["label"] == "Assura-Basis SA"]
    assert (change["before"], change["now"]) == (412.30, 431.00)
    assert change["pct"] == pytest.approx(4.54, abs=0.01)


def test_a_habit_is_never_a_price_change(ledger):
    """The canteen charges 8.00 and now and then 11.50: a different dish, not
    a price rise. Billed daily, it is not a fixed-price commitment."""
    for month in _every_month(ledger):
        assert all("Cantine" not in p["label"] for p in month["prices"])


def test_a_new_counterparty_paid_by_transfer_is_news(ledger):
    october = _month(ledger, 2025, 10)
    assert "Garage du Lac SA" in [p["label"] for p in october["new_payees"]]


def test_a_new_merchant_on_the_card_is_news_only_when_large(ledger):
    """Two tickets at 89.90 from a merchant never seen before: a new card
    merchant under 250 CHF is ordinary life, not news."""
    october = _month(ledger, 2025, 10)
    assert "Ticketcorner AG" not in [p["label"] for p in october["new_payees"]]


def test_a_debit_charged_twice_is_flagged(ledger):
    (double,) = _month(ledger, 2025, 10)["duplicates"]
    assert double["label"] == "Ticketcorner AG"
    assert double["dates"] == [dt.date(2025, 10, 14), dt.date(2025, 10, 15)]


def test_a_habit_never_reads_as_a_doubled_debit(ledger):
    """The canteen at 8.00 twice in two days is lunch, twice."""
    for month in _every_month(ledger):
        assert all(d["label"] == "Ticketcorner AG" for d in month["duplicates"])


def test_a_holiday_month_is_above_habit(ledger):
    july = _month(ledger, 2025, 7)
    assert "Loisirs & voyages" in [c["category"] for c in july["categories"]]


def test_no_review_without_a_usual_to_compare_against(ledger):
    """August 2024 is the first whole month; October has two before it."""
    assert _month(ledger, 2024, 10) is None
    assert _month(ledger, 2024, 11) is not None


def test_the_month_in_progress_says_so(ledger):
    found = review.month_review(ledger, dt.date(2026, 7, 1), dt.date(2026, 7, 30))
    assert found["partial"] is True
    assert _month(ledger, 2026, 6)["partial"] is False


def _bill(day: dt.date, amount: float, ref: str, payee: str = "Assurance",
          category: str = "Santé & assurance", currency: str = "CHF",
          chf: float | None = None) -> Transaction:
    txn = Transaction(date=day, reference=ref, currency=currency, amount=-amount,
                      value_date=day, balance=None, kind=f"Versement pour {payee}")
    txn.category = category
    txn.amount_chf = -(amount if chf is None else chf)
    return txn


def _history(rows: list[Transaction]) -> Statement:
    rows = sorted(rows, key=lambda t: t.date)
    return Statement(holder="", iban="", period_start=dt.date(2025, 1, 1),
                     period_end=dt.date(2025, 6, 30), generated_on=None,
                     reference_currency="CHF", accounts=[], transactions=rows)


def _june(statement: Statement) -> dict:
    return review.month_review(statement, dt.date(2025, 6, 1), dt.date(2025, 6, 30))


def test_a_daily_payee_with_a_steady_price_is_not_a_commitment():
    """Every weekday at 8.00, then one 11.50 on the last day of June: a
    different dish, not a price rise."""
    rows, n = [], 0
    day = dt.date(2025, 1, 1)
    while day <= dt.date(2025, 6, 30):
        if day.weekday() < 5:
            price = 11.50 if day == dt.date(2025, 6, 30) else 8.00
            rows.append(_bill(day, price, f"c{n}", "Cantine", "Restaurants & bars"))
            n += 1
        day += dt.timedelta(days=1)
    assert _june(_history(rows))["prices"] == []


def test_a_subscription_is_compared_in_its_own_currency():
    """20 USD every month. In francs it barely moved for five months, then the
    dollar jumped 3 % in June: that is the exchange rate, not the payee
    changing its price."""
    francs = [16.00, 16.02, 16.04, 16.03, 16.05, 16.60]
    rows = [_bill(dt.date(2025, month, 18), 20.00, f"u{month}", "OpenAI",
                  "Télécom & abonnements", "USD", chf=francs[month - 1])
            for month in range(1, 7)]
    assert _june(_history(rows))["prices"] == []


def test_a_variable_bill_is_not_a_price_change(ledger):
    """The energy bill moves every time: only a price that held still can
    change."""
    for month in _every_month(ledger):
        assert all(p["label"] != "Viteos SA" for p in month["prices"])


def test_a_weekly_habit_at_one_price_is_not_a_doubled_debit():
    """A class at 25.00, several times a week: two equal debits two days apart
    are the habit. The same pair from a payee seen twice is suspicious."""
    classes = [_bill(dt.date(2025, 6, d), 25.00, f"k{d}", "Studio Yoga",
                     "Loisirs & voyages") for d in (2, 4, 9, 11, 16, 18)]
    fillers = [_bill(dt.date(2025, m, 5), 100.0, f"f{m}", "Loyer", "Logement")
               for m in range(1, 7)]
    assert _june(_history(classes + fillers))["duplicates"] == []
    pair = classes[:2]
    (double,) = _june(_history(pair + fillers))["duplicates"]
    assert double["label"] == "Studio Yoga"


def _year_of_bills(december: dict[int, float]) -> Statement:
    rows = []
    for year in (2023, 2024, 2025):
        for month in range(1, 13):
            amount = 100.0 + (december[year] if month == 12 else 0.0)
            rows.append(_bill(dt.date(year, month, 5), amount, f"{year}{month:02d}"))
    return Statement(holder="", iban="", period_start=dt.date(2023, 1, 1),
                     period_end=dt.date(2025, 12, 31), generated_on=None,
                     reference_currency="CHF", accounts=[], transactions=rows)


def test_an_annual_bill_is_compared_with_last_year_not_the_ordinary_month():
    """A December premium is far above the ordinary month every year; once the
    history knows it is seasonal, only a jump against last December is news."""
    steady = _year_of_bills({2023: 2000.0, 2024: 2000.0, 2025: 2100.0})
    first = dt.date(2025, 12, 1)
    found = review.month_review(steady, first, dt.date(2025, 12, 31))
    assert found["categories"] == []

    jumped = _year_of_bills({2023: 2000.0, 2024: 2000.0, 2025: 4000.0})
    found = review.month_review(jumped, first, dt.date(2025, 12, 31))
    (flag,) = found["categories"]
    assert flag["seasonal"] is True
    assert flag["habit"] == pytest.approx(2100.0)


# --- the panel ---------------------------------------------------------------------

def test_the_review_appears_on_a_one_month_window_only(client):
    assert api(client, "/api/dashboard?from=2025-10-01&to=2025-10-31")["review"]
    assert api(client, "/api/dashboard?from=2025-10-01&to=2025-11-30")["review"] is None
    assert api(client, "/api/dashboard?preset=all")["review"] is None


def test_the_review_names_what_it_found(client):
    found = api(client, "/api/dashboard?from=2025-10-01&to=2025-10-31")["review"]
    assert found["label"] == "Octobre 2025"
    assert "Garage du Lac SA" in [p["label"] for p in found["new_payees"]]
    assert [d["label"] for d in found["duplicates"]] == ["Ticketcorner AG"]
    # An empty list is an answer, which the page says in words.
    assert found["prices"] == []


def test_the_review_covers_the_month_in_progress(client):
    found = api(client, "/api/dashboard?from=2026-07-01&to=2026-07-30")["review"]
    assert found["partial"] is True and found["last"] == "2026-07-30"
