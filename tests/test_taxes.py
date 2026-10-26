"""The tax return, rubric by rubric: what the statement brings, the federal
rule that turns it into a deduction, the lines behind it."""

from __future__ import annotations

import copy
import datetime as dt

import pytest

from pms import taxes
from pms.models import Transaction
from webhelpers import api

TODAY = dt.date(2026, 8, 10)


@pytest.fixture
def held(client):
    return client.application.extensions["pms_store"].statement


def _items(held, year=2025, **kw):
    out = taxes.return_items(held, year, net_income=kw.get("net"), finpension=None, ibkr=None,
                             crypto=None, franchise=300, insurer="Assura-Basis SA", today=TODAY)
    return out, {i["key"]: i for i in out["items"]}


def test_pay_is_the_employer_not_a_friend_paying_back(held):
    out, _ = _items(held)
    assert [p["label"] for p in out["salaries"]] == ["Alpha Conseil SA"]
    assert out["salaries"][0]["count"] == 13  # the thirteenth in November
    assert out["net"]["estimated"] and out["net"]["value"] == out["salaries"][0]["amount"]


def test_premiums_deduct_the_flat_amount_not_what_was_paid(held):
    _, items = _items(held)
    assert items["premiums"]["amount"] > 5000
    assert items["premiums"]["deductible"] == 1800


def test_care_counts_only_above_five_percent_of_net_income(held):
    _, items = _items(held, 2026)
    share = items["medical"]["amount"]
    assert share > 0 and items["medical"]["deductible"] == 0  # under 5 % of a salary
    _, low = _items(held, 2026, net=1000)
    assert low["medical"]["deductible"] == pytest.approx(max(share - 50, 0))
    # The refund from the insurer comes off the share.
    _, y2025 = _items(held)
    assert any(r["amount"] < 0 for r in y2025["medical"]["rows"])


def test_donations_and_training_are_found_by_name(held):
    _, items = _items(held)
    assert [r["label"] for r in items["donations"]["rows"]] == ["Croix-Rouge suisse"]
    assert items["donations"]["deductible"] == 150
    assert items["training"]["amount"] == 340
    # Under 100 CHF in the year a gift deducts nothing.
    _, y2024 = _items(held, 2024)
    assert y2024["donations"]["deductible"] == 0


def test_the_3a_deducts_up_to_the_ceiling(held):
    statement = copy.copy(held)
    deposit = Transaction(date=dt.date(2025, 12, 15), reference="9990001", currency="CHF", amount=-8000.0,
                          value_date=None, balance=None, kind="Versement pour finpension")
    deposit.amount_chf = -8000.0
    deposit.category, deposit.subcategory = "Épargne & investissement", "Prévoyance 3a"
    statement.transactions = [*held.transactions, deposit]
    _, items = _items(statement)
    assert items["3a"]["amount"] == 8000
    assert items["3a"]["deductible"] == 7258


def test_rules_carry_the_last_known_year():
    assert taxes.rules(2025) == (taxes.RULES[2025], True)
    assert taxes.rules(2031)[1] is False


def test_the_page_and_its_workbook(client):
    a = api(client, "/api/impots?year=2025")
    assert a["year"] == 2025 and 2025 in a["years"]
    assert a["deducted"] == pytest.approx(sum(i["deductible"] or 0 for i in a["items"]))
    assert a["wealth"]["taxable"] > 0
    b = api(client, "/api/impots?year=2025&net=1000")
    assert b["net"] == {"value": 1000, "estimated": False, "pay": a["net"]["pay"]}
    r = client.get("/impots/2025.xlsx")
    assert r.status_code == 200 and r.data[:2] == b"PK"
    assert client.get("/impots/1999.xlsx").status_code == 404


def test_geneva_from_2026_has_its_own_rules_and_pays_a_year_later(held):
    settings = {"canton": "GE", "since": 2026, "paid_next_year": True}
    before = taxes.return_items(held, 2025, net_income=None, finpension=None, ibkr=None, crypto=None,
                                franchise=300, insurer="Assura-Basis SA", today=TODAY, settings=settings)
    assert before["canton"] is None and "canton" not in before["items"][0]
    out = taxes.return_items(held, 2026, net_income=10_000, finpension=None, ibkr=None, crypto=None,
                             franchise=300, insurer="Assura-Basis SA", today=TODAY, settings=settings)
    items = {i["key"]: i for i in out["items"]}
    assert out["canton"]["code"] == "GE"
    # Care above 0.5 % of net income instead of 5 %; commuting capped at 529.
    share = items["medical"]["amount"]
    assert items["medical"]["canton"]["deductible"] == pytest.approx(max(share - 50, 0))
    assert items["medical"]["canton"]["deductible"] >= items["medical"]["deductible"]
    assert items["commute"]["canton"]["deductible"] <= 529
    assert out["deducted_canton"] == pytest.approx(sum(i["canton"]["deductible"] for i in out["items"]))
    # The 2026 tax is paid in 2027, which the statement has not reached.
    assert out["paid"]["year"] == 2027 and out["paid"]["later"] and not out["paid"]["seen"]


def test_the_canton_is_set_from_the_page(client):
    path = client.application.extensions["pms_store"].path.with_name("tax.json")
    try:
        r = client.post("/api/impots/reglages", json={"canton": "GE", "since": 2026, "paid_next_year": True},
                        headers={"Origin": "http://localhost"})
        assert r.status_code == 200
        a = api(client, "/api/impots?year=2026")
        assert a["canton"]["name"] == "Genève" and a["paid"]["year"] == 2027
        assert client.get("/impots/2026.xlsx").status_code == 200
        assert client.post("/api/impots/reglages", json={"canton": "ZZ"},
                           headers={"Origin": "http://localhost"}).status_code == 400
    finally:
        path.unlink(missing_ok=True)
