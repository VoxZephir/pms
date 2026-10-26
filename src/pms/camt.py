"""An ISO 20022 account statement (camt.053, XML) -> the same `Statement`.

camt.053 is the statement format Swiss banks share since the move to ISO
20022 (PostFinance, UBS, Raiffeisen, the cantonal banks), offered in the
e-banking next to the PDF. One parser for every bank that exports it -- read
from the standard and from published sample files, not yet from a real
customer's export (docs/releves.md).

What the format gives, and what this does with it:

* **One `Stmt` per account and period** (a day, a month), each with its IBAN,
  currency, an opening balance (OPBD, or PRCD: the previous day's close) and
  a closing one (CLBD). Several accounts can share a file.
* **No balance per entry.** A row's `balance` is therefore *computed*: the
  statement's opening plus the entries before it, in file order -- except the
  last entry of each statement, which carries the bank's closing balance as
  printed. `reconcile()` thus proves each statement adds up (an entry lost
  shows as a break on that statement's last row) and that consecutive
  statements chain (a statement missing shows on the next one's first row);
  it cannot point at the row inside a statement, as it can on Swissquote.
* **A stable reference per entry** (`AcctSvcrRef`, the bank's own). When the
  bank prints none, one is derived from the entry's content and its rank
  among identical entries of the day -- never from a counter.
* **A batch booking** (one entry, several `TxDtls`: a salary run, a
  collective order) becomes one row per transaction when their amounts add up
  to the entry's, so each payee is categorised on its own.
* **Only booked entries** (`Sts` BOOK): pending ones may still change.

The bank transaction code (domain / family / sub-family) is normalised to the
vocabulary the analysis knows (CLAUDE.md, "Ajouter une banque"): a card
payment is "Paiement par carte", a credit "Paiement entrant", a transfer out
"Versement pour X", interest "Intérêts", a transfer between two accounts of
the file "Virement entre comptes" (`categories.INTERNAL`) -- or, between two
currencies, "Transfert Forex manuel" with each leg carrying the other's
amount, like Swissquote's.

The first account of the file is the primary one (`Transaction.account` ""):
its IBAN names the ledger, so a statement of somebody else's account is
refused by `Ledger.merge` instead of mixed in. The others are secondary,
named after the end of their IBAN.

ElementTree is safe on this input: expat never fetches an external entity,
and refuses entity expansion bombs since 2.4.1.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .models import AccountSummary, Statement, Transaction

NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:camt.053"

# (domain, family) -> kind, for the families whose meaning does not depend on
# the sign. Unlisted codes keep the bank's own text (`AddtlNtryInf`).
CARD_FAMILIES = {"CCRD", "DCRD", "POSD"}          # customer card, debit card, POS
CASH_SUBFAMILIES = {"CWDL", "ATMW"}                # cash withdrawal
TRANSFER_OUT = {"ICDT", "ICHQ"}                    # issued credit transfer, cheque
TRANSFER_IN = {"RCDT", "RCHQ"}
DIRECT_DEBIT = {"IDDT", "RDDT"}
INTEREST_SUBFAMILIES = {"INTR"}
FEE_SUBFAMILIES = {"CHRG", "FEES", "COMM", "TAXE"}
TWINT = re.compile(r"\bTWINT\b", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _strip(root: ET.Element) -> ET.Element:
    """Drop the namespace from every tag: the versions (.001.02 to .001.13)
    differ by it, and only by a few element names past it."""
    for el in root.iter():
        el.tag = _local(el.tag)
    return root


def _text(el: ET.Element | None, path: str) -> str:
    if el is None:
        return ""
    found = el.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def _date(el: ET.Element | None) -> dt.date | None:
    """`<Dt>` or `<DtTm>`, with or without a time zone."""
    if el is None:
        return None
    value = _text(el, "Dt") or _text(el, "DtTm")
    return dt.date.fromisoformat(value[:10]) if value else None


def _amount(el: ET.Element | None) -> tuple[float, str] | None:
    if el is None or not (el.text or "").strip():
        return None
    return float(el.text), el.get("Ccy", "")


def _signed(value: float, indicator: str) -> float:
    return round(-value if indicator == "DBIT" else value, 2)


def looks_like(path: str | Path) -> bool:
    """A camt.053 statement, judged from its first bytes -- what the
    Downloads watcher asks of every XML there."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096).decode("utf-8", errors="ignore")
    except OSError:
        return False
    return NAMESPACE in head and "BkToCstmrStmt" in head


@dataclass
class _Account:
    iban: str
    currency: str
    holder: str = ""
    opening: float | None = None
    closing: float | None = None
    start: dt.date | None = None
    end: dt.date | None = None
    rows: list[Transaction] = field(default_factory=list)


def _balances(stmt: ET.Element) -> dict[str, tuple[float, dt.date | None]]:
    out = {}
    for bal in stmt.findall("Bal"):
        code = _text(bal, "Tp/CdOrPrtry/Cd") or _text(bal, "Tp/CdOrPrtry/Prtry")
        amount = _amount(bal.find("Amt"))
        if code and amount:
            out[code] = (_signed(amount[0], _text(bal, "CdtDbtInd")), _date(bal.find("Dt")))
    return out


def _booked(ntry: ET.Element) -> bool:
    status = _text(ntry, "Sts/Cd") or _text(ntry, "Sts")
    return status in ("", "BOOK")


def _party(tx: ET.Element, credit: bool) -> tuple[str, str, str]:
    """(name, IBAN, BIC) of the other side: who paid us, or whom we paid."""
    side = "Dbtr" if credit else "Cdtr"
    name = (_text(tx, f"RltdPties/{side}/Nm") or _text(tx, f"RltdPties/{side}/Pty/Nm")
            or _text(tx, f"RltdPties/Ultmt{side}/Nm"))
    iban = (_text(tx, f"RltdPties/{side}Acct/Id/IBAN")
            or _text(tx, f"RltdPties/{side}Acct/Id/Othr/Id"))
    agent = "DbtrAgt" if credit else "CdtrAgt"
    bic = (_text(tx, f"RltdAgts/{agent}/FinInstnId/BICFI")
           or _text(tx, f"RltdAgts/{agent}/FinInstnId/BIC"))
    return name, iban, bic


def _code(ntry: ET.Element, tx: ET.Element | None) -> tuple[str, str, str]:
    for el in (tx, ntry):
        if el is None:
            continue
        domain = _text(el, "BkTxCd/Domn/Cd")
        if domain:
            return (domain, _text(el, "BkTxCd/Domn/Fmly/Cd"),
                    _text(el, "BkTxCd/Domn/Fmly/SubFmlyCd"))
    return "", "", ""


def _shape(code: tuple[str, str, str], amount: float, name: str,
           info: str) -> tuple[str, str]:
    """(kind, merchant) in the vocabulary of the rest of the pipeline."""
    _, family, sub = code
    text = info or name
    if TWINT.search(info) and amount < 0:
        return "Paiement Twint", name
    if sub in CASH_SUBFAMILIES:
        return "Retrait d'espèces", name or info
    if family in CARD_FAMILIES:
        return "Paiement par carte", name or info
    if sub in INTEREST_SUBFAMILIES:
        return "Intérêts", name
    if sub in FEE_SUBFAMILIES:
        return "Frais bancaires", info
    if family in DIRECT_DEBIT and amount < 0:
        return "Recouvrement direct", name or info
    if family in TRANSFER_IN or (amount > 0 and name):
        return "Paiement entrant", name or info
    if family in TRANSFER_OUT or (amount < 0 and name):
        return f"Versement pour {name or info}", ""
    return text or "Mouvement", name if info else ""


def _transactions(ntry: ET.Element) -> list[tuple[ET.Element | None, float]]:
    """(transaction details, signed amount) per row this entry becomes: one
    per `TxDtls` when they add up to the entry, else the entry whole."""
    total = _amount(ntry.find("Amt"))
    if total is None:
        return []
    indicator = _text(ntry, "CdtDbtInd")
    whole = _signed(total[0], indicator)
    details = ntry.findall("NtryDtls/TxDtls") or ntry.findall("NtryDtls/Btch/TxDtls")
    if len(details) > 1:
        parts = []
        for tx in details:
            amount = _amount(tx.find("AmtDtls/TxAmt/Amt")) or _amount(tx.find("Amt"))
            if amount is None or amount[1] not in ("", total[1]):
                break
            parts.append((tx, _signed(amount[0], _text(tx, "CdtDbtInd") or indicator)))
        else:
            if abs(sum(a for _, a in parts) - whole) < 0.005:
                return parts
    return [(details[0] if details else None, whole)]


def _reference(ntry: ET.Element, tx: ET.Element | None, booked: dt.date,
               amount: float, text: str) -> str:
    ref = _text(ntry, "AcctSvcrRef")
    if not ref and tx is not None:
        ref = _text(tx, "Refs/AcctSvcrRef")
    if ref:
        return ref
    parts = (booked.isoformat(), f"{amount:.2f}", text, _text(ntry, "NtryRef"))
    return "camt-" + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _row(ntry: ET.Element, tx: ET.Element | None, amount: float,
         currency: str) -> Transaction:
    booked = _date(ntry.find("BookgDt")) or _date(ntry.find("ValDt"))
    name, iban, bic = _party(tx, amount > 0) if tx is not None else ("", "", "")
    info = _text(ntry, "AddtlNtryInf") or (_text(tx, "AddtlTxInf") if tx is not None else "")
    remittance = [u.text.strip() for u in (tx.findall("RmtInf/Ustrd") if tx is not None else [])
                  if u.text and u.text.strip()]
    structured = _text(tx, "RmtInf/Strd/CdtrRefInf/Ref") if tx is not None else ""
    kind, merchant = _shape(_code(ntry, tx), amount, name, info)
    detail = [d for d in (info, name, iban, bic, *remittance, structured) if d]
    reference = _reference(ntry, tx, booked, amount, "|".join(detail))
    if tx is not None and len(ntry.findall("NtryDtls/TxDtls")) > 1:
        reference = _text(tx, "Refs/AcctSvcrRef") or reference
    return Transaction(
        date=booked,
        reference=reference,
        currency=currency,
        amount=amount,
        value_date=_date(ntry.find("ValDt")),
        balance=None,
        kind=kind,
        merchant=merchant,
        detail=detail,
    )


def _read(path: Path) -> tuple[ET.Element, list[_Account]]:
    root = _strip(ET.parse(path).getroot())
    if not root.findall(".//BkToCstmrStmt"):
        raise ValueError(f"{Path(path).name}: not a camt.053 statement")
    accounts: dict[tuple[str, str], _Account] = {}
    for stmt in root.iter("Stmt"):
        iban = _text(stmt, "Acct/Id/IBAN") or _text(stmt, "Acct/Id/Othr/Id")
        balances = _balances(stmt)
        entries = [n for n in stmt.findall("Ntry") if _booked(n)]
        currency = (_text(stmt, "Acct/Ccy")
                    or next((n.find("Amt").get("Ccy", "") for n in entries
                             if n.find("Amt") is not None), "")
                    or "CHF")
        acct = accounts.setdefault((iban, currency), _Account(iban, currency))
        acct.holder = acct.holder or _text(stmt, "Acct/Ownr/Nm")
        opening = balances.get("OPBD") or balances.get("PRCD")
        closing = balances.get("CLBD")
        start = (_datetime_date(_text(stmt, "FrToDt/FrDtTm"))
                 or (opening[1] if opening else None))
        end = _datetime_date(_text(stmt, "FrToDt/ToDtTm")) or (closing[1] if closing else None)

        rows = [_row(n, tx, amount, currency)
                for n in entries for tx, amount in _transactions(n)]
        # The balance after each row, from the bank's opening; the last row
        # of the statement takes the bank's closing as printed, so a lost
        # entry breaks the chain there (module docstring).
        running = opening[0] if opening else None
        for row in rows:
            if running is not None:
                running = round(running + row.amount, 2)
                row.balance = running
        if rows and closing:
            rows[-1].balance = closing[0]
        if acct.opening is None and opening:
            acct.opening = opening[0]
        if closing:
            acct.closing = closing[0]
        acct.start = min((d for d in (acct.start, start) if d), default=None)
        acct.end = max((d for d in (acct.end, end) if d), default=None)
        acct.rows += rows
    return root, list(accounts.values())


def _datetime_date(value: str) -> dt.date | None:
    return dt.date.fromisoformat(value[:10]) if value else None


def _name(iban: str, currency: str, taken: set[str]) -> str:
    """The short name of a secondary account: "compte-1234", from the end of
    its IBAN, with the currency when one IBAN holds several."""
    digits = re.sub(r"\W", "", iban)[-4:] or "x"
    name = f"compte-{digits}"
    if name in taken:
        name = f"{name}-{currency.lower()}"
    taken.add(name)
    return name


def _pair_internal(accounts: list[_Account]) -> None:
    """A transfer between two accounts of the file is not spending: same
    currency, "Virement entre comptes"; two currencies, a conversion whose
    legs carry each other's amount, as Swissquote's do."""
    own = {re.sub(r"\s", "", a.iban): a for a in accounts if a.iban}
    for acct in accounts:
        for t in acct.rows:
            other = next((own[d] for d in (re.sub(r"\s", "", x) for x in t.detail)
                          if d in own and own[d] is not acct), None)
            if other is None:
                continue
            if other.currency == acct.currency:
                t.kind, t.merchant = "Virement entre comptes", ""
                continue
            leg = next((o for o in other.rows
                        if o.date == t.date and (o.amount > 0) != (t.amount > 0)
                        and re.sub(r"\s", "", acct.iban) in
                        {re.sub(r"\s", "", x) for x in o.detail}), None)
            t.kind, t.merchant = "Transfert Forex manuel", ""
            if leg is not None:
                t.fx_counter_amount = abs(leg.amount)
                t.fx_counter_currency = leg.currency


def parse_statement(path: str | Path) -> Statement:
    """Parse the export. Raises nothing on content -- `reconcile()` validates."""
    root, accounts = _read(Path(path))
    accounts = [a for a in accounts if a.rows or a.opening is not None]
    _pair_internal(accounts)

    # The francs account leads when there is one: the analysis counts in CHF.
    primary = next((a for a in accounts if a.currency == "CHF"), accounts[0] if accounts else None)
    taken: set[str] = set()
    transactions: list[Transaction] = []
    summaries: list[AccountSummary] = []
    for acct in accounts:
        name = "" if acct is primary else _name(acct.iban, acct.currency, taken)
        slots: dict[dt.date, int] = {}
        seen: dict[str, int] = {}
        for t in acct.rows:
            t.account = name
            count = seen.get(t.reference, 0)
            seen[t.reference] = count + 1
            if count:  # the same entry content twice the same day
                t.reference = f"{t.reference}-{count}"
            t.seq = slots.get(t.date, 0)
            slots[t.date] = t.seq + 1
        transactions += acct.rows
        opening = acct.opening if acct.opening is not None else (
            round(acct.rows[0].balance - acct.rows[0].amount, 2)
            if acct.rows and acct.rows[0].balance is not None else 0.0)
        closing = acct.closing if acct.closing is not None else round(
            opening + sum(t.amount for t in acct.rows), 2)
        summaries.append(AccountSummary(
            currency=acct.currency,
            opening_balance=opening,
            closing_balance=closing,
            credit_total=round(sum(t.amount for t in acct.rows if t.amount > 0), 2),
            debit_total=round(-sum(t.amount for t in acct.rows if t.amount < 0), 2),
            account=name,
        ))

    starts = [a.start for a in accounts if a.start] or [t.date for t in transactions]
    ends = [a.end for a in accounts if a.end] or [t.date for t in transactions]
    return Statement(
        holder=primary.holder if primary else "",
        iban=primary.iban if primary else "",
        period_start=min(starts) if starts else None,
        period_end=max(ends) if ends else None,
        generated_on=_datetime_date(_text(root, ".//GrpHdr/CreDtTm")),
        reference_currency="CHF",
        accounts=summaries,
        transactions=transactions,
    )
