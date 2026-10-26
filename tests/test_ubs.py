"""UBS's "Account transactions" PDF (`ubs.py`): the rows and their chain,
the vocabulary they are brought to, the period a cut export covers, the
references two overlapping exports share, and where the bank registry sends
the file. On an invented export (`synthetic_ubs.py`); the real one, when
inbox/ubs/ holds it, must reconcile."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

pytest.importorskip("pymupdf")

import synthetic_ubs  # noqa: E402

from pms import banks, categories, parser, ubs  # noqa: E402


@pytest.fixture
def export(tmp_path):
    return synthetic_ubs.build(tmp_path / "ubs.pdf")


def test_every_row_is_read_in_order_and_the_balances_chain(export):
    s = ubs.parse_statement(export)
    assert len(s.transactions) == len(synthetic_ubs.ROWS)
    assert [t.amount for t in s.transactions] == [r.amount for r in synthetic_ubs.ROWS]
    assert parser.reconcile(s) == []
    account = s.accounts[0]
    assert account.opening_balance == synthetic_ubs.OPENING
    assert round(account.opening_balance + sum(t.amount for t in s.transactions), 2) == account.closing_balance
    # Chronological, the day's rows numbered in order.
    assert [t.date for t in s.transactions] == sorted(t.date for t in s.transactions)
    first_day = [t.seq for t in s.transactions if t.date == dt.date(2025, 3, 3)]
    assert first_day == [0, 1]
    assert s.transactions[2].value_date == dt.date(2025, 3, 4)


def test_the_vocabulary_is_the_analysis_one(export):
    rows = {(t.date, t.amount): t for t in ubs.parse_statement(export).transactions}
    shapes = {
        (dt.date(2025, 3, 3), 5200.00): ("Paiement entrant - salaire", "EMPLOYEUR EXEMPLE SA"),
        (dt.date(2025, 3, 3), -1.50): ("Paiement par carte - TWINT", "PARKINGPAY-TWINT"),
        (dt.date(2025, 3, 4), -42.35): ("Paiement par carte", "Coop-1234 Exempleville"),
        (dt.date(2025, 3, 5), -60.00): ("Paiement Twint", "Jean Fictif"),
        (dt.date(2025, 3, 5), 25.00): ("Paiement Twint", "Marie Inventee"),
        (dt.date(2025, 3, 7), -1450.00): ("Versement pour Regie Imaginaire SA", ""),
        (dt.date(2025, 3, 10), -89.90): ("Facture eBill", "Assurance Fictive SA"),
        (dt.date(2025, 3, 12), -200.00): ("Retrait d'espèces", "UBS Exempleville"),
        (dt.date(2025, 3, 20), -310.40): ("Facture carte de crédit", "Carte de crédit UBS"),
        (dt.date(2025, 3, 21), 19.90): ("Paiement par carte", "Boutique Exemple"),
        (dt.date(2025, 3, 31), 0.00): ("Frais bancaires", ""),
        (dt.date(2025, 3, 31), 4.10): ("Intérêts", ""),
        (dt.date(2025, 4, 1), 150.00): ("Paiement entrant", "Association Exemple"),
        (dt.date(2025, 4, 2), -12.80): ("Paiement par carte - TWINT", "PIZZERIA EXEMPLE"),
        (dt.date(2025, 4, 2), -35.00): ("Paiement Twint", "COIFFEUR, Paul Fictif"),
        (dt.date(2025, 4, 3), 300.00): ("Dépôt d'espèces", "UBS Exempleville"),
    }
    for key, (kind, merchant) in shapes.items():
        t = rows[key]
        assert (t.kind, t.merchant) == (kind, merchant), key
    # The card number is never kept as the merchant, and a shop paid by
    # Twint is read by the rules like a card payment.
    t = rows[(dt.date(2025, 3, 3), -1.50)]
    categories.classify_all([t])
    assert t.category == "Transport"


def test_two_identical_payments_the_same_day_stay_two(export):
    s = ubs.parse_statement(export)
    twins = [t for t in s.transactions if t.amount == -42.35]
    assert len(twins) == 2 and twins[0].reference != twins[1].reference


def test_references_survive_an_overlapping_export(tmp_path):
    rows = synthetic_ubs.ROWS
    early = ubs.parse_statement(synthetic_ubs.build(tmp_path / "a.pdf", rows[:12]))
    opening = synthetic_ubs.OPENING + sum(r.amount for r in rows[:6])
    late = ubs.parse_statement(synthetic_ubs.build(tmp_path / "b.pdf", rows[6:], opening=opening))
    shared = {t.reference for t in early.transactions} & {t.reference for t in late.transactions}
    assert len(shared) == 6


def test_a_cut_export_covers_what_it_shows_not_what_was_asked(tmp_path):
    whole = ubs.parse_statement(synthetic_ubs.build(tmp_path / "whole.pdf"))
    assert (whole.period_start, whole.period_end) == (dt.date(2025, 1, 1), dt.date(2025, 6, 30))
    cut = ubs.parse_statement(synthetic_ubs.build(tmp_path / "cut.pdf", count=500))
    assert (cut.period_start, cut.period_end) == (dt.date(2025, 3, 3), dt.date(2025, 4, 4))
    assert cut.generated_on == dt.date(2025, 7, 15)


def test_the_registry_sends_a_ubs_export_to_its_parser(export, tmp_path):
    assert ubs.looks_like(export) and not parser.looks_like(export)
    assert banks.recognise(export) == "ubs/*.pdf"
    inbox = tmp_path / "inbox"
    (inbox / "ubs").mkdir(parents=True)
    filed = inbox / "ubs" / "export.pdf"
    filed.write_bytes(export.read_bytes())
    assert banks.parser_for(filed) is ubs.parse_statement
    assert filed in banks.discover(inbox)
    # Dropped at the top of inbox/ by hand, it is still read as UBS.
    loose = inbox / "loose.pdf"
    loose.write_bytes(export.read_bytes())
    assert len(banks.parser_for(loose)(loose).transactions) == len(synthetic_ubs.ROWS)


def test_a_real_ubs_export_reconciles():
    """On the exports in inbox/ubs/ when there are some. Skipped without."""
    folder = Path(__file__).resolve().parents[1] / "inbox" / "ubs"
    files = sorted(folder.glob("*.pdf")) if folder.is_dir() else []
    if not files:
        pytest.skip("pas d'export UBS dans inbox/ubs/")
    for path in files:
        s = ubs.parse_statement(path)
        assert s.transactions and parser.reconcile(s) == [], path.name
