"""Flask front-end for the statement analysis.

    python -m pms.web            # http://127.0.0.1:5000
    run.bat --web

The app reads `data/ledger.json`, the same file `python -m pms` writes, so
ingesting a new statement and refreshing the browser is all it takes.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, render_template

from .store import Store

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = ROOT / "data" / "ledger.json"


def create_app(ledger_path: Path | str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["LEDGER"] = Path(ledger_path or DEFAULT_LEDGER)
    app.extensions["pms_store"] = Store(app.config["LEDGER"])

    # Long, hard-to-read numbers are the norm here; keep them readable in the
    # generated HTML rather than collapsing all whitespace.
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    from .views import bp
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(error):
        """A bad day URL or a stale bookmark lands on a page that says where
        it is and offers a way back -- not on Flask's bare JSON/HTML."""
        return render_template("error.html.j2", status=404), 404

    return app
