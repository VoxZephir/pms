"""Parse a Swissquote "Relevé de transactions" PDF into `Transaction` objects.

Why geometry and not plain text
-------------------------------
`pdftotext -layout` mangles this document: the Information cell wraps over two
or three lines while the amount columns stay on one, so the text-mode heuristics
drift and end up pairing an amount with the wrong date. Every column here is
positioned at a fixed x offset, so we group words into rows by their `top`
coordinate and bucket them into columns by their `x0`/`x1`. That is exact.

Column geometry (A4 portrait, 595pt wide, constant across all 104 pages):

    x0 <  75          Date
    x0 <  145         Référence
    x0 <  300         Information   (wraps onto continuation lines)
    300 <= x0, x1<=400  Frais et taxes  (right-aligned; empty in practice)
    300 <= x0, x1<=446  Montant         (right-aligned on x1 = 444)
    446 <= x0 < 520   Date de valeur
    x0 >= 520         Solde           (right-aligned on x1 = 569)
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from pathlib import Path

import pdfplumber

from .models import AccountSummary, Statement, Transaction

# --- column boundaries --------------------------------------------------
X_REF, X_INFO, X_NUM, X_VALDATE, X_BALANCE = 75, 145, 300, 446, 520
X_AMOUNT_MIN_RIGHT = 400  # separates "Frais et taxes" from "Montant"
Y_FOOTER = 760  # legal disclaimer and page number live below this

DATE_RE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")
REF_RE = re.compile(r"^\d{6,}$")
CURRENCY_RE = re.compile(r"^(CHF|EUR|USD|GBP)$")
SECTION_RE = re.compile(r"^Relevé de transactions en (\w{3})$")
HEADER_ROW = "Date Référence Information"

FX_RATE_RE = re.compile(r"Taux de change\s*:\s*1\s+(\w{3})\s*=\s*([\d.]+)\s+(\w{3})")
FX_AMOUNT_RE = re.compile(r"Montant\s*:\s*([\d’',.]+)\s+(\w{3})")

# Continuation lines that describe the *mechanics* of the payment rather than
# the counterparty -- they must not be mistaken for a merchant name.
NOISE_LINE_RE = re.compile(
    r"^(IBAN\b|BIC/SWIFT\b|Reference\b|Référence\b|Taux de change\b|Montant\s*:)", re.I
)


def _to_float(token: str) -> float:
    """'-1’234.56' -> -1234.56 (the PDF uses U+2019 as thousands separator)."""
    return float(token.replace("’", "").replace("'", "").replace(",", "").replace("+", ""))


def _to_date(token: str) -> dt.date | None:
    m = DATE_RE.match(token)
    if not m:
        return None
    day, month, year = (int(g) for g in m.groups())
    return dt.date(year, month, day)


def _column(word: dict) -> str:
    x0, x1 = word["x0"], word["x1"]
    if x0 < X_REF:
        return "date"
    if x0 < X_INFO:
        return "ref"
    if x0 < X_NUM:
        return "info"
    if x0 >= X_BALANCE:
        return "balance"
    if x0 >= X_VALDATE:
        return "valdate"
    return "amount" if x1 > X_AMOUNT_MIN_RIGHT else "fee"


def _rows(page) -> list[tuple[float, dict[str, list[str]]]]:
    """Group a page's words into rows of column -> list of tokens."""
    buckets: dict[float, list[dict]] = defaultdict(list)
    for word in page.extract_words():
        buckets[round(word["top"] * 2) / 2].append(word)

    rows = []
    for top in sorted(buckets):
        cells: dict[str, list[str]] = defaultdict(list)
        for word in sorted(buckets[top], key=lambda w: w["x0"]):
            cells[_column(word)].append(word["text"])
        rows.append((top, cells))
    return rows


def _money(tokens: list[str]) -> tuple[float | None, str]:
    """['-4.50', 'CHF'] -> (-4.50, 'CHF'). Returns (None, '') if unparseable."""
    if not tokens:
        return None, ""
    currency = ""
    if CURRENCY_RE.match(tokens[-1]):
        currency = tokens[-1]
        tokens = tokens[:-1]
    if not tokens:
        return None, currency
    try:
        value = _to_float(tokens[0])
    except ValueError:
        return None, currency
    return (-value if tokens[0].startswith("-") and value > 0 else value), currency


def _enrich_forex(txn: Transaction) -> None:
    """Pull the exchange rate and counter-value out of a forex transfer's detail."""
    for line in txn.detail:
        rate = FX_RATE_RE.search(line)
        if rate:
            base, value, quote = rate.groups()
            # The statement always prints "1 <base> = <value> <quote>".
            txn.fx_rate = float(value)
            txn.fx_counter_currency = base if base != txn.currency else quote
        amount = FX_AMOUNT_RE.search(line)
        if amount:
            txn.fx_counter_amount = _to_float(amount.group(1))
            txn.fx_counter_currency = amount.group(2)


def _parse_cover(page) -> dict:
    """Read holder, IBAN and period from the cover page.

    The cover interleaves the account block and the postal address on the same
    physical lines, so each field is pulled with its own anchored pattern rather
    than by position.
    """
    meta: dict = {}
    text = page.extract_text() or ""

    period = re.search(r"(\d{2}\.\d{2}\.\d{4}) à (\d{2}\.\d{2}\.\d{4})", text)
    if period:
        meta["period_start"] = _to_date(period.group(1))
        meta["period_end"] = _to_date(period.group(2))

    generated = re.search(r"Généré le (\d{2}\.\d{2}\.\d{4})", text)
    meta["generated_on"] = _to_date(generated.group(1)) if generated else None

    # "IBAN CH00 0000 0000 0000 0000 0" -- runs to end of line.
    iban = re.search(r"\bIBAN\s+([A-Z]{2}[0-9A-Z][0-9A-Z ]+?)\s*$", text, re.MULTILINE)
    meta["iban"] = " ".join(iban.group(1).split()) if iban else ""

    client = re.search(r"\bClient\s+(\d+)", text)
    meta["client_number"] = client.group(1) if client else ""

    # The holder's name sits on its own line between the period and "Devise référence".
    holder = re.search(r"^(.+)\nDevise référence\b", text, re.MULTILINE)
    meta["holder"] = holder.group(1).strip() if holder else ""

    label = re.search(r"Devise référence\s+(\w+(?:\s+\w+)?)", text)
    meta["reference_currency_label"] = label.group(1).strip() if label else ""

    code = re.search(r"Solde d’ouverture\s+[\d’.,]+\s+(\w{3})", text)
    meta["reference_currency"] = code.group(1) if code else "CHF"

    return meta


def parse_statement(pdf_path: str | Path) -> Statement:
    """Parse the whole PDF. Raises nothing -- use `reconcile()` to validate."""
    pdf_path = Path(pdf_path)
    transactions: list[Transaction] = []
    accounts: list[AccountSummary] = []
    meta: dict = {}

    with pdfplumber.open(pdf_path) as pdf:
        meta = _parse_cover(pdf.pages[0])

        currency = ""
        current: Transaction | None = None
        day_counter: dict[tuple[str, dt.date], int] = {}

        for page_no, page in enumerate(pdf.pages[1:], start=2):
            rows = _rows(page)
            in_table = False

            for top, cells in rows:
                if top > Y_FOOTER:
                    break

                flat = " ".join(
                    " ".join(cells[c])
                    for c in ("date", "ref", "info", "fee", "amount", "valdate", "balance")
                    if cells.get(c)
                )

                section = SECTION_RE.match(flat)
                if section:
                    currency = section.group(1)
                    current = None
                    continue

                # Per-currency summary block, printed once per section.
                if flat.startswith("Solde d’ouverture") and "Crédit" in flat:
                    summary_row = next(
                        (c for t, c in rows if t > top and c.get("date") and
                         re.match(r"^-?[\d’.]+$", c["date"][0])),
                        None,
                    )
                    if summary_row:
                        accounts.append(AccountSummary(
                            currency=currency,
                            opening_balance=_to_float(summary_row["date"][0]),
                            credit_total=_to_float(summary_row["info"][0]),
                            debit_total=_to_float(summary_row["fee"][0]),
                            closing_balance=_to_float(summary_row["valdate"][0]),
                        ))
                    continue

                if flat.startswith(HEADER_ROW):
                    in_table = True
                    continue
                if not in_table:
                    continue

                date_tokens = cells.get("date", [])
                ref_tokens = cells.get("ref", [])
                starts_row = (
                    date_tokens and _to_date(date_tokens[0])
                    and ref_tokens and REF_RE.match(ref_tokens[0])
                )

                if starts_row:
                    amount, amount_ccy = _money(cells.get("amount", []))
                    balance, _ = _money(cells.get("balance", []))
                    fee, _ = _money(cells.get("fee", []))
                    info = " ".join(cells.get("info", []))

                    row_date = _to_date(date_tokens[0])
                    row_currency = amount_ccy or currency
                    slot = day_counter.get((row_currency, row_date), 0)
                    day_counter[(row_currency, row_date)] = slot + 1

                    current = Transaction(
                        date=row_date,
                        reference=ref_tokens[0],
                        currency=row_currency,
                        amount=amount if amount is not None else 0.0,
                        value_date=_to_date(cells.get("valdate", ["" ])[0]) if cells.get("valdate") else None,
                        balance=balance,
                        kind=info,
                        detail=[info] if info else [],
                        fee=fee or 0.0,
                        page=page_no,
                        seq=slot,
                    )
                    transactions.append(current)
                elif current is not None and cells.get("info"):
                    # Continuation line: merchant, address, IBAN, forex rate...
                    line = " ".join(cells["info"])
                    current.detail.append(line)
                    if NOISE_LINE_RE.match(line):
                        continue
                    if not current.merchant:
                        current.merchant = line
                    elif not current.location:
                        current.location = line

    for txn in transactions:
        if "Forex" in txn.kind or "Transfert automatisé" in txn.kind:
            _enrich_forex(txn)

    return Statement(
        holder=meta.get("holder", ""),
        iban=meta.get("iban", ""),
        client_number=meta.get("client_number", ""),
        period_start=meta.get("period_start"),
        period_end=meta.get("period_end"),
        generated_on=meta.get("generated_on"),
        reference_currency=meta.get("reference_currency", "CHF"),
        reference_currency_label=meta.get("reference_currency_label", ""),
        accounts=accounts,
        transactions=transactions,
    )


def reconcile(statement: Statement, tolerance: float = 0.005) -> list[str]:
    """Walk each currency's running balance and report any break.

    This is the parser's self-test: if a row was dropped, split or mis-paired,
    `balance[n-1] + amount[n] != balance[n]` and it shows up here.
    """
    problems: list[str] = []
    summaries = {a.currency: a for a in statement.accounts}

    for currency in sorted({t.currency for t in statement.transactions}):
        rows = statement.by_currency(currency)
        summary = summaries.get(currency)
        running = summary.opening_balance if summary else 0.0

        for txn in rows:
            running += txn.amount
            if txn.balance is not None and abs(running - txn.balance) > tolerance:
                problems.append(
                    f"{currency} p{txn.page} {txn.date} ref {txn.reference}: "
                    f"expected balance {running:.2f}, statement says {txn.balance:.2f} "
                    f"(delta {running - txn.balance:+.2f})"
                )
                running = txn.balance  # resync so we report each break once

        if summary and abs(running - summary.closing_balance) > tolerance:
            problems.append(
                f"{currency}: final balance {running:.2f} != "
                f"stated closing balance {summary.closing_balance:.2f}"
            )

    return problems
