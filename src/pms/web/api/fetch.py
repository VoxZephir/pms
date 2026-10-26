"""The savings page's "Rafraîchir" button: IBKR, the indices, the inflation
and the crypto fetched again (`refresh.py`), the run that `run.bat` does once
a day at launch, on demand.

The Flex service takes up to a minute, so the run goes in a thread of its
own and the page asks how it is going. One run at a time: a second press
while one is on returns the first one's state.
"""

from __future__ import annotations

import datetime as dt
import threading

from flask import current_app

from ... import refresh
from ..views import system
from . import api, payload, store

LOCK = threading.Lock()


def _state() -> dict:
    return current_app.extensions.setdefault("pms_fetch", {"running": False})


def _view(state: dict) -> dict:
    data_dir = store().path.parent
    record = refresh.load(data_dir)
    return {
        "running": state.get("running", False),
        "started": state.get("started"),
        "error": state.get("error", ""),
        "at": record.get("at"),
        "last": record.get("last"),
        "due": refresh.due(data_dir),
    }


@api.route("/api/fetch")
def fetch_state():
    return payload(_view(_state()))


@api.route("/api/fetch", methods=["POST"])
def fetch_start():
    state = _state()
    with LOCK:
        if state.get("running"):
            return payload(_view(state))
        state.update(running=True, error="", started=dt.datetime.now().isoformat(timespec="seconds"))
    data = store()
    ledger_path, inbox = data.path, system.INBOX

    def work():
        try:
            refresh.run(ledger_path, inbox)
        except Exception as exc:  # said on the page, never a stuck "en cours"
            state["error"] = f"échec ({type(exc).__name__})"
        finally:
            data.invalidate()  # the savings read their files again on the next request
            state["running"] = False

    threading.Thread(target=work, name="pms-fetch", daemon=True).start()
    return payload(_view(state)), 202
