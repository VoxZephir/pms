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


def test_a_street_name_says_nothing_about_the_payee():
    """The rules read who was paid, not where: streets are named after
    museums, hospitals and stations."""
    burger = _payment("Paiement par carte - se terminant par 1234", "Burger Factory")
    burger.location = "Rue de l'Hôpital 9, Suisse"
    assert classify(burger, PUBLIC)[0] != "Santé & assurance"
    salary = _payment("Paiement entrant", "Alpha Conseil SA", amount=6000.0)
    salary.location = "Rue du Musée,4"
    assert classify(salary, PUBLIC) == ("Revenus", "Virement entrant")


def test_an_insurer_named_assurances_is_not_a_health_insurer():
    home = _payment("Ordre de paiement", "La Mobilière Assurances")
    assert classify(home, PUBLIC) == ("Santé & assurance", "Autres assurances")
    assert classify(_payment("Ordre de paiement", "Assura-Basis SA"), PUBLIC)[1] == "Assurance maladie"


def test_a_transfer_from_or_to_the_holder_is_a_move_between_own_accounts():
    from pms.categories import INTERNAL, classify_all, is_to_self
    incoming = _payment("Paiement entrant", "DUPONT JEAN-MARC", amount=2500.0)
    outgoing = _payment("Versement pour Jean-Marc Dupont")
    card = _payment("Paiement par carte - se terminant par 1234", "Jean Marc Dupont Atelier")
    stranger = _payment("Paiement entrant", "Jean Dupuis", amount=50.0)
    assert is_to_self(incoming, "Jean-Marc Dupont") and is_to_self(outgoing, "Jean-Marc Dupont")
    assert not is_to_self(card, "Jean-Marc Dupont") and not is_to_self(stranger, "Jean-Marc Dupont")
    assert not is_to_self(incoming, "")  # no holder read: nothing assumed
    rows = [incoming, outgoing, stranger]
    classify_all(rows, PUBLIC, holder="Jean-Marc Dupont")
    assert [t.category for t in rows] == [INTERNAL, INTERNAL, "Revenus"]


def test_savings_to_ones_own_brokerage_stay_savings():
    from pms.categories import classify_all
    to_broker = _payment("Versement pour Jean-Marc Dupont", "Interactive Brokers")
    classify_all([to_broker], PUBLIC, holder="Jean-Marc Dupont")
    assert to_broker.category == "Épargne & investissement"


def test_taxes_and_administration_are_two_categories():
    assert classify(_payment("Ordre de paiement", "Administration fiscale cantonale"), PUBLIC) == ("Impôts", "Impôts")
    assert classify(_payment("Ordre de paiement", "Office des poursuites de Genève"), PUBLIC) == ("Administration", "Poursuites")
    assert classify(_payment("Ordre de paiement", "Poste CH SA"), PUBLIC) == ("Administration", "Poste")
    assert classify(_payment("Ordre de paiement", "OCPM Genève"), PUBLIC) == ("Administration", "Documents & autorités")
    assert classify(_payment("Ordre de paiement", "Service des contraventions"), PUBLIC) == ("Administration", "Amendes")


def test_corrections_written_under_the_old_name_read_as_the_new_ones():
    from pms.categories import current
    assert current("Impôts & administration", "Impôts") == ("Impôts", "Impôts")
    assert current("Impôts & administration", "Remboursement") == ("Impôts", "Remboursement")
    assert current("Impôts & administration", "Services publics") == ("Administration", "Documents & autorités")
    assert current("Impôts & administration", "") == ("Administration", "")
    assert current("Logement", "Loyer") == ("Logement", "Loyer")
