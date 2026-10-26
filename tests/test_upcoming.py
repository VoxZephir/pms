"""What comes next: commitments read off the payments, their due dates and
price moves, the deadlines to change them, the health franchise replayed."""

from __future__ import annotations

import datetime as dt

import pytest

from pms import health, upcoming
from webhelpers import api

END = dt.date(2026, 7, 30)


@pytest.fixture
def held(client):
    return client.application.extensions["pms_store"].statement


@pytest.fixture
def bills(held):
    return {c["label"]: c for c in upcoming.commitments(held, END)}


def test_commitments_are_the_bills_not_the_habits(bills):
    # Rent, premium, phone, energy, TV fee, streaming, the yearly insurance
    # and the tax: all there, with their rhythm.
    assert bills["Assura-Basis SA"]["cadence"] == "chaque mois"
    assert bills["SERAFE AG"]["cadence"] == "chaque trimestre"
    assert bills["La Mobilière Assurances"]["cadence"] == "chaque année"
    assert bills["Administration fiscale cantonale"]["cadence"] == "chaque année"
    assert bills["NETFLIX.COM"]["yearly"] == pytest.approx(20.90 * 12)
    # The pharmacy twice a year and the petrol station each August are card
    # payments at a till, not contracts.
    assert not any("Pharmacie" in label or "Tankstelle" in label for label in bills)
    # The fitness club stopped in May: over, not coming.
    assert "Fitness Club Exemple" not in bills
    # Nothing chosen at the till is a commitment, however regular.
    assert not any(c["category"] in upcoming.CHOSEN for c in bills.values())


def test_due_dates_keep_the_day_of_the_month(bills):
    rent = next(c for label, c in bills.items() if label.startswith("Régie"))
    assert rent["next"] == dt.date(2026, 8, 1)
    assert [d.day for d in rent["dues"]] == [1, 1, 1]
    assert bills["SERAFE AG"]["next"] == dt.date(2026, 10, 15)
    assert bills["La Mobilière Assurances"]["next"] == dt.date(2026, 12, 10)


def test_a_price_rise_is_measured_against_a_year_before(bills):
    price = bills["Assura-Basis SA"]["price"]
    assert (price["before"], price["now"]) == (412.30, 431.00)
    assert price["since"] == dt.date(2026, 1, 5)
    assert price["yearly_delta"] == pytest.approx(18.70 * 12, abs=0.5)
    assert bills["Swisscom (Schweiz) AG"]["price"] is None


def test_deadlines_name_the_lamal_date_and_check_the_contract(bills):
    rows = upcoming.deadlines(list(bills.values()), dt.date(2026, 8, 10))
    kinds = {r["kind"]: r for r in rows}
    assert kinds["lamal"]["by"] == dt.date(2026, 11, 30) and kinds["lamal"]["certain"]
    assert kinds["insurance"]["by"] == dt.date(2026, 9, 10) and not kinds["insurance"]["certain"]
    # Past the date, nothing to say until next year.
    assert not any(r["kind"] == "lamal" for r in upcoming.deadlines(list(bills.values()), dt.date(2026, 12, 2)))


def test_calendar_totals_leave_out_what_probably_went_already(bills, held):
    pay = upcoming.income(held, END)
    ahead = upcoming.calendar_ahead(list(bills.values()), pay, dt.date(2026, 8, 6), {},
                                    shown_from=dt.date(2026, 7, 31))
    pending = [r for r in ahead["rows"] if r["pending"]]
    assert {r["label"] for r in pending} >= {"Assura-Basis SA"}
    thirty = ahead["totals"][0]
    assert thirty["out"] == pytest.approx(sum(r["amount"] for r in ahead["rows"]
                                              if r["out"] and not r["pending"] and r["day"] <= dt.date(2026, 9, 5)))
    assert thirty["in"] > 0  # the salary on the 25th


def test_left_to_pay_follows_the_law():
    assert health.left_to_pay(200, 300) == 200
    assert health.left_to_pay(1300, 300) == pytest.approx(300 + 100)
    assert health.left_to_pay(50_000, 2500) == 2500 + 700
    # Read backwards: exact under the cap, a floor past it.
    assert health.gross_from_paid(400, 300) == (1300, True)
    assert health.gross_from_paid(1000, 300) == (7300, False)


def test_premiums_take_the_largest_discount_the_law_allows():
    month = health.premiums(400, 300)
    assert month[2500] == pytest.approx(400 - 0.7 * 2200 / 12, abs=0.01)
    # From any declared franchise, back to the same ladder.
    assert health.premiums(month[1500], 1500)[300] == pytest.approx(400, abs=0.02)


def test_replay_picks_the_cheapest_and_finds_the_crossing():
    r = health.replay(300, 400, 0, [])
    assert r["best"] == 2500 and r["saving"] > 1000
    r = health.replay(300, 400, 6000, [])
    assert r["best"] == 300
    assert 1000 < r["crossing"] < 3000


def test_the_page_answers(client):
    a = api(client, "/api/a-venir")
    assert a["commitments"] and a["summary"]["yearly"] > 0
    assert a["health"]["premium"]["label"] == "Assura-Basis SA"
    assert {r["franchise"] for r in a["health"]["replay"]["rows"]} == set(health.FRANCHISES)
    b = api(client, "/api/a-venir?costs=5000")
    assert b["health"]["replay"]["costs"] == 5000


def test_the_franchise_is_declared_and_remembered(client):
    path = client.application.extensions["pms_store"].path.with_name("health.json")
    try:
        assert client.post("/api/health", json={"franchise": 1234},
                           headers={"Origin": "http://localhost"}).status_code == 400
        assert client.post("/api/health", json={"franchise": 2500},
                           headers={"Origin": "http://localhost"}).status_code == 200
        a = api(client, "/api/a-venir")
        assert a["health"]["settings"] == {"franchise": 2500, "declared": True}
    finally:
        path.unlink(missing_ok=True)
