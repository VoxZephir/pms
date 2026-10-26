"""Who may talk to the app, now that a phone can reach it.

The server still listens on 127.0.0.1 only. What carries it to the phone is
`tailscale serve`: a proxy on this machine that answers on the tailnet, behind
a real HTTPS certificate, for the user's own devices and nobody else
(docs/acces-distant.md). The app has no login of its own, so three checks keep
that the only way in:

* the Host header must name this machine (`TRUSTED_HOSTS`). Without it, a web
  page that re-points its own domain at 127.0.0.1 (DNS rebinding) reads every
  page here as if it were its own;
* a write must come from one of the app's own pages, by its Origin. There is no
  session cookie to steal, so a foreign page posting a form to /api/refresh is
  the cross-site request this app can suffer -- and the Origin header is what
  tells it apart. A request with neither Origin nor Referer is not a browser
  (the test client, curl): no cross-site request without one;
* the Werkzeug debugger never listens beyond loopback: its console executes
  Python for whoever reaches it.
"""

from __future__ import annotations

import ipaddress
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, current_app, request

LOOPBACK_NAMES = ["localhost", "127.0.0.1"]
# MagicDNS names. Tailscale's DNS resolves them, never to 127.0.0.1, so a
# rebinding page cannot borrow one -- trusting the suffix is what lets the
# phone through even when the name could not be read at startup.
TAILNET_SUFFIX = ".ts.net"
# Tailscale hands out addresses from the carrier-grade NAT block, and IPv6
# from its own prefix: an address there is reachable from the tailnet only.
TAILNET_NETWORKS = [ipaddress.ip_network("100.64.0.0/10"),
                    ipaddress.ip_network("fd7a:115c:a1e0::/48")]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
WINDOWS_CLI = Path(r"C:\Program Files\Tailscale\tailscale.exe")


def _address(host: str):
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    address = _address(host)
    return bool(address and address.is_loopback)


def bind_problem(host: str, debug: bool = False) -> str | None:
    """Why the server must not listen on `host`, or None when it may.

    Loopback is the default and what `tailscale serve` points at. A tailnet
    address is accepted too -- only the user's devices route there. Anything
    else (every interface, a LAN address) would hand an app without a password
    to whichever Wi-Fi the laptop sits on.
    """
    if debug and not is_loopback(host):
        return ("--debug ouvre la console de Werkzeug, qui exécute du Python pour "
                "qui l'atteint : seulement sur 127.0.0.1")
    if is_loopback(host):
        return None
    address = _address(host)
    in_tailnet = (address is not None
                  and any(address in net for net in TAILNET_NETWORKS
                          if net.version == address.version))
    if in_tailnet or host.lower().endswith(TAILNET_SUFFIX):
        return None
    return (f"--host {host} exposerait l'app, qui n'a pas de mot de passe, à tout "
            "le réseau local : garder 127.0.0.1 et passer par `tailscale serve` "
            "(docs/acces-distant.md)")


def tailnet_name(run=subprocess.run) -> str | None:
    """This machine's MagicDNS name (`pc.tail1234.ts.net`), or None.

    None when Tailscale is not installed, not running, or says nothing
    readable: the name only feeds the startup banner and the allowed origins,
    so its absence must never stop the server.
    """
    exe = shutil.which("tailscale") or (str(WINDOWS_CLI) if WINDOWS_CLI.exists() else None)
    if not exe:
        return None
    try:
        out = run([exe, "status", "--json"], capture_output=True, text=True,
                  timeout=4, check=False)
        status = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(status, dict) or status.get("BackendState") != "Running":
        return None
    name = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".").lower()
    return name or None


def install(app: Flask, extra_hosts: list[str] | tuple[str, ...] = ()) -> None:
    extra = [h.strip().lower() for h in extra_hosts if h and h.strip()]
    app.config["TRUSTED_HOSTS"] = [*LOOPBACK_NAMES, TAILNET_SUFFIX, *extra]
    app.config["PMS_EXTRA_ORIGINS"] = set(extra)
    app.before_request(_same_origin)


def _own_hosts() -> set[str]:
    """The host[:port] values a page of this app can be served under."""
    own = {request.host.lower(), *current_app.config.get("PMS_EXTRA_ORIGINS", ())}
    # Behind `tailscale serve` the page's origin is the tailnet name while the
    # request may arrive addressed to 127.0.0.1. The proxy says which name it
    # answered on; a browser cannot forge that header across sites -- it is
    # not one a cross-origin request may carry without a preflight this app
    # never grants.
    forwarded = request.headers.get("X-Forwarded-Host")
    if forwarded:
        own.add(forwarded.split(",")[0].strip().lower())
    return own


def _same_origin():
    if request.method in SAFE_METHODS:
        return None
    claimed = request.headers.get("Origin") or request.headers.get("Referer")
    if claimed is None:
        return None
    # "null" (a sandboxed or privacy-stripped origin) parses to no host.
    origin = urlsplit(claimed).netloc.lower()
    if origin and origin in _own_hosts():
        return None
    abort(403, description=(
        f"Écriture refusée : la requête vient de {origin or 'une origine masquée'}, "
        "pas d'une page de l'app."))
