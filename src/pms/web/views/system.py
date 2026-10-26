"""Health, re-ingestion and the restart button. A statement sent from the
phone goes through `/api/import` (api/imports.py), into the same inbox."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from flask import current_app, jsonify, request

from ... import banks, intake
from .. import updates
from ...ledger import ingest
from .common import bp, store

INBOX = Path(__file__).resolve().parents[4] / "inbox"


# Werkzeug's reloader supervises the serving process and respawns it whenever it
# exits with this code -- that is how the reloader restarts itself on a file
# change, and reusing it is what makes the ⟳ button a real restart rather than a
# cache flush. Anything else (killing the socket, re-exec'ing in place) races the
# old process for the port.
RESTART_EXIT_CODE = 3


# Re-evaluated on every import, so a fresh process is recognisable as fresh: the
# browser polls until the PID changes and only then reloads. Without that it
# would race the dying process and reload the very code it asked to replace.
STARTED_AT = time.time()


def _restartable() -> bool:
    """True when a supervisor is watching that will bring the process back.

    Werkzeug sets this variable in the process it actually serves from; the
    parent is the reloader waiting on it. Outside that -- `--no-reload`, a test
    client, a WSGI host -- exiting would just kill the server for good, so the
    request has to be answered honestly instead.
    """
    return os.environ.get("WERKZEUG_RUN_MAIN") == "true"


def _schedule_restart(delay: float = 0.6) -> None:
    """Leave, once this response is safely on the wire.

    `os._exit` rather than `sys.exit`: raising SystemExit on a timer thread ends
    that thread and nothing else. The delay is what lets the answer -- which
    tells the browser what to wait for -- reach the client before the process
    that owes it disappears.
    """
    threading.Timer(delay, lambda: os._exit(RESTART_EXIT_CODE)).start()


@bp.route("/api/health")
def health():
    """Enough for the browser to tell a restarted server from a dying one."""
    return jsonify({"pid": os.getpid(), "started": STARTED_AT,
                    "restartable": _restartable()})


@bp.route("/api/update")
def update_check():
    """Commits waiting upstream (`updates.check`). Only in the process that
    serves: under the test client, or with `--no-update-check`, nothing."""
    if not current_app.config.get("PMS_UPDATES"):
        return jsonify({"available": False, "reason": "off"})
    return jsonify(updates.check(force=request.args.get("force") == "1"))


@bp.route("/api/update", methods=["POST"])
def update_apply():
    """Pull, then restart -- unless the dependencies changed: those need
    run.bat's `uv sync`, which cannot replace a package this process holds."""
    if not current_app.config.get("PMS_UPDATES"):
        return jsonify({"error": "mise à jour désactivée"}), 409
    try:
        done = updates.apply()
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    restarting = not done["dependencies"] and _restartable()
    if restarting:
        _schedule_restart()
    return jsonify({**done, "restarting": restarting, "pid": os.getpid()})


@bp.route("/api/refresh", methods=["POST"])
def refresh():
    """Re-ingest inbox/, then restart the server.

    Re-reading the ledger was never the hard part -- the store already does that
    on an mtime change. What it could not do is notice that the *code* had
    changed underneath it, so a session spent editing the backend was served by
    whatever was loaded at boot. So the button now does both, in that order: the
    ingestion writes to disk, and the new process picks that file up on its way
    up.

    `?restart=0` keeps the old behaviour, for the cases where dropping the
    process is not wanted.
    """
    data = store()
    added = 0
    imported: list[str] = []
    error = ""

    try:
        with intake.LOCK:
            exports = banks.discover(INBOX)
            if exports:
                ledger, reports = ingest(exports, data.path, strict=False)
                ledger.save()
                added = sum(r["added"] for r in reports)
                imported = [r["file"] for r in reports
                            if not r.get("skipped") and not r.get("refused")]
                error = " ".join(f"{r['file']} : {r['refused']}"
                                 for r in reports if r.get("refused"))
    except Exception as exc:  # a bad PDF must not take the running app down
        error = str(exc)

    data.invalidate()
    statement = data.statement  # rebuild now so the timing is visible here

    # A failed ingestion is exactly when the running code is worth keeping: the
    # error message is on screen, and restarting would throw it away.
    restarting = (not error
                  and request.args.get("restart") != "0"
                  and _restartable())

    payload = {
        "added": added,
        "files": imported,
        "movements": len(statement.transactions),
        "overrides": len(data.overrides),
        "gaps": len(data.gaps),
        "error": error,
        "restarting": restarting,
        "pid": os.getpid(),
    }

    response = jsonify(payload), (500 if error else 200)
    if restarting:
        _schedule_restart()
    return response


# --- a statement sent from the import page ----------------------------------
