"""Revolut's crypto statement: quantities that lost their decimal point,
staking rewards rebuilt, and the pocket that comes out of it.

Invented rows in the shape of the real fr-ch export, double-encoded like it.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from pms import crypto

D = dt.date
HEADER = "Symbol,Type,Quantity,Price,Value,Fees,Date"
ROWS = [
    # 0.03 ETH for 90 CHF, printed "3,000,000": the digits, no decimal point.
    'ETH,Achat,"3,000,000","3 000,00 CHF","90,00 CHF","1,50 CHF","3 avr. 2024, 16:22:43"',
    'ETH,Mise en staking,"3,000,000","3 000,00 CHF","90,00 CHF","0,00 CHF","3 avr. 2024, 16:23:17"',
    # Bought in euros; the staking move a minute later prices it in francs.
    'SOL,Achat,"1","100,00€","100,00€","2,00€","12 mai 2024, 11:35:30"',
    'SOL,Mise en staking,"1","95,00 CHF","95,00 CHF","0,00 CHF","12 mai 2024, 11:35:39"',
    # 104 USDC bought, 95 sent away, the fee taken in USDC.
    'USDC,Achat,"104","0,95€","98,80€","0,00€","5 déc. 2024, 13:54:09"',
    'USDC,Envoi,"95","0,90 CHF","85,50 CHF","8,10 CHF","5 déc. 2024, 14:08:50"',
    'BONK,Récompense Apprendre,"24 308,2596",,,,"12 mai 2025, 09:16:53"',
]


def _rewards():
    """Daily ETH rewards of ~4.1e-6 (5 % a year on 0.03), printed as bare
    digits -- and a few small ones whose scale only the yield can tell."""
    out, day = [], D(2024, 4, 4)
    digits = ["41", "411", "4", "412", "409", "41", "410", "408", "413", "41"]
    for i in range(60):
        out.append(f'ETH,Récompense de staking,{digits[i % len(digits)]},,,,'
                   f'"{day.day} {["", "janv.", "févr.", "mars", "avr.", "mai", "juin"][day.month]} {day.year}, 01:00:00"')
        day += dt.timedelta(days=1)
    return out


@pytest.fixture
def export(tmp_path):
    text = "\r\n".join([HEADER, *ROWS, *_rewards()]) + "\r\n"
    path = tmp_path / "crypto.csv"
    path.write_bytes(text.encode("utf-8").decode("latin-1").encode("utf-8"))
    return path


def _market(days=900):
    """Flat prices, so any change in value is a quantity."""
    start = D(2024, 4, 1)
    series = [start + dt.timedelta(days=i) for i in range(days)]
    return {"ETH": [(d, 2000.0) for d in series], "SOL": [(d, 95.0) for d in series],
            "USDC": [(d, 0.9) for d in series]}


def test_the_decimal_point_comes_back_from_value_over_price(export):
    rows = crypto.parse(export)
    assert rows[0]["quantity"] == pytest.approx(0.03) and rows[0]["currency"] == "CHF"
    reward = next(r for r in rows if "staking" in r["kind"] and "Récompense" in r["kind"])
    assert reward["quantity"] is None and reward["digits"] == 41
    # Formatted properly for once: read as written.
    assert next(r for r in rows if r["symbol"] == "BONK")["quantity"] == pytest.approx(24308.2596)


def test_staking_rewards_take_the_scale_of_the_yield(export):
    fit = crypto._rewards(crypto.parse(export), "ETH")
    # "41", "411" and "4" are all ~4.1e-6: a tenfold misreading would show.
    assert all(3e-6 < q < 5e-6 for q in fit["quantities"])
    assert fit["yield"] == pytest.approx(0.05, rel=0.05)
    # A quantity read in the app calibrates the total exactly.
    exact = crypto._rewards(crypto.parse(export), "ETH", target=0.0003)
    assert sum(exact["quantities"]) == pytest.approx(0.0003)


def test_flows_are_money_in_and_out_never_rewards(export):
    book = crypto.ledger(crypto.parse(export))
    flows = dict(book["flows"])
    assert flows[D(2024, 4, 3)] == pytest.approx(90.0)
    # The euro purchase is costed at the day's rate Revolut itself printed.
    assert flows[D(2024, 5, 12)] == pytest.approx(95.0)
    # Bought then sent the same day: in, then out.
    assert flows[D(2024, 12, 5)] == pytest.approx(98.8 * 0.9 / 0.95 - 85.5)
    assert book["held"].get("USDC", 0.0) == pytest.approx(0.0, abs=0.01)
    assert book["sent"][0]["value_chf"] == 85.5
    assert book["rewards"]["ETH"]["count"] == 60


def test_capture_values_the_pocket_day_by_day(export, tmp_path):
    out = tmp_path / "data" / "crypto.json"
    snap = crypto.capture(export, out, market=_market(), until=D(2024, 7, 1))
    assert json.loads(out.read_text(encoding="utf-8")) == snap
    daily = dict(snap["daily"])
    assert daily["2024-04-03"] == pytest.approx(60.0)          # 0.03 ETH x 2000
    assert daily["2024-05-12"] == pytest.approx(60.0 + 95.0 + 39 * 4.1e-6 * 2000, rel=0.01)
    loaded = crypto.load(out)
    assert crypto.value_at(loaded, D(2024, 4, 2)) == 0.0         # before it existed
    assert crypto.value_at(loaded, D(2030, 1, 1)) == loaded["daily_series"][-1][1]
    # A coin with no public price is shown without a value, not at zero.
    assert next(p for p in snap["positions"] if p["symbol"] == "BONK")["value_chf"] is None
    # The calibration is kept for the next capture.
    snap = crypto.capture(export, out, market=_market(), until=D(2024, 7, 1),
                          actual={"ETH": (D(2024, 7, 1), 0.0303)})
    again = crypto.capture(export, out, market=_market(), until=D(2024, 7, 1))
    eth = next(p for p in again["positions"] if p["symbol"] == "ETH")
    assert eth["quantity"] == pytest.approx(0.0303) and eth["rewards"]["calibrated"]


def test_the_pocket_joins_the_savings_book(export, tmp_path):
    """A purchase is a flow, so a flat price reads as no return at all."""
    from types import SimpleNamespace

    from pms.web.views.savings import SavingsBook
    out = tmp_path / "crypto.json"
    crypto.capture(export, out, market=_market(), until=D(2024, 7, 1))
    snap = crypto.load(out)
    statement = SimpleNamespace(transactions=[])
    book = SavingsBook(statement, {"nav": [], "nav_daily": [], "positions": []}, None, snap)
    assert book.value("crypto", D(2024, 6, 1)) > 150
    # Over the purchases only (before the rewards' value adds up), flat
    # prices: the TWR is the rewards alone, a few hundredths of a percent.
    twr = book.twr("crypto", D(2024, 4, 3), D(2024, 5, 31))
    assert 0 < twr < 0.01
    assert book.start_of("crypto", D(2024, 1, 1)) == D(2024, 4, 3)


def test_the_savings_panel_shows_the_pocket(client, export):
    from webhelpers import api, savings_snapshots
    store_ = client.application.extensions["pms_store"]
    out = store_.path.with_name("crypto.json")
    paths = savings_snapshots(client)
    try:
        crypto.capture(export, out, market=_market(1200), until=D(2026, 7, 1))
        data = api(client, "/api/savings?preset=all")
        assert "Crypto (Revolut)" in [p["name"] for p in data["pockets"]]
        assert data["crypto"]["positions"]                 # coin by coin
        assert "crypto" in [f["id"] for f in data["options"]["focuses"]]
        focused = api(client, "/api/savings?preset=all&focus=crypto")
        assert focused["focus"] == "crypto" and focused["hero"]["pocket"] == "crypto"
    finally:
        for p in (out, *paths):
            p.unlink(missing_ok=True)
