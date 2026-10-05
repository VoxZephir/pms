"""Loads the ledger once and serves period-scoped views of it.

Why a store rather than parsing per request
-------------------------------------------
`analysis.annotate_chf` scales every foreign amount against that currency's full
set of conversions, so it must see the whole ledger exactly once. Running it per
request -- or on a slice -- would produce different CHF values for the same
transaction depending on the window being viewed. So the ledger is annotated
once, up front, and every view is a filter over those same annotated objects.

The ledger file is re-read when its mtime changes, so `run.bat` in another window
is picked up without restarting the server.
"""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path

from .. import analysis, buckets
from .. import categories as categories_module
from ..categories import classify_all
from ..ledger import Ledger
from ..models import Statement
from ..overrides import Overrides


class Store:
    def __init__(self, ledger_path: Path, overrides_path: Path | None = None):
        self.path = Path(ledger_path)
        self.overrides_path = Path(
            overrides_path or self.path.with_name("overrides.json"))
        self.local_rules_path = self.path.with_name("local_rules.json")
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._statement: Statement | None = None
        self.overrides = Overrides.load(self.overrides_path)
        self.sources: list[dict] = []
        self.gaps: list[dict] = []

    # --- loading ---------------------------------------------------------

    def _load(self) -> Statement:
        ledger = Ledger.load(self.path)
        statement = ledger.to_statement()

        # The personal rules are re-read from disk on every load, so an edit
        # made from the app reclassifies on the next request, no restart
        # needed. `classify_all` gets the freshly compiled set; when no rules
        # file sits next to this ledger it gets None and the boot-time set
        # stands -- a never-created file is the same "no personal rules" as
        # at import, not a reason to drop the ones this process booted with.
        rules = None
        if self.local_rules_path.exists():
            rules = categories_module.compile_rules(
                categories_module.load_local_rules(self.local_rules_path))

        # Order matters. The static rules run first, manual corrections overlay
        # them, and only then is the Need/Want/Save mapping read -- otherwise a
        # reclassified transaction would keep the bucket of its old category.
        classify_all(statement.transactions, rules)
        self.overrides = Overrides.load(self.overrides_path)
        self.override_count = self.overrides.apply(statement.transactions)
        analysis.annotate_chf(statement)
        buckets.annotate(statement.transactions)

        self.sources = ledger.sources
        self.gaps = ledger.gaps()
        return statement

    def _fingerprint(self) -> tuple:
        """Reload when any watched file changes, so edits from another process
        land. The local rules are watched too: the app edits them itself, and a
        rule added here must reclassify on the next request."""
        def stamp(path: Path):
            return path.stat().st_mtime if path.exists() else None
        return (stamp(self.path), stamp(self.overrides_path),
                stamp(self.local_rules_path))

    @property
    def statement(self) -> Statement:
        with self._lock:
            stamp = self._fingerprint()
            if self._statement is None or stamp != self._stamp:
                self._statement = self._load()
                self._stamp = stamp
            return self._statement

    def invalidate(self) -> None:
        """Force a rebuild after this process edited the overrides."""
        with self._lock:
            self._stamp = None

    @property
    def empty(self) -> bool:
        return not self.statement.transactions

    # --- windows ---------------------------------------------------------

    @property
    def bounds(self) -> tuple[dt.date, dt.date]:
        rows = self.statement.transactions
        if not rows:
            today = dt.date.today()
            return today, today
        return rows[0].date, rows[-1].date

    def window(self, start: dt.date | None, end: dt.date | None) -> Statement:
        """A statement restricted to [start, end], clamped to what we hold."""
        low, high = self.bounds
        return analysis.slice_period(
            self.statement,
            max(start, low) if start else low,
            min(end, high) if end else high,
        )
