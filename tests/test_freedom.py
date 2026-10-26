"""Financial independence: years covered, the target at a withdrawal rate,
and when the plan reaches it."""

from __future__ import annotations

import pytest

from pms import freedom
from pms.plans import Plan
from webhelpers import api, plans_path


def test_reach_compounds_monthly_and_stops_at_fifty_years():
    assert freedom.reach(100, 100, 0, [], 0.0) == 0
    assert freedom.reach(0, 1200, 100, [], 0.0) == 12
    assert freedom.reach(0, 1e9, 1, [], 0.0) is None
    assert freedom.reach(0, 1200, 100, [], None) is None  # no rate, no date
    # A return brings the date nearer than saving alone.
    assert freedom.reach(10_000, 50_000, 500, [], 0.05) < freedom.reach(10_000, 50_000, 500, [], 0.0)


def test_the_target_is_the_spending_over_the_withdrawal_rate(client):
    held = client.application.extensions["pms_store"].statement
    out = freedom.independence(held, 100_000, 7000, Plan(plans_path(client)), 4.0)
    assert out["target"] == pytest.approx(out["spend"] / 0.04, abs=1)  # both rounded
    assert out["years_covered"] == pytest.approx(100_000 / out["spend"])
    assert out["months"] is None and out["months_flat"] is not None  # no declared return
    assert all(w["sooner"] is None or w["sooner"] >= 0 for w in out["what_ifs"])


def test_the_page_carries_it_and_the_rate_is_chosen(client):
    a = api(client, "/api/previsions")["freedom"]
    b = api(client, "/api/previsions?swr=3")["freedom"]
    assert b["withdrawal"] == 3.0 and b["target"] > a["target"]
    assert api(client, "/api/previsions?swr=9")["freedom"]["withdrawal"] == 4.0
