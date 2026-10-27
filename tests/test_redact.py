"""The PDF redaction tool (`redact.py`): what it removes from the file
itself, what it leaves, and the read-back that refuses a leak. On a PDF
written here, invented end to end."""

from __future__ import annotations

import pytest

from pms import redact

pymupdf = pytest.importorskip("pymupdf")

# The documentation IBAN (valid check digits), and an invented one that is not.
IBAN = "CH93 0076 2011 6238 5295 7"
LINES = [
    "Relevé de transactions",
    "Client 4455667",
    "Monsieur Albert Exemplaire",
    "Chemin des Lilas 12",
    "1200 Genève",
    f"IBAN {IBAN}",
    "Paiement par carte Coop Pronto Genève CH 23.50",
    "Ordre de paiement Régie Fictive SA 1'800.00",
    "Versement de Sophie Martinet, remboursement souper",
    "Contact: DUPONTEL Jean pour le dossier",
    "Référence CH12 3456 7890 1234 5678 9 non valide",
    "Swissquote Bank SA, Gland",
]


@pytest.fixture
def pdf(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(LINES):
        page.insert_text((50, 60 + 22 * i), line, fontsize=10)
    doc.set_metadata({"author": "Albert Exemplaire", "title": "Relevé"})
    path = tmp_path / "releve.pdf"
    doc.save(path)
    return path


def _text(path) -> str:
    doc = pymupdf.open(path)
    out = "\n".join(page.get_text() for page in doc)
    meta = doc.metadata
    doc.close()
    return out + "\n" + " ".join(v for v in meta.values() if v)


def test_names_ibans_and_the_address_leave_the_file(pdf, tmp_path):
    out = tmp_path / "out.pdf"
    report = redact.redact(pdf, out, also=["Régie Fictive SA"], keep=["Swissquote"])
    text = _text(out)
    for gone in ("Albert", "Exemplaire", "0076", "Lilas", "1200 Genève", "Sophie", "Martinet",
                 "DUPONTEL", "Régie Fictive", "4455667"):
        assert gone not in text, gone
    # What says nothing about anyone stays: the shop paid by card, the
    # amounts, the bank's name, a number that is not an IBAN.
    for kept in ("Coop Pronto", "23.50", "1'800.00", "Swissquote Bank", "CH12 3456", "remboursement souper"):
        assert kept in text, kept
    kinds = report.by_kind()
    assert kinds["IBAN"] >= 1 and kinds["adresse"] >= 2 and kinds["numéro de client"] == 1
    assert not report.leftover


def test_the_report_masks_what_it_names():
    assert redact.mask("Albert Exemplaire") == "A***** E*********"


def test_the_iban_check_digits_decide():
    assert redact.iban_ok(IBAN.replace(" ", ""))
    assert not redact.iban_ok("CH1234567890123456789")


def test_a_term_spared_stays(pdf, tmp_path):
    out = tmp_path / "out.pdf"
    redact.redact(pdf, out, keep=["Sophie Martinet"])
    assert "Sophie Martinet" in _text(out)


def test_the_cli_writes_the_copy_and_names_nothing_in_clear(pdf, tmp_path, monkeypatch, capsys):
    from pms import cli
    monkeypatch.setattr(redact, "OUTPUT", tmp_path / "caviarde")
    assert cli.main(["--redact", str(pdf), "--also", "Régie Fictive SA"]) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "caviarde" / "releve-caviarde.pdf").exists()
    assert "Albert" not in out and "Martinet" not in out and "A***** E*********" in out


def test_the_cli_refuses_what_is_not_a_pdf(tmp_path, capsys):
    from pms import cli
    other = tmp_path / "notes.txt"
    other.write_text("x")
    assert cli.main(["--redact", str(other)]) == 1


@pytest.mark.xdist_group("real")
def test_a_real_statement_loses_its_holder_and_iban(real_statement, tmp_path):
    """On the PDF in inbox/ when there is one: the holder, the IBAN and the
    client number leave the file, the card payments stay. Skipped without.
    The statement is the suite's one parse of it (`real_statement`), not a
    second one: 14 s each."""
    from conftest import STATEMENT
    statement = real_statement
    out = tmp_path / "out.pdf"
    redact.redact(STATEMENT, out)
    text = _text(out)
    assert statement.holder and statement.holder not in text
    assert statement.iban.replace(" ", "") not in text.replace(" ", "")
    assert statement.client_number not in text
    assert "Paiement par carte" in text


# --- the /caviarder page ------------------------------------------------------

@pytest.fixture
def copies(tmp_path, monkeypatch):
    folder = tmp_path / "caviarde"
    monkeypatch.setattr(redact, "OUTPUT", folder)
    return folder


def test_the_page_redacts_a_sent_pdf_and_serves_the_copy(client, pdf, copies):
    from webhelpers import api
    assert api(client, "/api/caviarder")["available"] is True
    with open(pdf, "rb") as f:
        r = client.post("/api/caviarder", data={"pdf": (f, "Relevé juillet.pdf"), "also": "Régie Fictive SA",
                                                "spare": "Swissquote"}, content_type="multipart/form-data")
    body = r.get_json()
    assert r.status_code == 200 and body["file"] == "Relevé-juillet-caviarde.pdf"
    assert body["count"] >= 8 and "M******* A***** E*********" in body["names"]
    assert not any("Albert" in n for n in body["names"])
    download = client.get(body["url"])
    assert download.status_code == 200 and download.data.startswith(b"%PDF")
    assert "Albert" not in _text_bytes(download.data)
    assert api(client, "/api/caviarder")["copies"][0]["file"] == body["file"]
    # Nothing of the original is kept: only the copy is in the folder.
    assert [p.name for p in copies.iterdir()] == [body["file"]]


def test_the_page_refuses_what_is_not_a_pdf_and_serves_nothing_else(client, copies):
    import io
    r = client.post("/api/caviarder", data={"pdf": (io.BytesIO(b"hello"), "notes.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert client.get("/caviarde/..%2F..%2Fpyproject.toml").status_code == 404
    assert client.get("/caviarde/absent.pdf").status_code == 404


def _text_bytes(data: bytes) -> str:
    doc = pymupdf.open(stream=data, filetype="pdf")
    out = " ".join(page.get_text() for page in doc)
    doc.close()
    return out


def test_an_iban_shaped_word_at_the_end_of_a_line_does_not_reach_the_next(tmp_path):
    """A statement whose line ends on "CH12 3456 7890 1234" followed by more
    capitals: the line break is not part of an IBAN (a UBS export broke on it)."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 400, 200),
                        f"Compte CH12 3456 7890 1234\nABCD EFGH IJKL 5678\nIBAN {IBAN}\nSolde 1'234.00", fontsize=10)
    src = tmp_path / "ubs.pdf"
    doc.save(src)
    out = tmp_path / "out.pdf"
    redact.redact(src, out)
    text = _text(out)
    assert "0076" not in text and "Solde 1'234.00" in text


def test_a_list_of_words_reads_lines_commas_and_semicolons():
    assert redact.terms("Jean Dupont\nRégie SA, Autre; Encore\n\n") == ["Jean Dupont", "Régie SA", "Autre", "Encore"]


def test_a_ubs_export_loses_its_people_and_keeps_the_words_around_them(tmp_path):
    """The Twints between people name them (UBS); the words of the line --
    "Debit UBS TWINT", "Payment UBS" -- are not part of a name, and the
    shops stay."""
    import synthetic_ubs
    src = synthetic_ubs.build(tmp_path / "ubs.pdf")
    out = tmp_path / "out.pdf"
    redact.redact(src, out)
    text = _text(out)
    for gone in ("Jean Fictif", "Marie Inventee", "Paul Fictif", "Fictif"):
        assert gone not in text, gone
    for kept in ("Debit UBS TWINT", "PIZZERIA EXEMPLE; Payment UBS TWINT", "Coop-1234", "Credit UBS TWINT"):
        assert kept in text, kept
    from pms import parser, ubs
    # The redacted copy still reads, and still adds up.
    s = ubs.parse_statement(out)
    assert len(s.transactions) == len(synthetic_ubs.ROWS) and parser.reconcile(s) == []


def test_a_name_goes_with_or_without_its_accents(tmp_path):
    """A counterparty printed « Genève Conseil » on a transfer and
    « GENEVE CONSEIL » elsewhere: one name. The match was accent-sensitive and
    the read-back not, so the second stayed and the real statement was refused."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Versement pour Genève Conseil", fontsize=10)
    page.insert_text((50, 90), "Paiement carte GENEVE CONSEIL 1204", fontsize=10)
    src = tmp_path / "accents.pdf"
    doc.save(src)
    out = tmp_path / "out.pdf"
    report = redact.redact(src, out, also=["Genève Conseil"])
    text = redact.fold(_text(out))
    assert "geneve" not in text and "1204" in text and report.leftover == []


def test_a_name_cut_across_two_blocks_is_removed_in_a_second_round(tmp_path):
    """« Jean Dupont » is found on its line; elsewhere the given name ends one
    block and the surname starts the next, where no rule sees a name. The
    read-back reads it, and the next round removes it word by word."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Virement de Jean Dupont", fontsize=10)
    page.insert_text((300, 200), "Remboursement Jean", fontsize=10)
    page.insert_text((50, 222), "Dupont, merci", fontsize=10)
    src = tmp_path / "cut.pdf"
    doc.save(src)
    out = tmp_path / "out.pdf"
    report = redact.redact(src, out)
    text = redact.fold(_text(out))
    assert "dupont" not in text and "merci" in text and "remboursement" in text
    assert report.leftover == []
