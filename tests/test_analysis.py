"""pms.analysis on the made-up statement: medians, merged brands, late
commitments, the income band."""

from __future__ import annotations

import datetime as dt

import pytest


def test_a_merged_brand_reports_the_category_that_carries_the_money(statement):
    """Reporting the first row's category was arbitrary once a brand's branches
    were merged: two petrol stops among hundreds of grocery runs must not
    relabel Coop."""
    import copy

    from pms import analysis
    from pms.categories import classify_all

    # A private copy: the merge below would relabel the session's rows.
    statement = copy.deepcopy(statement)
    classify_all(statement.transactions)
    analysis.annotate_chf(statement)
    for txn in statement.transactions:
        if txn.label.lower().startswith("coop"):
            txn.label_override = "Coop"

    row = next(m for m in analysis.top_merchants(
        analysis.spending(statement), limit=40) if m["name"] == "Coop")
    assert row["category"] == "Alimentation"
    assert row["categories"] > 1
    # 41 CHF of petrol next to thousands of groceries rounds to 100%, so
    # claiming a mix there states a falsehood.
    assert row["mixed"] is False


def test_median_and_mean_share_the_same_denominator(statement):
    """Both count every day of the window, empty ones included. Dropping the
    empty days from one of them would make two numbers sitting side by side
    answer different questions."""
    import datetime as dt

    from pms import analysis
    from pms.categories import classify_all

    classify_all(statement.transactions)
    analysis.annotate_chf(statement)
    spend = analysis.spending(statement)
    start, end = statement.period_start, statement.period_end

    days = analysis.daily_totals(spend)
    span = (end - start).days + 1
    values = sorted(days.get(start + dt.timedelta(days=i), {}).get("amount", 0.0)
                    for i in range(span))

    median = analysis.median_daily(spend, start, end)
    assert median == pytest.approx(
        values[span // 2] if span % 2
        else (values[span // 2 - 1] + values[span // 2]) / 2)


def test_the_median_is_well_below_the_mean_on_this_statement(statement):
    """Rent, taxes and insurance land on a handful of days, so the average day
    costs far more than a typical one -- which is the point of showing both."""
    from pms import analysis
    from pms.categories import classify_all

    classify_all(statement.transactions)
    analysis.annotate_chf(statement)
    spend = analysis.spending(statement)
    start, end = statement.period_start, statement.period_end

    mean = sum(abs(t.amount_chf) for t in spend) / ((end - start).days + 1)
    assert analysis.median_daily(spend, start, end) < mean


def test_median_of_an_empty_window_is_zero(statement):
    import datetime as dt

    from pms import analysis
    far = statement.period_end + dt.timedelta(days=400)
    assert analysis.median_daily([], far, far + dt.timedelta(days=10)) == 0.0


# --- commitments that stopped coming ----------------------------------------

def _fake(label, dates, amount=100.0, category="Logement"):
    """A counterparty billed on the given dates, for the recurrence tests."""
    from pms.models import Transaction
    rows = []
    for i, day in enumerate(dates):
        txn = Transaction(date=day, reference=str(1000 + i), currency="CHF",
                          amount=-amount, value_date=day, balance=None,
                          kind="Débit direct", merchant=label)
        txn.amount_chf = -amount
        txn.category = category
        rows.append(txn)
    return rows


def _statement(rows):
    from pms.models import Statement
    return Statement(holder="", iban="", period_start=rows[0].date,
                     period_end=rows[-1].date, generated_on=None,
                     reference_currency="CHF", accounts=[], transactions=rows)


def _monthly(count, start=dt.date(2025, 1, 5), step=30):
    return [start + dt.timedelta(days=step * i) for i in range(count)]


def test_a_commitment_still_arriving_is_not_reported(statement):
    from pms import analysis
    rows = _fake("Régie", _monthly(12))
    statement = _statement(rows)
    assert analysis.missing_commitments(statement) == []


def test_a_commitment_that_stopped_is_reported(statement):
    from pms import analysis
    rows = _fake("Régie", _monthly(12))
    statement = _statement(rows)
    statement.period_end = rows[-1].date + dt.timedelta(days=60)

    late = analysis.missing_commitments(statement)
    assert [r["label"] for r in late] == ["Régie"]
    assert late[0]["last"] == rows[-1].date
    assert late[0]["expected"] == rows[-1].date + dt.timedelta(days=30)
    assert late[0]["gap"] == 60


def test_a_stale_statement_does_not_make_everything_late(statement):
    """The last days of an export are always incomplete; a few of them missing
    is not a missed payment."""
    from pms import analysis
    rows = _fake("Régie", _monthly(12))
    statement = _statement(rows)
    statement.period_end = rows[-1].date + dt.timedelta(days=40)
    assert analysis.missing_commitments(statement) == []


def test_a_long_silence_reads_as_ended_not_as_late(statement):
    from pms import analysis
    rows = _fake("Régie", _monthly(12))
    statement = _statement(rows)
    statement.period_end = rows[-1].date + dt.timedelta(days=200)
    assert analysis.missing_commitments(statement)[0]["ended"] is True


def test_an_erratic_counterparty_is_not_a_commitment(statement):
    """A restaurant visited "regularly" recurs and costs a stable amount, which
    is enough for the monthly floor but not enough to have a due date."""
    from pms import analysis
    days = [dt.date(2025, 1, 5) + dt.timedelta(days=n)
            for n in (0, 3, 40, 44, 90, 91, 150, 200, 203, 260, 300, 301)]
    statement = _statement(_fake("Bistro", days, amount=18.0,
                                 category="Restaurants & bars"))
    statement.period_end = days[-1] + dt.timedelta(days=300)
    assert analysis.missing_commitments(statement) == []


def test_a_daily_habit_is_never_announced_as_an_overdue_debit(statement):
    """A canteen visited every working day passes the recurrence test on
    amount; telling someone their lunch is late is how a panel gets ignored."""
    from pms import analysis
    days = [dt.date(2025, 1, 1) + dt.timedelta(days=n) for n in range(200)]
    statement = _statement(_fake("Cantine", days, amount=8.5,
                                 category="Restaurants & bars"))
    statement.period_end = days[-1] + dt.timedelta(days=90)
    assert analysis.missing_commitments(statement) == []


def test_the_rhythm_is_a_median_so_one_missed_month_cannot_hide_the_next():
    from pms import analysis
    days = _monthly(6) + [dt.date(2025, 1, 5) + dt.timedelta(days=30 * 7)]
    statement = _statement(_fake("Régie", days))
    statement.period_end = days[-1] + dt.timedelta(days=60)
    late = analysis.missing_commitments(statement)
    assert late and late[0]["interval"] == 30  # not 34, the mean with the gap


def test_the_biggest_commitment_comes_first():
    from pms import analysis
    rows = (_fake("Régie", _monthly(12), amount=1600.0)
            + _fake("Assurance", _monthly(12), amount=280.0,
                    category="Santé & assurance"))
    statement = _statement(sorted(rows, key=lambda t: t.date))
    statement.period_end = statement.transactions[-1].date + dt.timedelta(days=60)
    assert [r["label"] for r in analysis.missing_commitments(statement)] \
        == ["Régie", "Assurance"]


def test_the_merchant_median_is_not_just_the_mean_again(statement):
    """They diverge where it matters: one large purchase at an otherwise cheap
    merchant drags the average to a figure nobody ever paid."""
    from pms import analysis
    from pms.categories import classify_all

    classify_all(statement.transactions)
    analysis.annotate_chf(statement)
    rows = analysis.top_merchants(analysis.spending(statement), limit=20)
    assert any(abs(r["median"] - r["average"]) > 1.0 for r in rows)
    for row in rows:
        assert 0 < row["median"] <= row["amount"]


def test_the_income_band_covers_every_period_including_the_empty_ones(
        statement):
    """A month with nothing coming in is the most informative point in the
    series; dropping it would close the very gap the band exists to show."""
    from pms import analysis
    from pms.categories import classify_all

    classify_all(statement.transactions)
    analysis.annotate_chf(statement)
    rows = analysis.income_timeline(statement, "month",
                                    statement.period_start,
                                    statement.period_end)
    months = (statement.period_end.year * 12 + statement.period_end.month
              - statement.period_start.year * 12
              - statement.period_start.month + 1)
    assert len(rows) == months
    assert any(r["total"] == 0 for r in rows), "this statement has a dry month"


def test_each_income_column_accounts_for_all_of_its_period(statement):
    from pms import analysis
    rows = analysis.income_timeline(statement, "month",
                                    statement.period_start,
                                    statement.period_end)
    for row in rows:
        assert sum(row["sources"].values()) == pytest.approx(row["total"], abs=0.01)


def test_the_band_fills_its_height_wherever_money_came_in(statement):
    """Shares, not amounts: every non-empty column is drawn full height, so a
    large month cannot flatten the transition next to it."""
    from pms import analysis
    from pms.web import charts

    rows = analysis.income_timeline(statement, "month",
                                    statement.period_start,
                                    statement.period_end)
    sources = analysis.income_sources(statement)
    fills = {r["label"]: f"var(--s{i})"
             for i, r in enumerate(sources[:analysis.INCOME_SLOTS])}
    fills[analysis.OTHER] = "var(--s7)"

    band = charts.income_band(rows, fills)
    assert band["gap_count"] >= 1
    for col in band["columns"]:
        if col["empty"]:
            assert not col["segments"]
            continue
        assert sum(s["h"] for s in col["segments"]) == pytest.approx(
            band["band_h"], abs=0.05)


def test_the_income_palette_never_needs_a_ninth_colour(statement):
    """More counterparties paid into this account than there are validated
    hues, so the tail has to fold."""
    from pms import analysis
    rows = analysis.income_timeline(statement, "month",
                                    statement.period_start,
                                    statement.period_end)
    names = {name for row in rows for name in row["sources"]}
    assert len(names) <= analysis.INCOME_SLOTS + 1
    assert len(analysis.income_sources(statement)) > len(names)


def test_a_payer_keeps_its_colour_across_the_whole_band(statement):
    """Ranking per column instead of over the window would make a payer change
    hue from one month to the next."""
    from pms import analysis
    rows = analysis.income_timeline(statement, "month",
                                    statement.period_start,
                                    statement.period_end)
    top = analysis.income_sources(statement)[0]["label"]
    seen = [r for r in rows if top in r["sources"]]
    assert len(seen) >= 6  # it really is spread over the series


def test_xirr_and_the_money_weighted_return():
    """A deposit just before a rise weighs more than the time-weighted return
    gives it credit for -- the whole difference the savings panel shows."""
    import datetime as dt

    from pms import analysis
    jan, jul, dec = dt.date(2025, 1, 1), dt.date(2025, 7, 2), dt.date(2026, 1, 1)
    # 365 days over a 365.25-day year: a hair above 10 %.
    assert analysis.xirr([(jan, -100.0), (dec, 110.0)]) == pytest.approx(0.1, abs=1e-3)
    assert analysis.xirr([(jan, 100.0), (dec, 110.0)]) is None  # one sign
    # 100 -> 100 by July (flat), +100 deposited, 200 -> 220 by December:
    # the TWR is +10 %, the MWR more, since twice the money took the rise.
    mwr = analysis.money_weighted(100.0, 220.0, [(jul, 100.0)], jan, dec)
    assert 0.13 < mwr < 0.14
    assert analysis.money_weighted(100.0, 110.0, [], jan, dec) == \
        pytest.approx(0.1, abs=1e-6)
