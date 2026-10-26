"""A statement sent from the phone (`/api/import`), filed in inbox/ and
ingested; the import log (`/api/imports`).

Each test runs on its own copy of the ledger and its own inbox: the route
writes both, and the session ledger is shared by every other web test.
"""

from __future__ import annotations

import io
import shutil

import pytest
from test_revolut import HEADER, ROWS

from pms import banks
from pms.ledger import Ledger
from pms.web import create_app

REVOLUT = ("\r\n".join([HEADER, *ROWS]) + "\r\n").encode("utf-8").decode("latin-1").encode("utf-8")


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    import pms.web.views.system as system_views
    folder = tmp_path / "inbox"
    folder.mkdir()
    monkeypatch.setattr(system_views, "INBOX", folder)
    return folder


@pytest.fixture
def web(ledger_file, tmp_path, inbox):
    ledger = tmp_path / "data" / "ledger.json"
    ledger.parent.mkdir()
    shutil.copy(ledger_file, ledger)
    app = create_app(ledger)
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


def _send(web, name, content, **headers):
    return web.post("/api/import", data={"releve": (io.BytesIO(content), name)},
                    content_type="multipart/form-data", headers=headers)


def _rows(web):
    return len(Ledger.load(web.application.config["LEDGER"]).transactions)


def test_the_page_says_what_it_reads_and_what_came_in(web):
    data = web.get("/api/imports").get_json()
    suffixes = {k["suffix"] for k in data["kinds"]}
    assert {".pdf", ".csv"} <= suffixes and "Revolut" in " ".join(k["label"] for k in data["kinds"])
    assert ".pdf" in data["accept"]
    assert data["imports"]      # the test ledger's own import


def test_an_export_lands_where_its_bank_is_read_and_joins_the_ledger(web, inbox):
    before = _rows(web)
    response = _send(web, "account-statement.csv", REVOLUT)
    assert response.status_code == 200
    assert response.get_json() == {"file": "account-statement.csv", "added": 8, "known": False}
    assert (inbox / "revolut" / "account-statement.csv").read_bytes() == REVOLUT
    assert _rows(web) == before + 8
    assert web.get("/api/imports").get_json()["imports"][0]["file"] == "account-statement.csv"


def test_the_same_file_twice_adds_nothing_and_no_copy(web, inbox):
    _send(web, "a.csv", REVOLUT)
    before = _rows(web)
    response = _send(web, "a-encore.csv", REVOLUT)
    assert response.status_code == 200 and response.get_json()["known"] is True
    assert sorted(p.name for p in (inbox / "revolut").iterdir()) == ["a.csv"]
    assert _rows(web) == before


def test_a_name_never_carries_a_path(web, inbox):
    _send(web, "../../../../évil name.csv", REVOLUT)
    assert [p.name for p in (inbox / "revolut").iterdir()] == ["evil-name.csv"]
    assert not list(inbox.parent.glob("*.csv"))


@pytest.mark.parametrize("name, content, says", [
    ("releve.xlsx", b"PK\x03\x04", "format non reconnu"),
    ("releve.pdf", b"<html>pas un pdf</html>", "pas un PDF"),
    ("releve.csv", b"\x00\x01\x02binaire", "pas du texte"),
])
def test_what_no_bank_reads_is_turned_away_before_the_disk(web, inbox, name, content, says):
    response = _send(web, name, content)
    assert response.status_code == 400
    assert says in response.get_json()["error"]
    assert not any(p.is_file() for p in inbox.rglob("*"))


def test_a_file_its_parser_cannot_read_is_removed_again(web, inbox):
    """Left in inbox/, it would fail every launch after."""
    before = _rows(web)
    response = _send(web, "vide.csv", "rien,à,voir\n1,2,3\n".encode())
    assert response.status_code == 422
    assert "n'a pas pu être lu" in response.get_json()["error"]
    assert not any(p.is_file() for p in inbox.rglob("*"))
    assert _rows(web) == before


def test_nothing_chosen_says_so(web):
    response = web.post("/api/import", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "Aucun fichier" in response.get_json()["error"]


def test_a_file_far_too_big_for_a_statement_is_refused(web, inbox):
    web.application.config["MAX_CONTENT_LENGTH"] = 1024
    response = _send(web, "gros.csv", b"a,b\n" * 1000)
    assert response.status_code == 413
    assert "trop lourd" in response.get_json()["error"]
    assert not any(p.is_file() for p in inbox.rglob("*"))


def test_another_site_cannot_send_one(web, inbox):
    response = _send(web, "a.csv", REVOLUT, Origin="https://attaquant.example")
    assert response.status_code == 403
    assert not any(p.is_file() for p in inbox.rglob("*"))


def test_placement_never_replaces_a_different_file(tmp_path):
    (tmp_path / "revolut").mkdir()
    (tmp_path / "revolut" / "export.csv").write_bytes(b"autre contenu")
    target, present = banks.placement("export.csv", REVOLUT, tmp_path)
    assert not present and target.name == "export-2.csv"
    target, present = banks.placement("x.pdf", b"%PDF-1.7\n", tmp_path)
    assert target == tmp_path / "x.pdf"


def test_the_table_filters_by_the_account_a_row_comes_from(web, inbox):
    """Swissquote and Revolut in one ledger: each account is a choice of the
    table's filter, named by its bank, and the filter keeps its rows only."""
    _send(web, "account-statement.csv", REVOLUT)
    window = "from=2020-01-01&to=2030-12-31&per=500"
    every = web.get(f"/api/transactions?{window}").get_json()
    accounts = {a["id"]: a["label"] for a in every["accounts"]}
    assert accounts == {"principal": "Swissquote", "revolut": "Revolut"}
    revolut = web.get(f"/api/transactions?{window}&acct=revolut").get_json()
    primary = web.get(f"/api/transactions?{window}&acct=principal").get_json()
    assert revolut["total"] == 8 and primary["total"] + revolut["total"] == every["total"]
    assert revolut["query"]["acct"] == "revolut"
    # The export reads the same filter.
    csv_text = web.get(f"/export.csv?{window}&acct=revolut").get_data(as_text=True)
    assert len([line for line in csv_text.splitlines() if line.strip()]) == 8 + 1


def test_one_bank_offers_no_account_choice(web):
    data = web.get("/api/transactions?from=2020-01-01&to=2030-12-31").get_json()
    assert len(data["accounts"]) == 1
