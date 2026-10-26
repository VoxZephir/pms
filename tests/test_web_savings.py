"""The savings (`/api/savings`): the snapshots, the split, the focus, the
returns, the fees, the stats, the year-ends."""

from __future__ import annotations

import json

import pytest
from webhelpers import api, savings_snapshots


def _ibkr(client, payload: dict):
    path = client.application.extensions["pms_store"].path.with_name("ibkr.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


LEVERED = {
    "captured_at": "2026-08-02T21:10:00", "base_currency": "CHF", "fx_chf_per_usd": 0.8,
    "account": {"net_liquidation": 9000.0, "total_cash": 95.0},
    "cash": [{"currency": "USD", "amount": 118.12}, {"currency": "CHF", "amount": 0.11}],
    "positions": [{"name": "TEST", "currency": "USD", "market_value": 1000.0,
                   "market_value_chf": 800.0, "asset_class": "Actions",
                   "asset_split": {"Actions": 50, "MF": 50}, "exposure": 2.0,
                   "unrealized_pnl": 200.0, "unrealized_pnl_chf": 160.0,
                   "unrealized_pnl_pct": 25.0}],
    "performance": {"measure": "TWR", "ytd_pct": 8.0, "one_year_pct": 12.0},
    "nav": [["2025-08-04", 6300.0], ["2026-08-02", 9000.0]],
}


@pytest.fixture
def pockets(client):
    """The levered brokerage and the 3a, removed afterwards."""
    ibkr_path, finp_path = savings_snapshots(client)
    _ibkr(client, LEVERED)
    yield
    ibkr_path.unlink(missing_ok=True)
    finp_path.unlink(missing_ok=True)


def test_without_a_snapshot_the_page_says_so(client):
    assert api(client, "/api/savings?preset=all")["available"] is False


def test_the_page_follows_the_window(client, pockets):
    """The state at the window's end; one point is not a curve."""
    data = api(client, "/api/savings?from=2025-12-01&to=2025-12-31")
    assert data["period"]["end"] == "2025-12-31"
    assert len(data["evolution"]["rows"]) > 1
    coarse = api(client, "/api/savings?from=2025-01-01&to=2025-12-31&grain=year")
    assert len(coarse["evolution"]["rows"]) <= 1


def test_the_split_is_one_money_seen_several_ways(client, pockets):
    by_account = api(client, "/api/savings?preset=all")
    assert {"Swissquote", "IBKR", "3a finpension"} <= {p["name"] for p in by_account["parts"]}
    by_currency = api(client, "/api/savings?preset=all&split=currency")
    assert "USD" in {p["name"] for p in by_currency["parts"]}
    by_asset = api(client, "/api/savings?preset=all&split=asset")
    names = {p["name"] for p in by_asset["parts"]}
    assert {"Actions", "Trend-Following", "Cash"} <= names     # RSST's managed-futures half
    total = sum(p["value"] for p in by_account["parts"])
    assert sum(p["value"] for p in by_asset["parts"]) == pytest.approx(total, abs=1)


def test_a_levered_fund_weighs_more_in_exposure(client, pockets):
    """The bar splits francs; the exposure says the risk beyond them."""
    exposure = api(client, "/api/savings?preset=all")["allocation"]["exposure"]
    assert exposure["gross"] > 100
    assert next(p for p in api(client, "/api/savings?preset=all")["positions"])["exposure"] == 2.0


def test_the_focus_drives_the_headline_and_the_curve(client, pockets):
    total = api(client, "/api/savings?preset=all")
    assert total["hero"]["pocket"] == "total"
    assert [p["pocket"] for p in total["pockets"]][:4] == ["total", "swissquote", "ibkr", "finpension"] or \
        {"total", "swissquote", "ibkr", "finpension"} <= {p["pocket"] for p in total["pockets"]}
    assert "total" in [s["key"] for s in total["evolution"]["spec"]]

    finp = api(client, "/api/savings?preset=all&focus=finpension")
    assert finp["hero"]["pocket"] == "finpension"
    assert [s["key"] for s in finp["evolution"]["spec"]] == ["finp"]


def test_a_focused_pocket_is_broken_down_on_its_own(client, pockets):
    """Clicking IBKR then "Monnaie" decomposes the brokerage, not the whole
    portfolio -- and never empties the chart (it used to 500)."""
    data = api(client, "/api/savings?preset=all&focus=ibkr&split=currency")
    assert {p["name"] for p in data["parts"]} == {"USD", "CHF"}
    assert [s["key"] for s in data["evolution"]["spec"]] == ["ibkr_usd", "ibkr_chf"]
    for combo in ("focus=ibkr&split=asset", "focus=finpension&split=fund",
                  "focus=swissquote&split=geo"):
        assert api(client, f"/api/savings?preset=all&{combo}")["evolution"]["spec"]


def test_a_pocket_younger_than_the_window_is_a_gap_not_a_zero(client, pockets):
    """The 3a only prints yearly values: before its first, nothing."""
    rows = api(client, "/api/savings?preset=all")["evolution"]["rows"]
    assert rows[0]["finp"] is None and rows[-1]["finp"] is not None


def test_the_stats_do_not_depend_on_the_grain(client, pockets):
    """Measured daily whatever the grain: feeding it the display rows used to
    scale the vol by sqrt(12) on daily returns (regression)."""
    window = "from=2025-08-01&to=2026-07-31"
    tables = [api(client, f"/api/savings?{window}&grain={g}")["risk"] for g in ("month", "day", "week")]
    assert tables[0] == tables[1] == tables[2]
    vol = next(r for r in tables[0]["rows"] if r["label"].startswith("Volatilité"))
    assert not any(c["text"].startswith("-100") for c in vol["cells"])


def test_a_stale_snapshot_is_announced(client):
    """A snapshot carries its last value forward: a stale one reads like a
    current one unless the page says which pocket is behind."""
    high = client.application.extensions["pms_store"].bounds[1]

    def snapshot(last):
        return _ibkr(client, {"captured_at": f"{last}T08:00:00",
                              "account": {"net_liquidation": 9000.0},
                              "nav": [["2025-01-06", 8000.0], [last, 9000.0]]})
    path = snapshot("2025-02-03")
    try:
        (note,) = api(client, "/api/savings?preset=all")["stale"]
        assert note.startswith("IBKR : chiffres arrêtés au 03.02.2025")
        snapshot(high.isoformat())
        assert api(client, "/api/savings?preset=all")["stale"] == []
    finally:
        path.unlink(missing_ok=True)


def test_a_deposit_is_not_a_return(client):
    """A NAV that jumps by a deposit: 10'000 -> 10'100 is +1 %, then 13'130
    on a 13'100 base is +0.23 % -- +1.2 %, not the +31 % of the ratio."""
    high = client.application.extensions["pms_store"].bounds[1]
    start, middle = high.replace(day=1), high.replace(day=10)
    path = _ibkr(client, {"account": {"net_liquidation": 13000.0},
                          "nav": [[start.isoformat(), 10000.0], [middle.isoformat(), 10100.0],
                                  [high.isoformat(), 13130.0]],
                          "flows": [[high.isoformat(), 3000.0]]})
    try:
        hero = api(client, f"/api/savings?from={start}&to={high}&focus=ibkr")["hero"]
        assert hero["put_in"] == 3000.0
        assert hero["twr"] == pytest.approx(0.0123, abs=0.0005)
    finally:
        path.unlink(missing_ok=True)


def test_returns_per_year_only_from_a_year_on(client, pockets):
    low, high = client.application.extensions["pms_store"].bounds
    year = api(client, f"/api/savings?from={low}&to={high}&rate=annual")
    assert year["rate"] == "annual"
    assert any(p["twr_pa"] is not None for p in year["pockets"] if p["pocket"] != "swissquote")
    month = api(client, f"/api/savings?from={high.replace(day=1)}&to={high}&rate=annual")
    assert all(p["twr_pa"] is None for p in month["pockets"])
    assert api(client, "/api/savings?preset=all&rate=<x>")["rate"] == "period"


def test_the_twr_mwr_switch_is_read_and_validated(client, pockets):
    assert api(client, "/api/savings?preset=all&perf=mwr")["perf"] == "mwr"
    assert api(client, "/api/savings?preset=all&perf=<x>")["perf"] == "twr"


def test_base_100_starts_every_line_at_100(client, pockets):
    for perf in ("twr", "mwr"):
        evolution = api(client, f"/api/savings?preset=all&scale=index&perf={perf}")["evolution"]
        assert evolution["unit"] == ""
        for spec in evolution["spec"]:
            first = next(r[spec["key"]] for r in evolution["rows"] if r[spec["key"]] is not None)
            assert first == pytest.approx(100.0), (perf, spec["name"])
    assert api(client, "/api/savings?preset=all")["evolution"]["unit"] == "CHF"


def test_the_fees_per_pocket_over_the_window(client):
    ibkr_path, finp_path = savings_snapshots(client)
    high = client.application.extensions["pms_store"].bounds[1]
    raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
    raw["costs_known_from"] = "2025-10-01"
    raw["costs"] = [{"date": high.isoformat(), "kind": "commission d'achat",
                     "label": "Achat TEST", "amount_chf": 0.83}]
    ibkr_path.write_text(json.dumps(raw), encoding="utf-8")
    raw = json.loads(finp_path.read_text(encoding="utf-8"))
    raw["fee_entries"] = [["2025-04-07", 1.96], ["2025-07-07", 7.19]]
    finp_path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        fees = api(client, "/api/savings?preset=all")["fees"]
        assert fees["ibkr"]["amount"] == pytest.approx(0.83)
        assert "commission d'achat" in fees["ibkr"]["detail"]
        # The record starts where the connector's history does -- said.
        assert "connus depuis le 01.10.2025" in fees["ibkr"]["detail"]
        assert fees["finpension"]["amount"] == pytest.approx(9.15)
        assert "marge de change sur" in fees["swissquote"]["detail"]
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_the_reserve_the_3a_ceiling_and_the_year_ends(client, pockets):
    low, high = client.application.extensions["pms_store"].bounds
    data = api(client, f"/api/savings?from={low}&to={high}")
    assert data["reserve"]["months"] > 0 and data["reserve"]["low"] < data["reserve"]["high"]
    assert data["pillar3a"]["ceiling"] > 0
    assert data["tax"]["years"] and data["tax"]["rows"]


def test_contributions_and_value_come_from_the_same_book(client):
    """The "Versements et valeur" panel: money put into the invested pockets
    since they opened, against their value, point by point; the gain is the
    gap at the end."""
    from webhelpers import savings_snapshots
    paths = savings_snapshots(client)
    try:
        s = api(client, "/api/savings?preset=all")
        iv = s["invested"]
        assert iv and iv["pockets"] == ["ibkr", "finpension"]
        last = iv["rows"][-1]
        assert last["value"] == iv["value"] and last["contributed"] == iv["contributed"]
        assert iv["gain"] == round(iv["value"] - iv["contributed"], 2)
        # Cumulated from each pocket's opening: never a negative deposit total
        # for pockets that only ever received money.
        assert all(r["contributed"] >= 0 for r in iv["rows"])
        alone = api(client, "/api/savings?preset=all&focus=ibkr")["invested"]
        assert alone["pockets"] == ["ibkr"]
    finally:
        for p in paths:
            p.unlink(missing_ok=True)


WEEKLY = {**LEVERED, "nav": [["2025-01-06", 6000.0], ["2025-02-03", 6600.0], ["2025-03-03", 5600.0],
                             ["2025-04-07", 5000.0], ["2025-05-05", 5900.0], ["2025-06-02", 6700.0],
                             ["2025-09-01", 7000.0], ["2026-01-05", 7600.0], ["2026-08-02", 9000.0]]}


@pytest.fixture
def moving(client):
    """A brokerage that falls and recovers: something for the months and the
    falls to say."""
    ibkr_path, finp_path = savings_snapshots(client)
    _ibkr(client, WEEKLY)
    yield
    ibkr_path.unlink(missing_ok=True)
    finp_path.unlink(missing_ok=True)


def test_the_bridge_adds_up_to_the_headline(client, moving):
    """From the total at the start to the total at the end: set aside, then
    each pocket's return -- the same book as the headline, so the steps add
    up to it and the returns to its gain."""
    for query in ("preset=all", "from=2025-03-01&to=2026-02-28"):
        s = api(client, f"/api/savings?{query}")
        b, total = s["reads"]["bridge"], s["pockets"][-1]
        assert b["start"] == total["start_value"] and b["end"] == total["value"]
        assert abs(b["start"] + sum(st["amount"] for st in b["steps"]) - b["end"]) < 0.05
        saved = next(st for st in b["steps"] if st["key"] == "saved")
        assert saved["amount"] == total["put_in"]
        assert abs(sum(st["amount"] for st in b["steps"] if st["key"] != "saved") - total["gain"]) < 0.05


def test_the_months_chain_to_the_window_return(client, moving):
    """Each pocket's months chain to its years, and the years to the TWR of
    the table; the best and worst months are whole ones."""
    s = api(client, "/api/savings?from=2025-01-15&to=2026-07-30")
    for pocket, m in s["reads"]["months"].items():
        chained = 1.0
        for year in m["years"]:
            in_year = 1.0
            for rate in year["months"]:
                if rate is not None:
                    in_year *= 1 + rate
            assert abs(in_year - 1 - year["rate"]) < 1e-6
            chained *= 1 + year["rate"]
        row = next(r for r in s["pockets"] if r["pocket"] == pocket)
        assert abs(chained - 1 - row["twr"]) < 1e-6, pocket
    ibkr = s["reads"]["months"]["ibkr"]
    assert ibkr["years"][0]["partial"][0] is True       # January cut on the 15th
    assert ibkr["worst"]["rate"] < 0 < ibkr["best"]["rate"]


def test_the_falls_are_measured_from_the_last_high(client, moving):
    s = api(client, "/api/savings?preset=all")
    dd = s["reads"]["drawdowns"]["ibkr"]
    assert all(r["dd"] <= 0 for r in dd["rows"])
    worst = dd["worst"]
    # 6'600 in February to 5'000 in April, made good by June.
    assert worst["depth"] == pytest.approx(5000 / 6600 - 1, abs=0.01)
    assert worst["peak"] < worst["trough"] < worst["recovered"]
    assert min(r["dd"] for r in dd["rows"]) == pytest.approx(worst["depth"], abs=1e-4)


def test_every_pocket_has_its_line_and_its_hue(client, moving):
    s = api(client, "/api/savings?preset=all")
    reads = s["reads"]
    for row in s["pockets"]:
        spark = reads["sparks"][row["pocket"]]
        assert len(spark) > 2 and spark[-1] == pytest.approx(row["value"], abs=0.01)
        assert reads["slots"][row["pocket"]] in range(8)


SHARE = {"holdings": [{"id": "s1", "name": "Port Exemple SA", "quantity": 1, "payer": "Club Nautique Exemple",
                       "withholding": True, "since": 2025, "values": {"2025": 1000, "2026": 1250}}]}


@pytest.fixture
def share(client, pockets):
    path = client.application.extensions["pms_store"].path.with_name("holdings.json")
    path.write_text(json.dumps(SHARE), encoding="utf-8")
    yield path
    path.unlink(missing_ok=True)


def _pocket(s, name):
    return next((r for r in s["pockets"] if r["pocket"] == name), None)


def test_an_unlisted_share_is_a_pocket_and_counts_in_the_total(client, share):
    q = "/api/savings?from=2025-01-01&to=2026-07-30"
    on, off = api(client, q), api(client, q + "&titres=0")
    titres = _pocket(on, "titres")
    assert titres["value"] == 1250 and _pocket(off, "titres") is None
    assert on["total"] == pytest.approx(off["total"] + 1250, abs=0.01)
    # It arrived on 01.01.2025 as a gift: money in, not a gain. Its gain is
    # the revaluation (+250) and the dividend paid out (40, received on the
    # current account in June 2026).
    assert titres["put_in"] == pytest.approx(-40, abs=0.01)
    assert titres["gain"] == pytest.approx(290, abs=0.01)
    total_on, total_off = _pocket(on, "total"), _pocket(off, "total")
    assert total_on["gain"] - total_off["gain"] == pytest.approx(290, abs=0.01)
    assert on["titres"] == {"declared": 1, "counted": True, "value": 1250}
    assert off["titres"]["counted"] is False


def test_the_share_is_in_the_curve_and_the_split(client, share):
    s = api(client, "/api/savings?from=2025-01-01&to=2026-07-30&split=account")
    assert any(p["key"] == "titres" for p in s["evolution"]["spec"])
    assert any(p["name"] == "Titres non cotés" and p["value"] == 1250 for p in s["parts"])
    assert sum(p["value"] for p in s["parts"]) == pytest.approx(s["total"], abs=1)
    focus = api(client, "/api/savings?from=2025-01-01&to=2026-07-30&focus=titres")
    assert focus["hero"]["pocket"] == "titres"
