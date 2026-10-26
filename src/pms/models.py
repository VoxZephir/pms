"""Domain objects shared by the parser, the analysis layer and the web app."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Transaction:
    """A single line of a bank statement (Swissquote's vocabulary).

    `amount` is signed the way the bank prints it: negative is money leaving
    the account. `balance` is the running account balance *after* the move.
    """

    date: dt.date
    reference: str
    currency: str
    amount: float
    value_date: dt.date | None
    balance: float | None
    kind: str  # first line of the Information cell, e.g. "Paiement Twint"
    merchant: str = ""  # second line, when present
    location: str = ""  # third line, when present
    detail: list[str] = field(default_factory=list)  # every Information line
    fee: float = 0.0  # "Frais et taxes" column, when populated
    page: int = 0

    # Position of this row among that currency's rows *on the same date*, in
    # statement order. The bank does not order a day's rows by reference, so
    # this is what makes the running-balance chain reproducible. It is scoped to
    # the date on purpose: that keeps it stable no matter where a later export
    # happens to start. See ledger.Ledger.ordered().
    seq: int = 0

    # Filled in by the categorisation layer.
    category: str = ""
    subcategory: str = ""

    # Filled in by buckets.annotate: Need / Want / Save / Non classé.
    bucket: str = ""

    # Set by overrides.apply when a manual correction touched this movement.
    # `bucket_override` wins over the bucket derived from the category, so a
    # transfer can be marked a need without changing what it is.
    overridden: bool = False
    bucket_override: str = ""

    # Set by overrides.apply when two spellings of the same counterparty have
    # been merged ("Muster Verwaltung AG" / "Muster Verwaltungs AG").
    label_override: str = ""

    # Filled in for forex transfers (see parser._enrich_forex).
    fx_rate: float | None = None
    fx_counter_amount: float | None = None
    fx_counter_currency: str = ""

    # Filled in by analysis.annotate_chf: the amount expressed in CHF so that
    # EUR/USD purchases can be compared with CHF ones.
    amount_chf: float = 0.0

    # The digest of the PDF that first brought this row into the ledger (see
    # ledger.merge). What makes `--forget` able to undo a bad import.
    source: str = ""

    # Which account the row belongs to: "" for the primary bank (the one the
    # ledger's IBAN names), a short name for any other ("revolut"). Each
    # account keeps its own balance chain -- a Revolut balance of 30 CHF
    # following a Swissquote one of 10'000 is not a 9'970 CHF break.
    account: str = ""

    @property
    def is_debit(self) -> bool:
        return self.amount < 0

    @property
    def label(self) -> str:
        """Best human-readable name for the counterparty.

        Card payments name the merchant on the second Information line; bank
        transfers ("Versement pour X") name it inline and put an IBAN on the
        second line instead.
        """
        if self.label_override:
            return self.label_override
        if self.kind.startswith("Versement pour "):
            return self.kind[len("Versement pour "):].strip()
        return self.merchant or self.kind

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        d["value_date"] = self.value_date.isoformat() if self.value_date else None
        return d


@dataclass
class AccountSummary:
    """The header block printed at the top of each currency section."""

    currency: str
    opening_balance: float
    closing_balance: float
    credit_total: float
    debit_total: float
    account: str = ""  # see Transaction.account


@dataclass
class Statement:
    holder: str
    iban: str
    period_start: dt.date
    period_end: dt.date
    generated_on: dt.date | None
    reference_currency: str
    accounts: list[AccountSummary]
    transactions: list[Transaction]
    client_number: str = ""
    reference_currency_label: str = ""
    # The bank, when the format does not say it by its file alone (two PDF
    # banks feed the primary account): written in the import log.
    bank: str = ""

    def by_currency(self, currency: str) -> list[Transaction]:
        return [t for t in self.transactions if t.currency == currency]

    def chains(self) -> dict[tuple[str, str], list[Transaction]]:
        """Rows per (account, currency): each pair is one running balance."""
        out: dict[tuple[str, str], list[Transaction]] = {}
        for t in self.transactions:
            out.setdefault((t.account, t.currency), []).append(t)
        return out
