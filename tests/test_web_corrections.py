"""Manual corrections: drop targets, the personal rules file, /reclasser."""

from __future__ import annotations

import re

from webhelpers import corrected_ledger, text

# --- the drop palette -------------------------------------------------------

def test_every_category_drop_zone_carries_its_name(client):
    """A dropzone with an empty data-drop-category posts nothing and the API
    answers "rien a appliquer" -- which is exactly what a name collision between
    the filter's category list and by_category() produced."""
    body = text(client.get("/?preset=all"))
    zones = re.findall(r'<button class="dropzone" data-drop-category="([^"]*)"', body)
    assert zones, "the palette must offer category targets"
    assert all(zones), f"{zones.count('')} drop zones have no category"


def test_bucket_drop_zones_are_present(client):
    body = text(client.get("/?preset=all"))
    buckets_found = re.findall(r'data-drop-bucket="([^"]+)"', body)
    for name in ("Need", "Want", "Save", "Non classé"):
        assert name in buckets_found


def test_drop_zone_colours_resolve(client):
    """`var(--s)` means the slot was missing; the swatch renders invisible."""
    body = text(client.get("/?preset=all"))
    assert "var(--s)" not in body


def test_a_bucket_only_correction_is_visible_in_the_table(client, ledger_file,
                                                          tmp_path_factory):
    """Reclassifying Need/Want/Save leaves the category cell untouched, so the
    bucket has to be shown or the change looks like it did nothing."""
    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("bucketview")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())

    app = create_app(ledger_copy)
    with app.test_client() as c:
        first = re.search(r'data-key="([^"]+)"',
                          c.get("/?preset=all").get_data(as_text=True)).group(1)
        response = c.post("/api/reclassify",
                          json={"key": first, "scope": "pin", "bucket": "Need"},
                          headers={"Accept": "application/json"})
        assert response.status_code == 200
        body = c.get("/?preset=all").get_data(as_text=True)
        assert 'class="chip ovr"' in body
        assert "is-overridden" in body


def test_reclassify_rejects_an_empty_target(client):
    body = text(client.get("/?preset=all"))
    key = re.search(r'data-key="([^"]+)"', body).group(1)
    response = client.post("/api/reclassify",
                           json={"key": key, "scope": "pin"},
                           headers={"Accept": "application/json"})
    assert response.status_code == 400


def test_the_corrections_table_is_sortable_once_it_has_rows(tmp_path_factory,
                                                            ledger_file):
    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("rulessort")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())

    app = create_app(ledger_copy)
    with app.test_client() as c:
        assert "Aucune correction" in c.get("/reclasser").get_data(as_text=True)

        key = re.search(r'data-key="([^"]+)"',
                        c.get("/?preset=all").get_data(as_text=True)).group(1)
        c.post("/api/reclassify",
               json={"key": key, "scope": "pin", "bucket": "Need"},
               headers={"Accept": "application/json"})
        assert "sortable-table" in c.get("/reclasser").get_data(as_text=True)


# --- personal rules (data/local_rules.json) --------------------------------

def test_local_rules_section_lists_the_personal_rules(tmp_path_factory,
                                                      ledger_file):
    """The Corrections page edits data/local_rules.json: the section is
    titled and the current rules are listed from the file."""
    import json as _json

    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("localrules")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())
    (workdir / "local_rules.json").write_text(_json.dumps([
        {"category": "Revenus", "subcategory": "Salaire / clients",
         "pattern": "Employeur Test"},
        {"category": "Logement", "subcategory": "Loyer / régie",
         "pattern": "Regie Test"},
    ], ensure_ascii=False, indent=1), encoding="utf-8")

    app = create_app(ledger_copy)
    with app.test_client() as c:
        body = text(c.get("/reclasser"))
        assert "Règles personnelles" in body
        assert "data/local_rules.json" in body
        assert "gitignoré" in body
        assert "Employeur Test" in body
        assert "Regie Test" in body
        assert "Salaire / clients" in body


def test_local_rules_invalid_pattern_rerenders_and_keeps_the_value(
        tmp_path_factory, ledger_file):
    """An unterminated regex is not silently dropped: the page comes back
    with the error stated, the typed pattern kept, and the file untouched."""
    import json as _json

    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("lrinvalid")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())
    rules_path = workdir / "local_rules.json"
    original = _json.dumps([
        {"category": "Revenus", "subcategory": "", "pattern": "Employeur Test"},
    ], ensure_ascii=False, indent=1)
    rules_path.write_text(original, encoding="utf-8")

    app = create_app(ledger_copy)
    with app.test_client() as c:
        response = c.post("/reclasser", data={
            "action": "lr-add", "pattern": "(", "category": "Revenus",
            "subcategory": "Salaire / clients"})
        body = text(response)
        assert response.status_code == 200
        assert "Vérifiez les champs suivants" in body
        assert "Motif invalide" in body
        assert 'href="#lr-pattern"' in body
        field = re.search(r'<input[^>]*id="lr-pattern"[^>]*>', body).group(0)
        assert 'aria-invalid="true"' in field
        assert 'value="("' in field
        assert rules_path.read_text(encoding="utf-8") == original


def test_local_rules_reject_a_pattern_that_matches_everything(
        tmp_path_factory, ledger_file):
    """`|` and `a*` compile fine but match the empty string, hence every
    transaction: one keystroke would silently reclassify the whole ledger
    into a single category. The page must refuse them."""
    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("lrempty")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())
    rules_path = workdir / "local_rules.json"
    rules_path.write_text("[]", encoding="utf-8")

    app = create_app(ledger_copy)
    with app.test_client() as c:
        for evil in ("|", "a*", ".*", "()"):
            response = c.post("/reclasser", data={
                "action": "lr-add", "pattern": evil,
                "category": "Logement", "subcategory": ""})
            body = text(response)
            assert response.status_code == 200, evil
            assert "ne doit pas matcher une chaîne vide" in body, evil
        assert rules_path.read_text(encoding="utf-8").strip() == "[]"


def test_local_rules_require_a_known_category(tmp_path_factory, ledger_file):
    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("lrcategory")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())

    app = create_app(ledger_copy)
    with app.test_client() as c:
        body = text(c.post("/reclasser", data={
            "action": "lr-add", "pattern": "Employeur Test",
            "category": "", "subcategory": ""}))
        assert "La catégorie est requise." in body
        assert 'href="#lr-category"' in body
        assert not (workdir / "local_rules.json").exists()

        body = text(c.post("/reclasser", data={
            "action": "lr-add", "pattern": "Employeur Test",
            "category": "Catégorie Inventée", "subcategory": ""}))
        assert "Catégorie inconnue." in body
        assert not (workdir / "local_rules.json").exists()


def test_local_rules_add_persists_and_redirects(tmp_path_factory, ledger_file):
    """A valid rule is written next to the ledger and the page redirects
    (PRG) -- the next render lists it."""
    import json as _json

    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("lradd")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())

    app = create_app(ledger_copy)
    with app.test_client() as c:
        response = c.post("/reclasser", data={
            "action": "lr-add", "pattern": "Employeur Test",
            "category": "Revenus", "subcategory": "Salaire / clients"})
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/reclasser")

        payload = _json.loads(
            (workdir / "local_rules.json").read_text(encoding="utf-8"))
        assert {"category": "Revenus", "subcategory": "Salaire / clients",
                "pattern": "Employeur Test"} in payload
        assert "Employeur Test" in text(c.get("/reclasser"))


def test_local_rules_delete_removes_the_rule(tmp_path_factory, ledger_file):
    import json as _json

    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("lrdelete")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())
    rules_path = workdir / "local_rules.json"
    rules_path.write_text(_json.dumps([
        {"category": "Revenus", "subcategory": "Salaire / clients",
         "pattern": "Employeur Test"},
    ], ensure_ascii=False, indent=1), encoding="utf-8")

    app = create_app(ledger_copy)
    with app.test_client() as c:
        assert "Employeur Test" in text(c.get("/reclasser"))
        response = c.post("/reclasser", data={
            "action": "lr-delete", "pattern": "Employeur Test",
            "category": "Revenus", "subcategory": "Salaire / clients"})
        assert response.status_code == 302
        assert _json.loads(rules_path.read_text(encoding="utf-8")) == []
        assert "Employeur Test" not in text(c.get("/reclasser"))


def test_the_store_fingerprint_tracks_the_local_rules_file(tmp_path):
    """An edit to the personal rules must reload the statement on the next
    request: the fingerprint watches data/local_rules.json like the ledger."""
    from pms.web.store import Store

    store = Store(tmp_path / "ledger.json")
    before = store._fingerprint()
    (tmp_path / "local_rules.json").write_text("[]", encoding="utf-8")
    assert store._fingerprint() != before


def test_corrections_are_grouped_by_kind_and_long_groups_fold(tmp_path_factory,
                                                              ledger_file):
    """228 corrections in one table were sixteen screens. One group per kind,
    with its count; a group past ten rows starts folded."""
    app = corrected_ledger(tmp_path_factory, ledger_file, pins=12)
    with app.test_client() as c:
        body = c.get("/reclasser").get_data(as_text=True)
    groups = {kind: bool(opened) for opened, kind in re.findall(
        r'<details class="fold group-fold"( open)? data-group="(\w+)"', body)}
    assert groups == {"rule": True, "pin": False, "alias": True}
    assert "Épingles <span class=\"muted num\">(12)</span>" in body
    # The filter only makes sense with JavaScript, which reveals it.
    assert re.search(r'<div class="field mb-3" hidden data-filter-wrap>', body)
