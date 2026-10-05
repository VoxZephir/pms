"""/previsions: the page, the plan forms, suggestions, the horizon,
scenarios, contributions, in-place edits."""

from __future__ import annotations

import re

import pytest
from webhelpers import plans_path, savings_snapshots, text

from pms import plans


def test_previsions_page_renders(client):
    body = text(client.get("/previsions"))
    for probe in ("Prévisions de trésorerie", "Mois par mois",
                  "Cash aujourd'hui", "Solde le plus bas prévu",
                  "Suggérés par l'historique", "Confirmer", "Ignorer",
                  "traitillé"):
        assert probe in body
    # A twelve-month horizon holds every calendar month exactly once,
    # whichever month the ledger happens to end on.
    for name in plans.MONTH_NAMES:
        assert name in body


def test_previsions_page_has_no_empty_coordinates(client):
    body = text(client.get("/previsions"))
    assert not re.search(r'\b(x|y|cx|cy|x1|y1|x2|y2|width|height)=""', body)


def test_the_monthly_analysis_section_renders_on_previsions(client):
    """The baseline's arithmetic, shown month by month: a chart and a table
    with the same numbers, and a sommaire entry that names the section."""
    body = text(client.get("/previsions"))
    assert 'id="p-analysis"' in body
    assert '<a href="#p-analysis">Analyse mensuelle</a>' in body
    for probe in ("Médiane brute", "Médiane hors saisonnier",
                  "Pics saisonniers retirés", "Années observées"):
        assert probe in body
    # Le sommaire et le titre de section ne peuvent pas se contredire.
    start = body.index('id="p-analysis"')
    heading = re.search(r"<h3[^>]*>(.*?)</h3>", body[start:start + 200])
    assert heading and heading.group(1).strip().startswith("Analyse mensuelle")


def test_plan_add_and_delete_roundtrip(client):
    path = plans_path(client)
    if path.exists():
        path.unlink()

    response = client.post("/previsions", data={
        "action": "add", "month": "2026-11", "label": "Facture inhabituelle",
        "amount": "1234.56"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/previsions")

    plan = plans.Plan.load(path)
    assert len(plan.one_offs) == 1
    assert plan.one_offs[0]["label"] == "Facture inhabituelle"
    assert plan.one_offs[0]["amount"] == 1234.56
    assert "Facture inhabituelle" in text(client.get("/previsions"))

    client.post("/previsions", data={
        "action": "delete", "month": "2026-11", "label": "Facture inhabituelle"})
    assert plans.Plan.load(path).one_offs == []
    path.unlink(missing_ok=True)


def test_plan_income_declared_overrides_history(client):
    path = plans_path(client)
    if path.exists():
        path.unlink()

    client.post("/previsions", data={"action": "income", "amount": "8000"})
    assert plans.Plan.load(path).income == 8000.0
    body = text(client.get("/previsions"))
    assert "déclaré dans le plan" in body

    client.post("/previsions", data={"action": "income", "amount": ""})
    assert plans.Plan.load(path).income is None
    path.unlink(missing_ok=True)


def test_plan_rate_error_rerenders_with_message(client):
    """A comma in a rate cell is not silently dropped: the page comes back
    with the error stated, the typed value kept, and nothing written. The
    error is keyed to the row, so the summary link lands on that very row."""
    path = plans_path(client)
    path.unlink(missing_ok=True)

    response = client.post("/previsions", data={
        "action": "rate", "months": ["12", "6"], "rates": ["3,5", "2"]})
    body = text(response)
    assert response.status_code == 200
    assert "Vérifiez les champs suivants" in body
    assert "Utilisez le point décimal" in body
    assert "Corrigez les erreurs pour enregistrer." in body
    assert 'href="#rate-row-0"' in body
    # The barème fold reopens on the failed POST -- the error must not sit
    # inside a closed details block.
    assert '<details class="scenario-block mb-3" id="plan-rate" open>' in body
    # The failing row keeps its typed value; the healthy row is untouched.
    row = re.search(r'<tr id="rate-row-0">(.*?)</tr>', body, re.S).group(0)
    assert 'value="3,5"' in row
    assert 'aria-invalid="true"' in row
    assert 'value="6"' in body and 'value="2"' in body
    assert not path.exists()


def test_plan_income_error_keeps_the_typed_value(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)

    body = text(client.post("/previsions", data={"action": "income", "amount": "abc"}))
    assert "Utilisez le point décimal" in body
    field = re.search(r'<input[^>]*id="plan-income"[^>]*>', body).group(0)
    assert 'aria-invalid="true"' in field
    assert 'value="abc"' in field


def test_plan_add_requires_a_label(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)

    body = text(client.post("/previsions", data={
        "action": "add", "month": "2026-11", "label": "", "amount": "150"}))
    assert "Le libellé est requis." in body
    field = re.search(r'<input[^>]*id="oneoff-label"[^>]*>', body).group(0)
    assert 'aria-invalid="true"' in field
    assert not path.exists()


def test_plan_rate_valid_post_redirects(client):
    ibkr_path, finp_path = savings_snapshots(client)
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        response = client.post("/previsions", data={
            "action": "rate", "months": ["12", "6"], "rates": ["3.5", "2"]})
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/previsions")
        plan = plans.Plan.load(path)
        assert plan.rate_segments == [(12, 0.035), (6, 0.02)]
        assert plan.rate == 0.035  # the first segment, echoed for older readers
        body = text(client.get("/previsions"))
        assert "Vérifiez les champs suivants" not in body
        assert 'value="3.5"' in body and 'value="2.0"' in body
        assert "selon votre barème" in body
    finally:
        path.unlink(missing_ok=True)
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_plan_rate_remove_drops_that_segment(client):
    """The per-row Retirer button (only the clicked one is transmitted) drops
    its row before parsing -- the row above is untouched."""
    path = plans_path(client)
    path.unlink(missing_ok=True)
    client.post("/previsions", data={
        "action": "rate", "months": ["12", "6", "6"], "rates": ["3.5", "2", "1"]})
    client.post("/previsions", data={
        "action": "rate", "months": ["12", "6", "6"], "rates": ["3.5", "2", "1"],
        "remove": "1"})
    assert plans.Plan.load(path).rate_segments == [(12, 0.035), (6, 0.01)]
    path.unlink(missing_ok=True)


def test_plan_rate_all_blank_clears_the_schedule(client):
    """Every row blank is undeclared, not an error -- the same clearing the
    single rate field used to do."""
    ibkr_path, finp_path = savings_snapshots(client)
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={
            "action": "rate", "months": ["12"], "rates": ["3.5"]})
        response = client.post("/previsions", data={
            "action": "rate", "months": [""], "rates": [""]})
        assert response.status_code == 302
        plan = plans.Plan.load(path)
        assert plan.rate_segments == []
        assert plan.rate is None
        assert "figés à leur dernière valeur" in text(client.get("/previsions"))
    finally:
        path.unlink(missing_ok=True)
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_confirm_suggestion_writes_its_provenance(client):
    """Confirming writes the declared entry tied to its suggestion, so the
    renamed confirmation is not counted twice on the next render."""
    path = plans_path(client)
    if path.exists():
        path.unlink()

    body = text(client.get("/previsions"))
    # Scoped to the one form that carries a `seasonal` field, then read field
    # by field. A single regex over the whole page pinned the exact order of
    # inputs and of the attributes inside them: adding a <label> before each
    # field made it stop matching, and the test skipped itself rather than
    # failing -- which is the worse outcome, since it then guards nothing.
    fragments = [f for f in body.split("<form") if 'name="seasonal"' in f]
    if not fragments:
        pytest.skip("no seasonal suggestion on this ledger")
    fragment = fragments[0]

    def field(pattern: str) -> str:
        found = re.search(pattern, fragment)
        assert found, f"{pattern} missing from the suggestion form"
        return found.group(1)

    month = field(r'name="month" value="([^"]+)"')
    seasonal = re.search(r'name="seasonal" value="([^"]+)\|(\d+)"', fragment)
    assert seasonal, "the suggestion form lost its provenance field"
    category, month_no = seasonal.groups()
    field(r'name="label"[^>]*?value="([^"]+)"')  # present, but renamed below
    amount = field(r'name="amount"[^>]*?value="([^"]+)"')

    client.post("/previsions", data={
        "action": "add", "month": month, "label": "Renommé",
        "amount": amount, "seasonal": f"{category}|{month_no}"})
    entry = plans.Plan.load(path).one_offs[0]
    assert entry["label"] == "Renommé"
    assert entry["seasonal"] == {"category": category, "month": int(month_no)}

    # The renamed confirmation and its suggestion are the same line: the
    # shadowed category is gone from the suggestions section (other
    # suggestions stay -- the folded month table even names them).
    body = text(client.get("/previsions"))
    assert body.count("Renommé") >= 1
    start = body.index("Suggérés par l'historique")
    assert category not in body[start:]  # no double counting

    client.post("/previsions", data={
        "action": "delete", "month": month, "label": "Renommé"})
    path.unlink(missing_ok=True)


def test_ignore_and_restore_suggestion(client):
    path = plans_path(client)
    if path.exists():
        path.unlink()

    body = text(client.get("/previsions"))
    form = re.search(
        r'<form method="post" action="/previsions"[^>]*>\s*'
        r'<input type="hidden" name="action" value="ignore">\s*'
        r'<input type="hidden" name="category" value="([^"]+)">\s*'
        r'<input type="hidden" name="month_no" value="(\d+)">', body)
    if not form:
        pytest.skip("no seasonal suggestion on this ledger")
    category, month_no = form.groups()

    client.post("/previsions", data={
        "action": "ignore", "category": category, "month_no": month_no})
    assert (category, int(month_no)) in plans.Plan.load(path).ignored
    assert "Suggestions ignorées" in text(client.get("/previsions"))

    client.post("/previsions", data={
        "action": "restore", "category": category, "month_no": month_no})
    assert plans.Plan.load(path).ignored == []
    path.unlink(missing_ok=True)


def test_a_one_off_can_carry_a_precise_date(client):
    """The bug this exists for: a transfer planned for the end of the current
    month used to vanish, because the projection started the month after the
    ledger. A date keeps it in view until the ledger passes it."""
    import json

    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        body = text(client.get("/previsions"))
        assert 'id="oneoff-date"' in body and 'type="date"' in body
        assert 'id="oneoff-destination"' in body

        response = client.post("/previsions", data={
            "action": "add", "date": "2026-08-28", "label": "Versement 3a",
            "amount": "3000", "destination": "3a"})
        assert response.status_code == 302

        saved = json.loads(path.read_text(encoding="utf-8"))["one_offs"][0]
        assert saved["date"] == "2026-08-28"
        assert saved["month"] == "2026-08"
        assert saved["transfer"] == "3a"

        body = text(client.get("/previsions"))
        assert "28.08" in body
        assert "3a · hors impôt" in body
    finally:
        path.unlink(missing_ok=True)


def test_a_bad_one_off_date_says_so_instead_of_swallowing_it(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    response = client.post("/previsions", data={
        "action": "add", "date": "pas-une-date", "label": "X", "amount": "10"})
    body = text(response)
    assert response.status_code == 200
    assert "La date est invalide." in body
    assert not path.exists()


def test_editing_the_plan_keeps_the_view_you_were_in(client):
    """The redirect after a POST carries the wealth view, or correcting a
    figure would snap the reader back to a page they were not reading."""
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        response = client.post("/previsions?wealth=sheltered",
                               data={"action": "rate",
                                     "months": ["12"], "rates": ["4"]})
        assert response.status_code == 302
        assert "wealth=sheltered" in response.headers["Location"]
        assert plans.Plan.load(path).rate_segments == [(12, 0.04)]
    finally:
        path.unlink(missing_ok=True)


# --- previsions: horizon, declared volatility, inline amount edits -----------

def test_the_horizon_select_controls_the_projection(client):
    """?months=N is view state like the wealth view: the select is a real GET
    form, and a hand-typed value shows as its own option rather than lying."""
    body = text(client.get("/previsions?months=24"))
    assert "2 ans à partir du solde" in body
    assert '<option value="24" selected>2 ans</option>' in body
    # The plan forms carry the horizon along -- editing must not snap back.
    assert 'action="/previsions?months=24"' in body
    # The horizon control itself is a GET form whose action carries no months
    # key: the select's value is the only one that reaches the server.
    assert ('<form method="get" action="/previsions" '
            'class="row-form horizon-form">') in body


def test_the_horizon_is_clamped_not_echoed(client):
    body = text(client.get("/previsions?months=abc"))
    assert "1 an à partir du solde" in body
    body = text(client.get("/previsions?months=0"))
    assert "1 mois à partir du solde" in body
    # Forty years is the ceiling, and it is a preset.
    body = text(client.get("/previsions?months=9999"))
    assert "40 ans à partir du solde" in body
    assert '<option value="480" selected>40 ans</option>' in body
    # A value outside the presets gets its own option, selected -- the select
    # must not silently show the nearest preset.
    body = text(client.get("/previsions?months=30"))
    assert '<option value="30" selected>30 mois</option>' in body


def test_the_partial_row_and_undated_entry_chips_render(client):
    """The table says what the rows are: the remainder of the month under way,
    and a declaration without a precise day."""
    body = text(client.get("/previsions"))
    assert "reste du mois" in body  # the statement ends mid-month
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={
            "action": "add", "month": "2026-08", "label": "Sans jour",
            "amount": "100"})
        assert "mois entier" in text(client.get("/previsions"))
    finally:
        path.unlink(missing_ok=True)


def test_a_scenario_apply_sets_the_live_barème(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        response = client.post("/previsions", data={
            "action": "scenario-apply", "scenario": "builtin:lost-decade"})
        assert response.status_code == 302
        # The lost decade is measured on the real S&P 500 in CHF, and it
        # carries its 15-year horizon: the redirect sets the view length.
        plan = plans.Plan.load(path)
        assert plan.rate_segments == [(102, -0.118), (69, 0.2027),
                                      (300, 0.0389)]
        assert plan.rate == -0.118
        assert plan.vol is None
        assert "months=180" in response.headers["Location"]
        # A saved scenario, recalled by name.
        plan.set_scenario("Ma copie", [(12, 0.05)], 0.12)
        plan.save()
        client.post("/previsions", data={
            "action": "scenario-apply", "scenario": "saved:Ma copie"})
        loaded = plans.Plan.load(path)
        assert loaded.rate_segments == [(12, 0.05)]
        assert loaded.vol == 0.12
    finally:
        path.unlink(missing_ok=True)


def test_a_scenario_save_and_delete_roundtrip(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={
            "action": "rate", "months": ["12"], "rates": ["4"]})
        response = client.post("/previsions", data={
            "action": "scenario-save", "name": "Croissance douce"})
        assert response.status_code == 302
        plan = plans.Plan.load(path)
        assert plan.scenarios["Croissance douce"]["rate_segments"] == [(12, 0.04)]
        body = text(client.get("/previsions"))
        assert "Croissance douce" in body
        assert "4 % pendant 12 mois" in body  # the summary line
        client.post("/previsions", data={
            "action": "scenario-delete", "name": "Croissance douce"})
        assert plans.Plan.load(path).scenarios == {}
        # Deleting a scenario never touches the live barème it set.
        assert plans.Plan.load(path).rate_segments == [(12, 0.04)]
    finally:
        path.unlink(missing_ok=True)


def test_a_scenario_save_error_rerenders(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        # The block is folded by default; a failed POST reopens it, or the
        # error would be invisible inside the closed details.
        body = text(client.get("/previsions"))
        assert '<details class="scenario-block mt-3">' in body
        assert '<details class="scenario-block mt-3" open>' not in body
        body = text(client.post("/previsions", data={
            "action": "scenario-save", "name": " "}))
        assert '<details class="scenario-block mt-3" open>' in body
        assert "Le nom est requis." in body
        body = text(client.post("/previsions", data={
            "action": "scenario-save", "name": "a:b"}))
        assert "ne peut pas contenir « : »" in body
        body = text(client.post("/previsions", data={
            "action": "scenario-save", "name": "x" * 61}))
        assert "Le nom est limité à 60 caractères." in body
        assert not path.exists()
    finally:
        path.unlink(missing_ok=True)


def test_an_unknown_scenario_is_refused(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        body = text(client.post("/previsions", data={
            "action": "scenario-apply", "scenario": "saved:Inconnu"}))
        assert "Scénario inconnu." in body
        body = text(client.post("/previsions", data={
            "action": "scenario-apply", "scenario": ""}))
        assert "Choisissez un scénario." in body
        assert not path.exists()
    finally:
        path.unlink(missing_ok=True)


def test_a_contribution_add_and_delete_roundtrip(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        response = client.post("/previsions", data={
            "action": "contrib", "amount": "1000", "every": "quarter",
            "months": "24", "pocket": "3a", "start": ""})
        assert response.status_code == 302
        entry = plans.Plan.load(path).contributions[0]
        assert entry == {"pocket": "3a", "amount": 1000.0,
                         "every": "quarter", "months": 24, "start": ""}
        body = text(client.get("/previsions"))
        assert "1’000 CHF" in body  # Swiss apostrophe
        assert "chaque trimestre pendant 24 mois" in body
        client.post("/previsions", data={
            "action": "contrib-del", "pocket": "3a", "amount": "1000.0",
            "every": "quarter", "months": "24", "start": ""})
        assert plans.Plan.load(path).contributions == []
    finally:
        path.unlink(missing_ok=True)


def test_a_bad_contribution_rerenders_with_the_error(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        body = text(client.post("/previsions", data={
            "action": "contrib", "amount": "abc", "every": "quarter",
            "months": "24", "pocket": "3a"}))
        assert "Utilisez le point décimal" in body
        assert 'href="#contrib-amount"' in body
        assert 'value="abc"' in body
        body = text(client.post("/previsions", data={
            "action": "contrib", "amount": "100", "every": "weekly",
            "months": "24", "pocket": "3a"}))
        assert "Choisissez une cadence." in body
        body = text(client.post("/previsions", data={
            "action": "contrib", "amount": "100", "every": "quarter",
            "months": "0", "pocket": "", "start": "2026-13"}))
        assert "Choisissez une poche." in body
        assert "La durée est d'au moins 1 mois." in body
        assert "Le mois de début est invalide." in body
        assert not path.exists()
    finally:
        path.unlink(missing_ok=True)


def test_editing_the_rate_barème_keeps_the_declared_volatility(client):
    """set_rates must not wipe the vol the user typed: editing the schedule
    and the volatility are independent declarations."""
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={"action": "vol", "amount": "12"})
        client.post("/previsions", data={
            "action": "rate", "months": ["12"], "rates": ["4"]})
        plan = plans.Plan.load(path)
        assert plan.rate_segments == [(12, 0.04)]
        assert plan.vol == 0.12
    finally:
        path.unlink(missing_ok=True)


def test_a_short_horizon_skips_out_of_reach_suggestions(client):
    """months=1 leaves every suggestion whose month is beyond the horizon
    without a target -- they must be skipped, not crash the page, and the
    suggestions section must be empty rather than listing a dead target."""
    body = text(client.get("/previsions?months=1"))
    assert "1 mois à partir du solde" in body
    assert "Suggérés par l'historique" not in body


def test_the_suggestion_target_skips_the_partial_row():
    """A "chaque mai" suggestion must anchor to the *future* May, not the
    nearly-over partial row -- confirming there would double-charge a bill
    the ledger already carries and shadow next year's occurrence."""
    from pms.web.views.previsions import _suggestion_target
    rows = [{"key": "2026-05", "partial": True},
            {"key": "2026-06", "partial": False},
            {"key": "2027-05", "partial": False}]
    assert _suggestion_target(rows, 5) == "2027-05"
    assert _suggestion_target(rows, 6) == "2026-06"
    assert _suggestion_target(rows, 12) is None


def test_the_horizon_rides_the_post_redirect(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        response = client.post("/previsions?months=24",
                               data={"action": "income", "amount": "8000"})
        assert response.status_code == 302
        assert "months=24" in response.headers["Location"]
    finally:
        path.unlink(missing_ok=True)


def test_the_horizon_select_and_wealth_seg_stay_coherent(client):
    """Switching the wealth view on a long horizon keeps the horizon, and vice
    versa -- the two controls share one URL builder."""
    ibkr_path, finp_path = savings_snapshots(client)
    try:
        body = text(client.get("/previsions?months=24&wealth=taxable"))
        # url_for's output is safe-marked, so the & stays literal; the query
        # keeps the view key first, then the horizon.
        assert 'href="/previsions?wealth=sheltered&months=24"' in body
        assert 'href="/previsions?months=24"' in body  # Tout drops its key
    finally:
        ibkr_path.unlink(missing_ok=True)
        finp_path.unlink(missing_ok=True)


def test_the_amount_of_a_declared_one_off_edits_in_place(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={
            "action": "add", "month": "2026-11", "label": "Facture inhabituelle",
            "amount": "1234.56"})
        response = client.post("/previsions", data={
            "action": "amount", "month": "2026-11",
            "label": "Facture inhabituelle", "amount": "2345.67"})
        assert response.status_code == 302
        entry = plans.Plan.load(path).one_offs[0]
        assert entry["amount"] == 2345.67
        assert "2345.67" in text(client.get("/previsions"))
    finally:
        path.unlink(missing_ok=True)


def test_editing_the_amount_keeps_the_seasonal_provenance(client):
    """The in-place edit must not go through delete-and-re-add: that would
    drop the seasonal link (silently un-shadowing the suggestion), the
    precise date and the transfer destination."""
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={
            "action": "add", "month": "2026-12", "label": "Assurance maladie",
            "amount": "3500", "seasonal": "Santé|12"})
        client.post("/previsions", data={
            "action": "add", "date": "2026-08-28", "label": "Versement 3a",
            "amount": "3000", "destination": "3a"})
        client.post("/previsions", data={
            "action": "amount", "month": "2026-12",
            "label": "Assurance maladie", "amount": "3800"})
        client.post("/previsions", data={
            "action": "amount", "month": "2026-08",
            "label": "Versement 3a", "amount": "3500"})
        entries = {e["label"]: e for e in plans.Plan.load(path).one_offs}
        assert entries["Assurance maladie"]["amount"] == 3800.0
        assert entries["Assurance maladie"]["seasonal"] == {
            "category": "Santé", "month": 12}
        assert entries["Versement 3a"]["amount"] == 3500.0
        assert entries["Versement 3a"]["date"] == "2026-08-28"
        assert entries["Versement 3a"]["transfer"] == "3a"
    finally:
        path.unlink(missing_ok=True)


def test_a_bad_amount_rerenders_onto_the_same_row(client):
    path = plans_path(client)
    path.unlink(missing_ok=True)
    try:
        client.post("/previsions", data={
            "action": "add", "month": "2026-11", "label": "Facture inhabituelle",
            "amount": "1234.56"})
        body = text(client.post("/previsions", data={
            "action": "amount", "month": "2026-11",
            "label": "Facture inhabituelle", "amount": "abc"}))
        assert "Vérifiez les champs suivants" in body
        assert "Utilisez le point décimal" in body
        assert 'href="#amount-1"' in body
        field = re.search(r'<input[^>]*id="amount-1"[^>]*>', body).group(0)
        assert 'aria-invalid="true"' in field
        # Nothing written: the failed edit must not change the plan.
        assert plans.Plan.load(path).one_offs[0]["amount"] == 1234.56
        body = text(client.post("/previsions", data={
            "action": "amount", "month": "2026-11",
            "label": "Facture inhabituelle", "amount": "0"}))
        assert "Montant invalide." in body
    finally:
        path.unlink(missing_ok=True)
