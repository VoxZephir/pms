"""Cash-flow planning: seasonal detection, the plan file and the projection.

The fixture builds two synthetic years: rent and groceries every month, a
December health-insurance bill and May taxes -- the exact pattern the
feature exists for. Amounts are made up; no identifying value lives here.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from pms import analysis, plans
from pms.models import AccountSummary, Statement, Transaction


def _txn(date: dt.date, amount: float, category: str) -> Transaction:
    return Transaction(
        date=date,
        reference=f"R{date:%Y%m%d}-{abs(amount):.0f}",
        currency="CHF", amount=amount, value_date=date, balance=None,
        kind="Paiement", merchant="", category=category)


def _two_years(closing: float = 15000.0) -> Statement:
    rows = []
    for year in (2024, 2025):
        for month in range(1, 13):
            rows.append(_txn(dt.date(year, month, 15), -400.0, "Alimentation"))
            rows.append(_txn(dt.date(year, month, 15), -2500.0, "Logement"))
            rows.append(_txn(dt.date(year, month, 16), 7000.0, "Revenus"))
    rows.append(_txn(dt.date(2024, 12, 10), -3400.0, "Santé"))
    rows.append(_txn(dt.date(2025, 12, 10), -3400.0, "Santé"))
    rows.append(_txn(dt.date(2025, 5, 12), -9000.0, "Impôts"))
    rows.append(_txn(dt.date(2026, 5, 12), -9200.0, "Impôts"))

    statement = Statement(
        holder="Test", iban="CH00 0000 0000 0000 0000 0",
        period_start=dt.date(2024, 7, 1), period_end=dt.date(2026, 5, 12),
        generated_on=dt.date(2026, 5, 12), reference_currency="CHF",
        accounts=[AccountSummary("CHF", 1000.0, closing, 0.0, 0.0)],
        transactions=rows)
    analysis.annotate_chf(statement)
    return statement


# --- seasonal detection ------------------------------------------------------

def test_seasonal_one_offs_finds_annual_bills():
    found = {s["category"]: s for s in plans.seasonal_one_offs(_two_years())}
    assert found["Santé"]["month"] == 12
    assert found["Santé"]["amount"] == 3400.0
    assert found["Santé"]["years"] == [2024, 2025]
    assert found["Impôts"]["month"] == 5
    assert found["Impôts"]["amount"] == 9100.0  # median of 9000 and 9200
    assert len(found) == 2


def test_rent_is_not_seasonal():
    """Paid every month, so December is not a December thing."""
    found = {s["category"] for s in plans.seasonal_one_offs(_two_years())}
    assert "Logement" not in found


def test_small_bills_are_not_seasonal():
    """A 400 CHF grocery month is a shop bill, not a one-off."""
    found = {s["category"] for s in plans.seasonal_one_offs(_two_years())}
    assert "Alimentation" not in found


def test_one_year_is_not_enough():
    """A single December tells nothing about a pattern."""
    statement = _two_years()
    statement.transactions = [
        t for t in statement.transactions
        if not (t.category == "Santé" and t.date.year == 2024)]
    found = {s["category"] for s in plans.seasonal_one_offs(statement)}
    assert "Santé" not in found


# --- baseline ----------------------------------------------------------------

def test_baseline_excludes_the_seasonal_bills():
    """December must keep its groceries and lose only the insurance, or the
    one-off would be counted twice in the projection."""
    assert plans.baseline(_two_years()) == 2900.0  # 400 groceries + 2500 rent


def test_monthly_profile_strips_each_month_like_the_baseline():
    """The same subtraction as `baseline()`, spread over the calendar: the
    ordinary months keep their groceries and rent, May and December lose
    their annual bill and nothing else."""
    profile = {p["month"]: p for p in plans.monthly_profile(_two_years())}
    assert profile[1]["raw_median"] == 2900.0
    assert profile[1]["stripped_median"] == 2900.0
    assert profile[1]["seasonal_median"] == 0.0
    assert profile[12]["raw_median"] == 6300.0
    assert profile[12]["stripped_median"] == 2900.0
    assert profile[12]["seasonal_median"] == 3400.0
    # May 2024 predates the tax rows and May 2026 carries only the tax
    # (the generator fills 2024-2025 whole, 2026 only with the bills), so
    # the raw median lands between the two billed years -- the median
    # strip still removes what the annual bill leaves over.
    assert profile[5]["raw_median"] == 9200.0  # median of 2'900, 9'200, 11'900
    assert profile[5]["stripped_median"] == 2900.0  # median of 2'900, 2'900, 100
    assert profile[5]["seasonal_median"] == 9000.0  # median of 0, 9'000, 9'100
    assert profile[5]["years"] == [2024, 2025, 2026]


def test_category_profile_names_the_regular_and_the_seasonal():
    profile = {c["category"]: c
               for c in plans.category_profile(_two_years())}
    # Une ligne plate : médiane partout, aucun saisonnier.
    assert profile["Logement"]["median"] == 2500.0
    assert profile["Logement"]["peak"] == 2500.0
    assert profile["Logement"]["seasonal"] is None
    # Les deux factures annuelles sont flaggées, avec leur mois et montant.
    assert profile["Santé"]["peak_month"] == 12
    assert profile["Santé"]["seasonal"]["month"] == 12
    assert profile["Santé"]["seasonal"]["amount"] == 3400.0
    assert profile["Santé"]["seasonal"]["years"] == [2024, 2025]
    assert profile["Impôts"]["peak_month"] == 5
    assert profile["Impôts"]["seasonal"]["amount"] == 9100.0
    # La catégorie la plus chère arrive en tête.
    assert plans.category_profile(_two_years())[0]["category"] == "Impôts"


def test_monthly_profile_omits_a_month_never_observed():
    """A calendar month no transaction falls in is absent -- an empty bar
    would read as a zero-spend month, which is a different claim."""
    statement = _two_years()
    statement.transactions = [t for t in statement.transactions
                              if t.date.month != 2]
    profile = {p["month"]: p for p in plans.monthly_profile(statement)}
    assert 2 not in profile
    assert profile[1]["years"] == [2024, 2025]


def test_monthly_profile_year_filter():
    """`year=` narrows the profile to that year: each month's median is
    that year's own value, and `years` carries the one year. May 2025
    has paid its taxes, May 2024 predates them."""
    year_2025 = {p["month"]: p
                 for p in plans.monthly_profile(_two_years(), year=2025)}
    assert len(year_2025) == 12
    assert all(p["years"] == [2025] for p in year_2025.values())
    assert year_2025[5]["raw_median"] == 11900.0  # 400 groceries + 2500 rent + 9000 taxes
    year_2024 = {p["month"]: p
                 for p in plans.monthly_profile(_two_years(), year=2024)}
    assert len(year_2024) == 12
    assert all(p["years"] == [2024] for p in year_2024.values())
    assert year_2024[5]["raw_median"] == 2900.0  # the taxes only start in 2025


def test_monthly_profile_reports_the_iqr():
    """The IQR is the spread of the month's raw values: May spans the
    ordinary month and both tax bills (11'900 - 2'900), while January's
    two identical months have no spread at all."""
    profile = {p["month"]: p for p in plans.monthly_profile(_two_years())}
    assert profile[5]["iqr"] == 9000.0
    assert profile[1]["iqr"] == 0.0


def test_category_profile_reports_the_trend():
    """The trend is the second half of the observed months against the
    first: flat lines stay flat, and a step that doubles the spend reads
    as a +100 % shift, not as an annualised slope that would go to +800."""
    profile = {c["category"]: c
               for c in plans.category_profile(_two_years())}
    assert profile["Alimentation"]["trend"] == 0.0
    assert profile["Logement"]["trend"] == 0.0
    # Une catégorie saisonnière n'a pas de tendance : sa médiane mensuelle
    # mélange la facture annuelle et les petits mois.
    assert profile["Impôts"]["trend"] is None
    assert profile["Santé"]["trend"] is None


def test_a_trend_compares_the_two_halves_of_the_history():
    """A level change is one visible shift: groceries going from 400 to
    600 a month halfway through the history read as +50 %, the actual
    change -- not an extrapolated yearly rate."""
    statement = _two_years()
    rows = []
    for t in statement.transactions:
        if t.category == "Alimentation" and t.date.year == 2025:
            rows.append(_txn(t.date, -600.0, "Alimentation"))
        else:
            rows.append(t)
    statement.transactions = rows
    analysis.annotate_chf(statement)
    profile = {c["category"]: c
               for c in plans.category_profile(statement)}
    assert profile["Alimentation"]["trend"] == 50.0
    assert profile["Logement"]["trend"] == 0.0


def test_a_trend_needs_six_observed_months():
    """Fewer than six observed months cannot split into two halves worth
    comparing -- the trend stays silent instead of guessing."""
    statement = _two_years()
    statement.transactions = [
        t for t in statement.transactions
        if t.category != "Alimentation"
        or t.date in (dt.date(2025, 1, 15), dt.date(2025, 2, 15))]
    profile = {c["category"]: c
               for c in plans.category_profile(statement)}
    assert profile["Alimentation"]["trend"] is None


# --- projection --------------------------------------------------------------

def test_projection_shape():
    """Twelve whole months ahead, plus the remainder of the month the
    statement stops inside -- the fixture ends on 12 May, so May is a
    partial row and June is the first full one."""
    result = plans.project(_two_years())
    assert result["cash"] == 15000.0
    assert result["income"] == 7000.0
    assert result["income_source"] == "history"
    assert result["baseline"] == 2900.0
    assert len(result["rows"]) == 13
    first, last = result["rows"][0], result["rows"][-1]
    assert first["key"] == "2026-05" and first["partial"] is True
    assert result["rows"][1]["key"] == "2026-06"
    assert result["rows"][1]["partial"] is False
    assert last["key"] == "2027-05"


def test_a_statement_ending_on_a_month_end_has_no_partial_row():
    """Nothing is left of a month that is over, so there is no remainder to
    show -- the projection starts on the next month, as it always did."""
    statement = _two_years()
    statement.period_end = dt.date(2026, 4, 30)
    result = plans.project(statement)
    assert len(result["rows"]) == 12
    assert result["rows"][0]["key"] == "2026-05"
    assert all(not r["partial"] for r in result["rows"])


def test_the_partial_month_keeps_what_it_has_not_spent_or_earned_yet():
    """The remainder counts what the month has left to deliver, measured
    against the ledger rather than prorated by days: the fixture's May has
    already paid its rent and groceries and received its salary by the 16th,
    but the statement stops on the 12th -- so the salary is still ahead."""
    result = plans.project(_two_years())
    partial = result["rows"][0]
    # 400 groceries + 2500 rent already recorded on the 15th? No: the ledger
    # stops on the 12th, so only the taxes of the 12th are in.
    assert partial["income"] == 7000.0        # the 16th has not happened
    assert partial["spend"] == pytest.approx(0.0)  # 9200 of taxes > 2900 base


def test_projection_arithmetic():
    result = plans.project(_two_years())
    for row in result["rows"]:
        expected = row["start"] + row["income"] - row["spend"]
        assert row["end"] == round(expected, 2)


def test_suggested_one_offs_land_in_their_months():
    rows = {r["key"]: r for r in plans.project(_two_years())["rows"]}
    december = rows["2026-12"]["one_offs"]
    assert december == [{"label": "Santé", "amount": 3400.0,
                         "source": "suggestion", "transfer": plans.SPENT,
                         "date": ""}]
    may = rows["2027-05"]["one_offs"]
    assert may == [{"label": "Impôts", "amount": 9100.0,
                    "source": "suggestion", "transfer": plans.SPENT,
                    "date": ""}]
    # An ordinary month carries no one-off.
    assert rows["2026-06"]["one_offs"] == []


def test_a_confirmed_current_month_suggestion_is_not_charged_twice(tmp_path):
    """The fixture's May taxes are in the ledger on the 12th. Confirming the
    undated "Impôts" suggestion for May must not re-add the full bill on the
    remainder row -- the ledger already carries it, and the declared path has
    the same guard as the unconfirmed suggestion path."""
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_one_off("2026-05", "Impôts", 9100.0, seasonal=("Impôts", 5))
    rows = {r["key"]: r for r in plans.project(statement, plan)["rows"]}
    assert rows["2026-05"]["one_offs"] == []
    assert rows["2026-05"]["spend"] == pytest.approx(0.0)


def test_a_seasonal_bill_already_paid_this_month_is_not_predicted_again():
    """The fixture's May taxes were paid on the 12th and the statement ends
    the same day. Predicting them again on the remainder row would charge the
    same bill twice -- the same rule the baseline follows."""
    rows = {r["key"]: r for r in plans.project(_two_years())["rows"]}
    assert rows["2026-05"]["one_offs"] == []


def test_ignored_suggestion_leaves_the_projection():
    plan = plans.Plan("unused")
    plan.ignore("Santé", 12)
    rows = {r["key"]: r for r in plans.project(_two_years(), plan)["rows"]}
    assert rows["2026-12"]["one_offs"] == []
    assert rows["2026-12"]["spend"] == 2900.0


def test_declared_one_off_shadows_its_suggestion():
    plan = plans.Plan("unused")
    plan.add_one_off("2026-12", "Santé", 3500.0)
    rows = {r["key"]: r for r in plans.project(_two_years(), plan)["rows"]}
    december = rows["2026-12"]
    assert december["one_offs"] == [
        {"label": "Santé", "amount": 3500.0, "source": "declared",
         "transfer": plans.SPENT, "date": ""}]
    assert december["spend"] == 2900.0 + 3500.0


def test_renamed_confirmation_still_shadows():
    """Confirming with a nicer label keeps the provenance, so the renamed
    entry and its suggestion are not counted twice."""
    plan = plans.Plan("unused")
    plan.add_one_off("2026-12", "Assurance maladie", 3500.0,
                     seasonal=("Santé", 12))
    rows = {r["key"]: r for r in plans.project(_two_years(), plan)["rows"]}
    december = rows["2026-12"]
    assert december["one_offs"] == [
        {"label": "Assurance maladie", "amount": 3500.0,
         "source": "declared", "transfer": plans.SPENT, "date": ""}]
    assert december["spend"] == 2900.0 + 3500.0


def test_low_point_is_today_when_cash_never_dips():
    low = plans.project(_two_years())["low"]
    assert low["key"] is None
    assert low["label"] == "aujourd'hui"
    assert low["amount"] == 15000.0


def test_low_point_is_the_dip_when_cash_does_dip():
    """With income matching the baseline, only the one-off months dip: the
    low point is then that month, not today."""
    statement = _two_years()
    for t in statement.transactions:
        if t.category == "Revenus":
            t.amount = 2900.0
            t.amount_chf = 2900.0
    low = plans.project(statement)["low"]
    assert low["key"] == "2027-05"   # the May taxes land on top of the
    assert low["label"] == "mai 2027"                  # December dip
    # The remainder of May adds the salary still to come (the 16th) without
    # re-charging the taxes the ledger already recorded on the 12th; every
    # ordinary month then nets to zero, and only the two bills dig.
    assert low["amount"] == 15000.0 + 2900.0 - 3400.0 - 9100.0


def test_declared_income_wins_over_history():
    plan = plans.Plan("unused")
    plan.income = 8000.0
    result = plans.project(_two_years(), plan)
    assert result["income"] == 8000.0
    assert result["income_source"] == "declared"


# --- the plan file -----------------------------------------------------------

def test_plan_roundtrip(tmp_path):
    path = tmp_path / "plans.json"
    plan = plans.Plan(path)
    plan.income = 8000.0
    plan.add_one_off("2026-12", "Assurance maladie", 3500.0,
                     seasonal=("Santé", 12))
    plan.ignore("Impôts", 5)
    plan.save()

    loaded = plans.Plan.load(path)
    assert loaded.income == 8000.0
    assert loaded.one_offs == [{
        "month": "2026-12", "label": "Assurance maladie", "amount": 3500.0,
        "date": "", "seasonal": {"category": "Santé", "month": 12},
        "transfer": plans.SPENT}]
    assert loaded.ignored == [("Impôts", 5)]
    assert not loaded.empty


def test_a_dated_one_off_survives_the_roundtrip(tmp_path):
    path = tmp_path / "plans.json"
    plan = plans.Plan(path)
    plan.add_one_off("2026-08", "Versement 3a", 3000.0,
                     transfer=plans.SHELTERED, date="2026-08-28")
    plan.save()

    entry = plans.Plan.load(path).one_offs[0]
    assert entry["date"] == "2026-08-28"
    assert entry["transfer"] == plans.SHELTERED


def test_a_date_alone_is_enough_to_place_an_entry(tmp_path):
    """The month is derivable from the day, so a file that carries only the
    date is still a valid declaration."""
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({
        "version": plans.VERSION,
        "one_offs": [{"date": "2026-08-28", "label": "Versement",
                      "amount": 3000.0}]}), encoding="utf-8")
    entry = plans.Plan.load(path).one_offs[0]
    assert entry["month"] == "2026-08"


def test_a_legacy_boolean_transfer_still_means_something(tmp_path):
    """The flag used to be a boolean. `true` has to keep meaning "moved to a
    pocket"; it is read as the taxable one, because calling an unspecified
    transfer sheltered would understate what the wealth tax reaches."""
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({
        "version": plans.VERSION,
        "one_offs": [{"month": "2026-08", "label": "Apport", "amount": 1000.0,
                      "transfer": True}]}), encoding="utf-8")
    assert plans.Plan.load(path).one_offs[0]["transfer"] == plans.TAXABLE


def test_plan_missing_file_is_empty():
    plan = plans.Plan("nope.json")
    assert plan.empty
    assert plan.income is None
    assert plan.one_offs == []


def test_plan_corrupt_file_is_empty(tmp_path):
    path = tmp_path / "plans.json"
    path.write_text("{not json", encoding="utf-8")
    assert plans.Plan.load(path).empty


def test_plan_save_is_clean_json(tmp_path):
    path = tmp_path / "plans.json"
    plans.Plan(path).save()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": plans.VERSION, "income": None, "rate": None,
        "rate_segments": [], "vol": None,
        "scenarios": {}, "contributions": [],
        "one_offs": [], "ignored_seasonal": []}


def test_plan_roundtrip_carries_the_rate_schedule_and_vol(tmp_path):
    path = tmp_path / "plans.json"
    plan = plans.Plan(path)
    plan.rate_segments = [(6, 0.05), (6, 0.02)]
    plan.vol = 0.12
    plan.save()

    loaded = plans.Plan.load(path)
    assert loaded.rate_segments == [(6, 0.05), (6, 0.02)]
    # The first segment is the closest single-number reading of the schedule,
    # and it is what an older checkout would compound at.
    assert loaded.rate == 0.05
    assert loaded.vol == 0.12


def test_a_legacy_rate_file_stays_a_single_unbounded_segment(tmp_path):
    """A file that only knows `rate` must keep meaning exactly what it meant:
    that rate for the whole horizon. The schedule stays empty -- it is a
    reading of the file, never a guess about its shape."""
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({
        "version": plans.VERSION, "rate": 0.04}), encoding="utf-8")
    plan = plans.Plan.load(path)
    assert plan.rate == 0.04
    assert plan.rate_segments == []
    assert plan.vol is None


def test_a_hand_edited_negative_vol_is_demoted_to_measured(tmp_path):
    """A negative volatility would silently invert the band; a file edit that
    wrote one is demoted to the measured fallback, never echoed."""
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({
        "version": plans.VERSION, "vol": -0.1}), encoding="utf-8")
    assert plans.Plan.load(path).vol is None
    path.write_text(json.dumps({
        "version": plans.VERSION, "vol": "abc"}), encoding="utf-8")
    assert plans.Plan.load(path).vol is None


def test_scenarios_roundtrip_and_upsert(tmp_path):
    path = tmp_path / "plans.json"
    plan = plans.Plan(path)
    plan.set_scenario("Croissance", [(12, 0.04)], None)
    plan.set_scenario("Croissance", [(24, 0.03)], 0.1, months=180)
    plan.set_scenario("", [(12, 0.04)], None)            # empty name: no-op
    plan.save()
    loaded = plans.Plan.load(path)
    assert set(loaded.scenarios) == {"Croissance"}
    assert loaded.scenarios["Croissance"] == {
        "rate_segments": [(24, 0.03)], "vol": 0.1, "months": 180}


def test_apply_scenario_sets_the_live_fields(tmp_path):
    plan = plans.Plan(tmp_path / "plans.json")
    plan.set_scenario("Décennie perdue", [(24, -0.02), (96, 0.03)], None,
                      months=180)
    assert plan.apply_scenario("Décennie perdue") == 180
    assert plan.rate_segments == [(24, -0.02), (96, 0.03)]
    assert plan.rate == -0.02
    assert plan.vol is None
    assert plan.apply_scenario("Inconnu") is None
    # A scenario without a horizon returns None -- the view keeps its own.
    plan.set_scenario("Sans horizon", [(12, 0.04)], None)
    assert plan.apply_scenario("Sans horizon") is None
    assert plan.rate_segments == [(12, 0.04)]
    # Removing a scenario never touches what it set.
    plan.remove_scenario("Décennie perdue")
    assert plan.rate_segments == [(12, 0.04)]


def test_a_saved_scenario_does_not_make_the_plan_non_empty(tmp_path):
    """A preset changes nothing until applied; a contribution is a live
    declaration and does count."""
    plan = plans.Plan(tmp_path / "plans.json")
    plan.set_scenario("Croissance", [(12, 0.04)], None)
    assert plan.empty
    plan.add_contribution("3a", 1000.0, "month", 24)
    assert not plan.empty


def test_scenario_summary_tells_two_scenarios_apart():
    assert plans.scenario_summary([], None) == "aucun rendement · vol mesuré"
    assert plans.scenario_summary([(12, 0.04)], 0.1) == \
        "4 % pendant 12 mois · vol 10 %"
    assert plans.scenario_summary([(24, -0.02), (96, 0.03)], None) == \
        "-2 % pendant 24 mois puis 3 % pendant 96 mois · vol mesuré"
    assert plans.scenario_summary([(102, -0.118), (69, 0.2027)], None,
                                  180) == \
        "-11.8 % pendant 102 mois puis 20.27 % pendant 69 mois · " \
        "vol mesuré · 15 ans d'horizon"


def test_builtin_scenarios_are_valid():
    for spec in plans.BUILTIN_SCENARIOS.values():
        assert spec["label"]
        assert spec["vol"] is None
        for months, rate in spec["rate_segments"]:
            assert months >= 1 and -100 <= rate <= 100
        # A scenario horizon is any length the projection accepts -- 180 for
        # the lost decade is a hand-picked value, and the select shows its
        # own option rather than lying about a preset.
        months = spec.get("months") or 0
        assert months == 0 or 1 <= months <= 480


def test_the_lost_decade_scenario_compounds_to_its_measured_depth():
    """The built-in must reproduce the real CHF episode: -65.6 % at the
    8.5-year bottom, back at the peak after the recovery leg -- and then
    settle at the long-run CHF average instead of compounding the recovery
    rate for ever."""
    spec = plans.BUILTIN_SCENARIOS["lost-decade"]
    down_months, down_rate = spec["rate_segments"][0]
    up_months, up_rate = spec["rate_segments"][1]
    tail_months, tail_rate = spec["rate_segments"][2]
    bottom = (1 + down_rate) ** (down_months / 12)
    assert bottom == pytest.approx(0.3441, abs=0.01)  # -65.6 %
    back = bottom * (1 + up_rate) ** (up_months / 12)
    assert back == pytest.approx(1.0, abs=0.02)
    # After the episode the declared rate is the historical CHF average, and
    # the carry-forward rule keeps it there -- never the recovery CAGR.
    assert tail_rate == pytest.approx(0.0389, abs=0.001)
    assert plans.rate_at(spec["rate_segments"], 171) == pytest.approx(0.2027)
    assert plans.rate_at(spec["rate_segments"], 172) == pytest.approx(0.0389)
    assert plans.rate_at(spec["rate_segments"], 600) == pytest.approx(0.0389)


def test_hand_edited_scenarios_are_sanitized(tmp_path):
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({
        "version": plans.VERSION,
        "scenarios": {
            "Mauvais vol": {"rate_segments": [[12, 0.04]], "vol": 1.5},
            "Mauvaises paires": {"rate_segments": [[0, 0.04], [12, 200]],
                                 "vol": None},
            "Pas un dict": "x",
            "": {"rate_segments": [[12, 0.04]], "vol": None},
        }}), encoding="utf-8")
    loaded = plans.Plan.load(path)
    assert loaded.scenarios["Mauvais vol"]["vol"] is None
    assert loaded.scenarios["Mauvaises paires"]["rate_segments"] == []
    assert "Pas un dict" not in loaded.scenarios
    assert "" not in loaded.scenarios


def test_set_rates_demotes_out_of_range_vol(tmp_path):
    plan = plans.Plan(tmp_path / "plans.json")
    plan.set_rates([(12, 0.04)], 1.5)
    assert plan.vol is None
    plan.set_rates([(12, 0.04)], 0.5)
    assert plan.vol == 0.5
    plan.set_rates([], 0.5)
    assert plan.rate is None and plan.rate_segments == []


def test_a_monthly_contribution_fires_on_every_full_row(tmp_path):
    """The fixture ends mid-May: twelve occurrences, none on the partial
    row -- that is the only row the ledger also covers."""
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("3a", 1000.0, "month", 24)
    rows = {r["key"]: r for r in plans.project(statement, plan)["rows"]}
    assert rows["2026-05"]["one_offs"] == []   # the partial row stays clean
    assert len(rows) == 13
    for key in ("2026-06", "2026-07", "2027-04", "2027-05"):
        assert any(o["transfer"] == "3a" and o["source"] == "contribution"
                   for o in rows[key]["one_offs"])


def test_semester_and_year_cadences_fire_phase_aligned(tmp_path):
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("3a", 1000.0, "semester", 24)
    rows = {r["key"]: r for r in plans.project(statement, plan)["rows"]}
    fired = [key for key, r in rows.items()
             if any(o["source"] == "contribution" for o in r["one_offs"])]
    # The fixture's horizon runs to May 2027, so the June 2027 occurrence
    # is beyond it -- the series simply stops at the horizon.
    assert fired == ["2026-06", "2026-12"]

    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("3a", 2000.0, "year", 24)
    rows = {r["key"]: r for r in plans.project(statement, plan)["rows"]}
    fired = [key for key, r in rows.items()
             if any(o["source"] == "contribution" for o in r["one_offs"])]
    assert fired == ["2026-06"]


def test_a_series_shorter_than_the_horizon_expires_on_time(tmp_path):
    """Six months of a monthly series inside a twelve-month projection fires
    on the first six full rows and never after -- the duration, not the
    horizon, is the stopping rule."""
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("3a", 1000.0, "month", 6)
    rows = {r["key"]: r for r in plans.project(statement, plan)["rows"]}
    fired = [key for key, r in rows.items()
             if any(o["source"] == "contribution" for o in r["one_offs"])]
    assert fired == ["2026-06", "2026-07", "2026-08",
                     "2026-09", "2026-10", "2026-11"]


def test_a_garbage_contribution_start_year_is_dropped_at_load(tmp_path):
    """A malformed year would crash the projection's month arithmetic; a
    non-sensical one would fire the series on every row. Both are rejected
    whole, like every bad entry."""
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({
        "version": plans.VERSION,
        "contributions": [
            {"pocket": "3a", "amount": 100.0, "every": "month", "months": 12,
             "start": "abc-05"},
            {"pocket": "3a", "amount": 100.0, "every": "month", "months": 12,
             "start": "00-01"},
        ]}), encoding="utf-8")
    assert plans.Plan.load(path).contributions == []


def test_a_quarterly_contribution_fires_phase_aligned(tmp_path):
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("taxable", 500.0, "quarter", 24)
    rows = {r["key"]: r for r in plans.project(statement, plan)["rows"]}
    # First full row is 2026-06; quarters land on 06, 09, 12, 03...
    fired = [key for key, r in rows.items()
             if any(o["source"] == "contribution" for o in r["one_offs"])]
    assert fired == ["2026-06", "2026-09", "2026-12", "2027-03"]


def test_a_series_longer_than_the_horizon_stops_at_it(tmp_path):
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("3a", 1000.0, "month", 24)
    rows = plans.project(statement, plan, months_ahead=12)["rows"]
    contributions = sum(1 for r in rows for o in r["one_offs"]
                        if o["source"] == "contribution")
    assert contributions == 12


def test_an_explicit_current_month_start_fires_on_the_partial_row(tmp_path):
    """Chosen deliberately, the current month is charged in full -- like any
    undated declaration. The app never prorates or guesses."""
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("3a", 1000.0, "month", 24, start="2026-05")
    rows = {r["key"]: r for r in plans.project(statement, plan)["rows"]}
    assert any(o["source"] == "contribution" for o in rows["2026-05"]["one_offs"])


def test_a_contribution_credits_the_pocket_and_dents_the_cash(tmp_path):
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("3a", 1000.0, "month", 24)
    projection = plans.project(statement, plan)
    plain = plans.project(statement)
    wealth = plans.project_wealth(projection, 10000.0, None)
    untouched = plans.project_wealth(plain, 10000.0, None)
    at = next(i for i, r in enumerate(projection["rows"])
              if r["key"] == "2026-06")
    # Cash really leaves, the pocket really receives it, net worth is
    # untouched by the move itself -- and moved counts each occurrence once.
    assert projection["rows"][at]["end"] == \
        pytest.approx(plain["rows"][at]["end"] - 1000.0)
    assert wealth["rows"][at]["invested"] == pytest.approx(11000.0)
    assert wealth["rows"][at]["total"] == \
        pytest.approx(untouched["rows"][at]["total"])
    assert wealth["moved"] == pytest.approx(12000.0)  # 12 occurrences


def test_the_sheltered_curve_ignores_a_taxable_contribution(tmp_path):
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_contribution("taxable", 500.0, "quarter", 24)
    projection = plans.project(statement, plan)
    sheltered = plans.project_wealth(projection, 4000.0, None,
                                     pocket=plans.SHELTERED, include_cash=False)
    assert sheltered["moved"] == 0.0
    assert all(r["invested"] == 4000.0 for r in sheltered["rows"])


def test_bad_hand_edited_contributions_are_skipped_whole(tmp_path):
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({
        "version": plans.VERSION,
        "contributions": [
            {"pocket": "", "amount": 100.0, "every": "month", "months": 12,
             "start": ""},
            {"pocket": "3a", "amount": 0.0, "every": "month", "months": 12,
             "start": ""},
            {"pocket": "3a", "amount": 100.0, "every": "weekly", "months": 12,
             "start": ""},
            {"pocket": "3a", "amount": 100.0, "every": "month", "months": 0,
             "start": ""},
            {"pocket": "3a", "amount": 100.0, "every": "month", "months": 12,
             "start": "2026-13"},
            {"pocket": "3a", "amount": 100.0, "every": "month", "months": 12,
             "start": ""},
        ]}), encoding="utf-8")
    loaded = plans.Plan.load(path)
    assert len(loaded.contributions) == 1
    assert loaded.contributions[0]["start"] == ""


def test_rate_at_uses_the_segment_that_covers_the_row():
    schedule = [(6, 0.05), (6, 0.02)]
    assert plans.rate_at(schedule, 1) == 0.05
    assert plans.rate_at(schedule, 6) == 0.05
    assert plans.rate_at(schedule, 7) == 0.02
    assert plans.rate_at(schedule, 12) == 0.02
    # Once the declared periods run out, the last declared rate carries
    # forward -- a one-segment schedule is exactly the legacy `rate`.
    assert plans.rate_at(schedule, 60) == 0.02
    assert plans.rate_at([], 3) is None


def test_parse_rate_segments_pairs_by_position_and_skips_blank_rows():
    segments, errors = plans.parse_rate_segments(
        ["6", "6", ""], ["5", "2", ""])
    assert segments == [(6, 0.05), (6, 0.02)]
    assert errors == {}
    # One blank of two is the row missing its half; both blank is the add row.
    segments, errors = plans.parse_rate_segments(["6", ""], ["5", ""])
    assert segments == [(6, 0.05)]
    assert errors == {}
    segments, errors = plans.parse_rate_segments(["6", "6"], ["", "2"])
    assert segments == [(6, 0.02)]
    assert errors == {0: "Complétez la durée et le taux."}
    # Comma and out-of-range rates are refused, with the row's index keyed.
    _, errors = plans.parse_rate_segments(["6", "6"], ["3,5", "150"])
    assert errors == {0: "Utilisez le point décimal, pas la virgule.",
                      1: "Le taux est entre -100 % et 100 %."}
    _, errors = plans.parse_rate_segments(["x", "0"], ["2", "2"])
    assert errors == {0: "La durée est un nombre de mois entier.",
                      1: "La durée est d'au moins 1 mois."}


def test_a_rate_schedule_compounds_each_month_at_its_own_rate():
    """Twelve months at 5 % then twelve at 2 % must compound at exactly those
    rates -- the same check as the single-rate annual test, per segment."""
    projection = plans.project(_two_years(), months_ahead=24)
    wealth = plans.project_wealth(
        projection, invested=10000.0, rate=None,
        rate_schedule=[(12, 0.05), (12, 0.02)])
    # Row 11 is the 12th step (the fixture opens on a partial month).
    assert wealth["rows"][11]["invested"] == pytest.approx(10500.0, abs=0.01)
    after = wealth["rows"][23]["invested"]
    assert after == pytest.approx(10500.0 * 1.02, abs=0.01)
    assert wealth["rate_schedule"] == [(12, 0.05), (12, 0.02)]


def test_a_one_segment_schedule_equals_the_legacy_rate():
    """The migration promise: a single (months, rate) segment must compound
    exactly like the `rate` field it replaces."""
    projection = plans.project(_two_years(), months_ahead=24)
    plain = plans.project_wealth(projection, 10000.0, 0.05)
    scheduled = plans.project_wealth(projection, 10000.0, 0.05,
                                     rate_schedule=[(24, 0.05)])
    assert [r["invested"] for r in plain["rows"]] == \
        [r["invested"] for r in scheduled["rows"]]


# --- net worth ---------------------------------------------------------------

def test_an_undeclared_rate_holds_the_pockets_flat():
    """Undeclared is not zero-growth-by-default dressed up: it is the app
    refusing to invent the one number on the page that came from nowhere. The
    pockets keep their last known value and the curve says so."""
    projection = plans.project(_two_years(), months_ahead=12)
    wealth = plans.project_wealth(projection, invested=10000.0, rate=None)

    assert all(r["invested"] == 10000.0 for r in wealth["rows"])
    assert wealth["rate"] is None
    for row, cash in zip(wealth["rows"], projection["rows"]):
        assert row["total"] == pytest.approx(cash["end"] + 10000.0)


def test_a_declared_rate_compounds_monthly_to_its_annual_figure():
    projection = plans.project(_two_years(), months_ahead=12)
    wealth = plans.project_wealth(projection, invested=10000.0, rate=0.05)
    # Twelve monthly steps must land on the annual rate, not 12 x (5/12).
    # Row 11 is the twelfth step: the fixture opens on a partial month.
    assert wealth["rows"][11]["invested"] == pytest.approx(10500.0, abs=0.01)


def test_the_rate_never_touches_the_cash_line():
    """A current account earns nothing here. Compounding it would put invented
    interest into the one number on the page that comes straight from the
    bank -- so only the pockets move when a rate is declared."""
    projection = plans.project(_two_years(), months_ahead=12)
    flat = plans.project_wealth(projection, invested=10000.0, rate=None)
    grown = plans.project_wealth(projection, invested=10000.0, rate=0.10)

    assert [r["cash"] for r in flat["rows"]] == [r["cash"] for r in grown["rows"]]
    assert grown["rows"][-1]["invested"] > flat["rows"][-1]["invested"]


def test_the_band_opens_from_nothing_and_widens_as_root_t():
    """Today carries no uncertainty -- the band has to pinch shut there, or the
    chart claims we do not know what we just measured."""
    projection = plans.project(_two_years(), months_ahead=12)
    wealth = plans.project_wealth(projection, invested=10000.0, rate=None,
                                  vol=0.12)
    rows = wealth["rows"]

    spreads = [r["high"] - r["total"] for r in rows]
    assert spreads[0] == pytest.approx(10000.0 * 0.12 * (1 / 12) ** 0.5)
    assert spreads[11] == pytest.approx(10000.0 * 0.12)  # twelve steps out
    assert spreads == sorted(spreads)
    # The cash half does not fluctuate, so the band is symmetric around the
    # invested part alone.
    for row in rows:
        assert row["high"] - row["total"] == pytest.approx(
            row["total"] - row["low"])


def test_a_transfer_leaves_the_cash_but_stays_in_the_net_worth(tmp_path):
    """The one entry the cash line gets wrong on its own. Moving 5'000 to a
    pocket must dent the cash and leave net worth flat -- the same mistake as
    counting an FX leg as spending, one horizon later."""
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    month = plans.month_key(plans._add_months(statement.period_end, 1))
    plan.add_one_off(month, "Vers le 3a", 5000.0, transfer=plans.SHELTERED)

    projection = plans.project(statement, plan, months_ahead=12)
    plain = plans.project(statement, months_ahead=12)
    wealth = plans.project_wealth(projection, invested=10000.0, rate=None)

    # The month the transfer sits in -- the row after the partial remainder.
    at = next(i for i, r in enumerate(projection["rows"]) if r["key"] == month)
    # The cash really does leave.
    assert projection["rows"][at]["end"] == pytest.approx(
        plain["rows"][at]["end"] - 5000.0)
    # The pocket really does receive it.
    assert wealth["rows"][at]["invested"] == pytest.approx(15000.0)
    # So net worth is untouched by the move itself.
    untouched = plans.project_wealth(plain, invested=10000.0, rate=None)
    assert wealth["rows"][at]["total"] == pytest.approx(
        untouched["rows"][at]["total"])
    assert wealth["moved"] == 5000.0


def test_a_sheltered_curve_ignores_a_taxable_transfer(tmp_path):
    """The two sides of the wealth tax are separate pockets: money moved to a
    brokerage must not grow the 3a curve, or the sheltered line would claim
    contributions it never received."""
    statement = _two_years()
    plan = plans.Plan(tmp_path / "plans.json")
    month = plans.month_key(plans._add_months(statement.period_end, 1))
    plan.add_one_off(month, "Vers le 3a", 5000.0, transfer=plans.SHELTERED)
    plan.add_one_off(month, "Vers le courtage", 2000.0, transfer=plans.TAXABLE)
    projection = plans.project(statement, plan, months_ahead=12)

    everything = plans.project_wealth(projection, 10000.0, None)
    sheltered = plans.project_wealth(projection, 4000.0, None,
                                     pocket=plans.SHELTERED, include_cash=False)
    taxable = plans.project_wealth(projection, 6000.0, None,
                                   pocket=plans.TAXABLE)

    assert everything["moved"] == 7000.0
    assert sheltered["moved"] == 5000.0
    assert taxable["moved"] == 2000.0
    # A sheltered pocket holds no current account, so its total is the pocket.
    assert all(r["cash"] == 0.0 for r in sheltered["rows"])
    assert sheltered["rows"][-1]["total"] == sheltered["rows"][-1]["invested"]
    assert sheltered["start"] == 4000.0


def test_a_dated_one_off_drops_out_once_the_ledger_passes_it(tmp_path):
    """The bug this exists for: the statement stops on 12 May, so a transfer
    planned for the 28th is still ahead and must stay in the projection --
    while one dated the 3rd is already in the ledger and must not be charged
    twice."""
    statement = _two_years()          # period_end = 2026-05-12
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_one_off("2026-05", "Encore à venir", 3000.0,
                     transfer=plans.SHELTERED, date="2026-05-28")
    plan.add_one_off("2026-05", "Déjà passé", 500.0, date="2026-05-03")
    plan.add_one_off("2026-05", "Sans date", 200.0)

    rows = {r["key"]: r for r in plans.project(statement, plan)["rows"]}
    labels = {o["label"] for o in rows["2026-05"]["one_offs"]}
    assert labels == {"Encore à venir", "Sans date"}


def test_an_unmarked_one_off_is_still_spent():
    """The flag has to be explicit: guessing from a label like "3a" would be
    the app inventing an intention the account holder never declared."""
    statement = _two_years()
    plan = plans.Plan(Path("unused"))
    month = plans.month_key(plans._add_months(statement.period_end, 1))
    plan.add_one_off(month, "Vers le 3a", 5000.0)

    projection = plans.project(statement, plan, months_ahead=12)
    wealth = plans.project_wealth(projection, invested=10000.0, rate=None)
    assert wealth["rows"][0]["invested"] == pytest.approx(10000.0)
    assert wealth["moved"] == 0.0


def test_setting_a_destination_keeps_the_seasonal_provenance(tmp_path):
    """Naming the pocket of an existing entry must not go through
    delete-and-re-add: that would drop the `seasonal` link and silently
    un-shadow the suggestion the entry was confirming, counting the same bill
    twice."""
    plan = plans.Plan(tmp_path / "plans.json")
    plan.add_one_off("2026-12", "Assurance maladie", 3500.0,
                     seasonal=("Santé", 12))

    assert plan.set_destination("2026-12", "Assurance maladie", plans.SHELTERED)
    assert plan.one_offs[0]["transfer"] == plans.SHELTERED
    assert plan.one_offs[0]["seasonal"] == {"category": "Santé", "month": 12}

    assert plan.set_destination("2026-12", "Assurance maladie", plans.SPENT)
    assert plan.one_offs[0]["transfer"] == plans.SPENT
    assert not plan.set_destination("2026-12", "Inconnu", plans.TAXABLE)


def test_without_volatility_there_is_no_band():
    projection = plans.project(_two_years(), months_ahead=12)
    wealth = plans.project_wealth(projection, invested=10000.0, rate=0.04)
    assert all(r["low"] == r["total"] == r["high"] for r in wealth["rows"])


def test_upsert_replaces_the_same_entry(tmp_path):
    path = tmp_path / "plans.json"
    plan = plans.Plan(path)
    plan.add_one_off("2026-12", "Santé", 3400.0)
    plan.add_one_off("2026-12", "Santé", 3500.0)
    assert len(plan.one_offs) == 1
    assert plan.one_offs[0]["amount"] == 3500.0
