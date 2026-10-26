"""The Downloads folder, watched: a statement downloaded on the PC goes in by itself.

Every test gets its own Downloads, inbox and copy of the ledger: the watcher
moves files and rewrites the ledger, and the session ledger is shared.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from types import SimpleNamespace

import pytest
from synthetic import cover_pdf
from test_revolut import HEADER, ROWS

from pms import banks
from pms.ledger import Ledger
from pms.web import watcher as watcher_module
from pms.web.watcher import Watcher

REVOLUT = ("\r\n".join([HEADER, *ROWS]) + "\r\n").encode("utf-8").decode("latin-1").encode("utf-8")
COVER = ["Swissquote Bank SA", "Relevé de transactions",
         "Période du 01.01.2026 à 31.01.2026", "Devise référence Franc suisse"]


@pytest.fixture
def room(tmp_path, ledger_file):
    downloads, inbox = tmp_path / "Téléchargements", tmp_path / "inbox"
    downloads.mkdir()
    inbox.mkdir()
    ledger = tmp_path / "data" / "ledger.json"
    ledger.parent.mkdir()
    shutil.copy(ledger_file, ledger)
    invalidated = []
    store = SimpleNamespace(path=ledger, invalidate=lambda: invalidated.append(1))
    # A clock a minute ahead: every file has settled.
    watch = Watcher(downloads, inbox, store, clock=lambda: time.time() + 60)
    return SimpleNamespace(downloads=downloads, inbox=inbox, ledger=ledger,
                           watch=watch, invalidated=invalidated)


def _rows(room):
    return len(Ledger.load(room.ledger).transactions)


# --- recognising an export by its content -----------------------------------

def test_each_bank_knows_its_own_export(tmp_path):
    (tmp_path / "account-statement.csv").write_bytes(REVOLUT)
    cover_pdf(tmp_path / "n-importe-quel-nom.pdf", COVER)
    assert banks.recognise(tmp_path / "account-statement.csv") == "revolut/*.csv"
    assert banks.recognise(tmp_path / "n-importe-quel-nom.pdf") == "*.pdf"


@pytest.mark.parametrize("name, content", [
    ("facture.pdf", None),                                   # another PDF
    ("crypto.csv", b"Symbol,Type,Quantity,Price,Value,Fees,Date\nETH,Buy,1,2,2,0,x\n"),
    ("liste.csv", b"nom,prix\npain,3\n"),
    ("faux.pdf", b"<html>pas un pdf</html>"),
    ("vide.csv", b""),
])
def test_anything_else_is_nobody_s_export(tmp_path, name, content):
    path = tmp_path / name
    if content is None:
        cover_pdf(path, ["Facture n° 42", "Montant dû : 120.00 CHF"])
    else:
        path.write_bytes(content)
    assert banks.recognise(path) is None


# --- the watcher --------------------------------------------------------------

def test_a_downloaded_export_is_ingested_and_leaves_downloads(room):
    before = _rows(room)
    (room.downloads / "account-statement_2026.csv").write_bytes(REVOLUT)
    events = room.watch.scan()
    assert [e["ok"] for e in events] == [True] and events[0]["added"] == 8
    assert _rows(room) == before + 8
    assert (room.inbox / "revolut" / "account-statement_2026.csv").read_bytes() == REVOLUT
    assert not list(room.downloads.iterdir())
    assert room.invalidated


def test_the_rest_of_downloads_is_never_touched(room):
    cover_pdf(room.downloads / "facture.pdf", ["Facture n° 42"])
    (room.downloads / "liste.csv").write_bytes(b"nom,prix\n")
    (room.downloads / "photo.jpg").write_bytes(b"\xff\xd8")
    stamps = {p.name: p.stat().st_mtime_ns for p in room.downloads.iterdir()}
    assert room.watch.scan() == []
    assert {p.name: p.stat().st_mtime_ns for p in room.downloads.iterdir()} == stamps
    assert not any(p.is_file() for p in room.inbox.rglob("*"))


def test_a_file_still_being_written_waits_for_the_next_look(room):
    (room.downloads / "a.csv").write_bytes(REVOLUT)
    now = time.time()
    room.watch._clock = lambda: now
    assert room.watch.scan() == []
    assert (room.downloads / "a.csv").exists()
    room.watch._clock = lambda: now + 60
    assert [e["ok"] for e in room.watch.scan()] == [True]


def test_a_statement_already_in_inbox_just_leaves_downloads(room):
    """The same export downloaded twice: the second copy adds nothing and
    leaves no clutter behind, in Downloads or in inbox/."""
    (room.downloads / "a.csv").write_bytes(REVOLUT)
    room.watch.scan()
    (room.downloads / "a (1).csv").write_bytes(REVOLUT)
    events = room.watch.scan()
    assert events[0]["ok"] and events[0]["known"]
    assert not list(room.downloads.iterdir())
    assert [p.name for p in (room.inbox / "revolut").iterdir()] == ["a.csv"]


def test_a_statement_its_parser_cannot_read_stays_and_says_why(room):
    """Recognised by its cover, but no movement in it: left in Downloads, out
    of inbox/, the reason kept -- and not tried again every minute."""
    before = _rows(room)
    cover_pdf(room.downloads / "releve.pdf", COVER)
    events = room.watch.scan()
    assert events and not events[0]["ok"] and "aucun mouvement" in events[0]["error"]
    assert (room.downloads / "releve.pdf").exists()
    assert not any(p.is_file() for p in room.inbox.rglob("*"))
    assert _rows(room) == before
    assert room.watch.scan() == []
    # Changed (downloaded again over it): judged again.
    cover_pdf(room.downloads / "releve.pdf", [*COVER, "page 1/1"])
    later = time.time() + 120
    os.utime(room.downloads / "releve.pdf", (later - 100, later - 100))
    assert len(room.watch.scan()) == 1


def test_the_watcher_outlives_a_failing_look(room, monkeypatch):
    def broken():
        raise RuntimeError("disque débranché")
    monkeypatch.setattr(room.watch, "scan", broken)
    stop = threading.Event()
    thread = threading.Thread(target=room.watch.run, args=(stop, 0.01), daemon=True)
    thread.start()
    time.sleep(0.1)
    stop.set()
    thread.join(1)
    assert not thread.is_alive()
    assert room.watch.events and "disque débranché" in room.watch.events[0]["error"]


def test_the_downloads_folder_is_found():
    folder = watcher_module.downloads_folder()
    assert folder is None or folder.is_dir()


# --- what the pages say ---------------------------------------------------------

def test_the_import_page_shows_what_the_watcher_did(client, room):
    (room.downloads / "a.csv").write_bytes(REVOLUT)
    room.watch.scan()
    client.application.extensions["pms_watcher"] = room.watch
    try:
        watcher = client.get("/api/imports").get_json()["watcher"]
    finally:
        del client.application.extensions["pms_watcher"]
    assert watcher["folder"] == str(room.downloads)
    (event,) = watcher["events"]
    assert event["ok"] and event["added"] == 8 and event["file"] == "a.csv"
