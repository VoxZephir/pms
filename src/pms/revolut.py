"""Revolut's account statement (CSV) -> the same `Statement` as Swissquote's.

What the export is, measured on a real one (fr-ch):

* **Double-encoded UTF-8.** "Ã©tat" for "État": the bytes were encoded twice.
  Undone by a latin-1 round trip, and only when the header shows it.
* **One row per movement, every currency in one file**, grouped by currency.
  `Solde` is the balance after the row, and the chain holds in *file order*
  with `Solde[n] = Solde[n-1] + Montant[n] - Frais[n]` -- not in the order of
  either date column. Sorted by the start date it breaks many times; by the
  completion date, never. So a row is dated by its completion (the booking,
  like a bank statement) and `seq` keeps its place in the file.
* **The fee is charged on top of the amount.** `amount` is what left the
  balance, fee included; `fee` keeps the fee alone.
* **No reference column.** One is derived from the row's own content, so the
  same row in a later, overlapping export gets the same key. The two legs of
  a conversion share theirs, as Swissquote's do.
* **Rows not completed** (TEMP_BLOCK, "RENVOYÉ": a card hold given back) carry
  no balance and moved no money: skipped.

The bank's vocabulary is normalised to the one the analysis knows (CLAUDE.md,
"Ajouter une banque"): a card payment is "Paiement par carte", a credit
"Paiement entrant", a transfer out "Versement pour X", a conversion
"Transfert Forex manuel", a top-up "Recharge Revolut" (an internal transfer,
`categories.INTERNAL`).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
from pathlib import Path

from .models import AccountSummary, Statement, Transaction

ACCOUNT = "revolut"

# French and English headers onto one set of names. Only the French export
# has been checked against a real file.
COLUMNS = {
    "type": ("Type",),
    "started": ("Date de début", "Started Date"),
    "completed": ("Date de fin", "Completed Date"),
    "description": ("Description",),
    "amount": ("Montant", "Amount"),
    "fee": ("Frais", "Fee"),
    "currency": ("Devise", "Currency"),
    "state": ("État", "State"),
    "balance": ("Solde", "Balance"),
}
COMPLETED = {"TERMINÉ", "COMPLETED"}

CARD = {"Paiement par carte", "Paiement Rev", "CARD_PAYMENT", "Card Payment"}
TRANSFER = {"Virement", "TRANSFER", "Transfer"}
TOPUP = {"Ajout de fonds", "TOPUP", "Topup", "Top-Up"}
EXCHANGE = {"Changes", "EXCHANGE", "Exchange"}
FX_PREFIXES = ("Change en", "Exchanged to")
TRANSFER_IN = ("Virement de", "Transfer from")
TRANSFER_OUT = ("Virement à", "Transfer to")


def _text(path: Path) -> str:
    # The crypto statement's header is plain ASCII: look at the whole text. A
    # correctly encoded "Ã" (a Portuguese name) fails the round trip and stays.
    text = Path(path).read_bytes().decode("utf-8-sig")
    if "Ã" in text or "Â" in text or "â\x80" in text:
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def _columns(fieldnames) -> dict[str, str]:
    """Our name -> the file's header, for every column recognised."""
    names = {}
    for field in fieldnames or []:
        for key, aliases in COLUMNS.items():
            if field.strip() in aliases:
                names[key] = field
    return names


def looks_like(path: str | Path) -> bool:
    """A Revolut account export, judged from its header line alone -- what the
    Downloads watcher asks of every CSV there. The crypto statement has other
    columns and is not one."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096).decode("utf-8-sig", errors="ignore")
    except OSError:
        return False
    if "Ã" in head:  # the double encoding, undone as in _text
        try:
            head = head.encode("latin-1").decode("utf-8", errors="ignore")
        except UnicodeEncodeError:
            pass
    header = next(csv.reader(io.StringIO(head.split("\n", 1)[0])), [])
    return len(_columns(header)) == len(COLUMNS)


def _rows(path: Path) -> list[dict]:
    reader = csv.DictReader(io.StringIO(_text(path), newline=""))
    names = _columns(reader.fieldnames)
    missing = [k for k in COLUMNS if k not in names]
    if missing:
        raise ValueError(f"{Path(path).name}: not a Revolut statement "
                         f"(missing {', '.join(missing)})")
    return [{key: (row.get(field) or "").strip() for key, field in names.items()}
            for row in reader]


def _when(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _num(value: str) -> float:
    return float(value) if value else 0.0


def _after(description: str, prefixes: tuple[str, ...]) -> str | None:
    """The name after "Virement de : ", or None if it does not start so."""
    for prefix in prefixes:
        if description.startswith(prefix):
            return description[len(prefix):].lstrip(" : ").strip()
    return None


def _shape(row: dict, amount: float) -> tuple[str, str]:
    """(kind, merchant) in the vocabulary of the rest of the pipeline."""
    kind, text = row["type"], row["description"]
    if kind in CARD:
        return "Paiement par carte", text
    if kind in TOPUP:
        return "Recharge Revolut", text
    if kind in EXCHANGE:
        if text.startswith(FX_PREFIXES):
            return "Transfert Forex manuel", text
        return "Change (autre)", text
    if kind in TRANSFER:
        sender = _after(text, TRANSFER_IN)
        if sender is not None:
            return "Paiement entrant", sender
        payee = _after(text, TRANSFER_OUT)
        if payee is not None:
            return f"Versement pour {payee}", ""
        return ("Paiement entrant", text) if amount > 0 else (f"Versement pour {text}", "")
    return kind, text


def _reference(row: dict) -> str:
    """Stable across exports: what the row says, not where it sits.

    A conversion's two legs hash the same (no amount, no currency in it), so
    they share a reference the way Swissquote's do.
    """
    if row["type"] in EXCHANGE and row["description"].startswith(FX_PREFIXES):
        parts = (row["type"], row["started"], row["description"])
    else:
        parts = (row["type"], row["started"], row["completed"], row["description"],
                 row["amount"], row["fee"], row["currency"])
    return "rev-" + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _pair_conversions(transactions: list[Transaction]) -> None:
    """Give each leg of a CHF conversion the other leg's amount.

    Same fields as Swissquote's foreign leg: `fx_counter_amount` is the CHF
    that left, so `analysis._fx_index` reads a CHF rate from it. A
    conversion between two foreign currencies gets nothing -- there is no
    CHF in it to read a rate from.
    """
    legs: dict[str, list[Transaction]] = {}
    for t in transactions:
        if t.kind == "Transfert Forex manuel":
            legs.setdefault(t.reference, []).append(t)
    for pair in legs.values():
        chf = [t for t in pair if t.currency == "CHF"]
        other = [t for t in pair if t.currency != "CHF"]
        if len(chf) == 1 and len(other) == 1:
            other[0].fx_counter_amount = abs(chf[0].amount)
            other[0].fx_counter_currency = "CHF"
            chf[0].fx_counter_amount = abs(other[0].amount)
            chf[0].fx_counter_currency = other[0].currency


def parse_statement(path: str | Path) -> Statement:
    """Parse the export. Raises nothing on content -- `reconcile()` validates."""
    rows = [r for r in _rows(Path(path)) if r["state"] in COMPLETED and r["balance"]]

    transactions: list[Transaction] = []
    seen: dict[str, int] = {}
    slots: dict[tuple[str, dt.date], int] = {}
    for row in rows:
        amount = round(_num(row["amount"]) - _num(row["fee"]), 2)
        booked = _when(row["completed"] or row["started"]).date()
        kind, merchant = _shape(row, amount)

        reference = _reference(row)
        count = seen.get(f"{reference}:{row['currency']}", 0)
        seen[f"{reference}:{row['currency']}"] = count + 1
        if count:  # the same row twice: two coffees, same minute
            reference = f"{reference}-{count}"

        slot = slots.get((row["currency"], booked), 0)
        slots[(row["currency"], booked)] = slot + 1
        transactions.append(Transaction(
            date=booked,
            reference=reference,
            currency=row["currency"],
            amount=amount,
            value_date=_when(row["started"]).date() if row["started"] else None,
            balance=_num(row["balance"]),
            kind=kind,
            merchant=merchant,
            detail=[d for d in (row["type"], row["description"]) if d],
            fee=_num(row["fee"]),
            seq=slot,
            account=ACCOUNT,
        ))

    _pair_conversions(transactions)

    accounts = []
    for currency in sorted({t.currency for t in transactions}):
        series = [t for t in transactions if t.currency == currency]
        accounts.append(AccountSummary(
            currency=currency,
            opening_balance=round(series[0].balance - series[0].amount, 2),
            closing_balance=series[-1].balance,
            credit_total=round(sum(t.amount for t in series if t.amount > 0), 2),
            debit_total=round(-sum(t.amount for t in series if t.amount < 0), 2),
            account=ACCOUNT,
        ))

    dates = [t.date for t in transactions]
    return Statement(
        holder="",
        iban="",
        period_start=min(dates) if dates else None,
        period_end=max(dates) if dates else None,
        generated_on=None,
        reference_currency="CHF",
        accounts=accounts,
        transactions=transactions,
    )
