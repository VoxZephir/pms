"""A note on a movement: the owner's words on what it was for -- shown,
searched and exported, never a correction."""

from __future__ import annotations

import pytest

from pms import categories, export
from pms.overrides import NOTE_MAX, key_of
from webhelpers import api


@pytest.fixture
def app(tmp_path, ledger_file):
    from pms.web import create_app
    copy = tmp_path / "ledger.json"
    copy.write_bytes(ledger_file.read_bytes())
    app = create_app(copy)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def web(app):
    with app.test_client() as c:
        yield c


def _post(web, body):
    response = web.post("/api/note", json=body, headers={"Origin": "http://localhost"})
    return response.status_code, response.get_json()


def _row(app, key):
    return next(t for t in app.extensions["pms_store"].statement.transactions
                if key_of(t) == key)


def _twint(app):
    return next(t for t in app.extensions["pms_store"].statement.transactions
                if t.kind in categories.PEER_KINDS and t.amount < 0)


def test_a_note_is_kept_searched_and_exported(app, web):
    twint = _twint(app)
    key, category = key_of(twint), twint.category
    status, body = _post(web, {"key": key, "text": "  parking   gare de Lausanne "})
    assert status == 200, body
    assert body["text"] == "parking gare de Lausanne" and body["undo"]["text"] == ""
    row = _row(app, key)
    assert row.note == "parking gare de Lausanne"
    # A note corrects nothing.
    assert row.category == category and not row.overridden
    found = api(web, "/api/transactions?preset=all&q=lausanne parking")
    rows = found.get("rows", found.get("transactions", []))
    assert [r["key"] for r in rows] == [key] and rows[0]["note"] == "parking gare de Lausanne"
    assert export.table([row])[0][export.HEADERS.index("Note")] == "parking gare de Lausanne"


def test_a_note_is_undone_cleared_and_capped(app, web):
    key = key_of(_twint(app))
    _post(web, {"key": key, "text": "premier"})
    status, body = _post(web, {"key": key, "text": "second"})
    assert body["undo"] == {"key": key, "text": "premier"}
    _post(web, body["undo"])
    assert _row(app, key).note == "premier"
    _post(web, {"key": key, "text": "   "})
    assert _row(app, key).note == "" and key not in app.extensions["pms_store"].overrides.notes
    _, body = _post(web, {"key": key, "text": "x" * (NOTE_MAX + 50)})
    assert len(body["text"]) == NOTE_MAX
    assert _post(web, {"key": "nope:CHF", "text": "a"})[0] == 404


def test_a_note_on_the_advanced_half_lives_on_the_printed_row(app, web):
    card = next(t for t in app.extensions["pms_store"].statement.transactions
                if t.kind.startswith(categories.CARD_KIND) and t.currency == "CHF"
                and t.amount < -20 and not t.account)
    key = key_of(card)
    web.post("/api/advance", json={"key": key, "amount": 5}, headers={"Origin": "http://localhost"})
    half = next(t for t in app.extensions["pms_store"].statement.transactions
                if t.advance_of == key)
    status, body = _post(web, {"key": key_of(half), "text": "dîner avec Léa"})
    assert status == 200 and body["key"] == key
    assert _row(app, key).note == "dîner avec Léa"
    assert next(t for t in app.extensions["pms_store"].statement.transactions
                if t.advance_of == key).note == "dîner avec Léa"
