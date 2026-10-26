"""The Downloads folder, watched: a statement downloaded on this PC goes in by itself.

The bank's own step stays manual -- log in, export; no bank here offers a way
round it (docs/releves.md). Everything after it is this. Every minute the
running server looks at Downloads; a file one of the banks recognises as its
export -- by content, never by name -- is filed into inbox/, ingested, and
removed from Downloads. The dashboard's "Nouveau relevé" says it arrived.

Anything else in Downloads is never touched: an invoice, a ticket, a statement
of another kind (the Revolut crypto one) are read once, found to be nobody's
export, and remembered as such until they change.
"""

from __future__ import annotations

import datetime as dt
import sys
import threading
import time
from collections import deque
from pathlib import Path

from .. import banks, intake

INTERVAL = 60      # seconds between two looks
# A browser writes a download under a temporary name and renames it when done;
# a file written in place by anything else gets this long to finish.
SETTLE = 5
HISTORY = 8        # what the import page lists


def downloads_folder() -> Path | None:
    """Windows' own Downloads folder -- wherever the user moved it -- or
    ~/Downloads elsewhere. None when there is none."""
    if sys.platform == "win32":
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
            folder_id = GUID.from_buffer_copy(
                uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}").bytes_le)
            found = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(folder_id), 0, None, ctypes.byref(found)) == 0:
                path = Path(found.value)
                ctypes.windll.ole32.CoTaskMemFree(found)
                if path.is_dir():
                    return path
        except (OSError, AttributeError, ValueError):
            pass
    path = Path.home() / "Downloads"
    return path if path.is_dir() else None


class Watcher:
    def __init__(self, folder: Path, inbox: Path, store, clock=time.time):
        self.folder = Path(folder)
        self.inbox = Path(inbox)
        self.store = store
        self.events: deque[dict] = deque(maxlen=HISTORY)
        self.last_scan: dt.datetime | None = None
        self._seen: set[tuple] = set()
        self._clock = clock

    def scan(self) -> list[dict]:
        """One look at the folder. Returns what was taken or turned away."""
        found = []
        try:
            entries = sorted(p for p in self.folder.iterdir() if p.is_file())
        except OSError:
            entries = []
        suffixes = set(banks.accepted_suffixes())
        for path in entries:
            if path.suffix.lower() not in suffixes:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            # A file is judged once per version of it: name, size and time.
            key = (path.name, stat.st_size, stat.st_mtime_ns)
            if key in self._seen:
                continue
            if self._clock() - stat.st_mtime < SETTLE:
                continue                       # still being written: next look
            self._seen.add(key)
            pattern = banks.recognise(path)
            if pattern is None:
                continue
            event = self._take(path, pattern)
            found.append(event)
            self.events.appendleft(event)
        self.last_scan = dt.datetime.now()
        return found

    def _take(self, path: Path, pattern: str) -> dict:
        event = {"file": path.name, "at": dt.datetime.now()}
        try:
            done = intake.take(path.name, path.read_bytes(), self.inbox,
                               self.store.path, pattern)
        except (ValueError, intake.Unreadable, OSError) as exc:
            # Left where it is, and not retried until it changes: the reason
            # is on the import page.
            print(f"Téléchargements : {path.name} refusé — {exc}", flush=True)
            return {**event, "ok": False, "error": str(exc)}
        # Moved, not copied: it is in inbox/ now, and inbox/ is backed up.
        try:
            path.unlink()
        except OSError:
            pass  # held open elsewhere: harmless, its digest is known now
        self.store.invalidate()
        print(f"Téléchargements : {path.name} → {done['added']} mouvement(s) ajouté(s)",
              flush=True)
        return {**event, "ok": True, "added": done["added"], "known": done["known"]}

    def run(self, stop: threading.Event, interval: float = INTERVAL) -> None:
        """Look now, then every `interval` seconds, until `stop` is set. A look
        that fails is reported, and the next one tries again: the thread
        must outlive any single bad file."""
        while True:
            try:
                self.scan()
            except Exception as exc:  # never let the watcher die silently
                self.events.appendleft({"file": "", "at": dt.datetime.now(),
                                        "ok": False, "error": str(exc)})
            if stop.wait(interval):
                return

    def start(self, interval: float = INTERVAL) -> threading.Event:
        stop = threading.Event()
        threading.Thread(target=self.run, args=(stop, interval), daemon=True,
                         name="pms-downloads").start()
        return stop
