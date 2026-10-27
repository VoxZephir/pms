"""The tax return, rubric by rubric: what the statement brings, the federal
rule that turns it into a deduction, the lines behind it."""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path

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


# --- the provision -----------------------------------------------------------------------------

def test_the_tax_still_owed_is_the_rate_paid_on_a_past_year_applied_to_the_open_one(statement):
    from pms import hindsight, plans
    # Before the year's bill: the whole of it is still owed.
    before = hindsight.truncate(statement, dt.date(2026, 4, 30))
    p = taxes.provision(before)
    basis = p["basis"]
    assert basis["year"] == 2025 and basis["rate"] == round(basis["tax"] / basis["pay"], 4)
    (open_year,) = p["years"]
    assert open_year["year"] == 2026 and open_year["pay_estimated"] and open_year["paid"] == 0
    assert open_year["pay"] > open_year["pay_so_far"]
    assert open_year["outstanding"] == p["outstanding"] == round(basis["rate"] * open_year["pay"], 2)
    # One year of history suggests no seasonal bill yet: the forecast pays
    # none of it, all of it is cash that is not free.
    cover = plans.tax_cover(plans.project(before, None, months_ahead=12), p)
    assert (cover["until"], cover["planned"], cover["uncovered"]) == ("2026-12", 0, p["outstanding"])
    # A bill declared in the plan, named after the tax, covers its amount.
    plan = plans.Plan(Path("unused"))
    plan.add_one_off("2026-06", "Impôts 2026", 2000.0)
    cover = plans.tax_cover(plans.project(before, plan, months_ahead=12), p)
    assert cover["planned"] == 2000 and cover["uncovered"] == round(max(p["outstanding"] - 2000, 0), 2)
    # After it: paid, nothing owed.
    after = taxes.provision(statement)
    assert after["years"][0]["paid"] > 0 and after["outstanding"] == 0
    # Paid the year after (Geneva) with no whole year settled: no basis, no guess.
    assert taxes.provision(statement, {"canton": "GE", "since": 2024, "paid_next_year": True}) is None


def test_the_provision_reaches_both_pages(client):
    assert api(client, "/api/impots")["provision"]["basis"]["year"] == 2025
    tax = api(client, "/api/previsions")["tax"]
    assert tax["outstanding"] == 0 and tax["uncovered"] == 0


# --- monthly installments ----------------------------------------------------------------------

INSTALLMENTS = {"canton": "", "since": None, "paid_next_year": False,
                "installments": {"since": "2026-02", "amount": 600.0, "months": []}}


def _tax_line(day, amount, kind="Ordre permanent", detail=()):
    t = Transaction(date=day, reference="x", currency="CHF", amount=amount, value_date=day,
                    balance=None, kind=kind, merchant="Administration fiscale", detail=list(detail))
    t.category, t.amount_chf = taxes.TAXES, amount
    return t


def test_each_tax_payment_settles_the_year_it_belongs_to():
    s = INSTALLMENTS
    assert taxes.tax_year(_tax_line(dt.date(2026, 3, 10), -600), s) == 2026      # an installment
    assert taxes.tax_year(_tax_line(dt.date(2026, 3, 10), -640), s) == 2026      # near enough
    assert taxes.tax_year(_tax_line(dt.date(2026, 5, 20), -6810), s) == 2025     # the last yearly bill
    assert taxes.tax_year(_tax_line(dt.date(2027, 4, 2), 380), s) == 2026        # a refund: the year before
    assert taxes.tax_year(_tax_line(dt.date(2026, 1, 20), -6000), s) == 2026     # before installments
    # A line that names its year says it, whatever the amount.
    assert taxes.tax_year(_tax_line(dt.date(2026, 3, 10), -600, detail=["ICC 2025 solde"]), s) == 2025
    # A year in a line that does not speak of tax (an IBAN group) is not one.
    assert taxes.tax_year(_tax_line(dt.date(2026, 3, 10), -600, detail=["CH12 2025 0000"]), s) == 2026
    # Without installments, the year after where it is paid the year after.
    ge = {**taxes.SETTINGS, "canton": "GE", "since": 2024, "paid_next_year": True}
    assert taxes.tax_year(_tax_line(dt.date(2026, 5, 20), -6810), ge) == 2025


def test_settings_keep_installments_and_refuse_a_malformed_one(tmp_path):
    path = tmp_path / "tax.json"
    saved = taxes.save_settings(path, "GE", 2024, True, {"since": "2027-01", "amount": "850", "months": [2, 3, 4]})
    assert saved["installments"] == {"since": "2027-01", "amount": 850.0, "months": [2, 3, 4]}
    assert taxes.load_settings(path)["installments"] == saved["installments"]
    # All twelve months is the whole year, written as none.
    assert taxes.save_settings(path, "", None, False, {"since": "2027-01", "amount": 1,
                                                       "months": list(range(1, 13))})["installments"]["months"] == []
    with pytest.raises(ValueError):
        taxes.save_settings(path, "", None, False, {"since": "2027-13", "amount": 10})
    assert taxes.save_settings(path, "", None, False, None)["installments"] is None


def test_the_projection_pays_installments_instead_of_the_yearly_bill(statement, tmp_path):
    from pms import hindsight, plans
    before = hindsight.truncate(statement, dt.date(2026, 4, 30))
    path = tmp_path / "plans.json"
    plain = plans.project(before, plans.Plan.load(path), months_ahead=12)
    assert [o["label"] for r in plain["rows"] for o in r["one_offs"] if o["label"] == "Impôts"] == []
    taxes.save_settings(tmp_path / "tax.json", "", None, False, {"since": "2026-06", "amount": 500})
    plan = plans.Plan.load(path)
    assert plan.installments["since"] == "2026-06" and plan.installments["lump_until"] is None
    shifted = plans.project(before, plan, months_ahead=12)
    paid = {r["key"]: [o for o in r["one_offs"] if o["label"] == plans.INSTALLMENT_LABEL] for r in shifted["rows"]}
    assert paid["2026-05"] == [] and len(paid["2026-06"]) == 1 and paid["2026-06"][0]["amount"] == 500
    assert all(len(v) == 1 for k, v in paid.items() if k >= "2026-06")
    # The tax leaves the ordinary month: it is on its own line now.
    assert shifted["baseline_history"] <= plain["baseline_history"]
    # Scenarios pay them too.
    plan.save_scenario_as("Autre")
    plan.save_scenario_as("Affiché")
    plan.save()
    assert plans.Plan.load(path).scenario_plan("Autre").installments == plan.installments


def test_the_provision_counts_the_installments_still_due_and_the_final_bill(statement):
    from pms import hindsight
    before = hindsight.truncate(statement, dt.date(2026, 4, 30))
    settings = {**taxes.SETTINGS, "installments": {"since": "2026-01", "amount": 300.0, "months": []}}
    p = taxes.provision(before, settings)
    (y,) = [y for y in p["years"] if y["year"] == 2026]
    inst = y["installments"]
    assert inst["months_to_come"] == 8 and inst["to_come"] == 2400 and inst["count"] == 12
    assert inst["balance"] == round(y["estimated"] - y["paid"] - inst["to_come"], 2)
    # The year's tax is settled the year after, with what the installments leave.
    assert y["later"] and y["paid_in"] == 2027
