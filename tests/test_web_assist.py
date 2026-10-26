"""The assisted features over HTTP (`web/api/assist.py`), with the model
replaced by canned answers: what each route sends, what it refuses from
the model, and that nothing is written without the user's click."""

from __future__ import annotations

import json

import pytest

from pms import ai

JUNE = "from=2026-06-01&to=2026-06-30"


@pytest.fixture
def app(tmp_path, ledger_file):
    from pms.web import create_app
    copy = tmp_path / "ledger.json"
    copy.write_bytes(ledger_file.read_bytes())
    app = create_app(copy)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def model(app, monkeypatch):
    """Switch a model on and answer from `model.answers`, by task: the
    system prompt names the task, the fake reads the request back."""
    folder = app.extensions["pms_store"].path.parent
    (folder / ai.CONFIG_NAME).write_text('{"provider": "deepseek"}', encoding="utf-8")
    (folder / ai.KEY_NAME).write_text("sk-test", encoding="utf-8")

    class Fake:
        answers: dict = {}
        sent: list = []

        def __call__(self, config, system, user, schema, max_tokens):
            self.sent.append(user)
            for marker, answer in self.answers.items():
                if marker in system:
                    value = answer(json.loads(user)) if callable(answer) else answer
                    return json.dumps(value)
            raise AssertionError("no canned answer for " + system[:80])

    fake = Fake()
    fake.answers, fake.sent = {}, []
    monkeypatch.setattr(ai, "_call", fake)
    return fake


def _post(client, url, body):
    return client.post(url, json=body, headers={"Origin": "http://localhost"})


def test_off_until_configured(app):
    with app.test_client() as c:
        assert c.get("/api/ai").get_json()["enabled"] is False
        r = _post(c, "/api/ai/ask", {"question": "combien ?"})
        assert r.status_code == 503 and "Assistant" in r.get_json()["error"]


def test_review_summary_is_kept_and_number_checked(app, model):
    model.answers["bilan d'un mois"] = lambda facts: {
        "headline": f"Juin a coûté {round(facts['depense'])} CHF, dans ta médiane.",
        "points": [f"Depuis janvier : {round(facts['depuis_janvier'])} CHF."]}
    with app.test_client() as c:
        assert c.get(f"/api/ai/review?{JUNE}").get_json()["summary"] is None
        summary = _post(c, "/api/ai/review", {"from": "2026-06-01", "to": "2026-06-30"}).get_json()["summary"]
        assert summary["headline"].startswith("Juin a coûté 3") and len(summary["points"]) == 1
        # Kept: the page shows it again without asking.
        assert c.get(f"/api/ai/review?{JUNE}").get_json()["summary"] == summary
    assert len(model.sent) == 1


def test_an_invented_number_gets_one_more_try_then_is_dropped(app, model):
    model.answers["bilan d'un mois"] = {"headline": "Juin a coûté 9'999 CHF.", "points": []}
    with app.test_client() as c:
        r = _post(c, "/api/ai/review", {"from": "2026-06-01", "to": "2026-06-30"})
        assert r.status_code == 502 and "chiffre" in r.get_json()["error"]
        assert c.get(f"/api/ai/review?{JUNE}").get_json()["summary"] is None
    assert len(model.sent) == 2 and "correction" in json.loads(model.sent[1])


def test_the_second_try_is_kept_when_it_is_right(app, model):
    tries = iter([{"headline": "Juin a coûté 9'999 CHF.", "points": []},
                  {"headline": "Juin est dans sa médiane.", "points": []}])
    model.answers["bilan d'un mois"] = lambda facts: next(tries)
    with app.test_client() as c:
        r = _post(c, "/api/ai/review", {"from": "2026-06-01", "to": "2026-06-30"})
    assert r.get_json()["summary"]["headline"] == "Juin est dans sa médiane."


def test_why_cites_rows_the_app_chose(app, model):
    model.answers["pourquoi ce mois"] = lambda f: {
        "text": f"Écart de {abs(round(f['ecart']))} CHF, porté par une ligne.",
        "lines": [0, 99], "nature": "ponctuel"}
    with app.test_client() as c:
        answer = _post(c, "/api/ai/why", {"from": "2026-06-01", "to": "2026-06-30"}).get_json()["answer"]
    assert answer["nature"] == "ponctuel" and len(answer["rows"]) == 1
    assert answer["rows"][0]["key"]


def test_a_question_becomes_a_query_the_app_runs(app, model):
    model.answers["traduis une question"] = _plan(focus="total", category="Restaurants & bars")
    model.answers["réponds à une question"] = lambda q: {
        "answer": f"{q['resultats']['depense']} CHF en restaurants.", "follow_ups": ["Et en 2025 ?"]}
    with app.test_client() as c:
        r = _post(c, "/api/ai/ask", {"question": "Combien en restaurants cette année ?"}).get_json()
    assert r["supported"] and r["view"]["category"] == "Restaurants & bars"
    assert r["view"]["path"] == "/transactions"
    store = app.extensions["pms_store"]
    expected = sum(abs(t.amount_chf) for t in store.statement.transactions
                   if t.category == "Restaurants & bars" and t.amount_chf < 0
                   and "2026-01-01" <= t.date.isoformat() <= "2026-06-30")
    assert r["table"]["rows"][0][1] == pytest.approx(expected, abs=0.01)
    assert r["answer"].startswith(str(round(expected, 2)))
    assert r["follow_ups"] == ["Et en 2025 ?"]


def test_an_unknown_category_from_the_model_is_dropped(app, model):
    model.answers["traduis une question"] = _plan(category="Catégorie inventée", to="2026-01-31")
    model.answers["réponds à une question"] = {"answer": "Rien.", "follow_ups": []}
    with app.test_client() as c:
        r = _post(c, "/api/ai/ask", {"question": "?"}).get_json()
    assert r["view"]["category"] is None


def test_names_of_people_are_masked_before_leaving(app, model):
    model.answers["traduis une question"] = _plan(focus="beneficiaires", start="2024-07-30",
                                                  to="2026-07-30")
    model.answers["réponds à une question"] = {"answer": "Surtout [P1].", "follow_ups": []}
    with app.test_client() as c:
        r = _post(c, "/api/ai/ask", {"question": "où va l'argent ?"}).get_json()
    sent = json.loads(model.sent[-1])
    names = [b["nom"] for b in sent["resultats"]["beneficiaires"]]
    assert any(n.startswith("[P") for n in names)
    assert "[P1]" not in r["answer"]
    # The table on screen reads the real names.
    assert not any(str(row[0]).startswith("[P") for row in r["table"]["rows"])


def _plan(focus="total", category=None, start="2026-01-01", to="2026-06-30", **extra):
    return {"supported": True, "focus": focus, "from": start, "to": to, "compare_from": None,
            "compare_to": None, "category": category, "search": None, "threshold": None,
            "months": None, "note": "", **extra}


def test_a_question_about_the_future_reads_the_projection(app, model):
    model.answers["traduis une question"] = _plan(focus="prevision", threshold=15000, months=12)
    model.answers["réponds à une question"] = lambda q: {
        "answer": f"Point bas {round(q['resultats']['point_bas']['montant'])} CHF, seuil 15'000.",
        "follow_ups": []}
    with app.test_client() as c:
        r = _post(c, "/api/ai/ask", {"question": "et si je ne veux jamais descendre sous 15k ?"}).get_json()
    sent = json.loads(model.sent[-1])["resultats"]
    assert sent["seuil"] == 15000 and len(sent["par_mois"]) >= 12
    assert (sent["sous_le_seuil"] is None) == all(m["solde_fin"] >= 15000 for m in sent["par_mois"])
    assert r["view"]["path"] == "/previsions" and r["table"]["columns"][1] == "Solde prévu"


def test_a_comparison_lays_out_both_periods(app, model):
    model.answers["traduis une question"] = _plan(focus="comparaison", compare_from="2025-01-01",
                                                  compare_to="2025-06-30")
    model.answers["réponds à une question"] = {"answer": "Comparé.", "follow_ups": []}
    with app.test_client() as c:
        r = _post(c, "/api/ai/ask", {"question": "2026 contre 2025 ?"}).get_json()
    assert len(r["table"]["columns"]) == 3 and r["table"]["rows"][0][0] == "Total"


def test_a_follow_up_carries_the_last_exchange(app, model):
    model.answers["traduis une question"] = _plan()
    model.answers["réponds à une question"] = {"answer": "Oui.", "follow_ups": []}
    with app.test_client() as c:
        _post(c, "/api/ai/ask", {"question": "et l'année d'avant ?",
                                 "history": [{"question": "combien en 2026 ?", "answer": "Beaucoup."}]})
    plan_request = json.loads(model.sent[0])
    assert plan_request["echanges_precedents"][0]["question"] == "combien en 2026 ?"


@pytest.mark.parametrize("proposed, kept", [("Alimentation", "Alimentation"),
                                             ("Inventée", None)])
def test_merchant_suggestions_stay_in_the_owner_list(app, model, proposed, kept):
    model.answers["classes des commerçants"] = lambda req: {"suggestions": [
        {"id": c["id"], "category": proposed, "subcategory": "",
         "confidence": "haute", "why": "un grossiste"} for c in req["commercants"]]}
    with app.test_client() as c:
        before = c.get("/api/ai/merchants").get_json()
        assert before["pending"] == len(before["payees"]) >= 1
        after = _post(c, "/api/ai/merchants", {}).get_json()
    assert {p["suggestion"]["category"] for p in after["payees"]} == {kept}
    assert after["pending"] == 0


def test_a_scenario_is_previewed_then_saved_unapplied(app, model):
    from pms import plans
    model.answers["modifications d'un plan"] = {
        "supported": True, "name": "IBKR +500", "note": "", "floor": None,
        "changes": [{"action": "contrib", "amount": 500, "pocket": "taxable", "every": "month",
                     "months": 480, "start": "2027-01", "label": None, "date": None,
                     "month": None, "destination": None}]}
    path = app.extensions["pms_store"].path.with_name("plans.json")
    with app.test_client() as c:
        preview = _post(c, "/api/ai/scenario", {"sentence": "500 de plus sur IBKR dès janvier"}).get_json()
        assert preview["supported"] and "500.00 CHF chaque mois" in preview["changes"][0]["text"]
        assert preview["scenario"]["end"] < preview["base"]["end"]
        assert not path.exists()
        saved = _post(c, "/api/ai/scenario", {"action": "save", "name": preview["name"],
                                               "changes": preview["changes"]})
        assert saved.status_code == 200
    plan = plans.Plan.load(path)
    assert "IBKR +500" in plan.plan_scenarios and plan.active is None
    assert plan.contributions == []


def test_a_change_the_plan_refuses_is_not_shown(app, model):
    model.answers["modifications d'un plan"] = {
        "supported": True, "name": "x", "note": "", "floor": None,
        "changes": [{"action": "contrib", "amount": 500, "pocket": None, "every": "month",
                     "months": 12, "start": None, "label": None, "date": None,
                     "month": None, "destination": None}]}
    with app.test_client() as c:
        r = _post(c, "/api/ai/scenario", {"sentence": "500 par mois"})
    assert r.status_code == 422 and "poche" in r.get_json()["note"]


def test_the_model_is_chosen_in_the_app_the_key_stays_a_file(app, monkeypatch):
    monkeypatch.setattr(ai, "local_models", lambda *a: None)
    folder = app.extensions["pms_store"].path.parent
    with app.test_client() as c:
        s = c.get("/api/ai/settings").get_json()
        assert s["provider"] is None and not s["status"]["enabled"]
        deepseek = next(p for p in s["providers"] if p["id"] == "deepseek")
        assert not deepseek["has_key"] and deepseek["key_file"] == "data/ai.deepseek.key"

        (folder / "ai.deepseek.key").write_text("sk-secret-deepseek\n", encoding="utf-8")
        r = _post(c, "/api/ai/settings", {"provider": "deepseek", "model": "deepseek-chat"})
        assert r.status_code == 200 and r.get_json()["status"]["enabled"]
        assert "sk-secret" not in r.get_data(as_text=True)
        assert json.loads((folder / ai.CONFIG_NAME).read_text())["model"] == "deepseek-chat"

        # Claude chosen without its key: saved, and the page says what is missing.
        s = _post(c, "/api/ai/settings", {"provider": "anthropic", "model": "claude-haiku-5-5"}).get_json()
        assert not s["status"]["enabled"] and "ai.anthropic.key" in s["status"]["reason"]

        assert _post(c, "/api/ai/settings", {"provider": "anthropic", "model": "x y"}).status_code == 400
        off = _post(c, "/api/ai/settings", {"provider": None}).get_json()
        assert not off["status"]["enabled"] and off["provider"] == "anthropic"


def test_the_test_button_is_never_cached(app, model):
    model.answers["Réponds par un objet JSON"] = {"ok": True}
    with app.test_client() as c:
        for _ in range(2):
            assert _post(c, "/api/ai/test", {}).get_json()["ok"]
        assert [e["task"] for e in c.get("/api/ai/settings").get_json()["journal"]] == ["test", "test"]
    assert len(model.sent) == 2


@pytest.mark.parametrize("threshold", [5_000, 60_000])
def test_how_much_a_month_keeps_every_month_end_above_the_threshold(app, threshold):
    """The answer to "how much can I save without going under X?" is worked
    out by the app: that amount every month, from now, leaves each projected
    month end at or above X -- and ten francs more would not."""
    from pms import assist, plans
    statement = app.extensions["pms_store"].statement
    facts, table = assist.forecast_facts(statement, plans.Plan.load("absent.json"), 12, threshold)
    cap = facts["capacite_sous_le_seuil"]
    sign = 1 if cap["sens"] == "marge" else -1
    ends = [m["solde_fin"] for m in facts["par_mois"]]
    assert all(end - sign * cap["par_mois"] * k >= threshold - 0.01
               for k, end in enumerate(ends, 1))
    if sign > 0:
        assert any(end - (cap["par_mois"] + 10) * k < threshold for k, end in enumerate(ends, 1))
    assert table["columns"][2] == "Épargne versée"


def _floor_answer(floor):
    return {"supported": True, "name": "", "note": "", "floor": floor, "changes": []}


def test_a_cash_floor_becomes_the_adjustment_the_app_computes(app, model):
    """« Et si je ne veux pas descendre sous 15k ? » is not a line of the
    plan; what keeps the plan above it is, and the app works it out."""
    from pms import assist, plans
    path = app.extensions["pms_store"].path.with_name("plans.json")
    plan = plans.Plan.load(path)
    statement = app.extensions["pms_store"].statement
    # Starting in a few months, as on the real plan: a reduction then runs
    # over fewer months, which a formula from "now" got wrong.
    later = plans.month_key(plans._add_months(statement.period_end, 4))
    plan.add_contribution(plans.TAXABLE, 2500.0, "month", 450, later)
    # A large bill in six months: the low point lies ahead, not today.
    plan.add_one_off(plans.month_key(plans._add_months(statement.period_end, 6)), "Voyage", 30_000.0)
    plan.save()
    low = assist.forecast_facts(statement, plan, 12, None)[0]["point_bas"]["montant"]
    with app.test_client() as c:
        # A little short: the monthly transfer gives it back.
        model.answers["modifications d'un plan"] = _floor_answer(low + 500)
        short = _post(c, "/api/ai/scenario", {"sentence": "jamais sous ce plancher"}).get_json()
        assert short.get("supported"), short
        assert "sous ton plancher" in short["floor_note"]
        assert short["lever"] == short["options"][0]["id"] and short["options"][0]["feasible"]
        assert [ch["action"] for ch in short["changes"]] == ["contrib-del", "contrib"]
        assert short["changes"][0]["rows"][0]["remove"]
        assert short["scenario"]["low"]["amount"] >= low + 500 - 0.01
        assert short["floor"] == low + 500

        # Far beyond what the plan can hold: said, not faked.
        model.answers["modifications d'un plan"] = _floor_answer(low + 10_000_000)
        far = _post(c, "/api/ai/scenario", {"sentence": "jamais sous 10 millions"}).get_json()
        assert not far["supported"] and ("pas tenable" in far["note"] or "déjà sous" in far["note"])

        # Room to spare: that much more to the investment pocket.
        model.answers["modifications d'un plan"] = _floor_answer(1000)
        room = _post(c, "/api/ai/scenario", {"sentence": "jamais sous 1k"}).get_json()
        assert room["supported"] and room["changes"][0]["action"] == "contrib"
        assert room["scenario"]["low"]["amount"] >= 1000 - 0.01


def test_a_payee_without_suggestion_can_be_asked_again(app, model):
    answers = iter([None, "Loisirs & voyages"])
    model.answers["classes des commerçants"] = lambda req: {"suggestions": [
        {"id": c["id"], "category": cat, "subcategory": "", "confidence": "moyenne",
         "why": "camping"} for c in req["commercants"] for cat in [next(answers)]]}
    with app.test_client() as c:
        first = _post(c, "/api/ai/merchants", {}).get_json()["payees"][0]
        assert first["suggestion"]["category"] is None
        again = _post(c, "/api/ai/merchants", {"retry": [first["label"]]}).get_json()["payees"][0]
    assert again["suggestion"]["category"] == "Loisirs & voyages"
    assert len(model.sent) == 2


def test_a_floor_is_held_by_the_spend_when_there_is_no_monthly_transfer(app, model):
    """The "Loyer 1'960" plan: a declared monthly spend, no monthly transfer,
    a floor just above the low point. It read "not tenable": the search's
    far end was itself refused."""
    from pms import assist, plans
    path = app.extensions["pms_store"].path.with_name("plans.json")
    plan = plans.Plan.load(path)
    statement = app.extensions["pms_store"].statement
    plan.spend = 4510.0
    plan.add_one_off(plans.month_key(plans._add_months(statement.period_end, 6)), "Voyage", 30_000.0)
    plan.save()
    low = assist.forecast_facts(statement, plan, 12, None)[0]["point_bas"]["montant"]
    model.answers["modifications d'un plan"] = _floor_answer(round(low + 1200, -2))
    with app.test_client() as c:
        r = _post(c, "/api/ai/scenario", {"sentence": "jamais sous ce plancher"}).get_json()
    assert r.get("supported"), r
    assert [ch["action"] for ch in r["changes"]] == ["spend"]
    assert r["scenario"]["low"]["amount"] >= round(low + 1200, -2) - 0.01


def test_the_floor_can_be_held_by_the_lever_chosen(app, model):
    """More finesse than "the largest transfer": each transfer, the monthly
    spend, each one-off ahead is offered, and the amount is found for the
    one chosen -- here, a trip made cheaper."""
    from pms import assist, plans
    path = app.extensions["pms_store"].path.with_name("plans.json")
    plan = plans.Plan.load(path)
    statement = app.extensions["pms_store"].statement
    trip = plans.month_key(plans._add_months(statement.period_end, 6))
    plan.add_contribution(plans.TAXABLE, 2500.0, "month", 450, "")
    plan.add_one_off(trip, "Voyage", 30_000.0)
    plan.save()
    low = assist.forecast_facts(statement, plan, 12, None)[0]["point_bas"]["montant"]
    model.answers["modifications d'un plan"] = _floor_answer(round(low + 2000, -2))
    with app.test_client() as c:
        auto = _post(c, "/api/ai/scenario", {"sentence": "plancher"}).get_json()
        ids = [o["id"] for o in auto["options"]]
        assert ids[0].startswith("contrib:") and "spend" in ids and f"oneoff:{trip}|Voyage" in ids
        # Every option priced at once, each one checked to hold on its own.
        for o in auto["options"]:
            if o["feasible"]:
                one = _post(c, "/api/ai/scenario", {"sentence": "plancher", "lever": o["id"]}).get_json()
                assert one["lever"] == o["id"]
                assert one["scenario"]["low"]["amount"] >= round(low + 2000, -2) - 0.01
        voyage = next(o for o in auto["options"] if o["id"] == f"oneoff:{trip}|Voyage")
        assert "au lieu de 30’000" in voyage["text"] or "au lieu de 30'000" in voyage["text"]
        r = _post(c, "/api/ai/scenario", {"sentence": "plancher", "lever": f"oneoff:{trip}|Voyage"}).get_json()
    assert r["lever"] == f"oneoff:{trip}|Voyage"
    assert [ch["action"] for ch in r["changes"]] == ["amount"]
    assert r["changes"][0]["amount"] < 30_000
    assert r["scenario"]["low"]["amount"] >= round(low + 2000, -2) - 0.01


def test_a_search_shows_what_it_found_even_without_a_category(monkeypatch, tmp_path):
    """« Redemander » with DeepSeek: the search ran, the model still did not
    decide. The answer says so, with the pages, rather than the same "no
    suggestion" read as if the button had done nothing."""
    from pms import ai, assist
    config = ai.Config(provider="deepseek", model="deepseek-flash", base_url="https://api.deepseek.com",
                       key="sk-x", effort="", folder=tmp_path)
    monkeypatch.setattr(ai, "search_snippets", lambda config, query: [
        {"titre": "Camping du lac", "url": "https://camp.example", "extrait": "camping"}] if "Camp" in query else [])
    monkeypatch.setattr(ai, "ask_json", lambda *a, **k: {"suggestions": [
        {"id": 0, "category": None, "subcategory": "", "confidence": "basse", "why": ""},
        {"id": 1, "category": None, "subcategory": "", "confidence": "basse", "why": ""}]})
    payees = [{"label": "Guillermo Camp", "location": "Bulle, Suisse", "kind": "carte", "count": 1, "median": 40},
              {"label": "XYZ SA", "location": "", "kind": "carte", "count": 1, "median": 10}]
    found = assist.suggest_merchants(config, payees, {"categories": ["Loisirs & voyages"], "subcategories": {}})
    assert found["Guillermo Camp"]["searched"] == 1
    assert found["Guillermo Camp"]["pages"] == [{"titre": "Camping du lac", "url": "https://camp.example"}]
    assert found["XYZ SA"]["searched"] == 0 and found["XYZ SA"]["category"] is None


def test_a_payment_without_a_place_is_searched_where_the_card_was_that_day():
    """Revolut prints no place: "Guillermo Camp" alone found a footballer.
    The town comes from the card payments around the same day."""
    import datetime as dt

    from pms import assist
    from pms.models import Statement, Transaction

    def card(day, label, location=""):
        return Transaction(date=dt.date(2024, 10, day), reference=f"r{day}{label}", currency="CHF",
                           amount=-20.0, value_date=None, balance=None,
                           kind="Paiement par carte - se terminant par 0000",
                           merchant=label, location=location)

    rows = [card(25, "Coop", "Rue 1, 1630 Bulle, Suisse"), card(26, "Guillermo Camp")]
    statement = Statement(holder="", iban="", client_number="", period_start=dt.date(2024, 10, 1),
                          period_end=dt.date(2024, 10, 31), generated_on=None, reference_currency="CHF",
                          accounts=[], transactions=rows)
    for t in rows:
        t.category = "Non catégorisé" if t.merchant == "Guillermo Camp" else "Alimentation"
    payees, _ = assist.uncategorised_payees(statement)
    camp = next(p for p in payees if p["label"] == "Guillermo Camp")
    assert camp["near"] == "Bulle"
    assert assist.search_query(camp) == '"Guillermo Camp" Bulle'


def test_the_settings_say_what_became_of_the_proposed_categories(app, model):
    """Kept, changed, still open -- read from the ledger, not from clicks."""
    model.answers["classes des commerçants"] = lambda req: {"suggestions": [
        {"id": c["id"], "category": "Shopping", "subcategory": "", "confidence": "moyenne",
         "why": ""} for c in req["commercants"]]}
    with app.test_client() as c:
        (payee,) = _post(c, "/api/ai/merchants", {}).get_json()["payees"]
        assert c.get("/api/ai/settings").get_json()["merchants"]["open"] == 1

        def choose(category):
            r = _post(c, "/api/reclassify", {"key": payee["key"], "scope": "merchant",
                                             "category": category})
            assert r.status_code == 200
            return c.get("/api/ai/settings").get_json()["merchants"]

        changed = choose("Loisirs & voyages")
        assert (changed["kept"], changed["changed"], changed["open"]) == (0, 1, 0)
        assert changed["examples"] == [{"label": payee["label"], "proposed": "Shopping",
                                        "chosen": "Loisirs & voyages"}]
        kept = choose("Shopping")
        assert (kept["kept"], kept["changed"]) == (1, 0)


def test_the_savings_are_explained_from_the_pocket_figures(app, model):
    """Versements against markets, from the figures the savings page shows;
    a number the model adds up itself is caught."""
    from webhelpers import savings_snapshots
    with app.test_client() as c:
        savings_snapshots(c)
        q = "/api/ai/savings?preset=all"
        assert c.get(q).get_json()["answer"] is None

        def answer(req):
            ibkr = next(p for p in req["poches"] if p["poche"] == "IBKR")
            return {"text": f"IBKR a reçu {ibkr['verse']:.0f} CHF de versements ; "
                            f"les marchés ont ajouté {ibkr['gain_marche']:.0f} CHF."}
        model.answers["ce qui a fait bouger l'épargne"] = answer
        done = _post(c, q, {}).get_json()["answer"]
        assert "IBKR a reçu" in done["text"]
        # Kept: a reload reads it back without asking again.
        assert c.get(q).get_json()["answer"] == done and len(model.sent) == 1

        model.answers["ce qui a fait bouger l'épargne"] = {"text": "En tout 123456 CHF."}
        r = _post(c, q, {"again": True})
        assert r.status_code >= 400


def test_a_question_on_the_investments_gets_the_pocket_table(app, model):
    from webhelpers import savings_snapshots
    model.answers["traduis une question"] = {
        "supported": True, "focus": "placements", "from": "2025-01-01", "to": "2026-06-30",
        "compare_from": None, "compare_to": None, "category": None, "search": None,
        "threshold": None, "months": None, "note": ""}
    model.answers["réponds à une question"] = lambda req: {
        "answer": "Le détail par poche est sous la réponse.", "follow_ups": []}
    with app.test_client() as c:
        savings_snapshots(c)
        r = _post(c, "/api/ai/ask", {"question": "combien ont rapporté mes placements ?"}).get_json()
    assert r["supported"] and r["focus"] == "placements" and r["view"]["path"] == "/epargne"
    assert r["table"]["columns"][:3] == ["", "Valeur", "Versé"]
    assert "IBKR" in [row[0] for row in r["table"]["rows"]]


def test_a_market_hypothesis_is_previewed_never_applied(app, model):
    """A sentence becomes a barème shown with the app's own arithmetic; the
    plan does not change until the page posts it."""
    model.answers["hypothèse de marché"] = {
        "supported": True, "name": "Krach puis reprise", "note": "", "source": "phrase",
        "segments": [{"months": 12, "rate_pct": -30}, {"months": 60, "rate_pct": 6}],
        "vol_pct": 18, "horizon_months": 120}
    path = app.extensions["pms_store"].path.with_name("plans.json")
    with app.test_client() as c:
        r = _post(c, "/api/ai/rates", {"sentence": "un krach de 30 % l'an prochain puis 6 % par an, vol 18 %, sur 10 ans"}).get_json()
    assert r["supported"] and r["segments"] == [{"months": 12, "rate": -0.3}, {"months": 60, "rate": 0.06}]
    assert (r["vol"], r["horizon"]) == (0.18, 120)
    assert r["path"]["months"] == 120 and r["path"]["low"] == pytest.approx(0.7, abs=0.01)
    assert r["current"]["end"] == 1.0  # no barème yet: a franc stays a franc
    assert not path.exists()


def test_a_market_hypothesis_out_of_bounds_is_refused(app, model):
    model.answers["hypothèse de marché"] = {
        "supported": True, "name": "Fou", "note": "", "source": "propose",
        "segments": [{"months": 12, "rate_pct": 300}], "vol_pct": None, "horizon_months": None}
    with app.test_client() as c:
        r = _post(c, "/api/ai/rates", {"sentence": "300 % par an"})
    assert r.status_code == 422 and "bornes" in r.get_json()["note"]
