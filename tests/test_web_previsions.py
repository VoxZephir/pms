"""The forecast (`/api/previsions`): the projection, the plan's edits and
their refusals, suggestions, the horizon, market and plan scenarios,
scheduled transfers."""

from __future__ import annotations

import json

import pytest
from webhelpers import api, plans_path, savings_snapshots

from pms import plans


@pytest.fixture
def plan_file(client):
    """No plan before the test, none left after it."""
    path = plans_path(client)
    path.unlink(missing_ok=True)
    yield path
    path.unlink(missing_ok=True)


def _edit(client, body: dict, months: int | None = None):
    """One edit; returns (status, json)."""
    url = "/api/previsions" + (f"?months={months}" if months else "")
    response = client.post(url, json=body)
    return response.status_code, response.get_json()


def _forecast(client, query: str = "") -> dict:
    return api(client, f"/api/previsions{'?' + query if query else ''}")


# --- the projection ------------------------------------------------------------

def test_a_year_holds_every_calendar_month_once(client):
    """Whichever month the ledger happens to end on."""
    rows = _forecast(client)["projection"]["rows"]
    months = [r["key"][5:] for r in rows if not r["partial"]]
    assert sorted(months) == [f"{m:02d}" for m in range(1, 13)]


def test_the_month_under_way_is_its_remainder(client):
    """The statement ends mid-month: the first row counts what is left."""
    assert _forecast(client)["projection"]["rows"][0]["partial"] is True


def test_the_ordinary_month_is_shown_month_by_month(client):
    profile = _forecast(client)["profile"]
    assert len(profile) == 12
    for month in profile:
        assert month["stripped_median"] + month["seasonal_median"] >= month["stripped_median"]


# --- the horizon ----------------------------------------------------------------

def test_the_horizon_is_clamped_not_echoed(client):
    assert _forecast(client, "months=24")["horizon_label"] == "2 ans"
    assert _forecast(client, "months=abc")["months"] == 12
    assert _forecast(client, "months=0")["horizon_label"] == "1 mois"
    assert _forecast(client, "months=9999")["horizon_label"] == "40 ans"
    assert _forecast(client, "months=30")["horizon_label"] == "30 mois"


def test_a_short_horizon_skips_out_of_reach_suggestions(client):
    assert _forecast(client, "months=1")["suggestions"] == []


def test_the_suggestion_target_skips_the_partial_row():
    """A "chaque mai" suggestion anchors to the future May, not the nearly-over
    partial row: confirming there would double-charge a bill the ledger
    already carries."""
    from pms.web.views.previsions import _suggestion_target
    rows = [{"key": "2026-05", "partial": True},
            {"key": "2026-06", "partial": False},
            {"key": "2027-05", "partial": False}]
    assert _suggestion_target(rows, 5) == "2027-05"
    assert _suggestion_target(rows, 6) == "2026-06"
    assert _suggestion_target(rows, 12) is None


# --- one-offs -----------------------------------------------------------------------

def test_a_one_off_is_added_shown_and_deleted(client, plan_file):
    status, _ = _edit(client, {"action": "add", "month": "2026-11",
                               "label": "Facture inhabituelle", "amount": "1234.56"})
    assert status == 200
    (entry,) = plans.Plan.load(plan_file).one_offs
    assert (entry["label"], entry["amount"]) == ("Facture inhabituelle", 1234.56)
    assert "Facture inhabituelle" in [e["label"] for e in _forecast(client)["plan"]["declared"]]
    _edit(client, {"action": "delete", "month": "2026-11", "label": "Facture inhabituelle"})
    assert plans.Plan.load(plan_file).one_offs == []


def test_a_one_off_can_carry_a_precise_date_and_a_destination(client, plan_file):
    """A transfer planned for the end of the current month used to vanish:
    a date keeps it in view until the ledger passes it."""
    _edit(client, {"action": "add", "date": "2026-08-28", "label": "Versement 3a",
                   "amount": "3000", "destination": "3a"})
    saved = json.loads(plan_file.read_text(encoding="utf-8"))["one_offs"][0]
    assert (saved["date"], saved["month"], saved["transfer"]) == ("2026-08-28", "2026-08", "3a")


def test_a_refused_one_off_says_why_and_writes_nothing(client, plan_file):
    status, body = _edit(client, {"action": "add", "date": "pas-une-date", "label": "X", "amount": "10"})
    assert status == 400 and body["errors"]["oneoff-date"] == "La date est invalide."
    status, body = _edit(client, {"action": "add", "month": "2026-11", "label": "", "amount": "150"})
    assert body["errors"]["oneoff-label"] == "Le libellé est requis."
    assert not plan_file.exists()


def test_the_amount_edits_in_place_keeping_what_else_was_declared(client, plan_file):
    """Not delete-and-re-add: that would drop the seasonal link, the precise
    date and the destination."""
    _edit(client, {"action": "add", "month": "2026-12", "label": "Assurance maladie",
                   "amount": "3500", "seasonal": "Santé|12"})
    _edit(client, {"action": "add", "date": "2026-08-28", "label": "Versement 3a",
                   "amount": "3000", "destination": "3a"})
    _edit(client, {"action": "amount", "month": "2026-12", "label": "Assurance maladie", "amount": "3800"})
    _edit(client, {"action": "amount", "month": "2026-08", "label": "Versement 3a", "amount": "3500"})
    entries = {e["label"]: e for e in plans.Plan.load(plan_file).one_offs}
    assert entries["Assurance maladie"]["amount"] == 3800.0
    assert entries["Assurance maladie"]["seasonal"] == {"category": "Santé", "month": 12}
    assert (entries["Versement 3a"]["amount"], entries["Versement 3a"]["date"],
            entries["Versement 3a"]["transfer"]) == (3500.0, "2026-08-28", "3a")


def test_a_bad_amount_is_refused_on_its_own_row(client, plan_file):
    _edit(client, {"action": "add", "month": "2026-11", "label": "Facture inhabituelle", "amount": "1234.56"})
    status, body = _edit(client, {"action": "amount", "month": "2026-11",
                                  "label": "Facture inhabituelle", "amount": "abc"})
    assert status == 400 and "point décimal" in body["errors"]["amount-1"]
    assert body["values"]["amount-1"] == "abc"
    assert plans.Plan.load(plan_file).one_offs[0]["amount"] == 1234.56
    _, body = _edit(client, {"action": "amount", "month": "2026-11",
                             "label": "Facture inhabituelle", "amount": "0"})
    assert body["errors"]["amount-1"] == "Montant invalide."


# --- suggestions ----------------------------------------------------------------------

def test_confirming_a_suggestion_keeps_its_provenance(client, plan_file):
    """The renamed confirmation and its suggestion are one line: it is not
    offered again, so it is never counted twice."""
    suggestions = _forecast(client)["suggestions"]
    if not suggestions:
        pytest.skip("no seasonal suggestion on this ledger")
    s = suggestions[0]
    _edit(client, {"action": "add", "month": s["target"], "label": "Renommé",
                   "amount": s["amount"], "seasonal": f"{s['category']}|{s['month']}"})
    (entry,) = plans.Plan.load(plan_file).one_offs
    assert entry["label"] == "Renommé"
    assert entry["seasonal"] == {"category": s["category"], "month": s["month"]}
    assert s["category"] not in [x["category"] for x in _forecast(client)["suggestions"]]


def test_a_suggestion_is_ignored_and_restored(client, plan_file):
    suggestions = _forecast(client)["suggestions"]
    if not suggestions:
        pytest.skip("no seasonal suggestion on this ledger")
    s = suggestions[0]
    _edit(client, {"action": "ignore", "category": s["category"], "month_no": s["month"]})
    assert (s["category"], s["month"]) in plans.Plan.load(plan_file).ignored
    assert _forecast(client)["plan"]["ignored"][0]["category"] == s["category"]
    _edit(client, {"action": "restore", "category": s["category"], "month_no": s["month"]})
    assert plans.Plan.load(plan_file).ignored == []


# --- income and spending ----------------------------------------------------------------

def test_a_declared_income_overrides_the_history(client, plan_file):
    _edit(client, {"action": "income", "amount": "8000"})
    data = _forecast(client)
    assert data["plan"]["income"] == 8000.0 and data["projection"]["income_source"] == "declared"
    _edit(client, {"action": "income", "amount": ""})
    assert plans.Plan.load(plan_file).income is None


def test_a_refused_income_keeps_the_typed_value(client, plan_file):
    status, body = _edit(client, {"action": "income", "amount": "abc"})
    assert status == 400 and "point décimal" in body["errors"]["plan-income"]
    assert body["values"]["plan-income"] == "abc"


# --- the assumed return -------------------------------------------------------------------

def test_the_rate_schedule_is_parsed_row_by_row(client, plan_file):
    status, _ = _edit(client, {"action": "rate", "months": ["12", "6", ""], "rates": ["3.5", "2", ""]})
    assert status == 200
    plan = plans.Plan.load(plan_file)
    assert plan.rate_segments == [(12, 0.035), (6, 0.02)]
    assert plan.rate == 0.035   # the first segment, echoed for older readers


def test_a_refused_rate_is_keyed_to_its_row_and_writes_nothing(client, plan_file):
    status, body = _edit(client, {"action": "rate", "months": ["12", "6"], "rates": ["3,5", "2"]})
    assert status == 400 and "point décimal" in body["errors"]["rate-row-0"]
    assert body["values"]["rate-rates"] == ["3,5", "2"]
    assert not plan_file.exists()


def test_every_row_blank_clears_the_schedule(client, plan_file):
    _edit(client, {"action": "rate", "months": ["12"], "rates": ["3.5"]})
    assert _edit(client, {"action": "rate", "months": [""], "rates": [""]})[0] == 200
    plan = plans.Plan.load(plan_file)
    assert plan.rate_segments == [] and plan.rate is None


def test_editing_the_barème_keeps_the_declared_volatility(client, plan_file):
    _edit(client, {"action": "vol", "amount": "12"})
    _edit(client, {"action": "rate", "months": ["12"], "rates": ["4"]})
    plan = plans.Plan.load(plan_file)
    assert plan.rate_segments == [(12, 0.04)] and plan.vol == 0.12


def test_the_years_cover_the_horizon_month_for_month(client, plan_file):
    forecast = _forecast(client, "months=24")
    years = forecast["plan"]["rate_years"]
    assert sum(y["months"] for y in years) == len(forecast["projection"]["rows"])
    assert [y["year"] for y in years] == list(range(years[0]["year"], years[-1]["year"] + 1))
    assert all(y["rate"] is None and not y["mixed"] for y in years)   # nothing declared


def test_a_rate_per_year_becomes_a_barème_with_equal_years_merged(client, plan_file):
    years = _forecast(client, "months=36")["plan"]["rate_years"]
    rates = ["5,25", "-12.5 %", "-12,5"] + ["4"] * (len(years) - 3)
    status, _ = _edit(client, {"action": "rate-years", "rates": rates}, months=36)
    assert status == 200
    plan = plans.Plan.load(plan_file)
    m = [y["months"] for y in years]
    assert plan.rate_segments == [(m[0], 0.0525), (m[1] + m[2], -0.125), (sum(m[3:]), 0.04)]
    shown = _forecast(client, "months=36")["plan"]["rate_years"]
    assert [y["rate"] for y in shown] == [0.0525, -0.125, -0.125] + [0.04] * (len(years) - 3)


def test_a_longer_horizon_carries_the_last_year_on(client, plan_file):
    years = _forecast(client, "months=12")["plan"]["rate_years"]
    _edit(client, {"action": "rate-years", "rates": ["3"] * (len(years) - 1) + ["7"]}, months=12)
    longer = _forecast(client, "months=60")["plan"]["rate_years"]
    assert longer[-1]["rate"] == 0.07 and len(longer) > len(years)


def test_a_year_across_two_periods_reads_as_mixed(client, plan_file):
    _edit(client, {"action": "rate", "months": ["1", "120"], "rates": ["2", "6"]})
    years = _forecast(client, "months=24")["plan"]["rate_years"]
    first = years[0]
    assert (first["mixed"], first["rate"]) == ((True, None) if first["months"] > 1 else (False, 0.02))


def test_a_refused_year_is_keyed_to_it_and_writes_nothing(client, plan_file):
    years = _forecast(client, "months=24")["plan"]["rate_years"]
    rates = ["4"] * len(years)
    rates[1] = "beaucoup"
    status, body = _edit(client, {"action": "rate-years", "rates": rates}, months=24)
    assert status == 400 and "rate-year-1" in body["errors"]
    assert not plan_file.exists()
    status, body = _edit(client, {"action": "rate-years", "rates": ["4"]}, months=24)
    assert status == 400 and "rechargez" in body["errors"]["rate-years"]


def test_rates_are_read_as_people_type_them():
    assert plans.parse_percent("5,25 %") == 5.25
    assert plans.parse_percent("\u22123,1") == -3.1
    assert plans.parse_percent("") is None and plans.parse_percent("x") is None


def test_a_market_scenario_sets_the_barème_and_its_horizon(client, plan_file):
    status, body = _edit(client, {"action": "scenario-apply", "scenario": "builtin:lost-decade"})
    assert status == 200
    plan = plans.Plan.load(plan_file)
    assert plan.rate_segments == [(102, -0.118), (69, 0.2027), (300, 0.0389)]
    assert plan.vol is None
    # Fifteen years: the page switches its horizon to it.
    assert body["months"] == 180
    plan.set_scenario("Ma copie", [(12, 0.05)], 0.12)
    plan.save()
    _edit(client, {"action": "scenario-apply", "scenario": "saved:Ma copie"})
    loaded = plans.Plan.load(plan_file)
    assert loaded.rate_segments == [(12, 0.05)] and loaded.vol == 0.12


def test_a_market_scenario_is_saved_summarised_and_deleted(client, plan_file):
    _edit(client, {"action": "rate", "months": ["12"], "rates": ["4"]})
    assert _edit(client, {"action": "scenario-save", "name": "Croissance douce"}, months=24)[0] == 200
    plan = plans.Plan.load(plan_file)
    assert plan.scenarios["Croissance douce"]["rate_segments"] == [(12, 0.04)]
    assert plan.scenarios["Croissance douce"]["months"] == 24   # the horizon it was read on
    (saved,) = _forecast(client)["plan"]["scenarios"]
    assert saved["summary"].startswith("4 % pendant 12 mois")
    _edit(client, {"action": "scenario-delete", "name": "Croissance douce"})
    plan = plans.Plan.load(plan_file)
    assert plan.scenarios == {} and plan.rate_segments == [(12, 0.04)]


def test_a_market_scenario_name_is_checked(client, plan_file):
    assert _edit(client, {"action": "scenario-save", "name": " "})[1]["errors"]["scenario-save"] == "Le nom est requis."
    assert "« : »" in _edit(client, {"action": "scenario-save", "name": "a:b"})[1]["errors"]["scenario-save"]
    assert "60 caractères" in _edit(client, {"action": "scenario-save", "name": "x" * 61})[1]["errors"]["scenario-save"]
    assert _edit(client, {"action": "scenario-apply", "scenario": "saved:Inconnu"})[1]["errors"]["scenario-apply"] == "Scénario inconnu."
    assert _edit(client, {"action": "scenario-apply", "scenario": ""})[1]["errors"]["scenario-apply"] == "Choisissez un scénario."
    assert not plan_file.exists()


# --- scheduled transfers ---------------------------------------------------------------------

def test_a_series_is_added_and_removed(client, plan_file):
    assert _edit(client, {"action": "contrib", "amount": "1000", "every": "quarter",
                          "months": "24", "pocket": "3a", "start": ""})[0] == 200
    (entry,) = plans.Plan.load(plan_file).contributions
    assert entry == {"pocket": "3a", "amount": 1000.0, "every": "quarter", "months": 24, "start": ""}
    (shown,) = _forecast(client)["plan"]["contributions"]
    assert shown["every_label"] == "chaque trimestre"
    _edit(client, {"action": "contrib-del", "pocket": "3a", "amount": 1000.0,
                   "every": "quarter", "months": 24, "start": ""})
    assert plans.Plan.load(plan_file).contributions == []


def test_a_bad_series_is_refused_field_by_field(client, plan_file):
    _, body = _edit(client, {"action": "contrib", "amount": "abc", "every": "quarter",
                             "months": "24", "pocket": "3a"})
    assert "en francs" in body["errors"]["contrib-amount"]
    _, body = _edit(client, {"action": "contrib", "amount": "100", "every": "weekly",
                             "months": "24", "pocket": "3a"})
    assert body["errors"]["contrib-every"] == "Choisissez une cadence."
    _, body = _edit(client, {"action": "contrib", "amount": "100", "every": "quarter",
                             "months": "0", "pocket": "", "start": "2026-13"})
    assert body["errors"]["contrib-pocket"] == "Choisissez une poche."
    assert body["errors"]["contrib-months"] == "La durée est d'au moins 1 mois."
    assert body["errors"]["contrib-start"] == "Le mois de début est invalide."
    assert not plan_file.exists()


# --- whole plans as scenarios ------------------------------------------------------------------

def test_plans_are_saved_switched_compared_and_deleted(client, plan_file):
    """The page edits the plan on screen, switching keeps its edits, the
    comparison projects every plan on the same horizon."""
    _edit(client, {"action": "income", "amount": "8000"})
    assert _edit(client, {"action": "plan-save-as", "name": "Prudent"})[0] == 200
    _edit(client, {"action": "plan-save-as", "name": "Loyer en hausse"})
    # The copy is on screen: its edits do not touch the original.
    _edit(client, {"action": "spend", "amount": "4500"})
    plan = plans.Plan.load(plan_file)
    assert plan.active == "Loyer en hausse" and plan.spend == 4500.0
    assert plan.plan_scenarios["Prudent"]["spend"] is None

    data = _forecast(client)
    assert data["active"] == "Loyer en hausse"
    assert [c["name"] for c in data["comparison"]] == ["Prudent", "Loyer en hausse"]
    assert all(len(c["line"]) == len(data["projection"]["rows"]) for c in data["comparison"])
    on = next(c for c in data["comparison"] if c["active"])
    assert on["spend_source"] == "declared"

    _edit(client, {"action": "plan-switch", "name": "Prudent"})
    plan = plans.Plan.load(plan_file)
    assert plan.active == "Prudent" and plan.spend is None and plan.income == 8000.0
    assert plan.plan_scenarios["Loyer en hausse"]["spend"] == {"amount": 4500.0}

    assert _edit(client, {"action": "plan-switch", "name": "Inconnu"})[1]["errors"]["plan-switch"] == "Scénario inconnu."
    assert _edit(client, {"action": "plan-save-as", "name": " "})[1]["errors"]["plan-new"] == "Le nom est requis."

    # Deleting the plan on screen keeps it, unnamed.
    _edit(client, {"action": "plan-delete", "name": "Prudent"})
    plan = plans.Plan.load(plan_file)
    assert plan.active is None and plan.income == 8000.0
    assert list(plan.plan_scenarios) == ["Loyer en hausse"]
    assert None in [c["name"] for c in _forecast(client)["comparison"]]


def test_a_plan_is_renamed_copied_from_another_and_its_deletion_undone(client, plan_file):
    _edit(client, {"action": "income", "amount": "8000"})
    # Naming the unnamed plan saves it.
    assert _edit(client, {"action": "plan-rename", "old": "", "name": "Base"})[0] == 200
    _edit(client, {"action": "plan-save-as", "name": "Prudent"})
    _edit(client, {"action": "spend", "amount": "4500"})
    # A name taken is refused, never overwritten.
    status, body = _edit(client, {"action": "plan-save-as", "name": "Base"})
    assert status == 400 and body["errors"]["plan-new"] == "Un scénario porte déjà ce nom."
    assert plans.Plan.load(plan_file).plan_scenarios["Base"]["income"] == {"amount": 8000.0}

    # A copy of another plan than the one shown: the shown one keeps its edits.
    _edit(client, {"action": "plan-save-as", "name": "Variante", "from": "Base"})
    plan = plans.Plan.load(plan_file)
    assert plan.active == "Variante" and plan.spend is None
    assert plan.plan_scenarios["Prudent"]["spend"] == {"amount": 4500.0}

    _edit(client, {"action": "plan-rename", "old": "Variante", "name": "Sabbatique"})
    assert _edit(client, {"action": "plan-rename", "old": "Sabbatique", "name": "Prudent"})[1]["errors"]["plan-rename"] \
        == "Un scénario porte déjà ce nom."
    plan = plans.Plan.load(plan_file)
    assert plan.active == "Sabbatique" and list(plan.plan_scenarios) == ["Base", "Prudent", "Sabbatique"]

    # Deleting one not on screen, then undoing: it comes back whole.
    _edit(client, {"action": "plan-delete", "name": "Prudent"})
    assert "Prudent" not in plans.Plan.load(plan_file).plan_scenarios
    assert _edit(client, {"action": "plan-undelete"})[0] == 200
    assert plans.Plan.load(plan_file).plan_scenarios["Prudent"]["spend"] == {"amount": 4500.0}
    assert _edit(client, {"action": "plan-undelete"})[0] == 400


def test_the_rate_reaches_the_net_worth(client, plan_file):
    paths = savings_snapshots(client)
    try:
        assert _forecast(client)["wealth"]["rate"] is None
        _edit(client, {"action": "rate", "months": ["12"], "rates": ["5"]})
        assert _forecast(client)["wealth"]["rate"] == pytest.approx(0.05)
    finally:
        for p in paths:
            p.unlink(missing_ok=True)


def test_a_series_is_edited_in_place(client, plan_file):
    for amount in ("700", "7258"):
        _edit(client, {"action": "contrib", "amount": amount, "every": "month", "months": "450",
                       "pocket": "taxable", "start": ""})
    status, _ = _edit(client, {"action": "contrib", "index": "0", "amount": "850", "every": "quarter",
                               "months": "120", "pocket": "3a", "start": "2027-08"})
    assert status == 200
    series = plans.Plan.load(plan_file).contributions
    assert series[0] == {"pocket": "3a", "amount": 850.0, "every": "quarter", "months": 120, "start": "2027-08"}
    assert series[1]["amount"] == 7258.0 and len(series) == 2
    # Typed the Swiss way.
    _edit(client, {"action": "contrib", "index": "1", "amount": "1'000,50", "every": "year",
                   "months": "12", "pocket": "3a", "start": ""})
    assert plans.Plan.load(plan_file).contributions[1]["amount"] == 1000.5
    # A series that is gone is said, nothing is added.
    status, body = _edit(client, {"action": "contrib", "index": "5", "amount": "10", "every": "month",
                                  "months": "1", "pocket": "3a", "start": ""})
    assert status == 400 and "n'existe plus" in body["errors"]["contrib-amount"]
    assert len(plans.Plan.load(plan_file).contributions) == 2


def test_a_one_off_is_edited_whole_in_place(client, plan_file):
    _edit(client, {"action": "add", "month": "2026-12", "label": "Assurance maladie",
                   "amount": "900", "seasonal": "Santé|12"})
    _edit(client, {"action": "add", "date": "2026-11-25", "label": "Meubles", "amount": "3000"})
    status, _ = _edit(client, {"action": "add", "was_month": "2026-11", "was_label": "Meubles",
                               "date": "2027-01-10", "label": "Meubles du salon", "amount": "2500",
                               "destination": ""})
    assert status == 200
    entries = plans.Plan.load(plan_file).one_offs
    e = entries[1]
    assert (e["month"], e["label"], e["amount"], e["date"]) == ("2027-01", "Meubles du salon", 2500.0, "2027-01-10")
    # A month-only entry keeps its month and its provenance when renamed.
    _edit(client, {"action": "add", "was_month": "2026-12", "was_label": "Assurance maladie",
                   "month": "2026-12", "date": "", "label": "LAMal", "amount": "950"})
    first = plans.Plan.load(plan_file).one_offs[0]
    assert (first["label"], first["month"], first["amount"]) == ("LAMal", "2026-12", 950.0)
    assert first["seasonal"] == {"category": "Santé", "month": 12}
    # One that is gone is said, nothing is added.
    status, body = _edit(client, {"action": "add", "was_month": "2026-11", "was_label": "Meubles",
                                  "date": "2026-11-25", "label": "X", "amount": "1"})
    assert status == 400 and "n'existe plus" in body["errors"]["oneoff-label"]
    assert len(plans.Plan.load(plan_file).one_offs) == 2


def test_a_series_can_skip_months_of_the_year(client, plan_file):
    status, _ = _edit(client, {"action": "contrib", "amount": "1000", "every": "month", "months": "24",
                               "pocket": "taxable", "start": "2027-01", "in_months": [5, 6, 7, 8, 9, 10, 11, 12],
                               "in_months_on": "1"})
    assert status == 200
    (series,) = plans.Plan.load(plan_file).contributions
    assert series["in_months"] == [5, 6, 7, 8, 9, 10, 11, 12]
    (shown,) = _forecast(client, "months=36")["plan"]["contributions"]
    assert shown["in_months_label"] == "de mai à décembre"
    rows = _forecast(client, "months=36")["projection"]["rows"]
    paid = {r["key"] for r in rows
            if any(o.get("source") == "contribution" for o in r["one_offs"])}
    assert "2027-04" not in paid and "2027-05" in paid and "2028-02" not in paid and "2028-12" in paid
    # Every month ticked is the whole year: stored as before.
    _edit(client, {"action": "contrib", "index": "0", "amount": "1000", "every": "month", "months": "24",
                   "pocket": "taxable", "start": "2027-01", "in_months": list(range(1, 13)), "in_months_on": "1"})
    assert "in_months" not in plans.Plan.load(plan_file).contributions[0]
    # None ticked is refused, not read as "all year".
    status, body = _edit(client, {"action": "contrib", "amount": "10", "every": "month", "months": "2",
                                  "pocket": "3a", "start": "", "in_months": [], "in_months_on": "1"})
    assert status == 400 and body["errors"]["contrib-in-months"]
    # Removed by its whole content, months included.
    _edit(client, {"action": "contrib", "index": "0", "amount": "1000", "every": "month", "months": "24",
                   "pocket": "taxable", "start": "2027-01", "in_months": [12], "in_months_on": "1"})
    _edit(client, {"action": "contrib-del", "pocket": "taxable", "amount": 1000.0, "every": "month",
                   "months": 24, "start": "2027-01", "in_months": [12]})
    assert plans.Plan.load(plan_file).contributions == []


def test_the_months_of_a_series_read_as_said():
    assert plans.months_phrase([5]) == "en mai"
    assert plans.months_phrase([3, 6, 9]) == "en mars, juin et septembre"
    assert plans.months_phrase([11, 12, 1, 2]) == "de novembre à février"
    assert plans.months_phrase([1, 2, 3, 4, 5, 6]) == "de janvier à juin"
    assert plans.months_phrase([4, 5, 6, 7, 8, 9, 10, 11, 12]) == "d'avril à décembre"
    assert plans.months_phrase([8, 9, 10]) == "d'août à octobre"
    assert plans.in_months_of(["13", "x", "5", 5]) == [5]


# --- smoothing the transfers to the brokerage account ----------------------------------------

def test_lumpy_brokerage_transfers_become_one_standing_order_with_the_same_low_point(client, plan_file):
    keys = [r["key"] for r in _forecast(client)["projection"]["rows"] if not r["partial"]]
    for key, amount in ((keys[1], "6000"), (keys[6], "9000")):
        _edit(client, {"action": "add", "month": key, "label": "Vers IBKR", "amount": amount,
                       "destination": "taxable"})
    _edit(client, {"action": "plan-save-as", "name": "À-coups"})
    preview = api(client, "/api/previsions/smooth?scenario=À-coups&months=12&step=50")
    assert preview["amount"] > 0 and preview["amount"] % 50 == 0
    assert preview["after"]["low"] >= preview["before"]["low"]
    assert preview["before"]["moved"] == 15000
    assert len(preview["rows"]) >= 12 and "declarations" not in preview
    # Limited to some months of the year: a larger amount in fewer months.
    may_on = api(client, "/api/previsions/smooth?scenario=À-coups&months=12&in_months=5,6,7,8,9,10,11,12")
    assert may_on["in_months"] == [5, 6, 7, 8, 9, 10, 11, 12]
    assert may_on["in_months_label"] == "de mai à décembre"
    assert may_on["after"]["low"] >= may_on["before"]["low"]

    response = client.post("/api/previsions/smooth", json={"scenario": "À-coups", "months": 12})
    assert response.status_code == 200 and response.get_json()["name"] == "À-coups — IBKR mensuel"
    plan = plans.Plan.load(plan_file)
    assert plan.active == "À-coups"
    smooth = plan.plan_scenarios["À-coups — IBKR mensuel"]
    assert not [e for e in smooth["one_offs"] if e.get("transfer") == "taxable"]
    (series,) = [c for c in smooth["contributions"] if c["pocket"] == "taxable"]
    assert (series["amount"], series["every"]) == (preview["amount"], "month")
    assert len([e for e in plan.one_offs if e.get("transfer") == "taxable"]) == 2
    # The same name twice is refused, not overwritten.
    again = client.post("/api/previsions/smooth", json={"scenario": "À-coups", "months": 12})
    assert again.status_code == 400 and "smooth-name" in again.get_json()["errors"]
    gone = api(client, "/api/previsions/smooth?scenario=Inconnu")
    assert gone["error"].startswith("Ce scénario n'existe plus")


# --- the cash floor ----------------------------------------------------------------------------

def test_a_cash_floor_alerts_on_the_page_every_page_and_the_weekly_summary(client, plan_file):
    assert _forecast(client)["floor_alert"] is None
    assert api(client, "/api/meta")["floor"] is None
    low = _forecast(client)["projection"]["low"]["amount"]
    # Under the lowest month-end: the plan holds, nothing is said elsewhere.
    _edit(client, {"action": "floor", "amount": "1"})
    held = _forecast(client)["floor_alert"]
    assert held == {"floor": 1.0, "below": False, "months": held["months"]}
    assert api(client, "/api/meta")["floor"] is None
    # Above it, typed the Swiss way: the first month under, the lowest, a sentence.
    floor = round(low + 5000, -3)
    assert _edit(client, {"action": "floor", "amount": f"{floor:,.0f}".replace(",", "'")})[0] == 200
    alert = _forecast(client)["floor_alert"]
    assert alert["below"] and alert["floor"] == floor and alert["low"]["amount"] == low
    assert alert["text"].startswith("Cash projeté sous ton seuil de ")
    assert api(client, "/api/meta")["floor"]["text"] == alert["text"]
    assert f"⚠ {alert['text']}" in api(client, "/api/semaine")["summary"]["lines"]
    assert json.loads(plan_file.read_text(encoding="utf-8"))["cash_floor"] == floor
    # Not part of a scenario: saving one leaves the floor where it is.
    _edit(client, {"action": "plan-save-as", "name": "Avec seuil"})
    assert "cash_floor" not in plans.Plan.load(plan_file).plan_scenarios["Avec seuil"]
    status, body = _edit(client, {"action": "floor", "amount": "beaucoup"})
    assert status == 400 and "plan-floor" in body["errors"]
    _edit(client, {"action": "floor", "amount": ""})
    assert _forecast(client)["floor_alert"] is None and api(client, "/api/meta")["floor"] is None
