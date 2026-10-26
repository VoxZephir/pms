"""How tidy the ledger is (`tidy.py`): the share classified, and the payees
one merge would gather."""

from __future__ import annotations

import pytest

from pms import tidy


@pytest.fixture(scope="module")
def held(client):
    return client.application.extensions["pms_store"]


def test_the_coverage_counts_what_is_left(held):
    c = tidy.coverage(held.statement)
    assert c["lines_done"] + c["twint"] + c["unknown"] == c["lines"]
    assert 0 <= c["share_amount"] <= 100 and 0 <= c["share_lines"] <= 100


def test_a_chain_is_proposed_and_two_restaurants_are_not(held):
    hints = tidy.merge_suggestions(held.statement.transactions, held.overrides)
    by_name = {h["canonical"]: h for h in hints}
    assert "Coop" in by_name and len(by_name["Coop"]["labels"]) >= 2
    assert all(len(h["labels"]) >= 2 for h in hints)
    assert tidy._common(["Restaurant Le Comptoir", "Restaurant Le Port"]) is None
    assert tidy._common(["Régie du Centre SA", "Régie du Centre S.A."]) == "Régie du Centre"
