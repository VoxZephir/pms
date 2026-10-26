"""Securities outside the statement: their declared value in the wealth,
their dividends grossed up for the Swiss withholding tax."""

from __future__ import annotations

import pytest

from pms import categories, holdings
from webhelpers import api

ORIGIN = {"Origin": "http://localhost"}
SHARE = {"name": "Port Exemple SA, 1 action", "quantity": 1, "payer": "Club Nautique Exemple",
         "withholding": True, "since": 2024, "values": {"2024": "1000", "2026": "1'250"}}


def test_the_value_holds_until_a_new_one_is_declared():
    h = holdings.clean(SHARE)
    assert holdings.value_at(h, 2023) is None
    assert holdings.value_at(h, 2025) == 1000 and holdings.value_at(h, 2026) == 1250
    with pytest.raises(ValueError):
        holdings.clean({**SHARE, "values": {}})


def test_a_net_dividend_is_grossed_up_for_the_withholding(client):
    held = client.application.extensions["pms_store"].statement
    paid = holdings.dividends(held, holdings.clean(SHARE), 2026)
    assert paid["net"] == 40.0
    assert paid["gross"] == pytest.approx(40 / 0.65, abs=0.01)
    assert paid["withheld"] == pytest.approx(paid["gross"] - 40, abs=0.01)


def test_the_tax_page_counts_the_share_and_its_dividend(client):
    path = client.application.extensions["pms_store"].path.with_name("holdings.json")
    try:
        r = client.post("/api/impots/titres", json={"holding": SHARE}, headers=ORIGIN).get_json()
        before = api(client, "/api/impots?year=2025")
        assert [s["value"] for s in before["securities"]] == [1000]
        assert any(row["name"] == SHARE["name"] for row in before["wealth"]["rows"])
        now = api(client, "/api/impots?year=2026")
        assert now["securities"][0]["dividends"]["net"] == 40.0
        assert client.get("/impots/2026.xlsx").status_code == 200
        client.post("/api/impots/titres", json=r["undo"], headers=ORIGIN)
        assert api(client, "/api/impots?year=2025")["securities"] == []
        assert client.post("/api/impots/titres", json={"holding": {"name": ""}},
                           headers=ORIGIN).status_code == 400
    finally:
        path.unlink(missing_ok=True)


def test_a_line_that_says_dividend_is_one():
    from test_categories import PUBLIC, _payment
    line = _payment("Paiement entrant", "Dividende Exemple SA", amount=71.5)
    assert categories.classify(line, PUBLIC) == ("Revenus", "Dividendes")
