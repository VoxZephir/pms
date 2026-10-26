"""UBS's "Account transactions" PDF (e-banking, English) -> the same
`Statement` (`docs/releves.md`, « UBS »).

Read from one real export (500 movements over seven months, redacted), by
the geometry of its words like the Swissquote parser. What the format gives:

* **One row per movement, newest first**: the trade date over the booking
  date, a description of one or two lines, sometimes a grey line saying what
  the movement is ("Debit card payment", "e-banking payment order", "Credit
  UBS TWINT", "salary payment"...), a debit (x1 ~ 335) or a credit
  (x1 ~ 397), the value date and the balance after the movement.
* **The balance chain holds in that order**, by trade date: reversed, it is
  chronological, and `reconcile()` checks every row against the one before.
* **"Closing balance" heads the table, "Opening balance" ends it**, then
  "Turnover" with the totals and "(N transactions dd.mm.yyyy - dd.mm.yyyy)".
* **An export stops at 500 movements**: when it does, the period it covers
  is the one the turnover line names, not the one asked for -- the months
  before are not quiet, they are missing (`ledger.gaps` says so).
* **No reference is printed**: one is derived from the row's content (dates,
  amount, description, grey line), with a rank among identical rows of the
  same day -- never from a position in the file, so two exports that overlap
  give the same rows the same references.
* **Words carry no space character**: the gaps between them are ~2.5 pt,
  so words are cut at 1 pt (`X_TOLERANCE`), not at pdfplumber's default 3.

The vocabulary is normalised to the analysis' (CLAUDE.md, "Ajouter une
banque"): a card payment and a Twint paid to a shop are "Paiement par carte"
(the shop is named, the rules read it), a Twint to or from a person is
"Paiement Twint" with the person as merchant, a payment order "Versement pour
X", a salary or a credit "Paiement entrant", a direct debit "Recouvrement
direct", an eBill "Facture eBill", the cash machine "Retrait d'espèces" /
"Dépôt d'espèces". A grey line not listed keeps the bank's own words.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .models import AccountSummary, Statement, Transaction

X_TOLERANCE = 1
DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
AMOUNT = re.compile(r"^-?[\d,]+\.\d{2}$")
IBAN = re.compile(r"\b(CH\d{2}(?: ?[0-9A-Z]{4}){4} ?[0-9A-Z]{1})\b")
# The totals' column labels ("Total debit Total credit") print between the
# two dates of the wrapped line.
TURNOVER = re.compile(r"\((\d+) transactions? (\d{2}\.\d{2}\.\d{4}) -[^()]*?(\d{2}\.\d{2}\.\d{4})\)")
PERIOD = re.compile(r"Time period:\s*(\d{2}\.\d{2}\.\d{4}) - (\d{2}\.\d{2}\.\d{4})")
CREATED = re.compile(r"Created on\s+(\d{2}\.\d{2}\.\d{4})")
LIMIT = 500

# Columns, by the words' edges (595 pt wide pages).
DATE_X1 = 110          # trade and booking dates
DESC = (120, 300)      # description and grey line
DESC_X1 = 312          # ...ending well before the debit's right edge (~335)
DEBIT_X1 = (320, 345)  # right-aligned on ~335
CREDIT_X1 = (380, 405)  # right-aligned on ~397
VALUE_X0 = (405, 470)
BALANCE_X0 = 480
TABLE_BOTTOM = 790     # the footer ("Displayed in Assets online", "Page n/N")

CLOSING = ("Closing balance", "Solde final", "Schlusssaldo")
OPENING = ("Opening balance", "Solde initial", "Anfangssaldo")

# Grey line (after the card number, when there is one) -> kind.
KINDS = {
    "debit card payment": "Paiement par carte",
    "refund debit card": "Paiement par carte",
    "ubs bancomat withdrawal": "Retrait d'espèces",
    "cash deposit bancomat": "Dépôt d'espèces",
    "credit ubs twint": "Paiement Twint",
    "salary payment": "Paiement entrant - salaire",
    "credit": "Paiement entrant",
    "direct debit": "Recouvrement direct",
    "paynet order": "Facture eBill",
}
# Rows with no grey line say what they are in their description.
DESCRIBED = {
    "balance closing of service prices": "Frais bancaires",   # the month's fees, often 0.00
    "interest calculation balance": "Intérêts",
}
TWINT_SHOP = re.compile(r"[;,]?\s*Payment UBS TWINT\s*$", re.IGNORECASE)
TWINT_PERSON = re.compile(r"[;,]?\s*Debit UBS TWINT\s*$", re.IGNORECASE)
# "... TWINT" with the words before it gone (a redacted copy): a Twint, to
# whom unknown -- read as one to a person, the cautious reading.
TWINT_ANY = re.compile(r"[;,]?\s*(?:(?:Payment|Debit) UBS\s+)?TWINT\s*$", re.IGNORECASE)
CARD_NUMBER = re.compile(r"^\S+ \d{2}/\d{2};\s*")
# The monthly bill of a UBS credit card, collected by direct debit: its
# grey line opens on the card's code ("VIS1W", Visa). What it paid for is on
# the card's own statement, not here.
CARD_BILL = re.compile(r"^VIS\w*\b")


def _date(text: str) -> dt.date:
    return dt.datetime.strptime(text, "%d.%m.%Y").date()


def _amount(text: str) -> float:
    return float(text.replace(",", ""))


def _words(page) -> list[dict]:
    return page.extract_words(x_tolerance=X_TOLERANCE, extra_attrs=["size"])


def _first_page_text(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return pdf.pages[0].extract_text(x_tolerance=X_TOLERANCE) or "" if pdf.pages else ""


def looks_like(path: str | Path) -> bool:
    """A UBS transactions export: the bank's name and the table's columns on
    the first page."""
    try:
        text = _first_page_text(Path(path))
    except Exception:
        return False
    return "UBS Switzerland AG" in text and "Value date" in text and "Balance" in text


@dataclass
class _Row:
    trade: dt.date
    booking: dt.date | None = None
    value: dt.date | None = None
    amount: float | None = None
    balance: float | None = None
    text: list[str] = field(default_factory=list)
    grey: list[str] = field(default_factory=list)
    page: int = 0


def _shape(description: str, grey: str, amount: float) -> tuple[str, str]:
    """(kind, merchant) in the vocabulary of the rest of the pipeline."""
    if TWINT_SHOP.search(description):
        return "Paiement par carte - TWINT", TWINT_SHOP.sub("", description).strip(" ,;")
    if TWINT_PERSON.search(description):
        return "Paiement Twint", TWINT_PERSON.sub("", description).strip(" ,;")
    if not grey and TWINT_ANY.search(description):
        return "Paiement Twint", TWINT_ANY.sub("", description).strip(" ,;")
    if description.casefold() in DESCRIBED:
        return DESCRIBED[description.casefold()], ""
    if CARD_BILL.match(grey):
        return "Facture carte de crédit", "Carte de crédit UBS"
    said = CARD_NUMBER.sub("", grey).split(";")[-1].strip()
    key = said.casefold()
    if key == "e-banking payment order":
        return (f"Versement pour {description}", "") if amount < 0 else ("Paiement entrant", description)
    if key in KINDS:
        return KINDS[key], description
    return said or "Mouvement", description


def _rows(pdf) -> tuple[list[_Row], dict]:
    rows: list[_Row] = []
    meta: dict = {}
    for number, page in enumerate(pdf.pages, start=1):
        words = [w for w in _words(page) if w["top"] < TABLE_BOTTOM]
        # The turnover's "(500 transactions DD.MM.YYYY - DD.MM.YYYY)" wraps:
        # read on the page's text, not line by line.
        turnover = TURNOVER.search(" ".join((page.extract_text(x_tolerance=X_TOLERANCE) or "").split()))
        if turnover:
            meta["count"] = int(turnover.group(1))
            meta["from"], meta["to"] = _date(turnover.group(2)), _date(turnover.group(3))
        lines: dict[int, list[dict]] = defaultdict(list)
        for w in words:
            lines[round(w["top"])].append(w)
        tops = sorted(lines)
        # A line sitting within 1 pt of another is the same line (the
        # balance is set a size larger, its top 0.3 pt lower).
        merged: list[tuple[int, list[dict]]] = []
        for top in tops:
            if merged and top - merged[-1][0] <= 1:
                merged[-1][1].extend(lines[top])
            else:
                merged.append((top, list(lines[top])))
        current: _Row | None = None
        for _top, line in merged:
            line.sort(key=lambda w: w["x0"])
            dates = [w for w in line if w["x1"] <= DATE_X1 and DATE.match(w["text"])]
            values = [w for w in line if VALUE_X0[0] <= w["x0"] <= VALUE_X0[1] and DATE.match(w["text"])]
            # By both edges: a debit of four digits starts left of x 300.
            desc = [w for w in line if DESC[0] <= w["x0"] < DESC[1] and w["x1"] <= DESC_X1]
            balance = [w for w in line if w["x0"] >= BALANCE_X0 and AMOUNT.match(w["text"])]
            label = " ".join(w["text"] for w in desc)
            if label.startswith(CLOSING) and balance:
                meta["closing"] = _amount(balance[-1]["text"])
                current = None
                continue
            if label.startswith(OPENING) and balance:
                meta["opening"] = _amount(balance[-1]["text"])
                current = None
                continue
            if dates and values:
                debit = [w for w in line if DEBIT_X1[0] <= w["x1"] <= DEBIT_X1[1] and AMOUNT.match(w["text"])]
                credit = [w for w in line if CREDIT_X1[0] <= w["x1"] <= CREDIT_X1[1] and AMOUNT.match(w["text"])]
                amount = (_amount(debit[0]["text"]) if debit
                          else _amount(credit[0]["text"]) if credit else None)
                if amount is not None and debit and amount > 0:
                    amount = -amount
                current = _Row(trade=_date(dates[0]["text"]), value=_date(values[0]["text"]),
                               amount=amount, balance=_amount(balance[-1]["text"]) if balance else None,
                               page=number)
                rows.append(current)
                if label:
                    current.text.append(label)
                continue
            if current is None:
                continue
            if dates and current.booking is None:
                current.booking = _date(dates[0]["text"])
            if desc:
                small = all(w["size"] < 8.5 for w in desc)
                (current.grey if small else current.text).append(label)
    return rows, meta


def parse_statement(path: str | Path) -> Statement:
    """Parse the export. Raises nothing on content -- `reconcile()` validates."""
    import pdfplumber
    path = Path(path)
    with pdfplumber.open(path) as pdf:
        first = pdf.pages[0].extract_text(x_tolerance=X_TOLERANCE) or ""
        rows, meta = _rows(pdf)

    transactions: list[Transaction] = []
    seen: dict[str, int] = {}
    slots: dict[dt.date, int] = {}
    for row in reversed(rows):  # newest first in the file
        if row.amount is None:
            continue
        description = " ".join(row.text).strip()
        grey = " ".join(row.grey).strip()
        kind, merchant = _shape(description, grey, row.amount)
        content = "|".join((row.trade.isoformat(), (row.booking or row.trade).isoformat(),
                            (row.value or row.trade).isoformat(), f"{row.amount:.2f}", description, grey))
        reference = "ubs-" + hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
        count = seen.get(reference, 0)
        seen[reference] = count + 1
        if count:  # the same movement content twice the same day
            reference = f"{reference}-{count}"
        seq = slots.get(row.trade, 0)
        slots[row.trade] = seq + 1
        transactions.append(Transaction(
            date=row.trade,
            reference=reference,
            currency="CHF",
            amount=row.amount,
            value_date=row.value,
            balance=row.balance,
            kind=kind,
            merchant=merchant,
            detail=[d for d in (description, grey) if d],
            page=row.page,
            seq=seq,
        ))

    iban = IBAN.search(first)
    period = PERIOD.search(first)
    created = CREATED.search(first)
    asked = (_date(period.group(1)), _date(period.group(2))) if period else (None, None)
    # Cut at 500: the months asked for before the first movement shown are
    # missing, not quiet. Otherwise the period asked for is the one covered.
    truncated = meta.get("count", 0) >= LIMIT
    start = meta.get("from") if truncated or not asked[0] else asked[0]
    end = asked[1] if asked[1] and not truncated else meta.get("to")
    if transactions:
        start = start or transactions[0].date
        end = end or transactions[-1].date
    opening = meta.get("opening")
    if opening is None and transactions and transactions[0].balance is not None:
        opening = round(transactions[0].balance - transactions[0].amount, 2)
    closing = meta.get("closing")
    if closing is None:
        closing = round((opening or 0.0) + sum(t.amount for t in transactions), 2)
    return Statement(
        holder=_holder(path),
        iban=" ".join(iban.group(1).split()) if iban else "",
        period_start=start,
        period_end=end,
        generated_on=_date(created.group(1)) if created else None,
        reference_currency="CHF",
        bank="UBS",
        accounts=[AccountSummary(
            currency="CHF",
            opening_balance=opening or 0.0,
            closing_balance=closing,
            credit_total=round(sum(t.amount for t in transactions if t.amount > 0), 2),
            debit_total=round(-sum(t.amount for t in transactions if t.amount < 0), 2),
        )],
        transactions=transactions,
    )


def _holder(path: Path) -> str:
    """The first line of the postal address, top left of the first page,
    above the account block ("Compte personnel UBS"...)."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        words = [w for w in _words(pdf.pages[0]) if w["x0"] < 300 and 120 < w["top"] < 185]
    if not words:
        return ""
    top = min(w["top"] for w in words)
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"]) if w["top"] - top < 2)
