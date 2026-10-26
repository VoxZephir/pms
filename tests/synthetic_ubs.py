"""A UBS "Account transactions" PDF, invented end to end, drawn at the
geometry of the real export (`ubs.py`): newest first, the trade date over
the booking date, a description of one or two lines, a grey line in a
smaller size, the debit right-aligned on ~335, the credit on ~397, the value
date, the balance after the movement. Names, shops and amounts are made up.

Written with PyMuPDF (the dev group); a test that needs it skips without.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

# Rows a page holds: the first starts lower, under the account block.
FIRST_PAGE_ROWS = 9
ROWS_PER_PAGE = 16


@dataclass
class Row:
    trade: dt.date
    amount: float
    description: list[str]
    grey: str = ""
    booking: dt.date | None = None


def _d(day: dt.date) -> str:
    return day.strftime("%d.%m.%Y")


def _money(value: float) -> str:
    return f"{value:,.2f}"


ROWS = [
    # chronological here; the PDF prints them newest first
    Row(dt.date(2025, 3, 3), 5200.00, ["EMPLOYEUR EXEMPLE SA"], "salary payment"),
    Row(dt.date(2025, 3, 3), -1.50, ["PARKINGPAY-TWINT; Payment UBS", "TWINT"]),
    Row(dt.date(2025, 3, 4), -42.35, ["Coop-1234 Exempleville"], "11112222-0 01/29; Debit card payment",
        booking=dt.date(2025, 3, 6)),
    Row(dt.date(2025, 3, 4), -42.35, ["Coop-1234 Exempleville"], "11112222-0 01/29; Debit card payment",
        booking=dt.date(2025, 3, 6)),
    Row(dt.date(2025, 3, 5), -60.00, [", Jean Fictif Debit UBS TWINT"]),
    Row(dt.date(2025, 3, 5), 25.00, ["Marie Inventee"], "Credit UBS TWINT"),
    Row(dt.date(2025, 3, 7), -1450.00, ["Regie Imaginaire SA"], "e-banking payment order"),
    Row(dt.date(2025, 3, 10), -89.90, ["Assurance Fictive SA"], "E-BILL; PayNet Order"),
    Row(dt.date(2025, 3, 12), -200.00, ["UBS Exempleville"], "11112222-0 01/29; UBS Bancomat Withdrawal"),
    Row(dt.date(2025, 3, 20), -310.40, ["UBS Switzerland AG"], "VIS1W CONTESTATION A UBS DANS LES 30 JOURS; direct debit"),
    Row(dt.date(2025, 3, 21), 19.90, ["Boutique Exemple"], "11112222-0 01/29; Refund debit card"),
    Row(dt.date(2025, 3, 31), 0.00, ["Balance closing of service prices"]),
    Row(dt.date(2025, 3, 31), 4.10, ["Interest calculation balance"], "Period: 01.01.2025 - 31.12.2025"),
    Row(dt.date(2025, 4, 1), 150.00, ["Association Exemple"], "credit"),
    Row(dt.date(2025, 4, 2), -12.80, ["PIZZERIA EXEMPLE; Payment UBS TWINT"]),
    Row(dt.date(2025, 4, 2), -35.00, ["COIFFEUR, Paul Fictif Debit UBS", "TWINT"]),
    Row(dt.date(2025, 4, 3), 300.00, ["UBS Exempleville"], "11112222-0 01/29; Cash Deposit Bancomat"),
    Row(dt.date(2025, 4, 4), -25.50, ["Boulangerie Exemple"], "11112222-0 01/29; Debit card payment",
        booking=dt.date(2025, 4, 7)),
]
OPENING = 1000.00


def build(path: Path, rows: list[Row] = ROWS, opening: float = OPENING,
          asked: tuple[dt.date, dt.date] = (dt.date(2025, 1, 1), dt.date(2025, 6, 30)),
          count: int | None = None) -> Path:
    """Write the export; `count` prints another number of transactions on
    the turnover line (500: the export was cut)."""
    import pymupdf

    balances, running = [], opening
    for r in rows:
        running = round(running + r.amount, 2)
        balances.append(running)
    printed = list(zip(rows, balances))[::-1]
    closing = balances[-1] if balances else opening
    doc = pymupdf.open()

    def text(page, x, y, s, size=9.0, grey=False, right=False):
        if right:
            x -= pymupdf.get_text_length(s, fontname="helv", fontsize=size)
        page.insert_text((x, y), s, fontsize=size, fontname="helv",
                         color=(0.5, 0.5, 0.5) if grey else (0, 0, 0))

    def new_page(first: bool):
        page = doc.new_page(width=595.3, height=841.9)
        text(page, 330, 40, "UBS Switzerland AG")
        text(page, 330, 52, "PO Box, CH-8098 Zurich")
        text(page, 510, 805, f"Page {doc.page_count}/N", size=8)
        if not first:
            return page, 150.0
        text(page, 57, 200, "Compte personnel UBS")
        text(page, 57, 230, "BIC UBSWCHZH80A")
        text(page, 440, 250, "Created on 15.07.2025")
        text(page, 57, 290, "Account transactions", size=14)
        text(page, 57, 330, "Time period:")
        text(page, 165, 330, f"{_d(asked[0])} - {_d(asked[1])}")
        text(page, 57, 360, "Trade date")
        y = 371
        for x, label, right in ((57, "Booking date", False), (127.6, "Description", False),
                                (334.6, "Debit", True), (397, "Credit", True), (417, "Value date", False),
                                (541.4, "Balance", True)):
            text(page, x, y, label, right=right)
        text(page, 127.6, 392, "Closing balance")
        text(page, 541.4, 392, _money(closing), right=True)
        return page, 420.0

    page, y = new_page(True)
    room = FIRST_PAGE_ROWS
    for r, balance in printed:
        if room == 0:
            page, y = new_page(False)
            room = ROWS_PER_PAGE
        room -= 1
        text(page, 56.8, y, _d(r.trade))
        text(page, 56.8, y + 10.8, _d(r.booking or r.trade))
        for k, line in enumerate(r.description):
            text(page, 127.6, y + 10.8 * k, line)
        if r.grey:
            text(page, 127.6, y + 21.4, r.grey, size=8, grey=True)
        if r.amount < 0 or (r.amount == 0 and not r.grey):
            text(page, 334.6, y, _money(r.amount) if r.amount else "0.00", right=True)
        else:
            text(page, 397, y, _money(r.amount), right=True)
        text(page, 417, y, _d(r.trade))
        text(page, 541.4, y, _money(balance), right=True)
        y += 37.5
    text(page, 127.6, y, "Opening balance")
    text(page, 541.4, y, _money(opening), right=True)
    first = rows[0].trade if rows else asked[0]
    last = rows[-1].trade if rows else asked[1]
    text(page, 127.6, y + 22, "Turnover")
    text(page, 127.6, y + 33, f"({count or len(rows)} transactions {_d(first)} -")
    text(page, 127.6, y + 44, f"{_d(last)})")
    text(page, 334.6, y + 33, "Total debit", right=True)
    text(page, 397, y + 33, "Total credit", right=True)
    doc.save(path)
    return path
