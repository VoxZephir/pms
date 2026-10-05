"""The savings panel: IBKR and 3a snapshots, the split, the stats table."""

from __future__ import annotations

import re

from webhelpers import text


def test_ibkr_panel_appears_with_a_snapshot(client):
    """The brokerage panel renders when a captured snapshot sits next to the
    ledger -- and the rest of the dashboard must not care about it."""
    import json

    store_ = client.application.extensions["pms_store"]
    path = store_.path.with_name("ibkr.json")
    path.write_text(json.dumps({
        "captured_at": "2026-08-02T21:10:00",
        "base_currency": "CHF",
        "account": {"net_liquidation": 8957.04, "total_cash": 95.53},
        "positions": [{"name": "TEST", "currency": "USD", "market_value": 1000.0,
                       "market_value_chf": 807.8,
                       "unrealized_pnl": 200.0, "unrealized_pnl_chf": 161.6,
                       "unrealized_pnl_pct": 25.0}],
        "performance": {"measure": "TWR", "ytd_pct": 8.0, "one_year_pct": 12.0},
        "other_accounts": [{"name": "3a", "value": 10000.0}],
        "nav": [["2025-08-04", 6307.59], ["2026-08-02", 8957.04]],
    }), encoding="utf-8")
    try:
        body = text(client.get("/?preset=all"))
        assert 'id="p-ibkr"' in body
        assert 'data-hero="total"' in body
        assert "3a" in body
        assert "IBKR" in body
        assert 'id="ibkrChart"' in body
        assert "Évolution de l'épargne" in body

        # The panel follows the window and the grain: a single month shows
        # the state at that month's end with daily points; a year bucketed
        # yearly yields one point and no curve (one point is not a line).
        one_month = text(client.get("/?from=2025-12-01&to=2025-12-31"))
        assert "au 31.12.2025" in one_month
        assert 'id="ibkrChart"' in one_month
        coarse = text(client.get("/?from=2025-01-01&to=2025-12-31&grain=year"))
        assert "au 31.12.2025" in coarse
        assert 'id="ibkrChart"' not in coarse
    finally:
        path.unlink(missing_ok=True)


def test_ibkr_panel_absent_without_snapshot(client):
    body = text(client.get("/?preset=all"))
    assert 'id="p-ibkr"' not in body
    assert 'class="cell empty"' in body or "--h0" in body


def test_savings_split_switches_views(client):
    """The savings bar is one money seen three ways: account, currency,
    asset class -- and the 3a is part of the picture."""
    import json

    store_ = client.application.extensions["pms_store"]
    ibkr_path = store_.path.with_name("ibkr.json")
    finp_path = store_.path.with_name("finpension.json")
    ibkr_path.write_text(json.dumps({
        "captured_at": "2026-08-02T21:10:00",
        "base_currency": "CHF",
        "fx_chf_per_usd": 0.8078,
        "account": {"net_liquidation": 8957.04, "total_cash": 95.53},
        "cash": [{"currency": "USD", "amount": 118.12},
                 {"currency": "CHF", "amount": 0.11}],
        "positions": [{"name": "TEST", "currency": "USD", "market_value": 1000.0,
                       "market_value_chf": 807.8, "asset_class": "Actions",
                       "asset_split": {"Actions": 50, "MF": 50},
                       "unrealized_pnl": 200.0, "unrealized_pnl_chf": 161.6,
                       "unrealized_pnl_pct": 25.0}],
        "performance": {"measure": "TWR", "ytd_pct": 8.0, "one_year_pct": 12.0},
        "nav": [["2025-08-04", 6307.59], ["2026-08-02", 8957.04]],
    }), encoding="utf-8")
    finp_path.write_text(json.dumps({
        "value": 8300.0, "value_as_of": "2025-12-31", "deposits": 7000.0,
        "dividends": 91.02, "fees": 42.04, "cash": 100.0,
        "yearly": [["2025-12-31", 8300.0]],
        "holdings": {"CH123": {"shares": 3.0, "price": 100.0,
                               "name": "Fonds Equity", "class": "Actions"}},
    }), encoding="utf-8")
    try:
        base = text(client.get("/?preset=all"))
        assert "3a finpension" in base
        assert "7’000 CHF versés en tout" in base
        assert "Épargne totale" in base

        # The pocket picker is a labelled control; the headline and the
        # table follow it.
        focused = text(client.get("/?preset=all&focus=finpension"))
        assert re.search(r'aria-current="true"\s+href="[^"]*focus=finpension', focused)
        assert 'data-hero="finpension"' in focused
        total = text(client.get("/?preset=all&focus=total"))
        table = total[total.index("data-pockets"):]
        table = table[:table.index("</table>")]
        for name in ("Swissquote", "IBKR", "3a finpension", "Épargne totale"):
            assert name in table

        by_currency = text(client.get("/?preset=all&split=currency"))
        assert 'class="seg"' in by_currency
        assert ">USD<" in by_currency or "USD " in by_currency
        assert ">Monnaie<" in by_currency

        by_asset = text(client.get("/?preset=all&split=asset"))
        assert ">Actions<" in by_asset or "Actions " in by_asset
        assert "Trend-Following" in by_asset   # RSST's managed-futures half
        assert ">Obligations<" not in by_asset or "Obligations " not in by_asset
        assert ">Cash<" in by_asset or "Cash " in by_asset

        # A focus combined with a split must not empty the chart: the
        # breakdown spec has no line for the focused pocket (regression:
        # clicking a box then a breakdown used to 500 on max() of nothing).
        for combo in ("focus=ibkr&split=currency", "focus=ibkr&split=asset",
                      "focus=finpension&split=fund",
                      "focus=swissquote&split=geo"):
            assert client.get(f"/?preset=all&{combo}").status_code == 200

        # The breakdown decomposes the focused pocket, not the whole
        # portfolio: IBKR is USD equity (the NAV, 6'307 at the window's
        # end) plus its CHF cash (0.11). And the pocket's curve shows its
        # own lines alone -- no "Épargne totale" on top.
        def legend(page):
            part = page[page.index('class="split-legend"'):]
            return part[:part.index("</ul>")]

        pocket = text(client.get("/?preset=all&focus=ibkr&split=currency"))
        assert re.search(r"USD</span>\s*<b>6’307</b>", legend(pocket))
        assert re.search(r"CHF</span>\s*<b>0</b>", legend(pocket))
        assert "Swissquote" not in legend(pocket)
        assert 'data-legend="total"' not in pocket
        asset = text(client.get("/?preset=all&focus=ibkr&split=asset"))
        assert "Trend-Following" in legend(asset)
        assert "3a finpension" not in legend(asset)
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_savings_stats_do_not_depend_on_the_grain(client):
    """The risk table is measured daily whatever the window's grain.
    Feeding it the display rows used to scale the vol by sqrt(12) on daily
    returns and land a whole month's flow on every day -- the total column
    read -100 % at day grain (regression)."""
    import json

    store_ = client.application.extensions["pms_store"]
    ibkr_path = store_.path.with_name("ibkr.json")
    finp_path = store_.path.with_name("finpension.json")
    ibkr_path.write_text(json.dumps({
        "captured_at": "2026-08-02T21:10:00",
        "base_currency": "CHF",
        "fx_chf_per_usd": 0.8078,
        "account": {"net_liquidation": 8957.04, "total_cash": 95.53},
        "cash": [{"currency": "USD", "amount": 118.12},
                 {"currency": "CHF", "amount": 0.11}],
        "positions": [{"name": "TEST", "currency": "USD", "market_value": 1000.0,
                       "market_value_chf": 807.8, "asset_class": "Actions",
                       "asset_split": {"Actions": 50, "MF": 50},
                       "unrealized_pnl": 200.0, "unrealized_pnl_chf": 161.6,
                       "unrealized_pnl_pct": 25.0}],
        "performance": {"measure": "TWR", "ytd_pct": 8.0, "one_year_pct": 12.0},
        "nav": [["2025-08-04", 6307.59], ["2026-08-02", 8957.04]],
    }), encoding="utf-8")
    finp_path.write_text(json.dumps({
        "value": 8300.0, "value_as_of": "2025-12-31", "deposits": 7000.0,
        "dividends": 91.02, "fees": 42.04, "cash": 100.0,
        "yearly": [["2025-12-31", 8300.0]],
        "holdings": {"CH123": {"shares": 3.0, "price": 100.0,
                               "name": "Fonds Equity", "class": "Actions"}},
    }), encoding="utf-8")
    try:
        window = "from=2025-08-01&to=2026-07-31"
        month = text(client.get(f"/?{window}&grain=month"))
        day = text(client.get(f"/?{window}&grain=day"))
        week = text(client.get(f"/?{window}&grain=week"))

        def vol_slice(page: str) -> str:
            i = page.find("Volatilité annualisée")
            assert i >= 0, "the stats table is missing"
            return page[i:i + 400]

        assert vol_slice(day) == vol_slice(month) == vol_slice(week)
        assert "-100" not in vol_slice(day)        # no exploded chain
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_stale_snapshot_is_announced(client):
    """A snapshot carries its last value forward, so a stale one reads like a
    current one. The panel names the pocket that is behind -- and stays quiet
    once the snapshot reaches the date on screen."""
    import json

    store_ = client.application.extensions["pms_store"]
    high = store_.bounds[1]
    path = store_.path.with_name("ibkr.json")

    def snapshot(last):
        path.write_text(json.dumps({
            "captured_at": f"{last}T08:00:00",
            "account": {"net_liquidation": 9000.0},
            "nav": [["2025-01-06", 8000.0], [last, 9000.0]],
        }), encoding="utf-8")

    try:
        snapshot("2025-02-03")
        body = text(client.get("/?preset=all"))
        assert "data-stale" in body
        assert "IBKR : chiffres arrêtés au 03.02.2025" in body

        snapshot(high.isoformat())
        assert "data-stale" not in text(client.get("/?preset=all"))
    finally:
        path.unlink(missing_ok=True)


def test_a_deposit_is_named_and_left_out_of_the_performance(client):
    """A NAV that jumps by a deposit is not a return: the panel says how much
    was deposited and leaves it out, instead of claiming "aucun flux"."""
    import json

    store_ = client.application.extensions["pms_store"]
    high = store_.bounds[1]
    path = store_.path.with_name("ibkr.json")
    start = high.replace(day=1)
    middle = start.replace(day=10)
    path.write_text(json.dumps({
        "account": {"net_liquidation": 13000.0},
        "nav": [[start.isoformat(), 10000.0], [middle.isoformat(), 10100.0],
                [high.isoformat(), 13130.0]],
        "flows": [[high.isoformat(), 3000.0]],
    }), encoding="utf-8")
    try:
        body = text(client.get(f"/?from={start}&to={high}&focus=ibkr"))
        # The headline separates the money put in from what it made.
        assert re.search(r"\+3’000</b>\s*versés", body)
        # 10'000 -> 10'100 is +1 %, then 13'130 on a 13'100 base is +0.23 %:
        # +1.2 %, not the +31 % of the plain ratio.
        assert re.search(r'hero-val pos">\+1\.2 %', body)
    finally:
        path.unlink(missing_ok=True)


def _savings_with_costs(client):
    """The two snapshots, plus what each charged."""
    import json

    from webhelpers import savings_snapshots
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
    return ibkr_path, finp_path


def test_fees_per_pocket_over_the_window(client):
    ibkr_path, finp_path = _savings_with_costs(client)
    try:
        body = text(client.get("/?preset=all"))
        section = body[body.index('id="savings-fees"'):]
        section = section[:section.index("</table>")]
        assert "Frais sur la période" in body
        assert "0.83 CHF" in section
        assert re.search(r"commission d(&#39;|')achat", section)
        assert "9.15 CHF" in section and "2 frais administratifs forfaitaires" in section
        # The IBKR record starts where the connector's history does -- said.
        assert "connus depuis le 01.10.2025" in section
        assert "marge de change sur" in section
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_the_twr_mwr_switch_follows_the_links(client):
    from webhelpers import savings_snapshots
    ibkr_path, finp_path = savings_snapshots(client)
    try:
        twr = text(client.get("/?preset=all&focus=ibkr"))
        assert 'data-perf="twr"' in twr
        mwr = text(client.get("/?preset=all&focus=ibkr&perf=mwr"))
        assert 'data-perf="mwr"' in mwr
        assert "versements retirés" in twr
        assert "pondéré par sa durée" in mwr
        # The choice rides along the other savings links, like the focus.
        assert re.search(r'href="[^"]*focus=finpension[^"]*perf=mwr', mwr) or \
            re.search(r'href="[^"]*perf=mwr[^"]*focus=finpension', mwr)
        # An unknown value falls back to the default, never echoed.
        assert 'data-perf="twr"' in text(client.get("/?preset=all&perf=<x>"))
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_base_100_starts_every_line_at_100_and_drops_the_francs(client):
    from webhelpers import chart_data, savings_snapshots
    ibkr_path, finp_path = savings_snapshots(client)
    try:
        for perf in ("twr", "mwr"):
            body = text(client.get(f"/?preset=all&scale=index&perf={perf}"))
            assert f'data-curve="index-{perf}"' in body
            payload = chart_data(body)["ibkr"]
            assert payload["unit"] == ""
            for series in payload["series"].values():
                first = next(p for p in series["pts"] if p)
                assert first[2] == 100.0, series["name"]
        chf = chart_data(text(client.get("/?preset=all")))["ibkr"]
        assert chf["unit"] == "CHF"
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)
