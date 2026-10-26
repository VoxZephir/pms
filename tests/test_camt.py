"""ISO 20022 camt.053 statements, the export most Swiss banks share.

The file is invented, in the shape of the standard (camt.053.001.08, checked
against its XSD): a CHF account over two daily statements, a EUR account of
the same holder, a conversion between them, a batch booking, a card payment,
a Twint, a pending entry, an entry without the bank's reference.
"""

from __future__ import annotations

import datetime as dt

import pytest

from pms import banks, camt, categories, intake
from pms.ledger import ForeignAccount, ingest
from pms.parser import reconcile

D = dt.date
NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
CHF_IBAN = "CH9300762011623852957"
EUR_IBAN = "CH5604835012345678009"


def bal(code, amount, ccy, day, sign="CRDT"):
    return (f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp>"
            f'<Amt Ccy="{ccy}">{amount:.2f}</Amt><CdtDbtInd>{sign}</CdtDbtInd>'
            f"<Dt><Dt>{day}</Dt></Dt></Bal>")


def entry(amount, ccy, sign, day, ref="", code=("PMNT", "ICDT", "DMCT"), info="",
          details="", status="BOOK"):
    domain, family, sub = code
    reference = f"<AcctSvcrRef>{ref}</AcctSvcrRef>" if ref else ""
    extra = f"<AddtlNtryInf>{info}</AddtlNtryInf>" if info else ""
    return (f'<Ntry><Amt Ccy="{ccy}">{amount:.2f}</Amt><CdtDbtInd>{sign}</CdtDbtInd>'
            f"<Sts><Cd>{status}</Cd></Sts><BookgDt><Dt>{day}</Dt></BookgDt>"
            f"<ValDt><Dt>{day}</Dt></ValDt>{reference}"
            f"<BkTxCd><Domn><Cd>{domain}</Cd><Fmly><Cd>{family}</Cd>"
            f"<SubFmlyCd>{sub}</SubFmlyCd></Fmly></Domn></BkTxCd>"
            f"{details}{extra}</Ntry>")


def tx(amount=None, ccy="CHF", creditor="", debtor="", iban="", ref="", text=""):
    amt = f'<Amt Ccy="{ccy}">{amount:.2f}</Amt>' if amount is not None else ""
    refs = f"<Refs><AcctSvcrRef>{ref}</AcctSvcrRef></Refs>" if ref else ""
    parties = ""
    if debtor:
        parties += f"<Dbtr><Pty><Nm>{debtor}</Nm></Pty></Dbtr>"
        if iban:
            parties += f"<DbtrAcct><Id><IBAN>{iban}</IBAN></Id></DbtrAcct>"
    if creditor:
        parties += f"<Cdtr><Pty><Nm>{creditor}</Nm></Pty></Cdtr>"
        if iban:
            parties += f"<CdtrAcct><Id><IBAN>{iban}</IBAN></Id></CdtrAcct>"
    rmt = f"<RmtInf><Ustrd>{text}</Ustrd></RmtInf>" if text else ""
    return (f"<TxDtls>{refs}{amt}<RltdPties>{parties}</RltdPties>{rmt}</TxDtls>"
            if parties else f"<TxDtls>{refs}{amt}{rmt}</TxDtls>")


def details(*txs):
    return f"<NtryDtls>{''.join(txs)}</NtryDtls>"


def stmt(sid, iban, ccy, day, opening, closing, entries, prev_day=None):
    return (f"<Stmt><Id>{sid}</Id><CreDtTm>{day}T23:00:00</CreDtTm>"
            f"<FrToDt><FrDtTm>{day}T00:00:00</FrDtTm><ToDtTm>{day}T23:59:59</ToDtTm></FrToDt>"
            f"<Acct><Id><IBAN>{iban}</IBAN></Id><Ccy>{ccy}</Ccy>"
            f"<Ownr><Nm>Alex Exemple</Nm></Ownr></Acct>"
            f"{bal('OPBD', opening, ccy, day)}{bal('CLBD', closing, ccy, day)}"
            f"{''.join(entries)}</Stmt>")


def document(*statements):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<Document xmlns="{NS}">'
            f"<BkToCstmrStmt><GrpHdr><MsgId>MSG-1</MsgId>"
            f"<CreDtTm>2026-03-03T06:00:00</CreDtTm></GrpHdr>"
            f"{''.join(statements)}</BkToCstmrStmt></Document>")


def chf_day1():
    return stmt("S1", CHF_IBAN, "CHF", "2026-03-01", 1000, 5_640.50, [
        entry(5_000, "CHF", "CRDT", "2026-03-01", "R-1", ("PMNT", "RCDT", "SALA"),
              details=details(tx(debtor="Employeur Exemple SA", iban="CH1100000000000000001"))),
        entry(59.50, "CHF", "DBIT", "2026-03-01", "R-2", ("PMNT", "CCRD", "POSD"),
              info="Paiement carte de débit Coop-1234 Lausanne"),
        entry(300, "CHF", "DBIT", "2026-03-01", "R-3", ("PMNT", "ICDT", "DMCT"),
              details=details(tx(250, creditor="Régie Exemple", ref="R-3a"),
                              tx(50, creditor="Assurance Exemple", ref="R-3b"))),
        entry(12, "CHF", "CRDT", "2026-03-01", "", ("PMNT", "RCDT", "DMCT"),
              details=details(tx(debtor="Sam Exemple", text="Pizza"))),
        # A hold the bank has not booked: not a movement yet.
        entry(80, "CHF", "DBIT", "2026-03-01", "R-P", ("PMNT", "CCRD", "POSD"),
              info="Réservation hôtel", status="PDNG"),
        entry(12, "CHF", "DBIT", "2026-03-01", "R-4", ("PMNT", "MCOP", "OTHR"),
              info="TWINT Paiement"),
    ])


def chf_day2():
    return stmt("S2", CHF_IBAN, "CHF", "2026-03-02", 5_640.50, 4_590.50, [
        entry(1_050, "CHF", "DBIT", "2026-03-02", "R-5", ("PMNT", "ICDT", "XBCT"),
              details=details(tx(creditor="Alex Exemple", iban=EUR_IBAN))),
    ])


def eur_day2():
    return stmt("E1", EUR_IBAN, "EUR", "2026-03-02", 0, 1_000, [
        entry(1_000, "EUR", "CRDT", "2026-03-02", "R-6", ("PMNT", "RCDT", "XBCT"),
              details=details(tx(debtor="Alex Exemple", iban=CHF_IBAN))),
    ])


def write(tmp_path, xml, name="releve.xml"):
    folder = tmp_path / "camt"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text(xml, encoding="utf-8")
    return path


@pytest.fixture
def export(tmp_path):
    return write(tmp_path, document(chf_day1(), chf_day2(), eur_day2()))


def test_the_statements_reconcile(export):
    s = camt.parse_statement(export)
    assert reconcile(s) == []
    assert s.iban == CHF_IBAN and s.holder == "Alex Exemple"
    assert (s.period_start, s.period_end) == (D(2026, 3, 1), D(2026, 3, 2))
    chf = {a.account: a for a in s.accounts}[""]
    assert (chf.currency, chf.opening_balance, chf.closing_balance) == ("CHF", 1000, 4590.5)
    # The pending hold is not a movement; the batch is two.
    assert len([t for t in s.transactions if not t.account]) == 7


def test_a_lost_entry_breaks_its_statement(tmp_path):
    xml = document(chf_day1(), chf_day2()).replace(
        entry(59.50, "CHF", "DBIT", "2026-03-01", "R-2", ("PMNT", "CCRD", "POSD"),
              info="Paiement carte de débit Coop-1234 Lausanne"), "")
    problems = reconcile(camt.parse_statement(write(tmp_path, xml)))
    # Found on the statement's last row, by the money it misses.
    assert len(problems) == 1 and "R-4" in problems[0] and "+59.50" in problems[0]


def test_a_missing_day_breaks_the_chain(tmp_path):
    day3 = stmt("S3", CHF_IBAN, "CHF", "2026-03-04", 4_000, 3_990, [
        entry(10, "CHF", "DBIT", "2026-03-04", "R-9", ("PMNT", "CCRD", "POSD"), info="Kiosque")])
    problems = reconcile(camt.parse_statement(write(tmp_path, document(chf_day1(), chf_day2(), day3))))
    assert len(problems) == 1 and "R-9" in problems[0]


def test_the_vocabulary_is_the_pipelines(export):
    s = camt.parse_statement(export)
    by_ref = {t.reference: t for t in s.transactions}
    assert by_ref["R-1"].kind == "Paiement entrant" and by_ref["R-1"].label == "Employeur Exemple SA"
    assert by_ref["R-2"].kind == "Paiement par carte"
    assert by_ref["R-4"].kind == "Paiement Twint"
    rent = by_ref["R-3a"]
    assert (rent.kind, rent.amount, rent.label) == ("Versement pour Régie Exemple", -250, "Régie Exemple")
    assert by_ref["R-3b"].amount == -50
    # No bank reference: one derived from the content, stable.
    derived = next(t for t in s.transactions if t.reference.startswith("camt-"))
    assert derived.amount == 12 and "Pizza" in derived.detail
    assert derived.reference == next(
        t for t in camt.parse_statement(export).transactions if t.amount == 12 and t.kind == "Paiement entrant"
    ).reference


def test_a_conversion_between_own_accounts_is_internal(export):
    s = camt.parse_statement(export)
    out = next(t for t in s.transactions if t.reference == "R-5")
    into = next(t for t in s.transactions if t.reference == "R-6")
    assert out.kind == into.kind == "Transfert Forex manuel"
    assert into.account == "compte-8009" and into.currency == "EUR"
    assert (into.fx_counter_amount, into.fx_counter_currency) == (1050, "CHF")
    rules = categories.compile_rules([])
    assert categories.classify(out, rules=rules)[0] == "Frais bancaires"  # an FX leg, as Swissquote's


def test_a_transfer_between_own_accounts_in_one_currency(tmp_path):
    other = "CH4431999123000889012"
    xml = document(
        stmt("S1", CHF_IBAN, "CHF", "2026-03-01", 100, 50, [
            entry(50, "CHF", "DBIT", "2026-03-01", "X-1",
                  details=details(tx(creditor="Alex Exemple", iban=other)))]),
        stmt("S9", other, "CHF", "2026-03-01", 0, 50, [
            entry(50, "CHF", "CRDT", "2026-03-01", "X-2", ("PMNT", "RCDT", "DMCT"),
                  details=details(tx(debtor="Alex Exemple", iban=CHF_IBAN)))]))
    s = camt.parse_statement(write(tmp_path, xml))
    assert reconcile(s) == []
    rules = categories.compile_rules([])
    assert {categories.classify(t, rules=rules)[0] for t in s.transactions} == {categories.INTERNAL}


def test_reimporting_an_overlapping_export_adds_nothing(tmp_path, export):
    ledger, _ = ingest([export], tmp_path / "ledger.json")
    ledger.save()
    later = write(tmp_path, document(chf_day2(), eur_day2()), name="suivant.xml")
    ledger, reports = ingest([later], tmp_path / "ledger.json")
    assert reports[0]["added"] == 0 and reports[0]["conflicts"] == 0
    assert ledger.gaps() == []


def test_the_bank_is_recognised_by_content(tmp_path, export):
    assert banks.recognise(export) == "camt/*.xml"
    assert banks.parser_for(export) is camt.parse_statement
    other = tmp_path / "autre.xml"
    other.write_text("<root/>", encoding="utf-8")
    assert banks.recognise(other) is None


def test_somebody_elses_statement_is_refused_whole(tmp_path, export):
    """The friend's file dropped in by mistake: nothing of it enters."""
    ledger_path = tmp_path / "ledger.json"
    ledger, _ = ingest([export], ledger_path)
    ledger.save()
    before = ledger_path.read_bytes()
    theirs = document(stmt("T1", "CH3908704016075473007", "CHF", "2026-03-05", 10, 5, [
        entry(5, "CHF", "DBIT", "2026-03-05", "T-1", ("PMNT", "CCRD", "POSD"), info="Café")]))

    with pytest.raises(intake.Unreadable, match="autre compte"):
        intake.take("theirs.xml", theirs.encode(), tmp_path, ledger_path)
    assert ledger_path.read_bytes() == before
    assert not (tmp_path / "camt" / "theirs.xml").exists()

    # Left in inbox/ by hand: a launch says so and goes on.
    stray = write(tmp_path, theirs, name="theirs.xml")
    with pytest.raises(ForeignAccount):
        ingest([stray], ledger_path)
    ledger, reports = ingest([stray], ledger_path, strict=False)
    assert "autre compte" in reports[0]["refused"] and len(ledger) == 8
