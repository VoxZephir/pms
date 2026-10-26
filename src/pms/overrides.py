"""Manual reclassification that survives the next import.

Why this is a separate file from the ledger
-------------------------------------------
`data/ledger.json` is derived data: it is rebuilt from the PDFs and must stay a
faithful copy of what the bank printed. Editing a category in place there would
be lost the moment a statement is re-ingested, and worse, it would blur the line
between what the bank said and what you decided. So corrections live in
`data/overrides.json` and are applied *on top* of the rule engine at load time.

Two kinds of correction, deliberately distinct:

* a **pin** on one movement, keyed on `(reference, currency)` -- the same
  identity the ledger dedupes on, so it survives re-import;
* a **rule** on a counterparty, which catches that counterparty's past *and
  future* movements. This is the one that makes the correction permanent: next
  month's payment to the same merchant lands in the right place without you
  touching anything.

Precedence, from weakest to strongest: static rules in `categories.py`, then
learned merchant rules, then per-transaction pins. A pin always wins, so
correcting one odd payment never fights the rule you set for its merchant.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
from pathlib import Path
from typing import Iterable

from . import categories
from .models import Transaction

VERSION = 1
EXACT = "exact"
CONTAINS = "contains"


def key_of(txn: Transaction) -> str:
    """Same identity the ledger uses, so a pin survives re-ingestion."""
    return f"{txn.reference}:{txn.currency}"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _valid(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


class Overrides:
    """The set of manual corrections, loaded from and saved to one JSON file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.pins: dict[str, dict] = {}
        self.rules: list[dict] = []
        self.aliases: dict[str, str] = {}
        self.alias_patterns: list[dict] = []

    # --- persistence -----------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> "Overrides":
        store = cls(path)
        if not store.path.exists():
            return store
        try:
            raw = json.loads(store.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt overrides file must not take the whole app down; the
            # ledger is the source of truth and still renders without it.
            return store
        store.pins = raw.get("transactions", {})
        store.rules = raw.get("merchants", [])
        store.aliases = raw.get("aliases", {})
        store.alias_patterns = [
            entry for entry in raw.get("alias_patterns", [])
            if entry.get("pattern") and entry.get("canonical")
            and _valid(entry["pattern"])
        ]
        return store

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": VERSION,
            "transactions": self.pins,
            "merchants": self.rules,
            "aliases": self.aliases,
            "alias_patterns": self.alias_patterns,
        }
        # Write then move, so an interrupted save cannot leave a truncated file.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        temporary.replace(self.path)
        return self.path

    def __len__(self) -> int:
        return (len(self.pins) + len(self.rules)
                + len(self.aliases) + len(self.alias_patterns))

    @property
    def empty(self) -> bool:
        return not (self.pins or self.rules or self.aliases or self.alias_patterns)

    # --- editing ---------------------------------------------------------

    def pin(self, key: str, *, category: str = "", subcategory: str = "",
            bucket: str = "", label: str = "") -> dict:
        """Reclassify exactly one movement."""
        entry = {
            "category": category, "subcategory": subcategory, "bucket": bucket,
            "label": label, "at": _now(),
        }
        with self._lock:
            self.pins[key] = entry
        return entry

    def unpin(self, key: str) -> bool:
        with self._lock:
            return self.pins.pop(key, None) is not None

    def rule(self, match: str, *, mode: str = EXACT, category: str = "",
             subcategory: str = "", bucket: str = "") -> dict:
        """Reclassify a counterparty, past and future.

        Re-stating a rule for the same match replaces it rather than stacking a
        second one -- two rules for the same merchant would make the outcome
        depend on list order, which is not something you can see in the UI.
        """
        entry = {
            "match": match, "mode": mode if mode in (EXACT, CONTAINS) else EXACT,
            "category": category, "subcategory": subcategory, "bucket": bucket,
            "at": _now(),
        }
        with self._lock:
            self.rules = [r for r in self.rules
                          if not (r["match"] == match and r.get("mode", EXACT) == entry["mode"])]
            self.rules.append(entry)
        return entry

    def unrule(self, match: str, mode: str = EXACT) -> bool:
        with self._lock:
            before = len(self.rules)
            self.rules = [r for r in self.rules
                          if not (r["match"] == match and r.get("mode", EXACT) == mode)]
            return len(self.rules) < before

    def yield_to_rule(self, key: str, *, category: str = "", bucket: str = "") -> None:
        """A row reclassified by its merchant drops what its own pin said on
        the same point.

        A pin outranks its merchant's rule -- that is what lets one odd
        payment differ. But when the user acts on *this* row and asks for a
        rule, the row must move: on 15.10 a payment pinned to "Non
        catégorisé" was dragged onto Restaurants, the rule was written, the
        toast said so, and the row stayed where it was. Only the conflicting
        part goes: a bucket decided on the pin outlives a rule that names a
        category (the Twint lesson, docs/corrections.md).
        """
        with self._lock:
            pin = self.pins.get(key)
            if not pin:
                return
            rest = dict(pin)
            if category:
                rest["category"], rest["subcategory"] = "", ""
            if bucket:
                rest["bucket"] = ""
            if rest.get("category") or rest.get("bucket"):
                self.pins[key] = rest
            else:
                del self.pins[key]

    # --- undoing ---------------------------------------------------------
    # An undo puts back what was there, not "nothing": a rule restated over an
    # older one for the same merchant, or a pin written over a bucket-only
    # pin, used to be undone into no rule and no pin at all.

    def snapshot(self, keys: Iterable[str] = (), matches: Iterable[str] = (),
                 mode: str = EXACT) -> dict:
        """These pins and rules as they are now -- None where there is none."""
        def found(match):
            # Its place too: when two rules catch one row, the later one wins.
            return next(((i, r) for i, r in enumerate(self.rules) if r["match"] == match
                         and r.get("mode", EXACT) == mode), (None, None))
        with self._lock:
            return {
                "pins": {key: self.pins.get(key) for key in keys},
                "rules": [{"match": match, "mode": mode, "index": found(match)[0],
                           "entry": found(match)[1]}
                          for match in dict.fromkeys(matches)],
            }

    def restore(self, snapshot: dict) -> int:
        """Put pins and rules back as `snapshot` saw them. Returns how many
        entries were set back."""
        count = 0
        with self._lock:
            for key, entry in (snapshot.get("pins") or {}).items():
                if isinstance(entry, dict):
                    self.pins[key] = entry
                else:
                    self.pins.pop(key, None)
                count += 1
            for item in snapshot.get("rules") or []:
                match, mode = item.get("match"), item.get("mode", EXACT)
                if not isinstance(match, str):
                    continue
                self.rules = [r for r in self.rules
                              if not (r["match"] == match and r.get("mode", EXACT) == mode)]
                if isinstance(item.get("entry"), dict):
                    index = item.get("index")
                    at = index if isinstance(index, int) else len(self.rules)
                    self.rules.insert(min(max(at, 0), len(self.rules)), item["entry"])
                count += 1
        return count

    # --- bulk editing ----------------------------------------------------
    # One `save()` for the whole batch: reclassifying 443 movements one at a
    # time would rewrite the file 443 times, and a crash halfway would leave a
    # half-applied correction that nothing records as incomplete.

    def pin_many(self, transactions: Iterable[Transaction], *, category: str = "",
                 subcategory: str = "", bucket: str = "") -> list[str]:
        keys = []
        for txn in transactions:
            key = key_of(txn)
            self.pin(key, category=category, subcategory=subcategory,
                     bucket=bucket, label=txn.label)
            keys.append(key)
        return keys

    def rule_many(self, transactions: Iterable[Transaction], *, category: str = "",
                  subcategory: str = "", bucket: str = "") -> list[str]:
        """One rule per distinct counterparty in the batch.

        This is what makes a bulk edit stick: the rules also catch next month's
        payments to the same people, whereas pins only cover what is already
        in the ledger.
        """
        labels = []
        for label in dict.fromkeys(t.label for t in transactions if t.label):
            self.rule(label, category=category, subcategory=subcategory,
                      bucket=bucket)
            labels.append(label)
        return labels

    def unpin_many(self, keys: Iterable[str]) -> int:
        return sum(1 for key in keys if self.unpin(key))

    def unrule_many(self, matches: Iterable[str], mode: str = EXACT) -> int:
        return sum(1 for match in matches if self.unrule(match, mode))

    # --- aliases ---------------------------------------------------------

    def alias(self, variant: str, canonical: str) -> None:
        """Treat two spellings as one counterparty.

        Banks are not consistent: the same landlord shows up as "Muster
        Verwaltung AG" and "Muster Verwaltungs AG", and every total, ranking
        and merchant rule then counts them as two different people.
        """
        variant, canonical = variant.strip(), canonical.strip()
        if not variant or not canonical or variant == canonical:
            return
        with self._lock:
            # Repoint anything that already aliased to `variant`, so a chain
            # never forms -- resolution stays a single lookup.
            for key, value in list(self.aliases.items()):
                if value == variant:
                    self.aliases[key] = canonical
            self.aliases[variant] = canonical

    def alias_pattern(self, pattern: str, canonical: str) -> bool:
        """Merge a whole family of branches under one name.

        A supermarket prints a different counterparty per till -- 40 spellings
        of Coop on this statement -- so merging them one exact name at a time
        would be a list that grows every month. Matching on a pattern collapses
        the family once and keeps catching new branches.
        """
        pattern, canonical = pattern.strip(), canonical.strip()
        if not pattern or not canonical or not _valid(pattern):
            return False
        with self._lock:
            self.alias_patterns = [p for p in self.alias_patterns
                                   if p["pattern"] != pattern]
            self.alias_patterns.append({"pattern": pattern,
                                        "canonical": canonical, "at": _now()})
        return True

    def unalias(self, variant: str) -> bool:
        with self._lock:
            if self.aliases.pop(variant, None) is not None:
                return True
            before = len(self.alias_patterns)
            self.alias_patterns = [p for p in self.alias_patterns
                                   if p["pattern"] != variant]
            return len(self.alias_patterns) < before

    def canonical(self, label: str) -> str:
        """Exact merges win over patterns: they are the more specific statement."""
        if label in self.aliases:
            return self.aliases[label]
        for entry in self.alias_patterns:
            if re.search(entry["pattern"], label, re.IGNORECASE):
                return entry["canonical"]
        return label

    # --- applying --------------------------------------------------------

    def _matches(self, rule: dict, txn: Transaction) -> bool:
        target = rule["match"]
        if rule.get("mode", EXACT) == CONTAINS:
            return target.casefold() in txn.label.casefold()
        return txn.label.casefold() == target.casefold()

    def apply(self, transactions: Iterable[Transaction]) -> int:
        """Overlay the corrections. Returns how many movements were changed.

        Call after `categories.classify_all` and before `buckets.annotate`:
        a category override has to be in place before the Need/Want/Save mapping
        reads it, and an explicit bucket override is recorded on the transaction
        for `buckets.bucket_of` to honour.
        """
        if self.empty:
            return 0

        compiled = [(rule, re.compile(re.escape(rule["match"]), re.IGNORECASE))
                    for rule in self.rules]
        touched = 0

        for txn in transactions:
            applied = False

            # First, so that a rule written against the canonical name catches
            # every spelling of that counterparty.
            merged = self.canonical(txn.label)
            if merged != txn.label:
                txn.label_override = merged
                applied = True

            for rule, _ in compiled:
                if not self._matches(rule, txn):
                    continue
                if rule.get("category"):
                    txn.category, txn.subcategory = categories.current(
                        rule["category"], rule.get("subcategory", ""))
                if rule.get("bucket"):
                    txn.bucket_override = rule["bucket"]
                applied = True

            pin = self.pins.get(key_of(txn))
            if pin:
                if pin.get("category"):
                    txn.category, txn.subcategory = categories.current(
                        pin["category"], pin.get("subcategory", ""))
                if pin.get("bucket"):
                    txn.bucket_override = pin["bucket"]
                applied = True

            if applied:
                txn.overridden = True
                touched += 1

        return touched

    # --- reporting -------------------------------------------------------

    def affected(self, transactions: Iterable[Transaction],
                 match: str, mode: str = EXACT) -> list[Transaction]:
        """Which movements a rule would catch -- shown before it is created."""
        probe = {"match": match, "mode": mode}
        return [t for t in transactions if self._matches(probe, t)]

    def describe(self, transactions: Iterable[Transaction]) -> list[dict]:
        """Every correction with its current reach, for the management page."""
        rows = list(transactions)
        out = []

        for rule in sorted(self.rules, key=lambda r: r["at"], reverse=True):
            hits = self.affected(rows, rule["match"], rule.get("mode", EXACT))
            out.append({
                "kind": "rule",
                "match": rule["match"],
                "mode": rule.get("mode", EXACT),
                "category": rule.get("category", ""),
                "subcategory": rule.get("subcategory", ""),
                "bucket": rule.get("bucket", ""),
                "at": rule["at"],
                "count": len(hits),
                "amount": sum(abs(t.amount_chf) for t in hits if t.amount_chf < 0),
            })

        for entry in self.alias_patterns:
            hits = [t for t in rows if t.label == entry["canonical"]]
            out.append({
                "kind": "alias", "match": entry["pattern"],
                "canonical": entry["canonical"], "pattern": True,
                "category": "", "subcategory": "", "bucket": "",
                "at": entry.get("at", ""),
                "count": len(hits),
                "amount": sum(abs(t.amount_chf) for t in hits if t.amount_chf < 0),
            })

        for variant, canonical in sorted(self.aliases.items()):
            hits = [t for t in rows if t.label == canonical]
            out.append({
                "kind": "alias", "match": variant, "canonical": canonical,
                "category": "", "subcategory": "", "bucket": "", "at": "",
                "count": len(hits),
                "amount": sum(abs(t.amount_chf) for t in hits if t.amount_chf < 0),
            })

        by_key = {key_of(t): t for t in rows}
        for key, pin in sorted(self.pins.items(),
                               key=lambda kv: kv[1]["at"], reverse=True):
            txn = by_key.get(key)
            out.append({
                "kind": "pin",
                "key": key,
                "match": pin.get("label") or (txn.label if txn else key),
                "category": pin.get("category", ""),
                "subcategory": pin.get("subcategory", ""),
                "bucket": pin.get("bucket", ""),
                "at": pin["at"],
                "count": 1 if txn else 0,
                "amount": abs(txn.amount_chf) if txn and txn.amount_chf < 0 else 0.0,
                "date": txn.date if txn else None,
                "orphan": txn is None,
            })

        return out
