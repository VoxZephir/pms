"""Who may talk to the app: the Host, the Origin of a write, the bind address.

The app has no login. On 127.0.0.1 that was enough; reached from a phone
through `tailscale serve`, these checks are what keeps a foreign web page --
open in the same browser -- from reading the pages (DNS rebinding) or posting
to them (a cross-site form).
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from pms.web import create_app, guard


@pytest.fixture
def app(ledger_file):
    app = create_app(ledger_file, ["pc.tail1234.ts.net"])
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def web(app):
    with app.test_client() as c:
        yield c


# --- the Host header --------------------------------------------------------

@pytest.mark.parametrize("host", ["localhost", "127.0.0.1:5000",
                                  "pc.tail1234.ts.net", "autre.tail1234.ts.net"])
def test_the_machine_s_own_names_are_served(web, host):
    assert web.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["attaquant.example", "127.0.0.1.attaquant.example",
                                  "ts.net.attaquant.example"])
def test_a_foreign_host_is_refused(web, host):
    """A page that rebinds its own domain to 127.0.0.1 sends its own name
    as the Host: refused before any route reads the ledger."""
    assert web.get("/", headers={"Host": host}).status_code == 400


# --- the Origin of a write --------------------------------------------------

def _post(web, **headers):
    # A route that refuses an empty body with 400 once past the guard: the
    # guard's 403 is the only way to get anything else.
    return web.post("/api/reclassify", json={}, headers=headers)


def test_a_write_from_the_app_s_own_page_passes(web):
    assert _post(web, Origin="http://localhost").status_code == 400


def test_a_write_from_another_site_is_refused(web):
    response = _post(web, Origin="https://attaquant.example",
                     Accept="application/json")
    assert response.status_code == 403
    assert "attaquant.example" in response.get_json()["error"]


def test_another_local_app_is_another_origin(web):
    """Same machine, other port: a different site, with its own scripts."""
    assert _post(web, Origin="http://localhost:3000").status_code == 403


def test_a_masked_origin_is_refused(web):
    """"null" is what a sandboxed frame or a stripped referrer sends."""
    assert _post(web, Origin="null").status_code == 403


def test_the_referer_stands_in_for_a_missing_origin(web):
    assert _post(web, Referer="https://attaquant.example/page").status_code == 403
    assert _post(web, Referer="http://localhost/transactions").status_code == 400


def test_a_client_that_is_not_a_browser_is_let_through(web):
    """No Origin and no Referer: curl, the test client. A cross-site request
    always carries one of them, so this is not the attack."""
    assert _post(web).status_code == 400


def test_the_tailnet_page_may_write_through_the_proxy(web):
    """Behind `tailscale serve` the page's origin is the tailnet name, while
    the request itself may be addressed to 127.0.0.1."""
    tailnet = "https://pc.tail1234.ts.net"
    assert _post(web, Origin=tailnet, Host="127.0.0.1:5000").status_code == 400
    assert _post(web, Origin="https://autre.tail9999.ts.net",
                 Host="127.0.0.1:5000").status_code == 403
    # The name the proxy answered on, even when it was not read at startup.
    bare = create_app(web.application.config["LEDGER"])
    bare.config.update(TESTING=True)
    with bare.test_client() as c:
        assert _post(c, Origin="https://pc.tail5678.ts.net", Host="127.0.0.1:5000",
                     **{"X-Forwarded-Host": "pc.tail5678.ts.net"}).status_code == 400
        assert _post(c, Origin="https://pc.tail5678.ts.net",
                     Host="127.0.0.1:5000").status_code == 403


def test_a_refused_write_says_why(web):
    response = web.post("/api/budgets", json={}, headers={"Origin": "https://attaquant.example"})
    assert response.status_code == 403
    assert "attaquant.example" in response.get_json()["error"]


# --- where the server listens -----------------------------------------------

@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "100.101.102.103",
                                  "fd7a:115c:a1e0::1", "pc.tail1234.ts.net"])
def test_loopback_and_the_tailnet_are_fine(host):
    assert guard.bind_problem(host) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "10.0.0.5"])
def test_every_interface_or_the_lan_is_refused(host):
    """Without a password, the LAN of whichever café the laptop is in."""
    assert "tailscale serve" in guard.bind_problem(host)


def test_the_debugger_stays_on_loopback():
    """Werkzeug's console executes Python for whoever reaches it."""
    assert guard.bind_problem("127.0.0.1", debug=True) is None
    assert "console" in guard.bind_problem("100.101.102.103", debug=True)


def test_the_server_will_not_start_on_the_lan(monkeypatch, capsys):
    """Refused before anything listens -- not a warning printed while it
    already serves."""
    import sys

    from pms.web import __main__ as entry
    monkeypatch.setattr(sys, "argv", ["pms.web", "--host", "0.0.0.0"])
    monkeypatch.setattr(entry, "create_app", lambda *a, **k: pytest.fail("app built"))
    assert entry.main() == 2
    assert "tailscale serve" in capsys.readouterr().err


# --- reading the tailnet name -----------------------------------------------

def _status(payload):
    def run(*args, **kwargs):
        return SimpleNamespace(stdout=json.dumps(payload) if payload is not None else "")
    return run


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda name: "tailscale")


def test_the_tailnet_name_is_read_from_tailscale(cli):
    status = {"BackendState": "Running", "Self": {"DNSName": "PC.tail1234.ts.net."}}
    assert guard.tailnet_name(run=_status(status)) == "pc.tail1234.ts.net"


@pytest.mark.parametrize("payload", [None, {"BackendState": "Stopped"},
                                     {"BackendState": "Running", "Self": {}}])
def test_no_name_when_tailscale_has_none_to_give(cli, payload):
    assert guard.tailnet_name(run=_status(payload)) is None


def test_no_name_when_tailscale_does_not_answer(cli):
    def hangs(*args, **kwargs):
        raise subprocess.TimeoutExpired("tailscale", 4)
    assert guard.tailnet_name(run=hangs) is None


def test_no_name_without_tailscale(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda name: None)
    monkeypatch.setattr(guard, "WINDOWS_CLI", guard.Path("nowhere/tailscale.exe"))
    assert guard.tailnet_name(run=_status({"BackendState": "Running"})) is None
