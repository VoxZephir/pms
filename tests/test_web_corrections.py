"""Manual corrections: reclassifying a row or its payee, undoing it, the
personal rules file, the merges (`/api/reclassify*`, `/api/corrections`)."""

from __future__ import annotations

import json

import pytest
from webhelpers import corrected_ledger


@pytest.fixture
def app(tmp_path_factory, ledger_file):
    """A private ledger copy: every test here writes corrections."""
    from pms.web import create_app
    workdir = tmp_path_factory.mktemp("corrections")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())
    return create_app(ledger_copy)


def _first_key(c) -> str:
    return c.get("/api/transactions?preset=all&per=20").get_json()["rows"][0]["key"]


def _rules(app):
    return app.extensions["pms_store"].path.with_name("local_rules.json")


def test_a_bucket_only_correction_shows_on_the_row(app):
    """Reclassifying Need/Want/Save leaves the category untouched, so the row
    says it was corrected, or the change looks like it did nothing."""
    with app.test_client() as c:
        key = _first_key(c)
        assert c.post("/api/reclassify", json={"key": key, "scope": "pin",
                                               "bucket": "Need"}).status_code == 200
        row = next(r for r in c.get("/api/transactions?preset=all&per=20").get_json()["rows"]
                   if r["key"] == key)
        assert row["overridden"] and row["bucket"] == "Need"


def test_a_pinned_row_moves_when_its_merchant_is_reclassified(app):
    """Pinned to "Non catégorisé", then reclassified with its payee (a rule):
    the row lands in Restaurants, and "Annuler" gives back the pin."""
    from pms.overrides import key_of
    data = app.extensions["pms_store"]

    def category_of(key):
        return next(t.category for t in data.statement.transactions if key_of(t) == key)

    target = next(t for t in data.statement.transactions
                  if t.label and t.category != "Restaurants & bars" and t.amount < 0)
    key = key_of(target)
    with app.test_client() as c:
        c.post("/api/reclassify", json={"key": key, "scope": "pin", "category": "Non catégorisé"})
        assert category_of(key) == "Non catégorisé"
        answer = c.post("/api/reclassify", json={"key": key, "scope": "merchant",
                                                 "category": "Restaurants & bars"}).get_json()
        assert category_of(key) == "Restaurants & bars"
        c.post("/api/reclassify/undo", json=answer["undo"])
        assert category_of(key) == "Non catégorisé"
        assert not [r for r in data.overrides.rules if r["match"] == target.label]


def test_reclassify_rejects_an_empty_target(client):
    key = _first_key(client)
    assert client.post("/api/reclassify", json={"key": key, "scope": "pin"}).status_code == 400


def test_a_bulk_correction_of_the_whole_filter_and_its_undo(app):
    """Everything matching the filter, across pages, as the screen counted it."""
    with app.test_client() as c:
        listed = c.get("/api/transactions?preset=all&q=coop").get_json()["total"]
        answer = c.post("/api/reclassify/bulk", json={
            "preset": "all", "q": "coop", "scope_all": 1,
            "to_bucket": "Want", "apply_as": "pin"}).get_json()
        assert answer["count"] == listed
        rows = c.get("/api/transactions?preset=all&q=coop&per=60").get_json()["rows"]
        assert {r["bucket"] for r in rows} == {"Want"}
        c.post("/api/reclassify/bulk/undo", json=answer["undo"])
        assert c.get("/api/corrections").get_json()["total"] == 0


def test_the_corrections_list_every_kind(tmp_path_factory, ledger_file):
    app = corrected_ledger(tmp_path_factory, ledger_file, pins=12)
    with app.test_client() as c:
        data = c.get("/api/corrections").get_json()
    kinds = [e["kind"] for e in data["entries"]]
    assert kinds.count("pin") == 12 and kinds.count("rule") == 2 and kinds.count("alias") == 1
    assert data["total"] == 15


def test_a_correction_is_removed_by_kind(tmp_path_factory, ledger_file):
    app = corrected_ledger(tmp_path_factory, ledger_file, pins=2)
    with app.test_client() as c:
        entries = c.get("/api/corrections").get_json()["entries"]
        for entry in entries:
            assert c.post("/api/corrections", json={"action": "delete", **entry}).status_code == 200
        assert c.get("/api/corrections").get_json()["total"] == 0


def test_two_spellings_merge_and_a_chain_merges_by_prefix(app):
    with app.test_client() as c:
        assert c.post("/api/corrections", json={"action": "merge", "variant": "Coop-1234 Carouge",
                                                "canonical": "Coop"}).status_code == 200
        assert c.post("/api/corrections", json={"action": "merge", "prefix": "Migros",
                                                "canonical": "Migros"}).status_code == 200
        assert c.post("/api/corrections", json={"action": "merge", "canonical": "Coop"}).status_code == 400
        aliases = [e for e in c.get("/api/corrections").get_json()["entries"] if e["kind"] == "alias"]
    assert len(aliases) == 2


# --- personal rules (data/local_rules.json) ------------------------------------

def test_the_personal_rules_are_listed_from_the_file(app):
    _rules(app).write_text(json.dumps([
        {"category": "Revenus", "subcategory": "Salaire / clients", "pattern": "Employeur Test"},
        {"category": "Logement", "subcategory": "Loyer / régie", "pattern": "Regie Test"},
    ], ensure_ascii=False), encoding="utf-8")
    with app.test_client() as c:
        rules = c.get("/api/corrections").get_json()["local_rules"]
    assert [r["pattern"] for r in rules] == ["Employeur Test", "Regie Test"]


def test_an_invalid_pattern_is_refused_and_the_file_untouched(app):
    original = json.dumps([{"category": "Revenus", "subcategory": "", "pattern": "Employeur Test"}])
    _rules(app).write_text(original, encoding="utf-8")
    with app.test_client() as c:
        response = c.post("/api/corrections", json={"action": "lr-add", "pattern": "(",
                                                    "category": "Revenus", "subcategory": ""})
    assert response.status_code == 400
    assert response.get_json()["errors"]["lr-pattern"].startswith("Motif invalide")
    assert _rules(app).read_text(encoding="utf-8") == original


def test_a_pattern_that_matches_everything_is_refused(app):
    """`|` and `a*` compile but match the empty string, hence every
    transaction: one keystroke would reclassify the whole ledger."""
    _rules(app).write_text("[]", encoding="utf-8")
    with app.test_client() as c:
        for evil in ("|", "a*", ".*", "()"):
            response = c.post("/api/corrections", json={"action": "lr-add", "pattern": evil,
                                                        "category": "Logement"})
            assert "chaîne vide" in response.get_json()["errors"]["lr-pattern"], evil
    assert _rules(app).read_text(encoding="utf-8").strip() == "[]"


def test_a_personal_rule_needs_a_known_category(app):
    with app.test_client() as c:
        missing = c.post("/api/corrections", json={"action": "lr-add", "pattern": "Employeur Test",
                                                   "category": ""}).get_json()
        assert missing["errors"]["lr-category"] == "La catégorie est requise."
        unknown = c.post("/api/corrections", json={"action": "lr-add", "pattern": "Employeur Test",
                                                   "category": "Catégorie Inventée"}).get_json()
        assert unknown["errors"]["lr-category"] == "Catégorie inconnue."
    assert not _rules(app).exists()


def test_a_personal_rule_is_added_and_removed(app):
    rule = {"category": "Revenus", "subcategory": "Salaire / clients", "pattern": "Employeur Test"}
    with app.test_client() as c:
        assert c.post("/api/corrections", json={"action": "lr-add", **rule}).status_code == 200
        assert rule in json.loads(_rules(app).read_text(encoding="utf-8"))
        assert c.post("/api/corrections", json={"action": "lr-delete", **rule}).status_code == 200
    assert json.loads(_rules(app).read_text(encoding="utf-8")) == []


def test_the_store_fingerprint_tracks_the_local_rules_file(tmp_path):
    """An edit to the personal rules must reload the statement on the next
    request: the fingerprint watches data/local_rules.json like the ledger."""
    from pms.web.store import Store

    store = Store(tmp_path / "ledger.json")
    before = store._fingerprint()
    (tmp_path / "local_rules.json").write_text("[]", encoding="utf-8")
    assert store._fingerprint() != before


def test_a_rule_is_edited_in_place_and_the_edit_undone(tmp_path_factory, ledger_file):
    """An edit keeps the rule's reach; its undo puts the old category back.
    A delete answers with the body that restores it, and a merge with the
    one that removes it."""
    import shutil

    from pms.web import create_app
    work = tmp_path_factory.mktemp("edit") / "ledger.json"
    shutil.copy(ledger_file, work)
    c = create_app(work).test_client()
    H = {"Origin": "http://localhost"}
    store_ = c.application.extensions["pms_store"]
    store_.overrides.rule("Coop City Neuchâtel", category="Shopping")
    store_.overrides.save()
    store_.invalidate()

    r = c.post("/api/corrections", json={"action": "edit", "kind": "rule", "match": "Coop City Neuchâtel",
                                         "mode": "exact", "category": "Loisirs & voyages"}, headers=H)
    assert r.status_code == 200
    undo = r.get_json()["undo"]
    rules = c.get("/api/corrections").get_json()["entries"]
    assert next(e for e in rules if e["match"] == "Coop City Neuchâtel")["category"] == "Loisirs & voyages"
    assert c.post("/api/corrections", json=undo, headers=H).status_code == 200
    rules = c.get("/api/corrections").get_json()["entries"]
    assert next(e for e in rules if e["match"] == "Coop City Neuchâtel")["category"] == "Shopping"

    r = c.post("/api/corrections", json={"action": "delete", "kind": "rule", "match": "Coop City Neuchâtel",
                                         "mode": "exact"}, headers=H)
    assert not any(e["kind"] == "rule" for e in c.get("/api/corrections").get_json()["entries"])
    c.post("/api/corrections", json=r.get_json()["undo"], headers=H)
    assert any(e["kind"] == "rule" for e in c.get("/api/corrections").get_json()["entries"])

    r = c.post("/api/corrections", json={"action": "merge", "prefix": "Coop", "canonical": "Coop"}, headers=H)
    data = c.get("/api/corrections").get_json()
    assert not any(h["canonical"] == "Coop" for h in data["merges"])
    c.post("/api/corrections", json=r.get_json()["undo"], headers=H)
    assert not any(e["kind"] == "alias" for e in c.get("/api/corrections").get_json()["entries"])
    assert c.post("/api/corrections", json={"action": "edit", "kind": "rule", "match": "nobody",
                                            "category": "Shopping"}, headers=H).status_code == 404
