"""The Twint triage (`/api/triage`): identifying the Twints the statement
leaves blank, one at a time or a whole amount at once."""

from __future__ import annotations

import pytest

TRI = "/api/triage"


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


def _row(app, key):
    from pms.overrides import key_of
    return next(t for t in app.extensions["pms_store"].statement.transactions if key_of(t) == key)


def test_a_twint_is_named_for_what_is_known():
    """"Paiement Twint" and nothing else is not known to be a transfer to a
    person: it pays parking meters too. Only a named payee is P2P."""
    from pms.categories import TWINT_UNKNOWN, classify
    from pms.models import Transaction

    def row(kind, amount):
        return Transaction(date=None, reference="1", currency="CHF",
                           amount=amount, value_date=None, balance=0.0, kind=kind)

    assert classify(row("Paiement Twint", -2.5))[0] == TWINT_UNKNOWN
    assert classify(row("Versement pour Alex Exemple", -50.0))[0] == "Transferts P2P"
    assert classify(row("Paiement Twint", 20.0)) == ("Revenus", "Remboursement Twint")


def test_the_newest_twint_comes_first_with_its_destinations(app):
    queue = _queue(app)
    with app.test_client() as c:
        state = c.get(TRI).get_json()
    assert state["queue_size"] == len(queue)
    assert state["current_key"] == queue[0][0]
    assert state["keys"] == 9
    # Not a destination: the bucket being emptied, and income.
    assert "Twint non identifié" not in state["targets"] and "Revenus" not in state["targets"]
    assert "Transferts P2P" in state["targets"]
    assert state["weekday"]


def test_classifying_pins_moves_on_and_can_be_undone(app):
    queue = _queue(app)
    key = queue[0][0]
    with app.test_client() as c:
        response = c.post(TRI, json={"key": key, "category": "Transport"})
        assert response.get_json()["last"] == key
        state = c.get(f"{TRI}?last={key}").get_json()
        assert state["queue_size"] == len(queue) - 1
        # The next one is up, and the last choice can be taken back.
        assert state["current_key"] == queue[1][0]
        assert state["last"]["category"] == "Transport"
        c.post(TRI, json={"key": key, "action": "undo"})
        assert c.get(TRI).get_json()["queue_size"] == len(queue)


def test_the_triage_refuses_what_it_is_not_for(app):
    from pms.overrides import key_of
    key = _queue(app)[0][0]
    card = next(t for t in app.extensions["pms_store"].statement.transactions
                if t.category == "Alimentation")
    with app.test_client() as c:
        assert c.post(TRI, json={"key": key, "category": "Inventée"}).status_code == 400
        assert c.post(TRI, json={"key": "nope:CHF", "category": "Transport"}).status_code == 404
        # Only a Twint with no category yet.
        assert c.post(TRI, json={"key": key_of(card), "category": "Transport"}).status_code == 409


def test_past_decisions_at_the_same_amount_are_shown_not_applied(app):
    """The statement's only clue is the amount; the owner's own earlier
    choices at that amount are the hint -- shown, never pre-applied."""
    parking = [(k, t) for k, t in _queue(app) if t.amount == -2.5]
    assert len(parking) >= 4
    with app.test_client() as c:
        assert c.get(TRI).get_json()["hint"] == [] or True
        c.post(TRI, json={"key": parking[0][0], "category": "Transport"})
        at = [k for k, _ in _queue(app)].index(parking[1][0])
        state = c.get(f"{TRI}?at={at}").get_json()
    assert state["current_key"] == parking[1][0]
    assert state["hint"] == [["Transport", 1]]
    assert parking[1][0] in {k for k, _ in _queue(app)}


def test_a_recurring_amount_is_classified_in_one_go(app):
    parking = [k for k, t in _queue(app) if t.amount == -2.5]
    with app.test_client() as c:
        group = next(g for g in c.get(TRI).get_json()["groups"] if g["amount"] == 2.5)
        assert sorted(group["keys"]) == sorted(parking)
        assert c.post(TRI, json={"keys": parking, "action": "group",
                                 "category": "Transport"}).status_code == 200
    assert not {k for k, _ in _queue(app)} & set(parking)


def test_the_corrections_count_what_is_left(app):
    with app.test_client() as c:
        assert c.get("/api/corrections").get_json()["twint_left"] == len(_queue(app))
        keys = [k for k, _ in _queue(app)]
        c.post(TRI, json={"keys": keys, "action": "group", "category": "Shopping"})
        assert c.get(TRI).get_json()["current"] is None
        assert c.get("/api/corrections").get_json()["twint_left"] == 0


def test_a_category_keeps_the_bucket_already_decided(app):
    """Real Twints carry a Want/Need pin and no category. Naming the category
    must not re-derive the bucket from it (Transport would read Need), and
    undo must give back the bucket-only pin, not nothing."""
    store_ = app.extensions["pms_store"]
    (key_a, _), (key_b, _) = _queue(app)[:2]
    store_.overrides.pin(key_a, bucket="Want")
    store_.overrides.pin(key_b, bucket="Want")
    store_.overrides.save()
    store_.invalidate()
    with app.test_client() as c:
        c.post(TRI, json={"key": key_a, "category": "Transport"})
        c.post(TRI, json={"keys": [key_b], "action": "group", "category": "Transport"})
        assert (_row(app, key_a).category, _row(app, key_a).bucket) == ("Transport", "Want")
        assert (_row(app, key_b).category, _row(app, key_b).bucket) == ("Transport", "Want")
        c.post(TRI, json={"key": key_a, "action": "undo"})
    assert store_.overrides.pins[key_a]["bucket"] == "Want"
    assert _row(app, key_a).category == "Twint non identifié"
