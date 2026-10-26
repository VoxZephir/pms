"""One export into inbox/ and the ledger, or turned away with the reason.

Two doors lead here: the import page (a file sent from the phone or the PC)
and the Downloads watcher (a statement just downloaded on this PC). Both file
it where its bank's glob reads, ingest it at once, and take it back out when
no parser makes anything of it -- left in inbox/, it would fail every launch
after (docs/releves.md).
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import banks
from .ledger import ingest

# Every ingestion in the server goes through this lock: the ⟳ button, the
# import page and the watcher all rewrite ledger.json, and two at once would
# each save the ledger they read -- the second dropping the first one's rows.
LOCK = threading.Lock()


class Unreadable(Exception):
    """Filed, handed to its parser, and nothing came of it."""


def take(filename: str, content: bytes, inbox: Path, ledger_path: Path,
         pattern: str | None = None) -> dict:
    """File `content` in inbox/ and merge it into the ledger.

    Raises ValueError (no bank reads this kind of file: nothing was written)
    or Unreadable (its parser failed or found no movement: the file was
    removed again). Returns the file's name in inbox/, the rows it added, and
    whether the very same export had been imported before.
    """
    target, present = banks.placement(filename, content, inbox, pattern)
    with LOCK:
        if not present:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        try:
            ledger, reports = ingest([target], ledger_path)
            report = reports[0]
            if not report.get("skipped"):
                if not report.get("rows"):
                    raise ValueError("aucun mouvement lu — est-ce bien un relevé "
                                     "de cette banque ?")
                ledger.save()
        except Exception as exc:  # whatever the parser says, the app stays up
            if not present:
                target.unlink(missing_ok=True)
            raise Unreadable(str(exc)) from exc
    return {"file": target.name, "added": report["added"],
            "known": bool(report.get("skipped"))}
