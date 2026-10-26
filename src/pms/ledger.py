"""A durable ledger that accumulates statements across imports.

The problem this solves
-----------------------
Swissquote only serves a rolling 24-month window, and you never quite know what
the next export will contain: the full two years again, only the new month, or
some overlapping slice. All three must land on the same result.

They do, because the bank gives us an exact identity for every movement. The
`Référence` column is a unique, monotonically increasing operation id. It is not
quite a primary key on its own -- a currency conversion prints the *same*
reference on both its legs (the CHF debit and the EUR credit) -- so the key is
**(reference, currency)**: one distinct key per row.

So ingestion is a set union keyed on (reference, currency):

* re-importing the same PDF adds nothing;
* an overlapping export contributes only its genuinely new rows;
* an increment-only export contributes all of its rows;
* and the ledger keeps history *past* the bank's 24-month window, which is the
  real reason to keep one at all.

Two integrity checks run on every merge. A row that already exists must arrive
identical -- a changed amount or balance means the bank restated something, and
that is surfaced rather than silently overwritten. And the merged result is
walked as a balance chain (`gaps()`): since every row carries the running
balance the bank printed, a missing period shows up as a break, so the ledger
can tell you it is incomplete instead of quietly under-reporting.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import fields
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .models import AccountSummary, Statement, Transaction

LEDGER_VERSION = 1


class ForeignAccount(ValueError):
    """A statement of another account than the ledger's -- somebody else's,
    dropped here by mistake. Refused whole: nothing of it is merged."""

    def __init__(self, theirs: str, ours: str):
        def end(iban):
            return "…" + iban.replace(" ", "")[-4:]
        super().__init__(
            f"ce relevé est celui d'un autre compte (IBAN {end(theirs)}) que celui "
            f"de ce ledger ({end(ours)}) : rien n'en a été importé. Un autre "
            f"titulaire a sa propre copie de l'app (docs/releves.md).")


def content_of(txn: Transaction) -> tuple | None:
    """A movement by what it is rather than by its reference: account,
    currency, day, amount and the balance after it. Two exports of one bank
    in two regional formats print the same row with differently written
    fields ("0" and "0.00" for a Revolut fee): a reference hashed from that
    text differs, this does not. None without a balance -- the amount and
    the day alone do not tell two coffees apart."""
    if txn.balance is None:
        return None
    return (txn.account, txn.currency, txn.date, round(txn.amount, 2), round(txn.balance, 2))


def key_of(txn: Transaction) -> str:
    """The identity of a movement: reference + currency (conversions share a ref).

    A row of another account is prefixed with it; the primary account keeps
    the bare form, so the keys of a ledger written before accounts existed
    are unchanged.
    """
    if txn.account:
        return f"{txn.account}:{txn.reference}:{txn.currency}"
    return f"{txn.reference}:{txn.currency}"


def _accounts(rows: list[Transaction]) -> list[AccountSummary]:
    """Opening and closing per (account, currency), read off the rows."""
    out = []
    chains: dict[tuple[str, str], list[Transaction]] = {}
    for t in rows:
        chains.setdefault((t.account, t.currency), []).append(t)
    for (account, currency), series in sorted(chains.items()):
        with_balance = [t for t in series if t.balance is not None]
        opening = ((with_balance[0].balance - with_balance[0].amount)
                   if with_balance else 0.0)
        out.append(AccountSummary(
            currency=currency,
            opening_balance=round(opening, 2),
            closing_balance=with_balance[-1].balance if with_balance else 0.0,
            credit_total=round(sum(t.amount for t in series if t.amount > 0), 2),
            debit_total=round(-sum(t.amount for t in series if t.amount < 0), 2),
            account=account,
        ))
    return out


def primary_start(rows: Iterable[Transaction]) -> dt.date | None:
    """First day the primary account is covered, if it is in the ledger.

    Rows of another account dated before it stay in the ledger but out of
    the analysis: a year of Revolut alone, with the main account missing,
    reads as a year of spending nearly nothing -- every average, baseline
    and "par jour" over "Tout" would drop. Importing an older statement of
    the primary account brings them in on its own.
    """
    return min((t.date for t in rows if not t.account), default=None)


def _to_date(value):
    if isinstance(value, dt.date) or value is None:
        return value
    return dt.date.fromisoformat(value)


def _txn_from_dict(row: dict) -> Transaction:
    known = {f.name for f in fields(Transaction)}
    data = {k: v for k, v in row.items() if k in known}
    data["date"] = _to_date(data["date"])
    data["value_date"] = _to_date(data.get("value_date"))
    return Transaction(**data)


class Ledger:
    """Every movement ever seen, plus a log of where each import came from."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.account: dict = {}
        self.sources: list[dict] = []
        self.transactions: dict[str, Transaction] = {}
        # Rows `dedupe` dropped on this load (`ingest`), for the console.
        self.deduped = 0

    # --- persistence -----------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        ledger = cls(Path(path))
        if not ledger.path.exists():
            return ledger
        raw = json.loads(ledger.path.read_text(encoding="utf-8"))
        ledger.account = raw.get("account", {})
        ledger.sources = raw.get("sources", [])
        for row in raw.get("transactions", []):
            txn = _txn_from_dict(row)
            ledger.transactions[key_of(txn)] = txn
        return ledger

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": LEDGER_VERSION,
            "account": self.account,
            "sources": self.sources,
            "transactions": [t.to_dict() for t in self.ordered()],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return self.path

    # --- reading ---------------------------------------------------------

    def ordered(self) -> list[Transaction]:
        """Statement order, reproduced.

        Sorting by reference would be wrong: the bank does not order a day's
        rows by reference (a day can print a higher reference before a lower
        one), and
        getting this wrong turns every such day into a phantom balance break.
        `seq` is the row's position within its own date, so (date, seq) restores
        the printed order exactly.
        """
        return sorted(self.transactions.values(),
                      key=lambda t: (t.date, t.seq, t.currency))

    def __len__(self) -> int:
        return len(self.transactions)

    # --- merging ---------------------------------------------------------

    def _reorder(self, statement: Statement, aliases: dict[str, str] | None = None) -> None:
        """A day the statement holds whole is ordered as it prints it.

        `seq` is a row's position within its date *in the export it came
        from*. An export downloaded during the day holds part of that day,
        numbered within that part; the next export holds the whole day,
        numbered differently. Kept as each numbered them, the day's rows
        interleave and the balance breaks inside the day. So when the
        incoming export holds every row the ledger has for a (date, account,
        currency), its numbering wins for all of them; when it holds fewer
        (an older, partial export imported again), the ledger's order stays.
        """
        incoming: dict[tuple, list[Transaction]] = defaultdict(list)
        for txn in statement.transactions:
            incoming[(txn.date, txn.account, txn.currency)].append(txn)
        held: dict[tuple, set] = defaultdict(set)
        for key, txn in self.transactions.items():
            group = (txn.date, txn.account, txn.currency)
            if group in incoming:
                held[group].add(key)
        aliases = aliases or {}
        for group, rows in incoming.items():
            keys = {aliases.get(key_of(t), key_of(t)) for t in rows}
            if held[group] <= keys:
                for t in rows:
                    self.transactions[aliases.get(key_of(t), key_of(t))].seq = t.seq

    def dedupe(self) -> int:
        """Drop a row another import already brought under another reference
        (`content_of`): what a ledger merged before that match existed may
        hold. Only across two imports -- two equal rows of one export are two
        movements. The first import's row stays. Returns how many went."""
        first: dict[tuple, str] = {}
        dropped = []
        for key, txn in self.transactions.items():
            content = content_of(txn)
            if content is None:
                continue
            kept = first.get(content)
            if kept is None:
                first[content] = key
            elif self.transactions[kept].source != txn.source and txn.source and self.transactions[kept].source:
                dropped.append(key)
        for key in dropped:
            del self.transactions[key]
        return len(dropped)

    def merge(self, statement: Statement, source: Path | None = None) -> dict:
        """Union a freshly parsed statement into the ledger.

        Returns a summary: how many rows were new, how many were already known,
        and any row that came back with different values than we had stored.
        """
        if self.account and statement.iban and \
                self.account.get("iban") not in ("", statement.iban):
            raise ForeignAccount(statement.iban, self.account["iban"])
        # The ledger's account is the primary bank's; a statement without an
        # IBAN (a CSV export) never claims it from one that has one.
        if not self.account or (statement.iban and not self.account.get("iban")):
            self.account = {
                "iban": statement.iban,
                "holder": statement.holder,
                "client_number": statement.client_number,
                "reference_currency": statement.reference_currency,
            }

        digest = _digest(source) if source else ""

        added, seen, conflicts = 0, 0, []
        # What the ledger held before this export, by content: matched only
        # against those, so two equal rows of this one export stay two.
        by_content: dict[tuple, str] = {}
        for held_key, held in self.transactions.items():
            content = content_of(held)
            if content is not None:
                by_content.setdefault(content, held_key)
        aliases: dict[str, str] = {}
        for txn in statement.transactions:
            key = key_of(txn)
            existing = self.transactions.get(key)
            if existing is None:
                same = by_content.get(content_of(txn)) if content_of(txn) else None
                if same is not None:
                    # Known under another reference: the same row, written
                    # by another export format.
                    aliases[key] = same
                    seen += 1
                    continue
                # Tag the row with the import that brought it, so a bad
                # import can be undone (Ledger.forget). Rows that were
                # already known keep their first import's tag.
                txn.source = digest
                self.transactions[key] = txn
                added += 1
                continue
            seen += 1
            if (round(existing.amount, 2) != round(txn.amount, 2)
                    or existing.date != txn.date
                    or (existing.balance is not None and txn.balance is not None
                        and round(existing.balance, 2) != round(txn.balance, 2))):
                conflicts.append({
                    "key": key,
                    "stored": f"{existing.date} {existing.amount:+.2f} "
                              f"{existing.currency} bal {existing.balance}",
                    "incoming": f"{txn.date} {txn.amount:+.2f} "
                                f"{txn.currency} bal {txn.balance}",
                })

        self._reorder(statement, aliases)

        entry = {
            "file": source.name if source else "?",
            "sha256": digest,
            "period_start": statement.period_start.isoformat() if statement.period_start else None,
            "period_end": statement.period_end.isoformat() if statement.period_end else None,
            "generated_on": statement.generated_on.isoformat() if statement.generated_on else None,
            "ingested_at": dt.datetime.now().isoformat(timespec="seconds"),
            "rows": len(statement.transactions),
            "account": next((t.account for t in statement.transactions), ""),
            "bank": getattr(statement, "bank", ""),
            "added": added,
            "already_known": seen,
            "conflicts": len(conflicts),
        }

        # Re-running on an unchanged file refreshes its log entry instead of
        # appending a new one, so the history stays a list of distinct exports.
        previous = next((i for i, s in enumerate(self.sources)
                         if digest and s.get("sha256") == digest), None)
        if previous is None:
            self.sources.append(entry)
        else:
            entry["added"] = self.sources[previous].get("added", added)
            entry["reimported"] = self.sources[previous].get("reimported", 0) + 1
            self.sources[previous] = entry

        return {**entry, "added": added, "conflict_detail": conflicts}

    # --- undoing ---------------------------------------------------------

    def forget(self, sha256: str) -> dict | None:
        """Drop every movement one import brought in, and its log entry.

        Returns a summary, or None when no import carries that digest. The
        forgotten period will show up as a gap until the correct statement
        is imported -- that is the honest state after undoing a bad import.
        Rows imported before the provenance tag existed cannot be forgotten;
        re-importing the statement tags them for next time.
        """
        entry = next((s for s in self.sources if s.get("sha256") == sha256), None)
        if entry is None:
            return None
        keys = [k for k, t in self.transactions.items() if t.source == sha256]
        for key in keys:
            del self.transactions[key]
        self.sources = [s for s in self.sources if s.get("sha256") != sha256]
        return {"file": entry.get("file", "?"), "rows": len(keys)}

    # --- integrity -------------------------------------------------------

    def gaps(self, tolerance: float = 0.005) -> list[dict]:
        """Breaks in the running balance -- i.e. periods the ledger is missing.

        Every row carries the balance the bank printed after it, so consecutive
        rows must satisfy `balance[n-1] + amount[n] == balance[n]`. A break means
        movements between those two dates were never imported, and the size of
        the break is exactly the money unaccounted for.
        """
        breaks = []
        chains: dict[tuple[str, str], list[Transaction]] = {}
        for t in self.ordered():
            if t.balance is not None:
                chains.setdefault((t.account, t.currency), []).append(t)
        for (account, currency), rows in sorted(chains.items()):
            for previous, current in zip(rows, rows[1:]):
                expected = previous.balance + current.amount
                if abs(expected - current.balance) > tolerance:
                    breaks.append({
                        "account": account,
                        "currency": currency,
                        "after": previous.date,
                        "before": current.date,
                        "missing": round(current.balance - expected, 2),
                        "between_refs": f"{previous.reference} → {current.reference}",
                    })
        return breaks

    # --- export ----------------------------------------------------------

    def to_statement(self, start: dt.date | None = None,
                     end: dt.date | None = None) -> Statement:
        """Rebuild a `Statement` over everything held, for analysis and reporting.

        Opening and closing balances are recomputed from the ledger's own first
        and last row per currency rather than copied from any one import, which
        is also what makes an arbitrary `start`/`end` window work: the window's
        opening balance is read off its own first row.
        """
        rows = self.ordered()
        first = primary_start(rows)
        if first:
            rows = [t for t in rows if not t.account or t.date >= first]
        if start:
            rows = [t for t in rows if t.date >= start]
        if end:
            rows = [t for t in rows if t.date <= end]
        accounts = _accounts(rows)

        periods = [s for s in self.sources if s.get("period_start")]
        if first:
            periods = [s for s in periods if not s.get("account")] or periods
        covered_start = (min(_to_date(s["period_start"]) for s in periods)
                         if periods else (rows[0].date if rows else None))
        if first and covered_start:
            covered_start = max(covered_start, first)
        covered_end = (max(_to_date(s["period_end"]) for s in periods)
                       if periods else (rows[-1].date if rows else None))
        return Statement(
            holder=self.account.get("holder", ""),
            iban=self.account.get("iban", ""),
            client_number=self.account.get("client_number", ""),
            period_start=start or covered_start,
            period_end=end or covered_end,
            generated_on=max((_to_date(s["generated_on"]) for s in self.sources
                              if s.get("generated_on")), default=None),
            reference_currency=self.account.get("reference_currency", "CHF"),
            accounts=accounts,
            transactions=rows,
        )


def _digest(path: Path) -> str:
    """Short content hash, so a re-import of the identical file is visible."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:16]


def ingest(paths: Iterable[Path], ledger_path: Path, parse=None,
           reparse: bool = False, strict: bool = True) -> tuple[Ledger, list[dict]]:
    """Parse each export and merge it in, newest export last.

    `parse` reads every file; without it each one goes to the parser of its
    bank (`banks.parser_for`).

    A file whose digest is already in the import log is not parsed again:
    merging it could only find rows the ledger already holds, and parsing is
    the slow part of a launch -- 14 s for a two-year statement, paid again on
    every start for every PDF left in inbox/. `reparse=True` reads it anyway,
    which is how a parser change gets checked against the rows it wrote
    before: a row that comes back different is reported as a conflict, never
    overwritten.

    `strict=False` reports a statement of another account (`ForeignAccount`)
    as `refused` and goes on with the next file -- what a launch wants: one
    stray file in inbox/ must not stop the app from starting.
    """
    ledger = Ledger.load(ledger_path)
    # A twin left by an older merge goes first: the rows read next match
    # the one that stays.
    ledger.deduped = ledger.dedupe()
    known = {s["sha256"] for s in ledger.sources if s.get("sha256")}
    reports = []
    for path in paths:
        if not reparse and _digest(path) in known:
            reports.append({"file": path.name, "skipped": True, "rows": 0,
                            "added": 0, "already_known": 0, "conflicts": 0,
                            "conflict_detail": []})
            continue
        if parse is None:
            from .banks import parser_for
            statement = parser_for(path)(path)
        else:
            statement = parse(path)
        try:
            reports.append(ledger.merge(statement, source=path))
        except ForeignAccount as refused:
            if strict:
                raise
            reports.append({"file": path.name, "refused": str(refused), "rows": 0,
                            "added": 0, "already_known": 0, "conflicts": 0,
                            "conflict_detail": []})
    return ledger, reports
