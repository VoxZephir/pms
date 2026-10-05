"""The public rule set, checked on made-up transactions -- no statement needed."""

from __future__ import annotations

import datetime as dt
import re

import pytest

from pms.categories import RULES, classify, compile_rules


def _payment(kind: str, merchant: str = "", amount: float = -100.0):
    from pms.models import Transaction
    return Transaction(date=dt.date(2025, 1, 1), reference="R1", currency="CHF",
                       amount=amount, value_date=None, balance=None,
                       kind=kind, merchant=merchant)


PUBLIC = compile_rules([])  # the public rules alone, whatever data/ holds


def test_no_rule_hides_a_control_character():
    """A backspace typed where `\\b` was meant compiles fine and never
    matches: the rent rule carried one after "Régie" for months."""
    for category, subcategory, pattern in RULES:
        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", pattern), \
            (category, subcategory)


@pytest.mark.parametrize("name", ["Régie du Rhône SA", "REGIE DU RHONE",
                                  "Gérance Immobilière Exemple"])
def test_a_property_manager_is_rent(name):
    txn = _payment(f"Versement pour {name}")
    assert classify(txn, PUBLIC) == ("Logement", "Loyer / régie")


def test_regie_needs_a_word_boundary():
    """`\\b` after "Régie" is there so a longer word does not match."""
    txn = _payment("Versement pour Régiedirect Sàrl")
    assert classify(txn, PUBLIC)[0] != "Logement"


def test_a_credit_in_a_spending_category_is_a_refund():
    txn = _payment("Paiement entrant", "Régie du Rhône SA", amount=250.0)
    assert classify(txn, PUBLIC) == ("Logement", "Remboursement")
