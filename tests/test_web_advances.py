"""Advances: the part of a payment made for someone who pays it back, and
the repayment -- out of spending and income alike, owed until repaid."""

from __future__ import annotations

import pytest

from pms import analysis, categories
from pms.overrides import key_of
from webhelpers import api


@pytest.fixture
def app(tmp_path, ledger_file):
    """A private ledger copy: every test here writes advances."""
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


def _store(app):
    return app.extensions["pms_store"]


def _spent(app) -> float:
    return round(sum(-t.amount_chf for t in analysis.spending(_store(app).statement)), 2)


def _earned(app) -> float:
    return round(sum(t.amount_chf for t in analysis.income(_store(app).statement)), 2)


def _row(app, test):
    return next(t for t in _store(app).statement.transactions if test(t))


def _post(web, url, body):
    response = web.post(url, json=body, headers={"Origin": "http://localhost"})
    return response.status_code, response.get_json()


def _card(t):
    return (t.kind.startswith(categories.CARD_KIND) and t.currency == "CHF" and t.amount < -20
            and not t.account)


def test_a_whole_twint_advanced_leaves_spending_and_is_owed(app, web):
    twint = _row(app, lambda t: t.kind in categories.PEER_KINDS and t.amount < 0)
    key, amount, before = key_of(twint), -twint.amount, _spent(app)
    status, body = _post(web, "/api/advance", {"key": key, "amount": amount})
    assert status == 200, body
    row = _row(app, lambda t: key_of(t) == key)
    assert row.category == categories.ADVANCE and row.subcategory == categories.ADVANCE_OUT
    assert row.bucket == ""
    assert _spent(app) == pytest.approx(before - amount, abs=0.01)
    owed = api(web, "/api/advances")
    assert owed["owed"] == pytest.approx(amount) and owed["count"] == 1
    assert owed["rows"][0]["key"] == key


def test_a_shared_payment_is_split_and_the_rest_keeps_its_category(app, web):
    card = _row(app, _card)
    key, printed, category = key_of(card), card.amount, card.category
    closing = analysis.closing_chf(_store(app).statement)
    before, count = _spent(app), len(_store(app).statement.transactions)
    part = round(-printed / 2, 2)
    assert _post(web, "/api/advance", {"key": key, "amount": part})[0] == 200

    rows = _store(app).statement.transactions
    assert len(rows) == count + 1
    own = _row(app, lambda t: key_of(t) == key)
    split = _row(app, lambda t: t.advance_of == key)
    assert own.category == category and split.category == categories.ADVANCE
    assert own.amount + split.amount == pytest.approx(printed)
    assert own.printed == split.printed == printed
    assert key_of(split) != key
    # The balance chain still holds: the split-off row sits between the two.
    assert split.balance == pytest.approx(own.balance - own.amount)
    assert rows.index(split) == rows.index(own) - 1
    assert analysis.closing_chf(_store(app).statement) == pytest.approx(closing)
    assert _spent(app) == pytest.approx(before - part, abs=0.01)

    # The sheet of either half reads the printed amount; the half's key works.
    page = api(web, "/api/transactions?preset=all&category=Avances")
    assert any(r["printed"] == printed and r["advance_of"] == key
               for r in page.get("rows", page.get("transactions", [])))
    assert _post(web, "/api/advance", {"key": key_of(split), "amount": 0})[0] == 200
    assert len(_store(app).statement.transactions) == count
    assert _row(app, lambda t: key_of(t) == key).amount == printed


def test_a_repayment_leaves_income_and_settles_what_is_owed(app, web):
    twint = _row(app, lambda t: t.kind in categories.PEER_KINDS and t.amount < 0)
    back = _row(app, lambda t: t.amount > 0 and t.currency == "CHF"
                and not analysis.is_internal(t) and t.amount < 500)
    _post(web, "/api/advance", {"key": key_of(twint), "amount": -twint.amount})
    earned = _earned(app)
    repaid = min(back.amount, -twint.amount)
    status, body = _post(web, "/api/advance", {"key": key_of(back), "amount": repaid})
    assert status == 200, body
    assert _earned(app) == pytest.approx(earned - repaid, abs=0.01)
    owed = api(web, "/api/advances")
    assert owed["owed"] == pytest.approx(-twint.amount - repaid, abs=0.01)
    assert owed["repaid"] == pytest.approx(repaid)


def test_an_advance_is_undone_and_refused_where_it_cannot_be(app, web):
    card = _row(app, _card)
    status, body = _post(web, "/api/advance", {"key": key_of(card), "amount": -card.amount + 1})
    assert status == 400
    fx = _row(app, analysis.is_fx_leg)
    assert _post(web, "/api/advance", {"key": key_of(fx), "amount": 1})[0] == 409
    assert _post(web, "/api/advance", {"key": "nope:CHF", "amount": 1})[0] == 404

    before = _spent(app)
    status, body = _post(web, "/api/advance", {"key": key_of(card), "amount": 5})
    assert _spent(app) == pytest.approx(before - 5, abs=0.01)
    assert _post(web, "/api/reclassify/undo", body["undo"])[0] == 200
    assert _spent(app) == pytest.approx(before, abs=0.01)
    assert not _store(app).overrides.advances


def test_the_twint_triage_offers_an_advance(app, web):
    state = api(web, "/api/triage")
    assert categories.ADVANCE in state["targets"]
    key = state["current_key"]
    status, body = _post(web, "/api/triage", {"action": "pin", "key": key,
                                              "category": categories.ADVANCE})
    assert status == 200, body
    row = _row(app, lambda t: key_of(t) == key)
    assert row.category == categories.ADVANCE and row.advanced == -row.amount
    assert key not in _store(app).overrides.pins
    # "Annuler" puts the Twint back in the queue.
    assert _post(web, "/api/triage", {"action": "undo", "key": key})[0] == 200
    assert _row(app, lambda t: key_of(t) == key).category == categories.TWINT_UNKNOWN


def test_an_advance_is_not_a_category_to_pin(app, web):
    twint = _row(app, lambda t: t.kind in categories.PEER_KINDS and t.amount < 0)
    _post(web, "/api/advance", {"key": key_of(twint), "amount": -twint.amount})
    assert categories.ADVANCE not in api(web, "/api/choices")["categories"]
