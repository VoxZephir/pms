"""`--backup`: data/ and inbox/ encrypted elsewhere, only when they changed;
`--restore`: back into place, never over anything."""

from __future__ import annotations

import datetime as dt
import zipfile

import pytest
from cryptography.fernet import Fernet

from pms import backup, cli

KEY = Fernet.generate_key()


def _tree(tmp_path):
    data, inbox = tmp_path / "repo" / "data", tmp_path / "repo" / "inbox"
    (inbox / "revolut").mkdir(parents=True)
    data.mkdir()
    (data / "overrides.json").write_text('{"pins": {}}', encoding="utf-8")
    (inbox / "revolut" / "export.csv").write_text("a,b\n", encoding="utf-8")
    return {"data": data, "inbox": inbox}


def _at(minute):
    return dt.datetime(2026, 10, 8, 10, minute)


def _run(sources, dest, **kwargs):
    return backup.backup(sources, dest, key=KEY, **kwargs)


def test_a_backup_holds_data_and_inbox_under_their_own_names(tmp_path):
    sources = _tree(tmp_path)
    done = _run(sources, tmp_path / "out", now=_at(0))
    assert not done["skipped"] and done["files"] == 2
    with backup.open_copy(done["path"], KEY) as archive:
        assert sorted(archive.namelist()) == ["data/overrides.json",
                                              "inbox/revolut/export.csv"]
        assert archive.read("data/overrides.json") == b'{"pins": {}}'


def test_the_copy_on_disk_reads_as_nothing_without_the_key(tmp_path):
    """The destination is someone else's cloud: what lands there must not be
    a zip, nor carry a line of the statements in clear."""
    sources = _tree(tmp_path)
    done = _run(sources, tmp_path / "out", now=_at(0))
    raw = done["path"].read_bytes()
    assert done["path"].name.endswith(".zip.enc")
    assert not zipfile.is_zipfile(done["path"])
    assert b"pins" not in raw and b"export.csv" not in raw
    with pytest.raises(ValueError, match="clé incorrecte"):
        backup.open_copy(done["path"], Fernet.generate_key())


def test_the_key_never_travels_with_the_copy(tmp_path):
    """A copy that carried its own key would be no lock at all."""
    sources = _tree(tmp_path)
    key, created = backup.ensure_key(sources["data"])
    assert created and backup.ensure_key(sources["data"]) == (key, False)
    done = backup.backup(sources, tmp_path / "out", key=key, now=_at(0),
                         exclude={backup.key_path(sources["data"])})
    with backup.open_copy(done["path"], key) as archive:
        assert "data/backup.key" not in archive.namelist()
        assert "data/overrides.json" in archive.namelist()


def test_nothing_is_written_when_nothing_changed(tmp_path):
    """run.bat backs up at every launch: identical copies would push the
    one that mattered out of the kept set."""
    sources = _tree(tmp_path)
    first = _run(sources, tmp_path / "out", now=_at(0))
    # Rewritten byte for byte, as an ingestion does: still no change.
    path = sources["data"] / "overrides.json"
    path.write_bytes(path.read_bytes())
    again = _run(sources, tmp_path / "out", now=_at(1))
    assert again["skipped"] and again["path"] == first["path"]
    assert len(backup.copies(tmp_path / "out")) == 1


def test_a_new_key_writes_a_new_copy(tmp_path):
    """The last copy cannot be read under another key, so it cannot vouch
    that nothing changed."""
    sources = _tree(tmp_path)
    _run(sources, tmp_path / "out", now=_at(0))
    other = backup.backup(sources, tmp_path / "out", key=Fernet.generate_key(), now=_at(1))
    assert not other["skipped"]


def test_a_change_makes_a_new_copy_and_the_oldest_ones_go(tmp_path):
    sources = _tree(tmp_path)
    for minute in range(4):
        (sources["data"] / "overrides.json").write_text(f'{{"n": {minute}}}',
                                                        encoding="utf-8")
        _run(sources, tmp_path / "out", keep=2, now=_at(minute))
    kept = backup.copies(tmp_path / "out")
    assert [p.name for p in kept] == ["pms-20261008-100200.zip.enc",
                                      "pms-20261008-100300.zip.enc"]
    with backup.open_copy(kept[-1], KEY) as archive:
        assert archive.read("data/overrides.json") == b'{"n": 3}'


def test_the_copies_from_before_the_encryption_are_named_not_deleted(tmp_path):
    """They are the only copies the old way could restore; removing them is
    the user's call, once the key is safe."""
    sources = _tree(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    old = out / "pms-20261001-090000.zip"
    with zipfile.ZipFile(old, "w") as archive:
        archive.writestr("data/overrides.json", "{}")
    done = _run(sources, out, keep=1, now=_at(0))
    assert done["plain"] == [old] and old.exists()
    assert backup.copies(out) == [done["path"]]


def test_a_destination_inside_the_repository_is_refused(tmp_path):
    """In the repository, a copy of the statements is one `git add -A`
    away from being published; inside data/ it would zip itself."""
    sources = _tree(tmp_path)
    with pytest.raises(ValueError):
        _run(sources, tmp_path / "repo" / "sauvegardes", repo=tmp_path / "repo")
    with pytest.raises(ValueError):
        _run(sources, sources["data"] / "copies")


def test_a_restore_lays_the_tree_back_out(tmp_path):
    sources = _tree(tmp_path)
    done = _run(sources, tmp_path / "out", now=_at(0))
    fresh = tmp_path / "clone"
    written = backup.restore(done["path"], KEY, fresh)
    assert len(written) == 2
    assert (fresh / "data" / "overrides.json").read_text(encoding="utf-8") == '{"pins": {}}'
    assert (fresh / "inbox" / "revolut" / "export.csv").exists()


def test_a_restore_never_overwrites(tmp_path):
    """Over a live data/, an older copy would erase the corrections made
    since. One file in the way stops the whole restore."""
    sources = _tree(tmp_path)
    done = _run(sources, tmp_path / "out", now=_at(0))
    (sources["data"] / "overrides.json").write_text('{"newer": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="rien n'a été écrasé"):
        backup.restore(done["path"], KEY, tmp_path / "repo")
    assert "newer" in (sources["data"] / "overrides.json").read_text(encoding="utf-8")


def test_a_mistyped_key_is_named_as_such():
    with pytest.raises(ValueError, match="44 caractères"):
        backup.check_key(b"pas-une-cle")
    assert backup.check_key(KEY + b"\n") == KEY


def test_the_cli_writes_to_the_folder_given(tmp_path, monkeypatch, capsys):
    sources = _tree(tmp_path)
    monkeypatch.setattr(cli, "INBOX", sources["inbox"])
    out = tmp_path / "out"
    code = cli.main(["--ledger", str(sources["data"] / "ledger.json"),
                     "--backup", str(out), "--keep", "3"])
    assert code == 0
    assert len(backup.copies(out)) == 1
    said = capsys.readouterr().out
    assert "2 fichiers" in said and "clé de chiffrement créée" in said
    # The key is named, never printed.
    key = backup.key_path(sources["data"]).read_text(encoding="ascii").strip()
    assert key not in said
    assert cli.main(["--ledger", str(sources["data"] / "ledger.json"),
                     "--backup", str(out)]) == 0
    said = capsys.readouterr().out
    assert "rien n'a changé" in said and "clé" not in said


def test_the_cli_restores_with_the_key_on_disk(tmp_path, monkeypatch, capsys):
    sources = _tree(tmp_path)
    monkeypatch.setattr(cli, "INBOX", sources["inbox"])
    out, clone = tmp_path / "out", tmp_path / "clone"
    ledger = str(sources["data"] / "ledger.json")
    assert cli.main(["--ledger", ledger, "--backup", str(out)]) == 0
    archive = backup.copies(out)[-1]
    assert cli.main(["--ledger", ledger, "--restore", str(archive),
                     "--into", str(clone)]) == 0
    assert "2 fichiers" in capsys.readouterr().out
    assert (clone / "data" / "overrides.json").exists()


def test_the_cli_asks_for_the_key_on_a_fresh_clone(tmp_path, monkeypatch, capsys):
    """After a lost disk there is no data/backup.key: the key comes from the
    password manager, typed without echo."""
    sources = _tree(tmp_path)
    archive = _run(sources, tmp_path / "out", now=_at(0))["path"]
    monkeypatch.setattr("getpass.getpass", lambda prompt="": KEY.decode())
    empty = tmp_path / "nouveau" / "data"
    assert cli.main(["--ledger", str(empty / "ledger.json"), "--restore", str(archive),
                     "--into", str(tmp_path / "nouveau")]) == 0
    assert (tmp_path / "nouveau" / "inbox" / "revolut" / "export.csv").exists()


def test_the_cli_refuses_a_restore_inside_the_repository(tmp_path, monkeypatch, capsys):
    """Anywhere in the repository but its root, the restored data/ and
    inbox/ would not be git-ignored."""
    sources = _tree(tmp_path)
    archive = _run(sources, tmp_path / "out", now=_at(0))["path"]
    code = cli.main(["--ledger", str(sources["data"] / "ledger.json"),
                     "--restore", str(archive), "--into", str(cli.ROOT / "restauration")])
    assert code == 2
    assert "dans le dépôt" in capsys.readouterr().err
    assert not (cli.ROOT / "restauration").exists()


def test_a_copy_is_read_back_in_full(tmp_path):
    done = _run(_tree(tmp_path), tmp_path / "out", now=_at(0))
    assert backup.verify(done["path"], KEY) == 2


@pytest.mark.parametrize("damage", ["truncate", "key"])
def test_a_copy_that_does_not_read_back_is_named(tmp_path, damage):
    """A sync client cutting the file short, a key replaced by hand: the
    first sign must not be the day of the lost disk."""
    done = _run(_tree(tmp_path), tmp_path / "out", now=_at(0))
    if damage == "truncate":
        blob = done["path"].read_bytes()
        done["path"].write_bytes(blob[: len(blob) // 2])
    with pytest.raises(ValueError, match=done["path"].name):
        backup.verify(done["path"], KEY if damage == "truncate" else Fernet.generate_key())


def test_the_cli_reads_the_new_copy_back_and_says_so_to_the_app(tmp_path, monkeypatch, capsys):
    sources = _tree(tmp_path)
    monkeypatch.setattr(cli, "INBOX", sources["inbox"])
    ledger, out = str(sources["data"] / "ledger.json"), tmp_path / "out"
    assert backup.health(sources["data"])["title"] == "Aucune sauvegarde"
    assert cli.main(["--ledger", ledger, "--backup", str(out)]) == 0
    assert "relue en entier, 2 fichiers intacts" in capsys.readouterr().out
    status = backup.read_status(sources["data"])
    assert status["ok"] and status["verified_copy"] == backup.copies(out)[-1].name
    assert backup.health(sources["data"]) is None
    # The status file itself is not backed up: writing it is not a change.
    assert cli.main(["--ledger", ledger, "--backup", str(out)]) == 0
    assert len(backup.copies(out)) == 1
    # Two weeks without a run: said.
    later = dt.datetime.fromisoformat(status["ran_at"]) + backup.STALE_AFTER
    assert backup.health(sources["data"], later)["title"] == "Sauvegarde ancienne"

    # A copy that no longer reads: the run fails, and the app says so.
    copy = backup.copies(out)[-1]
    copy.write_bytes(copy.read_bytes()[:40])
    (sources["data"] / "overrides.json").write_text('{"pins": {"x": 1}}', encoding="utf-8")
    monkeypatch.setattr(backup, "verify", lambda *a: (_ for _ in ()).throw(ValueError("copie abîmée")))
    assert cli.main(["--ledger", ledger, "--backup", str(out)]) == 2
    warning = backup.health(sources["data"])
    assert warning["title"] == "Sauvegarde en échec" and "copie abîmée" in warning["detail"]
