"""The stacked fund against its replica (`stacked.py`): invented series,
built so the right answer is known."""

from __future__ import annotations

import datetime as dt
import json
import math
import random

import pytest

from pms import benchmarks, stacked

D = dt.date


def _days(n: int) -> list[D]:
    out, day = [], D(2024, 1, 1)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def _series(fund_extra: float = 0.0, fx: bool = False, n: int = 400, seed: int = 7) -> dict:
    """USD returns for stocks, trend and cash; the fund is exactly
    stocks + trend - cash, plus `fund_extra` a day. In francs when `fx`:
    every level times the same wandering rate."""
    rng = random.Random(seed)
    days = _days(n)
    levels = {k: [100.0] for k in stacked.NEEDED}
    rate = [1.0]
    for _ in days[1:]:
        s, t, c = rng.gauss(0.0005, 0.01), rng.gauss(0.0002, 0.008), 0.00015
        f = s + t - c + fund_extra
        for k, r in ((stacked.STOCKS, s), (stacked.TREND, t), (stacked.CASH, c), (stacked.FUND, f)):
            levels[k].append(levels[k][-1] * (1 + r))
        rate.append(rate[-1] * (1 + (rng.gauss(0, 0.006) if fx else 0)))
    return {k: [(d, v * x) for d, v, x in zip(days, levels[k], rate)] for k in stacked.NEEDED}


def test_a_fund_that_delivers_its_promise_tracks_its_replica():
    read = stacked.analyse(_series(), D(2024, 1, 1), D(2026, 1, 1))
    assert not read["short"]
    assert read["tracking"]["difference"] == pytest.approx(0, abs=1e-9)
    assert read["tracking"]["error_pa"] == pytest.approx(0, abs=1e-9)
    fit = read["regression"]
    assert fit["beta_stocks"] == pytest.approx(1, abs=1e-6)
    assert fit["beta_trend"] == pytest.approx(1, abs=1e-6)
    # Its trend leg is the trend fund itself.
    assert read["stats"]["leg"]["total"] == pytest.approx(read["stats"]["trend"]["total"], abs=1e-9)
    assert all(v["tone"] == "good" for v in read["verdict"])


def test_the_franc_cancels_out_of_the_replica():
    """All four in francs, through the same exchange rate: the replica's
    weights sum to one, so the comparison is the USD one, to the cent."""
    usd = stacked.analyse(_series(fx=False), D(2024, 1, 1), D(2026, 1, 1))
    chf = stacked.analyse(_series(fx=True), D(2024, 1, 1), D(2026, 1, 1))
    assert chf["tracking"]["error_pa"] == pytest.approx(0, abs=1e-9)
    assert chf["regression"]["beta_stocks"] == pytest.approx(1, abs=1e-6)
    assert usd["tracking"]["difference"] == pytest.approx(0, abs=1e-9)


def test_a_fee_reads_as_a_gap_to_the_replica():
    fee = 0.01 / stacked.TRADING_DAYS   # 1 % a year, taken daily
    read = stacked.analyse(_series(fund_extra=-fee), D(2024, 1, 1), D(2026, 1, 1))
    # A gap between two rates per year: the fee times (1 + the return), so
    # more than 1 % on an invented series growing ~30 % a year.
    assert -0.02 < read["tracking"]["difference_pa"] < -0.009
    assert read["regression"]["alpha_pa"] == pytest.approx(-0.01, abs=1e-6)  # exact


def test_a_short_window_says_so_and_where_the_fund_starts():
    series = _series()
    read = stacked.analyse(series, D(2025, 3, 3), D(2025, 3, 20))
    assert read["short"] and read["since"] == series[stacked.FUND][0][0]
    assert stacked.analyse({**series, stacked.CASH: []}, D(2024, 1, 1), D(2026, 1, 1)) is None


def test_a_window_is_read_from_its_first_day_and_rates_wait_for_a_year():
    series = _series(n=600)
    read = stacked.analyse(series, D(2024, 6, 3), D(2024, 12, 31))
    assert read["from"] < D(2024, 6, 3) <= read["rows"][1]["date"]   # the base is the day before
    assert read["stats"]["fund"]["annual"] is None
    assert "sur la période" in read["verdict"][-1]["text"]
    for row in read["rows"]:
        assert all(math.isfinite(row[k]) for k in ("fund", "replica", "stocks", "trend", "leg"))


def test_months_are_whole_and_the_falls_count_them():
    read = stacked.analyse(_series(n=400), D(2024, 2, 1), D(2025, 6, 30))
    falls = read["falls"]
    assert falls is not None and 0 < falls["months"] <= falls["of"] == 17
    assert falls["stocks"] < 0


def test_the_pocket_and_the_indices_above_cash_by_period(tmp_path):
    """Invented returns: a pocket exactly the fund minus the S&P 500, indices
    over cash, cumulated period after period."""
    rows = [{"periode": "A", "ordre": 1, "rsst": 21.0, "sptr": 10.0, "sg_trend": 6.0, "sg_cta": 4.0,
             "dbmf": 9.0, "cash": 4.0, "sources": "inventé"},
            {"periode": "B", "ordre": 2, "rsst": -5.0, "sptr": -5.0, "sg_trend": 1.0, "sg_cta": 1.0,
             "dbmf": 1.0, "cash": 1.0, "sources": "est."}]
    path = tmp_path / "trend_periods.json"
    path.write_text(json.dumps({"rows": rows[::-1], "meta": []}), encoding="utf-8")
    read = stacked.periods(path)
    a, b = read["rows"]                                    # sorted by `ordre`
    assert a["period"] == "A" and a["pocket"] == pytest.approx((10 + 11) / 2, abs=0.01)
    assert a["sg_cta"] == pytest.approx(0.0, abs=1e-9)     # 4 % against 4 % of cash
    assert b["pocket"] == pytest.approx(0.0) and b["sg_trend"] == pytest.approx(0.0)
    assert read["total"]["pocket"] == pytest.approx(a["pocket"], abs=0.01)
    assert read["total"]["gap_trend"] == pytest.approx(read["total"]["pocket"] - read["total"]["sg_trend"])
    assert read["estimated"]                               # one row says "est."
    assert stacked.periods(tmp_path / "absent.json") is None


def test_the_sg_lines_join_their_anchors_in_francs():
    """No franc move and an index returning what DBMF returned: the SG CTA
    line lands where DBMF does at each anchor, and is None outside."""
    series = _series(n=520)
    # DBMF over 2024, in the invented series (no exchange rate: fx = 1).
    lv = dict(series[stacked.TREND])
    a, z = D(2024, 1, 31), D(2024, 12, 31)
    day_a = max(d for d in lv if d <= a)
    day_z = max(d for d in lv if d <= z)
    dbmf = (lv[day_z] / lv[day_a] - 1) * 100
    read = stacked.analyse(series, D(2024, 1, 1), D(2026, 1, 1))
    rows = [{"debut": a.isoformat(), "fin": z.isoformat(), "dbmf": dbmf, "sg_cta": dbmf, "sg_trend": 0.0}]
    stacked.overlay(read, rows, series[stacked.TREND])
    curve = read["rows"]
    at_z = next(r for r in reversed(curve) if r["date"] <= z)
    start = next(r for r in reversed(curve) if r["date"] <= a)
    assert read["anchors"]["sg_cta"][-1]["level"] == pytest.approx(
        start["trend"] * lv[day_z] / lv[day_a], rel=1e-3)
    assert at_z["sg_cta"] == pytest.approx(at_z["trend"], rel=0.02)
    assert curve[0]["sg_cta"] is None and curve[-1]["sg_cta"] is None
    # An index that made nothing in USD stays flat in a USD world.
    assert read["anchors"]["sg_trend"][-1]["level"] == pytest.approx(
        read["anchors"]["sg_trend"][0]["level"], rel=1e-9)


def test_the_components_are_captured_but_not_offered(tmp_path):
    out = tmp_path / "benchmarks.json"
    snap = benchmarks.capture(out, D(2026, 1, 1), D(2026, 7, 1),
                              fetcher=lambda k, s, e: [["2026-01-02", 1.0]])
    assert {"rsst", "tbill", "managed_futures"} <= set(snap["series"])
    assert "managed_futures" in benchmarks.KEYS
    assert "rsst" not in benchmarks.available(out, None)


def test_the_savings_page_reads_the_fund_it_holds(client):
    from webhelpers import api, savings_snapshots
    store_ = client.application.extensions["pms_store"]
    out = store_.path.with_name("benchmarks.json")
    ibkr_path, finp_path = savings_snapshots(client)
    try:
        assert api(client, "/api/savings?preset=all")["stacked"] is None   # no RSST held
        raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
        raw["positions"].append({"name": "RSST", "currency": "USD", "market_value": 100.0,
                                 "market_value_chf": 80.0, "unrealized_pnl_chf": 4.0,
                                 "unrealized_pnl_pct": 5.0, "exposure": 2.0})
        ibkr_path.write_text(json.dumps(raw), encoding="utf-8")
        assert api(client, "/api/savings?preset=all")["stacked"]["missing"]

        high = store_.bounds[1]
        series = _series(n=500, seed=3)
        shift = high - series[stacked.FUND][-1][0]
        out.write_text(json.dumps({"series": {k: [[(d + shift).isoformat(), v] for d, v in s]
                                              for k, s in series.items()}}), encoding="utf-8")
        pack = api(client, "/api/savings?preset=all")["stacked"]
        assert not pack["missing"] and pack["position"]["value"] == 80.0
        assert pack["launch"]["days"] == 499
        assert pack["launch"]["tracking"]["error_pa"] == pytest.approx(0, abs=1e-9)
    finally:
        for p in (out, ibkr_path, finp_path):
            p.unlink(missing_ok=True)
