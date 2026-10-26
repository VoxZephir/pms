"""Helpers shared by the web tests (the `client` fixture lives in conftest)."""

from __future__ import annotations

import json


def api(client, url: str) -> dict:
    """GET an endpoint of the JSON API; it must answer, and in JSON a browser
    can parse -- no NaN, no Infinity: the browser refuses the whole payload
    over one."""
    response = client.get(url)
    assert response.status_code == 200, (url, response.status_code, response.get_data()[:300])
    assert response.mimetype == "application/json", (url, response.mimetype)

    def refuse(constant):
        raise ValueError(f"{url}: {constant} is not JSON")

    return json.loads(response.get_data(), parse_constant=refuse)


def plans_path(client):
    return client.application.extensions["pms_store"].path.with_name("plans.json")


def savings_snapshots(client):
    """The two pockets the net-worth curve needs, written next to the ledger.
    Returns the paths so the caller can clean up -- the store reads them fresh
    on every request, so leaving them behind would leak into other tests."""
    store_ = client.application.extensions["pms_store"]
    ibkr_path = store_.path.with_name("ibkr.json")
    finp_path = store_.path.with_name("finpension.json")
    ibkr_path.write_text(json.dumps({
        "captured_at": "2026-08-02T21:10:00", "base_currency": "CHF",
        "fx_chf_per_usd": 0.8,
        "account": {"net_liquidation": 9000.0, "total_cash": 95.0},
        "cash": [{"currency": "CHF", "amount": 0.11}],
        "positions": [{"name": "TEST", "currency": "USD",
                       "market_value": 1000.0, "market_value_chf": 800.0,
                       "asset_class": "Actions",
                       "unrealized_pnl": 200.0, "unrealized_pnl_chf": 160.0,
                       "unrealized_pnl_pct": 25.0}],
        "performance": {"measure": "TWR", "ytd_pct": 8.0, "one_year_pct": 12.0},
        # Three levels, so the measured volatility exists when nothing is
        # declared -- the band note then has something honest to say.
        "nav": [["2025-08-04", 6300.0], ["2026-01-02", 7600.0],
                ["2026-08-02", 9000.0]],
    }), encoding="utf-8")
    finp_path.write_text(json.dumps({
        "value": 8300.0, "value_as_of": "2025-12-31", "deposits": 7000.0,
        "dividends": 90.0, "fees": 40.0, "cash": 100.0,
        "yearly": [["2025-12-31", 8300.0]],
        "holdings": {"CH123": {"shares": 3.0, "price": 100.0,
                               "name": "Fonds Equity", "class": "Actions"}},
    }), encoding="utf-8")
    return ibkr_path, finp_path


# --- a long list of corrections ---------------------------------------------------

def corrected_ledger(tmp_path_factory, ledger_file, pins: int = 12):
    """A private ledger copy with `pins` pinned movements, two merchant rules
    and one merge -- corrections with something in every group."""
    from pms.overrides import Overrides
    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("rulesgroups")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())
    app = create_app(ledger_copy)
    rows = app.extensions["pms_store"].statement.transactions
    store = Overrides.load(workdir / "overrides.json")
    for txn in rows[:pins]:
        store.pin(f"{txn.reference}:{txn.currency}", bucket="Need", label=txn.label)
    store.rule("Pizzeria Da Mario", category="Restaurants & bars")
    store.rule("Sushi Zen", category="Restaurants & bars")
    store.alias("Régie du Centre S.A.", "Régie du Centre SA")
    store.save()
    return app
