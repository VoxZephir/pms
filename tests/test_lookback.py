"""The past spending read several ways (`lookback.py`): whole months only,
the year against the one before, the rhythm of a month, the weekdays, one
category up close."""

from __future__ import annotations

import datetime as dt

import pytest

from pms import analysis, lookback, plans


@pytest.fixture(scope="module")
def held(client):
    """The synthetic statement as the app holds it: classified, in francs."""
    return client.application.extensions["pms_store"].statement


def test_only_whole_months_count(held):
    months = lookback.whole_months(held)
    assert months
    first = dt.date.fromisoformat(months[0] + "-01")
    assert first >= min(t.date for t in held.transactions)
    last = dt.date.fromisoformat(months[-1] + "-01")
    assert (last.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1) <= held.period_end
    # The month the held ends in is still running: not a whole one.
    assert f"{held.period_end:%Y-%m}" not in months or held.period_end.day >= 28


def test_the_year_change_adds_up(held):
    monthly = analysis.monthly(held)
    months = lookback.whole_months(held)
    change = lookback.year_change(held, monthly, months)
    assert change and change["months"] == lookback.compare_span(months)
    rows = change["rows"]
    assert abs(sum(r["now"] for r in rows) - change["total"]["now"]) < 0.1
    assert abs(sum(r["before"] for r in rows) - change["total"]["before"]) < 0.1
    assert [abs(r["delta"]) for r in rows] == sorted((abs(r["delta"]) for r in rows), reverse=True)
    assert change["last"]["to"] == months[-1]


def test_a_short_history_has_no_comparison():
    assert lookback.compare_span(["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]) == 0
    assert lookback.compare_span([f"2025-{m:02d}" for m in range(1, 9)]) == 4


def test_regularity_tells_the_rent_from_the_tax(held):
    monthly = analysis.monthly(held)
    months = lookback.whole_months(held)
    categories = plans.category_profile(held)
    seasonal = {c["category"] for c in categories if c["seasonal"]}
    lines = lookback.category_lines(monthly, months, categories, seasonal)
    assert lines["Logement"]["kind"] == "regular"
    assert all(lines[c]["kind"] == "seasonal" for c in seasonal)
    assert abs(sum(v["share"] for v in lines.values()) - 100) < 1
    assert all(len(v["spark"]) == min(len(months), lookback.SPARK_MONTHS) for v in lines.values())


def test_the_rhythm_of_a_month_only_climbs(held):
    r = lookback.rhythm(held, lookback.whole_months(held))
    assert r and len(r["median"]) == 31
    assert all(a <= b + 0.01 for a, b in zip(r["median"], r["median"][1:]))
    assert all(lo <= m + 0.01 and m <= hi + 0.01 for lo, m, hi in zip(r["low"], r["median"], r["high"]))
    cur = r["current"]
    assert cur and len(cur["values"]) == held.period_end.day
    assert 1 <= r["half_day"] <= 31


def test_the_weekdays_are_card_payments_per_day(held):
    w = lookback.weekdays(held, lookback.whole_months(held))
    assert w and [r["day"] for r in w["rows"]][0] == "Lundi"
    assert all(r["per_day"] >= 0 for r in w["rows"])


def test_a_category_up_close(held):
    monthly = analysis.monthly(held)
    months = lookback.whole_months(held)
    d = lookback.category_detail(held, monthly, months, "Alimentation")
    assert d["merchants"] and d["count_year"] > 0
    assert sum(m["share"] for m in d["merchants"]) <= 100.5
    assert d["max"] >= d["mean"] > 0
    assert sum(len([v for v in y["months"] if v is not None]) for y in d["years"]) == d["months"]
