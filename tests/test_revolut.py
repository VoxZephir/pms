"""Revolut's CSV export, and a second account next to the primary one.

The export is invented, in the shape of the real fr-ch one: double-encoded
UTF-8, every currency in one file, the fee charged on top of the amount, rows
in an order neither date column follows, card holds given back.
"""

from __future__ import annotations

import datetime as dt

import pytest

from pms import analysis, banks, categories, revolut
from pms.ledger import Ledger
from pms.models import AccountSummary, Statement, Transaction
from pms.parser import reconcile

D = dt.date

HEADER = "Type,Produit,Date de début,Date de fin,Description,Montant,Frais,Devise,État,Solde"
ROWS = [
    # CHF: a top-up, a card payment with a fee, a conversion to EUR. The
    # payment started before the top-up but completed after it -- the file,
    # and the balance, follow the completion.
    "Ajout de fonds,Valeur actuelle,2026-03-01 9:00:00,2026-03-01 9:00:01,Recharge sur Google Pay via *1234,200,0,CHF,TERMINÉ,200",
    "Paiement par carte,Valeur actuelle,2026-02-28 22:10:00,2026-03-02 10:00:00,Café du Port,-10,0.1,CHF,TERMINÉ,189.9",
    "Changes,Valeur actuelle,2026-03-03 12:00:00,2026-03-03 12:00:00,Change en EUR,-100,1,CHF,TERMINÉ,88.9",
    # A card hold given back: no balance, no money moved.
    "TEMP_BLOCK,Valeur actuelle,2026-03-04 8:00:00,,To someone,-40,0,CHF,RENVOYÉ,",
    "Virement,Valeur actuelle,2026-03-05 18:00:00,2026-03-05 18:00:01,Virement à : ALEX EXEMPLE,-20,0,CHF,TERMINÉ,68.9",
    # EUR
    "Changes,Valeur actuelle,2026-03-03 12:00:00,2026-03-03 12:00:00,Change en EUR,105,0,EUR,TERMINÉ,105",
    "Paiement par carte,Valeur actuelle,2026-03-06 13:00:00,2026-03-07 09:00:00,Boulangerie Exemple,-5,0,EUR,TERMINÉ,100",
    "Paiement par carte,Valeur actuelle,2026-03-06 13:00:00,2026-03-07 09:00:00,Boulangerie Exemple,-5,0,EUR,TERMINÉ,95",
    "Virement,Valeur actuelle,2026-03-08 10:00:00,2026-03-08 10:00:01,Virement de : SAM EXEMPLE,15,0,EUR,TERMINÉ,110",
]


def _export(tmp_path, rows=ROWS, name="export.csv"):
    folder = tmp_path / "revolut"
    folder.mkdir(exist_ok=True)
    text = "\r\n".join([HEADER, *rows]) + "\r\n"
    # What Revolut ships: UTF-8 bytes read as latin-1 and encoded again.
    path = folder / name
    path.write_bytes(text.encode("utf-8").decode("latin-1").encode("utf-8"))
    return path


def test_the_export_reconciles_in_its_own_order(tmp_path):
    s = revolut.parse_statement(_export(tmp_path))
    assert reconcile(s) == []
    assert len(s.transactions) == 8  # the hold is not a movement
    chf = {a.currency: a for a in s.accounts}["CHF"]
    assert (chf.opening_balance, chf.closing_balance, chf.account) == (0.0, 68.9, "revolut")
    payment = next(t for t in s.transactions if t.merchant == "Café du Port")
    # Dated by its completion; the fee is part of what left.
    assert payment.date == D(2026, 3, 2) and payment.value_date == D(2026, 2, 28)
    assert payment.amount == -10.1 and payment.fee == 0.1


def test_the_vocabulary_is_the_pipelines(tmp_path):
    s = revolut.parse_statement(_export(tmp_path))
    kinds = {t.merchant or t.kind: t.kind for t in s.transactions}
    assert kinds["Café du Port"] == "Paiement par carte"
    assert kinds["SAM EXEMPLE"] == "Paiement entrant"
    assert "Versement pour ALEX EXEMPLE" in kinds
    out = next(t for t in s.transactions if t.kind.startswith("Versement pour"))
    assert out.label == "ALEX EXEMPLE"
    topup = next(t for t in s.transactions if t.kind == "Recharge Revolut")
    assert categories.classify(topup, rules=categories.compile_rules([]))[0] == categories.INTERNAL


def test_a_conversion_carries_the_francs_on_its_foreign_leg(tmp_path):
    s = revolut.parse_statement(_export(tmp_path))
    legs = [t for t in s.transactions if t.kind == "Transfert Forex manuel"]
    assert len(legs) == 2 and legs[0].reference == legs[1].reference
    eur = next(t for t in legs if t.currency == "EUR")
    assert eur.fx_counter_amount == 101.0 and eur.fx_counter_currency == "CHF"
    assert analysis.is_fx_leg(eur)


def test_references_survive_an_overlapping_export(tmp_path):
    first = revolut.parse_statement(_export(tmp_path))
    later = revolut.parse_statement(_export(tmp_path, ROWS + [
        "Paiement par carte,Valeur actuelle,2026-03-09 13:00:00,2026-03-09 14:00:00,Kiosque,-3,0,CHF,TERMINÉ,65.9",
    ], name="later.csv"))
    keys = {(t.reference, t.currency) for t in first.transactions}
    assert keys < {(t.reference, t.currency) for t in later.transactions}
    # Two identical coffees on the same minute are two rows, not one.
    assert len(keys) == len(first.transactions)


def test_each_bank_reads_its_own_folder(tmp_path):
    csv_path = _export(tmp_path)
    (tmp_path / "releve.pdf").write_bytes(b"%PDF")
    assert banks.parser_for(csv_path) is revolut.parse_statement
    assert banks.discover(tmp_path) == [tmp_path / "releve.pdf", csv_path]
    with pytest.raises(ValueError):
        banks.parser_for(tmp_path / "notes.txt")


def _primary() -> Statement:
    """A primary-account statement: a salary, then a Revolut top-up by card."""
    def txn(day, ref, kind, amount, balance, merchant=""):
        return Transaction(date=day, reference=ref, currency="CHF", amount=amount,
                           value_date=day, balance=balance, kind=kind, merchant=merchant)
    rows = [txn(D(2026, 2, 25), "1", "Paiement entrant", 5000.0, 6000.0),
            txn(D(2026, 3, 1), "2", "Paiement par carte", -200.0, 5800.0, "Revolut**1234*")]
    return Statement(holder="Test", iban="CH00 0000 0000 0000 0000 0",
                     period_start=D(2026, 2, 1), period_end=D(2026, 3, 31), generated_on=None,
                     reference_currency="CHF",
                     accounts=[AccountSummary("CHF", 1000.0, 5800.0, 5000.0, 200.0)],
                     transactions=rows)


def test_two_accounts_keep_two_chains(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(revolut.parse_statement(_export(tmp_path)))
    ledger.merge(_primary())
    # The primary bank's IBAN names the ledger, whatever came first.
    assert ledger.account["iban"].startswith("CH")
    assert ledger.gaps() == []
    s = ledger.to_statement()
    assert {(a.account, a.currency) for a in s.accounts} == {
        ("", "CHF"), ("revolut", "CHF"), ("revolut", "EUR")}
    assert analysis.closing_chf(s) == pytest.approx(5800.0 + 68.9)
    # Cash is both accounts summed, never one balance read after the other.
    assert analysis.cash_points(s.transactions)[-1][1] == pytest.approx(5868.9)


def test_a_top_up_is_neither_spent_nor_earned(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(_primary())
    ledger.merge(revolut.parse_statement(_export(tmp_path)))
    s = ledger.to_statement()
    categories.classify_all(s.transactions, rules=categories.compile_rules([]))
    analysis.annotate_chf(s)
    moved = [t for t in s.transactions if t.category == categories.INTERNAL]
    assert len(moved) == 2  # the card payment and the Revolut credit
    assert not set(map(id, moved)) & set(map(id, analysis.spending(s)))
    assert not set(map(id, moved)) & set(map(id, analysis.income(s)))


def test_another_account_waits_for_the_primary_one(tmp_path):
    """A month of Revolut alone, before the main account starts, would read
    as a month of spending nearly nothing: it stays in the ledger, out of the
    analysis."""
    early = [r.replace("2026-03-0", "2026-01-0").replace("2026-02-28", "2026-01-01")
             for r in ROWS]
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(revolut.parse_statement(_export(tmp_path, early)))
    ledger.merge(_primary())
    s = ledger.to_statement()
    assert all(t.date >= D(2026, 2, 25) for t in s.transactions)
    assert len(ledger) == 2 + 8
    # Without a primary account, nothing is held back.
    alone = Ledger(tmp_path / "alone.json")
    alone.merge(revolut.parse_statement(_export(tmp_path, early)))
    assert len(alone.to_statement().transactions) == 8


def test_an_export_in_another_regional_format_adds_nothing(tmp_path):
    """The fr-ch export writes a fee "0" and an amount "35.1", the fr-fr one
    "0.00" and "35.10": one row, two references -- it came in twice and broke
    the balance by its own amount (5.49 CHF, 22.08.2026). The ledger knows it
    by what it is."""
    import csv
    import io

    from pms.ledger import Ledger

    def padded(row: str) -> str:
        cells = next(csv.reader(io.StringIO(row)))
        for i in (5, 6, 9):  # Montant, Frais, Solde
            if cells[i]:
                cells[i] = f"{float(cells[i]):.2f}"
        out = io.StringIO()
        csv.writer(out, lineterminator="").writerow(cells)
        return out.getvalue()

    ch = revolut.parse_statement(_export(tmp_path, name="ch.csv"))
    fr = revolut.parse_statement(_export(tmp_path, [padded(r) for r in ROWS], name="fr.csv"))
    assert {t.reference for t in ch.transactions} != {t.reference for t in fr.transactions}
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(ch)
    report = ledger.merge(fr)
    assert report["added"] == 0 and len(ledger) == len(ch.transactions)
    assert ledger.gaps() == []
