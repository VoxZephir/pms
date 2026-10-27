"""Forecast against what happened (`hindsight.py`): the method replayed from
past month-ends, the plan's forecasts kept once a month, and the API."""

from __future__ import annotations

import datetime as dt
import json

from webhelpers import api, plans_path

from pms import analysis, hindsight, plans


def test_the_ledger_cut_at_a_day_closes_on_the_cash_of_that_day(statement):
    day = dt.date(2025, 9, 30)
    past = hindsight.truncate(statement, day)
    assert past.period_end == day and max(t.date for t in past.transactions) <= day
    assert analysis.closing_chf(past) == hindsight.cash_at(statement, day)
    # The whole ledger, cut at its own end, is itself.
    assert analysis.closing_chf(hindsight.truncate(statement, statement.period_end)) == \
        analysis.closing_chf(statement)


def test_a_replayed_month_splits_its_cash_gap_into_income_and_outflows(statement):
    out = hindsight.method(statement)
    assert 3 <= len(out["months"]) <= 12
    for m in out["months"]:
        assert m["ahead"] == 1
        # end = start + income - outflows on both sides, from the same start.
        assert abs(m["gap"] - (m["income_gap"] - m["outflow_gap"])) < 0.05
        assert m["key"] in hindsight.complete_months(statement)
    assert out["bias"]["count"] == len(out["months"])
    # A month that overran says which categories ran above their usual month.
    worst = max(out["months"], key=lambda m: m["outflow_gap"])
    assert worst["why"] and worst["why"][0]["over"] >= 50


def test_the_plan_is_kept_once_a_month_and_compared_when_its_months_are_whole(statement, tmp_path):
    path = tmp_path / "forecasts.json"
    now = plans.project(statement, None, months_ahead=12)
    assert hindsight.record(path, statement, now, None)
    assert not hindsight.record(path, statement, now, "Autre")   # the same month: the first stays
    assert hindsight.kept(statement, path)["months"] == []        # nothing whole after it yet
    # A forecast kept three months ago, under a plan's name.
    cutoff = dt.date(2026, 3, 31)
    past = hindsight.truncate(statement, cutoff)
    assert hindsight.record(path, past, plans.project(past, None, months_ahead=12), "Prudent")
    kept = hindsight.kept(statement, path)
    assert kept["kept"] == 2 and kept["first"] == "2026-03-31"
    assert [m["key"] for m in kept["months"]] == ["2026-04"]
    assert [p["key"] for p in kept["runs"][0]["points"]] == ["2026-04", "2026-05", "2026-06"]
    assert kept["months"][0]["plan"] == "Prudent"
    assert [f["made"][:7] for f in json.loads(path.read_text(encoding="utf-8"))["forecasts"]] == ["2026-03", "2026-07"]


def test_the_page_keeps_its_first_look_of_the_month_and_answers_both_sources(client):
    forecasts = plans_path(client).with_name("forecasts.json")
    forecasts.unlink(missing_ok=True)
    try:
        api(client, "/api/previsions")
        api(client, "/api/previsions?months=24")
        assert len(json.loads(forecasts.read_text(encoding="utf-8"))["forecasts"]) == 1
        h = api(client, "/api/previsions/hindsight")
        assert h["plan"]["kept"] == 1 and h["plan"]["months"] == []
        assert h["method"]["months"] and h["method"]["bias"]
        assert h["spend"] > 0 and h["spend_declared"] is False
        suggest = h["method"]["suggest_spend"]
        bias = h["method"]["bias"]["outflow"]
        assert (suggest is not None) == (bias["steady"] and bias["mean"] > 0)
    finally:
        forecasts.unlink(missing_ok=True)
