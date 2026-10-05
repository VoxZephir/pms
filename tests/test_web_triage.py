"""/reclasser/tri: identifying the Twints the statement leaves blank."""

from __future__ import annotations

import re
from urllib.parse import unquote

import pytest

from webhelpers import text

TRI = "/reclasser/tri"


@pytest.fixture
def app(tmp_path_factory, ledger_file):
    """A private ledger copy: every test here writes pins."""
    from pms.web import create_app

    workdir = tmp_path_factory.mktemp("triage")
    ledger_copy = workdir / "ledger.json"
    ledger_copy.write_bytes(ledger_file.read_bytes())
    return create_app(ledger_copy)


def _queue(app):
    from pms.categories import TWINT_UNKNOWN
    from pms.overrides import key_of
    rows = app.extensions["pms_store"].statement.transactions
    return [(key_of(t), t) for t in sorted(
        (t for t in rows if t.category == TWINT_UNKNOWN),
        key=lambda t: (t.date, t.seq), reverse=True)]


def test_a_twint_is_named_for_what_is_known():
    """"Paiement Twint" and nothing else is not known to be a transfer to a
    person: it pays parking meters too. Only a named payee is P2P."""
    from pms.categories import TWINT_UNKNOWN, classify
    from pms.models import Transaction

    def row(kind, amount):
        return Transaction(date=None, reference="1", currency="CHF",
                           amount=amount, value_date=None, balance=0.0,
                           kind=kind)

    assert classify(row("Paiement Twint", -2.5))[0] == TWINT_UNKNOWN
    assert classify(row("Versement pour Alex Exemple", -50.0))[0] == "Transferts P2P"
    assert classify(row("Paiement Twint", 20.0)) == ("Revenus", "Remboursement Twint")


def test_triage_shows_the_newest_twint_with_one_key_per_category(app):
    queue = _queue(app)
    with app.test_client() as c:
        body = text(c.get(TRI))
    assert f"{len(queue)} à identifier" in body
    key, newest = queue[0]
    assert f'name="key" value="{key}"' in body
    keys = re.findall(r'data-key="(\d)"', body)
    assert keys == [str(n) for n in range(1, 10)]
    # Not a destination: the bucket being emptied, and income.
    targets = re.findall(r'name="category" value="([^"]+)"', body)
    assert "Twint non identifié" not in targets and "Revenus" not in targets
    assert "Transferts P2P" in targets


def test_classifying_pins_moves_on_and_can_be_undone(app):
    queue = _queue(app)
    key, first = queue[0]
    with app.test_client() as c:
        response = c.post(TRI, data={"key": key, "category": "Transport"})
        assert response.status_code == 302
        assert f"last={key}" in unquote(response.headers["Location"])

        body = text(c.get(response.headers["Location"]))
        assert f"{len(queue) - 1} à identifier" in body
        # The next one is up, and the last choice can be taken back.
        assert f'name="key" value="{queue[1][0]}"' in body
        assert "data-undo" in body and "<b>Transport</b>" in body

        c.post(TRI, data={"key": key, "action": "undo"})
        assert f"{len(queue)} à identifier" in text(c.get(TRI))


def test_triage_refuses_an_unknown_category(app):
    key, _ = _queue(app)[0]
    with app.test_client() as c:
        assert c.post(TRI, data={"key": key, "category": "Inventée"}).status_code == 400
        assert c.post(TRI, data={"key": "nope:CHF", "category": "Transport"}).status_code == 404


def test_past_decisions_at_the_same_amount_are_shown_not_applied(app):
    """The statement's only clue is the amount; the owner's own earlier
    choices at that amount are the hint -- outlined, never preselected."""
    parking = [(k, t) for k, t in _queue(app) if t.amount == -2.5]
    assert len(parking) >= 4
    with app.test_client() as c:
        before = text(c.get(TRI))
        assert "suggested" not in before
        c.post(TRI, data={"key": parking[0][0], "category": "Transport"})
        at = [k for k, _ in _queue(app)].index(parking[1][0])
        body = text(c.get(f"{TRI}?at={at}"))
    assert f'name="key" value="{parking[1][0]}"' in body
    assert re.search(r"Déjà classé à ce montant :\s*<b>Transport</b> ×1", body)
    assert re.search(r'class="btn suggested"[^>]*value="Transport"', body)
    # Shown, not applied: the row is still in the queue until a key is pressed.
    assert parking[1][0] in {k for k, _ in _queue(app)}


def test_a_recurring_amount_is_classified_in_one_go(app):
    parking = [k for k, t in _queue(app) if t.amount == -2.5]
    with app.test_client() as c:
        body = text(c.get(TRI))
        assert f"Classer les {len(parking)}" in body
        response = c.post(TRI, data={"keys": parking, "action": "group",
                                     "category": "Transport"})
        assert response.status_code == 302
    left = {k for k, _ in _queue(app)}
    assert not left & set(parking)


def test_corrections_page_points_at_the_triage(app):
    with app.test_client() as c:
        body = text(c.get("/reclasser"))
    assert f"{len(_queue(app))} Twint à identifier" in body
    assert f'href="{TRI}"' in body


def test_empty_queue_says_so(app):
    with app.test_client() as c:
        keys = [k for k, _ in _queue(app)]
        c.post(TRI, data={"keys": keys, "action": "group", "category": "Shopping"})
        body = text(c.get(TRI))
    assert "Plus aucun Twint à identifier" in body
    assert "Twint à identifier" not in text(app.test_client().get("/reclasser"))


def test_a_category_keeps_the_bucket_already_decided(app):
    """153 real Twints carry a Want/Need pin and no category. Naming the
    category must not re-derive the bucket from it (Transport would read
    Need), and undo must give back the bucket-only pin, not nothing."""
    store_ = app.extensions["pms_store"]
    (key_a, _), (key_b, _) = _queue(app)[:2]
    store_.overrides.pin(key_a, bucket="Want")
    store_.overrides.pin(key_b, bucket="Want")
    store_.overrides.save()
    store_.invalidate()

    def row(key):
        return next(t for k, t in _queue_all(app) if k == key)

    with app.test_client() as c:
        c.post(TRI, data={"key": key_a, "category": "Transport"})
        c.post(TRI, data={"keys": [key_b], "action": "group", "category": "Transport"})
        assert (row(key_a).category, row(key_a).bucket) == ("Transport", "Want")
        assert (row(key_b).category, row(key_b).bucket) == ("Transport", "Want")

        c.post(TRI, data={"key": key_a, "action": "undo"})
    assert store_.overrides.pins[key_a]["bucket"] == "Want"
    assert row(key_a).category == "Twint non identifié"


def test_the_triage_only_touches_unidentified_twints(app):
    from pms.overrides import key_of
    rows = app.extensions["pms_store"].statement.transactions
    card = next(t for t in rows if t.category == "Alimentation")
    with app.test_client() as c:
        assert c.post(TRI, data={"key": key_of(card),
                                 "category": "Transport"}).status_code == 409


def _queue_all(app):
    from pms.overrides import key_of
    return [(key_of(t), t)
            for t in app.extensions["pms_store"].statement.transactions]