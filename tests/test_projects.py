"""Projects: movements gathered under a name, at their net cost, and the
stays abroad proposed as projects."""

from __future__ import annotations

import pytest

from pms import projects
from webhelpers import api

ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture
def clean(client):
    path = client.application.extensions["pms_store"].path.with_name("projects.json")
    path.unlink(missing_ok=True)
    yield client
    path.unlink(missing_ok=True)


def test_each_stay_abroad_is_proposed_with_its_bookings_and_paybacks(client):
    held = client.application.extensions["pms_store"].statement
    found = {s["name"]: s for s in projects.suggestions(held, set())}
    assert set(found) == {"Espagne, août 2024", "Italie, juillet 2025", "France, mars 2026"}
    italy = found["Italie, juillet 2025"]
    assert italy["net"] == pytest.approx(italy["spent"] - italy["back"])
    # Proposed once: a stay already in a project is not offered again.
    again = {s["name"] for s in projects.suggestions(held, set(italy["keys"][:1]))}
    assert "Italie, juillet 2025" not in again and "Espagne, août 2024" in again


def test_create_add_remove_and_undo(clean):
    s = api(clean, "/api/projets")["suggestions"][0]
    r = clean.post("/api/projets", json={"action": "create", "name": s["name"], "keys": s["keys"]}, headers=ORIGIN)
    created = r.get_json()
    a = api(clean, "/api/projets")
    assert [p["name"] for p in a["projects"]] == [s["name"]]
    assert a["projects"][0]["net"] == s["net"]
    assert s["name"] not in {x["name"] for x in a["suggestions"]}

    detail = api(clean, f"/api/projets?p={created['id']}")["detail"]
    assert len(detail["rows"]) == s["count"] and detail["candidates"]
    extra = detail["candidates"][0]["key"]
    r = clean.post("/api/projets", json={"action": "add", "id": created["id"], "keys": [extra]}, headers=ORIGIN)
    assert api(clean, f"/api/projets?p={created['id']}")["detail"]["count"] == s["count"] + 1
    clean.post("/api/projets", json=r.get_json()["undo"], headers=ORIGIN)
    assert api(clean, f"/api/projets?p={created['id']}")["detail"]["count"] == s["count"]

    r = clean.post("/api/projets", json={"action": "delete", "id": created["id"]}, headers=ORIGIN)
    assert api(clean, "/api/projets")["projects"] == []
    clean.post("/api/projets", json=r.get_json()["undo"], headers=ORIGIN)
    assert [p["name"] for p in api(clean, "/api/projets")["projects"]] == [s["name"]]


def test_a_project_needs_a_name_and_an_existing_id(clean):
    assert clean.post("/api/projets", json={"action": "create", "name": " "}, headers=ORIGIN).status_code == 400
    assert clean.post("/api/projets", json={"action": "add", "id": "nope", "keys": []}, headers=ORIGIN).status_code == 404


def test_names_make_distinct_ids(tmp_path):
    book = projects.Projects(tmp_path / "p.json")
    assert book.create("Déménagement", [])["id"] == "demenagement"
    assert book.create("Déménagement", [])["id"] == "demenagement-2"


def test_the_sheet_lists_projects_and_membership(clean):
    s = api(clean, "/api/projets")["suggestions"][0]
    clean.post("/api/projets", json={"action": "create", "name": "Voyage", "keys": s["keys"]}, headers=ORIGIN)
    inside = api(clean, f"/api/projets/liste?key={s['keys'][0]}")["projects"]
    assert inside == [{"id": "voyage", "name": "Voyage", "member": True}]
    assert api(clean, "/api/projets/liste?key=nope")["projects"][0]["member"] is False


def test_a_trip_lasts_its_own_days_not_its_booking(clean):
    italy = next(s for s in api(clean, "/api/projets")["suggestions"] if s["name"].startswith("Italie"))
    r = clean.post("/api/projets", json={"action": "create", "name": "Italie", "keys": italy["keys"]}, headers=ORIGIN)
    p = api(clean, f"/api/projets?p={r.get_json()['id']}")["detail"]
    assert (p["start"], p["end"], p["days"]) == ("2025-07-12", "2025-07-19", 8)
    assert p["per_day"] == pytest.approx(p["net"] / 8, abs=0.01)


def _card(day, merchant, country, amount, category, sub=""):
    import datetime as dt

    from pms.models import Transaction
    t = Transaction(date=dt.date.fromisoformat(day), reference=f"77{merchant[:3]}{day}", currency="CHF",
                    amount=-amount, value_date=None, balance=None,
                    kind="Paiement par carte - se terminant par 1234", merchant=merchant,
                    location=f"Somewhere 1, {country}")
    t.amount_chf, t.category, t.subcategory = -amount, category, sub
    return t


def test_websites_billing_from_abroad_are_not_a_trip(client):
    import copy
    held = client.application.extensions["pms_store"].statement
    statement = copy.copy(held)
    statement.transactions = [*held.transactions,
                              _card("2025-10-18", "SHOP.EXAMPLE.COM", "Etats-Unis", 40, "Shopping", "En ligne & marketplaces"),
                              _card("2025-10-19", "APPSTORE EXAMPLE", "Pays-Bas", 9, "Télécom & abonnements"),
                              _card("2025-10-20", "GAMES EXAMPLE", "Etats-Unis", 15, "Télécom & abonnements")]
    names = {s["name"] for s in projects.suggestions(statement, set())}
    assert not any("Etats-Unis" in n or "Pays-Bas" in n for n in names)


def test_each_proposed_line_says_why(client):
    held = client.application.extensions["pms_store"].statement
    italy = next(s for s in projects.suggestions(held, set()) if s["name"].startswith("Italie"))
    reasons = {r["reason"].split(" ")[0] for r in italy["rows"]}
    assert reasons == {"sur", "réservé", "reçu"}
    assert "paiements sur place" in italy["why"]


def test_a_dismissed_stay_is_not_proposed_again(clean):
    s = api(clean, "/api/projets")["suggestions"][0]
    r = clean.post("/api/projets", json={"action": "dismiss", "id": s["id"]}, headers=ORIGIN).get_json()
    assert s["id"] not in {x["id"] for x in api(clean, "/api/projets")["suggestions"]}
    clean.post("/api/projets", json=r["undo"], headers=ORIGIN)
    assert s["id"] in {x["id"] for x in api(clean, "/api/projets")["suggestions"]}


def test_settling_up_after_the_trip_is_proposed(client):
    import copy
    import datetime as dt

    from pms.models import Transaction
    held = client.application.extensions["pms_store"].statement
    statement = copy.copy(held)

    def move(day, kind, amount, category, sub, merchant=""):
        t = Transaction(date=dt.date.fromisoformat(day), reference=f"88{day}{amount}", currency="CHF",
                        amount=amount, value_date=None, balance=None, kind=kind, merchant=merchant)
        t.amount_chf, t.category, t.subcategory = amount, category, sub
        return t
    statement.transactions = [*held.transactions,
                              move("2025-07-26", "Paiement Twint", -240.0, "Twint non identifié", "Twint envoyé"),
                              move("2025-07-24", "Paiement Twint", -30.0, "Twint non identifié", "Twint envoyé"),
                              move("2025-07-23", "Paiement entrant", 120.0, "Revenus", "Virement entrant", "Léa Exemple")]
    italy = next(s for s in projects.suggestions(statement, set()) if s["name"].startswith("Italie"))
    why = {r["amount"]: r["reason"] for r in italy["rows"]}
    assert "Tricount" in why[-240.0] and -30.0 not in why
    assert "remboursée" in why[120.0]
    # The salary paid on the 25th is not a share paid back.
    assert not any(r["label"] == "Alpha Conseil SA" for r in italy["rows"])
