"""Flask back end for the statement analysis, and the React app it serves.

    python -m pms.web            # http://127.0.0.1:5000
    run.bat --web

The app reads `data/ledger.json`, the same file `python -m pms` writes, so
ingesting a new statement and refreshing the browser is all it takes. Flask
computes; the page in the browser (frontend/, built into static/spa/) lays
out and draws.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from flask import Flask, jsonify, request

from . import compress, guard
from .store import Store

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = ROOT / "data" / "ledger.json"

# A two-year Swissquote statement is about a megabyte; a CSV export far less.
# Anything near this is not a statement, and refusing it early keeps a stray
# upload from filling the disk the ledger lives on.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Python's table does not know the manifest's extension: served as
# octet-stream, a phone would not read it as the app's manifest.
mimetypes.add_type("application/manifest+json", ".webmanifest")


def create_app(ledger_path: Path | str | None = None,
               allowed_hosts: list[str] | tuple[str, ...] = ()) -> Flask:
    """`allowed_hosts`: names this app is also served under -- the tailnet
    name `tailscale serve` answers on, read at startup (`guard.tailnet_name`)."""
    app = Flask(__name__)
    app.config["LEDGER"] = Path(ledger_path or DEFAULT_LEDGER)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.extensions["pms_store"] = Store(app.config["LEDGER"])
    guard.install(app, allowed_hosts)
    compress.install(app)

    from .api import api, index
    from .views import bp
    app.register_blueprint(bp)
    app.register_blueprint(api)

    def _is_page(path: str) -> bool:
        return not path.startswith(("/api/", "/static/"))

    @app.errorhandler(404)
    def not_found(error):
        """A stale bookmark lands on the app, whose router says the page does
        not exist and offers the way back; the API answers in JSON."""
        if _is_page(request.path) and request.method == "GET":
            return index(404)
        return jsonify({"error": "introuvable"}), 404

    @app.errorhandler(403)
    def refused(error):
        """A write from a foreign page (guard._same_origin)."""
        return jsonify({"error": error.description}), 403

    return app
