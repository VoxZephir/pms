"""Health, re-ingestion, restart, and the CLI flags run.bat forwards."""

from __future__ import annotations


def test_the_cli_accepts_every_flag_run_bat_forwards(tmp_path, ledger_file):
    """run.bat passes its own mode flag straight through to the CLI. An
    unrecognised one makes argparse exit, so `run.bat --report` died."""
    import re as _re
    from pathlib import Path

    from pms import cli

    script = (Path(__file__).resolve().parents[1] / "run.bat").read_text(
        encoding="utf-8", errors="replace")
    forwarded = set(_re.findall(r'MODE%"=="(--[a-z-]+)"', script))
    assert forwarded, "run.bat must define at least one mode"

    parser_flags = set()
    for line in cli.__doc__.splitlines():
        parser_flags.update(_re.findall(r"(--[a-z-]+)", line))

    handled = {"--test"}          # intercepted by run.bat, never reaches Python
    for flag in forwarded - handled:
        assert flag in parser_flags, f"{flag} is forwarded but undocumented"


# --- reloading and restarting -----------------------------------------------

def test_health_identifies_the_process(client):
    payload = client.get("/api/health").get_json()
    import os
    assert payload["pid"] == os.getpid()
    assert payload["started"] > 0


def test_refresh_never_exits_a_process_nobody_is_watching(client, tmp_path,
                                                        monkeypatch):
    """The restart works by exiting with the code Werkzeug's supervisor respawns
    on. Without a supervisor -- a test client, `--no-reload`, a WSGI host --
    that is not a restart, it is the end of the server. The suite finishing is
    itself the assertion; the flag says so out loud.

    The route re-ingests inbox/ into the client's ledger, so the real inbox
    must not leak into the shared tmp ledger: point it at an empty directory,
    or the statements the user dropped there reclassify the other tests' view
    of the ledger."""
    import pms.web.views.system as system_views
    monkeypatch.setattr(system_views, "INBOX", tmp_path)
    payload = client.post("/api/refresh",
                          headers={"Accept": "application/json"}).get_json()
    assert payload["restarting"] is False
    assert payload["added"] == 0  # nothing ingested, ledger untouched


def test_refresh_can_be_asked_not_to_restart(client, tmp_path, monkeypatch):
    import pms.web.views.system as system_views
    monkeypatch.setattr(system_views, "INBOX", tmp_path)
    payload = client.post("/api/refresh?restart=0",
                          headers={"Accept": "application/json"}).get_json()
    assert payload["restarting"] is False
