"""A statement sent from the phone, and the import log: the `/importer`
page's two halves, as JSON."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from flask import current_app, request
from werkzeug.exceptions import RequestEntityTooLarge

from ... import banks, intake
from ..views import system
from . import api, payload, store


@api.route("/api/imports")
def imports():
    data = store()

    def day(value):
        return dt.date.fromisoformat(value[:10]) if value else None

    log = [] if data.empty else data.sources
    watcher = current_app.extensions.get("pms_watcher")
    return payload({
        "imports": [{"file": s.get("file", "?"), "account": s.get("account", ""),
                     "ingested": day(s.get("ingested_at")), "until": day(s.get("period_end")),
                     "added": s.get("added")}
                    # Newest first; two imports in the same second, the later
                    # one in the log first.
                    for _, s in sorted(enumerate(log), key=lambda p: (p[1].get("ingested_at") or "", p[0]),
                                       reverse=True)[:12]],
        "kinds": [{"label": bank.export, "suffix": Path(pattern).suffix.lower()}
                  for pattern, bank in banks.BANKS.items()],
        "accept": ",".join(banks.accepted_suffixes()),
        "watcher": ({"folder": str(watcher.folder), "last_scan": watcher.last_scan,
                     "events": list(watcher.events)} if watcher else None),
    })


@api.route("/api/import", methods=["POST"])
def import_file():
    """Read a statement, file it in inbox/, ingest it -- or refuse it with
    the reason (a file no parser reads is removed again)."""
    try:
        sent = request.files.get("releve")
    except RequestEntityTooLarge:
        return payload({"error": "Fichier trop lourd pour un relevé (plus de 25 Mo)."}), 413
    if sent is None or not sent.filename:
        return payload({"error": "Aucun fichier choisi."}), 400
    data = store()
    try:
        done = intake.take(sent.filename, sent.read(), system.INBOX, data.path)
    except intake.Unreadable as exc:
        return payload({"error": f"{sent.filename} n'a pas pu être lu : {exc}"}), 422
    except ValueError as exc:
        return payload({"error": f"{sent.filename} : {exc}."}), 400
    data.invalidate()
    return payload({"file": done["file"], "added": done["added"], "known": bool(done["known"])})
