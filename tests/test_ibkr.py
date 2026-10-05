"""The brokerage snapshot: a captured state, and its absence is fine.

Everything here is fake -- the invariant is that no real account data ever
lives in the repository.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from pms import ibkr


def _snapshot(**overrides) -> dict:
    base = {
        "captured_at": "2026-08-02T21:10:00",
        "base_currency": "CHF",
        "fx_chf_per_usd": 0.8078,
        "account": {"net_liquidation": 8957.04, "total_cash": 95.53},
        "cash": [{"currency": "USD", "amount": 118.12},
                 {"currency": "CHF", "amount": 0.11}],
        "positions": [{"name": "TEST", "currency": "USD", "market_value": 1000.0,
                       "market_value_chf": 807.8,
                       "unrealized_pnl": 200.0, "unrealized_pnl_chf": 161.6,
                       "unrealized_pnl_pct": 25.0}],
        "performance": {"measure": "TWR", "ytd_pct": 16.4, "one_year_pct": 46.8},
        "other_accounts": [{"name": "3a (exemple)", "value": 10000.0}],
        "nav": [["2025-08-04", 6307.59], ["2026-08-02", 8957.04]],
    }
    base.update(overrides)
    return base


def _write(tmp_path, payload) -> None:
    path = tmp_path / "ibkr.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_file_is_none(tmp_path):
    assert ibkr.load(tmp_path / "ibkr.json") is None


def test_corrupt_file_is_none(tmp_path):
    path = tmp_path / "ibkr.json"
    path.write_text("{not json", encoding="utf-8")
    assert ibkr.load(path) is None


def test_empty_nav_is_none(tmp_path):
    assert ibkr.load(_write(tmp_path, _snapshot(nav=[]))) is None


def test_normalizes(tmp_path):
    data = ibkr.load(_write(tmp_path, _snapshot()))
    assert data["equity"] == 8957.04
    assert data["cash"] == [{"currency": "USD", "amount": 118.12},
                            {"currency": "CHF", "amount": 0.11}]
    assert data["fx_rate"] == 0.8078
    pos = data["positions"][0]
    assert pos["name"] == "TEST"
    assert pos["value"] == 807.8          # the CHF figure wins
    assert pos["value_currency"] == 1000.0
    assert pos["pnl"] == 161.6
    assert pos["pnl_pct"] == 25.0
    assert data["other_accounts"] == [{"name": "3a (exemple)", "value": 10000.0}]
    assert data["performance"]["one_year_pct"] == 46.8
    assert data["nav"][0] == (dt.date(2025, 8, 4), 6307.59)
    assert data["nav"][-1] == (dt.date(2026, 8, 2), 8957.04)


def test_position_falls_back_to_own_currency(tmp_path):
    payload = _snapshot()
    del payload["positions"][0]["market_value_chf"]
    del payload["positions"][0]["unrealized_pnl_chf"]
    data = ibkr.load(_write(tmp_path, payload))
    assert data["positions"][0]["value"] == 1000.0
    assert data["positions"][0]["pnl"] == 200.0


def test_nav_is_sorted(tmp_path):
    payload = _snapshot(nav=[["2026-01-01", 1.0], ["2025-01-01", 2.0]])
    dates = [d for d, _ in ibkr.load(_write(tmp_path, payload))["nav"]]
    assert dates == [dt.date(2025, 1, 1), dt.date(2026, 1, 1)]


def test_nav_daily_scales_onto_the_monthly_anchors(tmp_path):
    """The daily capture is the position's share price, not the NAV: each
    day is the monthly anchor's value scaled by the price move since the
    anchor, so the series agrees with the bank's figure at every anchor."""
    payload = _snapshot(
        nav=[["2025-08-04", 6307.59], ["2025-09-01", 6577.73]],
        nav_daily=[["2025-08-04", 23.0], ["2025-08-20", 24.0],
                   ["2025-09-01", 24.5]])
    data = ibkr.load(_write(tmp_path, payload))
    daily = dict(data["nav_daily"])
    assert daily[dt.date(2025, 8, 4)] == 6307.59              # the anchor
    assert daily[dt.date(2025, 8, 20)] == 6581.83             # 6307.59*24/23
    assert daily[dt.date(2025, 9, 1)] == 6577.73              # next anchor
    assert len(data["nav_daily"]) == 3


def test_nav_at_prefers_the_daily_series(tmp_path):
    payload = _snapshot(
        nav=[["2025-08-04", 6307.59], ["2025-09-01", 6577.73]],
        nav_daily=[["2025-08-04", 23.0], ["2025-08-20", 24.0],
                   ["2025-09-01", 24.5]])
    data = ibkr.load(_write(tmp_path, payload))
    assert ibkr.nav_at(data, dt.date(2025, 8, 20)) == 6581.83
    assert ibkr.nav_at(data, dt.date(2025, 8, 25)) == 6581.83  # last <= day
    assert ibkr.nav_at(data, dt.date(2025, 9, 1)) == 6577.73
    # Without a daily capture, the monthly staircase still rules.
    assert ibkr.nav_at({"nav": [(dt.date(2025, 8, 4), 6307.59)]},
                       dt.date(2025, 8, 20)) == 6307.59


def test_nav_at():
    snapshot = {"nav": [(dt.date(2025, 8, 4), 6307.59),
                        (dt.date(2025, 9, 1), 6577.73)]}
    assert ibkr.nav_at(snapshot, dt.date(2025, 8, 20)) == 6307.59
    assert ibkr.nav_at(snapshot, dt.date(2025, 9, 1)) == 6577.73
    assert ibkr.nav_at(snapshot, dt.date(2025, 7, 1)) == 6307.59  # before the series
    assert ibkr.nav_at(snapshot, dt.date(2026, 1, 1)) == 6577.73  # past the end


def test_evolution_chart_geometry():
    from pms.web import charts
    rows = [
        {"date": dt.date(2025, 9, 30), "swiss": 30000.0, "ibkr": 6000.0,
         "finp": None, "total": 36000.0},
        {"date": dt.date(2025, 10, 31), "swiss": 31000.0, "ibkr": 7000.0,
         "finp": 8000.0, "total": 46000.0},
        {"date": dt.date(2025, 11, 30), "swiss": 32000.0, "ibkr": 8000.0,
         "finp": 8000.0, "total": 48000.0},
    ]
    chart = charts.evolution_chart(rows)
    assert any(d["slot"] == 1 for d in chart["draw"])   # the total line
    assert chart["series"][0]["name"] == "Swissquote"
    assert chart["series"][1]["name"] == "Épargne totale"
    assert chart["series"][2]["name"] == "IBKR"
    assert chart["series"][3]["name"] == "3a finpension"
    assert chart["series"][3]["pts"][0] is None          # the gap is a gap
    assert chart["series"][3]["pts"][-1][2] == 8000.0
    assert chart["series"][1]["pts"][-1][2] == 48000.0
    assert charts.evolution_chart([rows[0]]) == {}


def test_evolution_chart_focus_shows_only_the_pocket():
    from pms.web import charts
    rows = [
        {"date": dt.date(2025, 9, 30), "swiss": 30000.0, "ibkr": 6000.0,
         "finp": None, "total": 36000.0},
        {"date": dt.date(2025, 10, 31), "swiss": 31000.0, "ibkr": 7000.0,
         "finp": 8000.0, "total": 46000.0},
    ]
    chart = charts.evolution_chart(rows, focus="finpension")
    assert list(chart["series"]) == [3]          # only the 3a, in its own slot
    assert chart["series"][3]["pts"][-1][2] == 8000.0
    assert len(chart["draw"]) == 1               # one line, not a dimmed crowd

    chart = charts.evolution_chart(rows, focus="swissquote")
    assert list(chart["series"]) == [0]
    assert chart["ticks"][0]["value"] == 0.0     # zero-anchored even solo


def test_evolution_chart_an_explicit_spec_wins_over_the_focus():
    """A caller-built spec names every line to draw; the focus filter only
    applies to the default spec. That is what lets a focused pocket draw
    its own breakdown (clicking IBKR then "Monnaie" decomposes the pocket)
    instead of an empty chart."""
    from pms.web import charts
    rows = [
        {"date": dt.date(2025, 9, 30), "ibkr": 6000.0, "total": 36000.0,
         "ibkr_usd": 5999.9, "ibkr_chf": 0.1},
        {"date": dt.date(2025, 10, 31), "ibkr": 7000.0, "total": 46000.0,
         "ibkr_usd": 6999.9, "ibkr_chf": 0.1},
        {"date": dt.date(2025, 11, 30), "ibkr": 8000.0, "total": 48000.0,
         "ibkr_usd": 7999.9, "ibkr_chf": 0.1},
    ]
    spec = [{"key": "ibkr_usd", "name": "USD", "slot": 2},
            {"key": "ibkr_chf", "name": "CHF", "slot": 0},
            {"key": "total", "name": "Épargne totale", "slot": 1}]
    chart = charts.evolution_chart(rows, focus="ibkr", spec=spec)
    assert list(chart["series"]) == [2, 0, 1]
    assert chart["series"][2]["pts"][-1][2] == 7999.9


def test_evolution_chart_scale():
    from pms.web import charts
    rows = [
        {"date": dt.date(2025, 9, 30), "swiss": 30000.0, "ibkr": 6000.0,
         "finp": None, "total": 36000.0},
        {"date": dt.date(2025, 10, 31), "swiss": 31000.0, "ibkr": 7000.0,
         "finp": 8000.0, "total": 46000.0},
    ]
    # Zero-anchored by default: the bottom tick is 0, the top a clean bound.
    chart = charts.evolution_chart(rows)
    assert chart["ticks"][0]["value"] == 0.0
    assert chart["ticks"][2]["value"] == 50000.0
    # "auto" fits the lowest value instead -- and hugs the top too: the
    # data peaks at 46'000, which the 50'000 ceiling would pad into a band
    # of empty plot above the line.
    chart = charts.evolution_chart(rows, scale="auto")
    assert chart["ticks"][0]["value"] == 6000.0
    assert chart["ticks"][2]["value"] == 46000.0


def _with_flows(tmp_path):
    import json

    from pms import ibkr
    path = tmp_path / "ibkr.json"
    path.write_text(json.dumps({
        "account": {"net_liquidation": 11704.40},
        # The shape of a first deposit: it lands the same day the fund
        # rises 0.9 %.
        "nav": [["2026-09-01", 9000.00], ["2026-09-23", 9600.00],
                ["2026-09-24", 11704.40], ["2026-09-30", 11679.54]],
        "flows": [["2026-08-15", 100.0], ["bad", 1]],
    }), encoding="utf-8")
    return ibkr.load(path)


def test_a_deposit_is_not_a_return(tmp_path):
    """The ratio of two NAVs reads the first deposit as +30 % for September;
    the TWR says +7.4 %. The flow joins the base at the start of its
    interval -- the broker's convention, +0.90 % on the 24th, not +1.09 %."""
    import datetime as dt

    from pms import ibkr
    from pms.models import Transaction
    snap = _with_flows(tmp_path)

    def txn(day, kind, amount):
        return Transaction(date=dt.date.fromisoformat(day), reference="1",
                           currency="CHF", amount=amount, value_date=None,
                           balance=0.0, kind=kind, amount_chf=amount)

    rows = [txn("2026-09-24", "Versement pour Interactive Brokers LLC", -2000.0),
            txn("2026-09-24", "Versement pour Régie SA", -1500.0)]
    flows = ibkr.flows(snap, rows)
    # From the ledger (the transfer, seen from the brokerage); the snapshot's
    # declared deposit of 15.08 predates the first value point (01.09), so it
    # is already inside it and not counted again; a malformed row is dropped.
    assert flows == [(dt.date(2026, 9, 24), 2000.0)]

    day = ibkr.twr(snap, flows, dt.date(2026, 9, 23), dt.date(2026, 9, 24))
    assert round(day * 100, 2) == 0.90
    month = ibkr.twr(snap, flows, dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert round(month * 100, 1) == 7.4
    # Without flows it is the plain ratio, as before there were any.
    assert ibkr.twr(snap, [], dt.date(2026, 9, 1), dt.date(2026, 9, 23)) == \
        pytest.approx(9600.00 / 9000.00 - 1)


def test_the_brokers_daily_nav_wins_over_the_scaled_price(tmp_path):
    import datetime as dt
    import json

    from pms import ibkr
    path = tmp_path / "ibkr.json"
    path.write_text(json.dumps({
        "account": {"net_liquidation": 110.0},
        "nav": [["2026-01-01", 100.0], ["2026-01-05", 110.0]],
        "nav_daily": [["2026-01-01", 10.0], ["2026-01-02", 10.5],
                      ["2026-01-05", 12.0]],
    }), encoding="utf-8")
    snap = ibkr.load(path)
    # The scaled price fills the day without a NAV; the NAV is the figure
    # on the days it exists.
    assert dict(snap["nav_daily"]) == {dt.date(2026, 1, 1): 100.0,
                                       dt.date(2026, 1, 2): 105.0,
                                       dt.date(2026, 1, 5): 110.0}
