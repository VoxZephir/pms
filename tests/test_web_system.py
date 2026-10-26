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


def test_the_phone_finds_a_manifest_and_its_icons(client):
    """"Add to home screen" reads the manifest; iOS reads only the 180 px
    apple-touch-icon. Served as a manifest, or a phone ignores it."""
    page = client.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in page and "icon-180.png" in page
    response = client.get("/static/manifest.webmanifest")
    assert response.mimetype == "application/manifest+json"
    manifest = response.get_json(force=True)
    # minimal-ui keeps a back button: the app leans on the browser's history.
    assert manifest["start_url"] == "/" and manifest["display"] == "minimal-ui"
    assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])
    for icon in [*manifest["icons"], {"src": "/static/icon-180.png"}]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]


def test_refresh_can_be_asked_not_to_restart(client, tmp_path, monkeypatch):
    import pms.web.views.system as system_views
    monkeypatch.setattr(system_views, "INBOX", tmp_path)
    payload = client.post("/api/refresh?restart=0",
                          headers={"Accept": "application/json"}).get_json()
    assert payload["restarting"] is False
