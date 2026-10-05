"""The parser's contract: every row, exactly, and provably.

The running-balance reconciliation is the real test here. If a row were dropped,
split across two, or paired with the wrong amount, the chain would break.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pms import analysis
from pms.categories import UNCATEGORISED, classify_all
from pms.ledger import key_of
from pms.parser import reconcile


def test_running_balance_reconciles(real_statement):
    assert reconcile(real_statement) == []


def test_columns_sit_in_their_documented_bands(real_statement):
    """The geometry is the parser's contract.

    If Swissquote shifts a column, `reconcile()` only reports a balance
    break -- it cannot say the layout moved. This test pins the documented
    x-bands of `parser.py` against the real document's words, so the first
    thing to break is a message naming the column.
    """
    import pdfplumber
    from pms.parser import (DATE_RE, REF_RE, X_BALANCE, X_INFO, X_NUM,
                            X_REF, X_VALDATE, Y_FOOTER)

    path = Path(__file__).resolve().parents[1] / "inbox" / "transactionStatement.pdf"
    with pdfplumber.open(path) as pdf:
        # Data rows only: the header line and the legal disclaimer below
        # Y_FOOTER contain words that straddle the column bands.
        words = [w for page in pdf.pages[1:4] for w in page.extract_words()
                 if 50 <= w["top"] < Y_FOOTER]

    # A movement date is the leftmost word of its row (the Information cell
    # can also contain a date, "paiement du 15.08.2024", so text alone is
    # ambiguous). Group rows the way the parser does.
    rows: dict[float, list] = {}
    for w in words:
        rows.setdefault(round(w["top"] * 2) / 2, []).append(w)
    dates = []
    for row in rows.values():
        leftmost = min(row, key=lambda w: w["x0"])
        if DATE_RE.match(leftmost["text"]):
            dates.append(leftmost)
    assert dates
    assert max(w["x0"] for w in dates) < X_REF, "date column moved right"

    # The value date column prints the same shape, in its own band.
    valdates = [w for w in words
                if DATE_RE.match(w["text"]) and X_VALDATE <= w["x0"] < X_BALANCE]
    refs = [w for w in words
            if REF_RE.match(w["text"]) and X_REF <= w["x0"] < X_INFO]
    assert valdates and refs

    # Right-aligned columns keep their edges: amounts end at 444, balances
    # at 569 (0.5 pt of tolerance for the extraction's own rounding).
    amounts = [w for w in words
               if X_NUM <= w["x0"] < X_VALDATE and w["x1"] > 400]
    balances = [w for w in words if w["x0"] >= X_BALANCE]
    assert amounts and balances
    assert max(w["x1"] for w in amounts) <= 446.5, "amount column moved right"
    assert max(w["x1"] for w in balances) <= 569.5, "balance column moved right"


def test_cover_page_metadata(real_statement):
    """Shape, not values: the account's real IBAN and client number have no
    business being committed to a repository."""
    assert re.fullmatch(r"CH\d{2}(?: [0-9A-Z]{4}){4} \d", real_statement.iban), \
        f"unexpected IBAN shape: {real_statement.iban!r}"
    assert real_statement.client_number.isdigit()
    assert len(real_statement.holder.split()) >= 2
    assert real_statement.reference_currency == "CHF"
    assert real_statement.period_start < real_statement.period_end


def test_all_three_currency_sections_are_read(real_statement):
    currencies = {a.currency for a in real_statement.accounts}
    assert currencies == {"CHF", "EUR", "USD"}


def test_reference_plus_currency_is_a_unique_key(real_statement):
    keys = [key_of(t) for t in real_statement.transactions]
    assert len(set(keys)) == len(keys)


def test_forex_legs_share_a_reference(real_statement):
    """The two sides of a conversion carry the same reference -- which is why the
    dedup key needs the currency too."""
    legs = [t for t in real_statement.transactions if analysis.is_fx_leg(t)]
    assert legs
    assert len(legs) % 2 == 0
    by_ref: dict[str, list] = {}
    for leg in legs:
        by_ref.setdefault(leg.reference, []).append(leg)
    assert all(len(pair) == 2 for pair in by_ref.values())
    for pair in by_ref.values():
        assert {t.currency for t in pair} != {"CHF"}


def test_forex_details_are_parsed(real_statement):
    foreign = [t for t in real_statement.transactions
               if analysis.is_fx_leg(t) and t.currency != "CHF"]
    assert foreign
    for leg in foreign:
        assert leg.fx_rate and leg.fx_rate > 0
        assert leg.fx_counter_amount and leg.fx_counter_amount > 0


def test_transfers_name_the_counterparty_not_the_iban(real_statement):
    """"Versement pour X" puts an IBAN on the second line; the label must be X."""
    transfers = [t for t in real_statement.transactions
                 if t.kind.startswith("Versement pour ")]
    assert transfers
    assert not any(t.label.startswith("IBAN") for t in transfers)


def test_amounts_agree_with_the_stated_totals(real_statement):
    for account in real_statement.accounts:
        rows = real_statement.by_currency(account.currency)
        credits = sum(t.amount for t in rows if t.amount > 0)
        debits = -sum(t.amount for t in rows if t.amount < 0)
        assert credits == pytest.approx(account.credit_total, abs=0.01)
        assert debits == pytest.approx(account.debit_total, abs=0.01)


def test_chf_conversion_ties_out_to_the_closing_balance(real_statement):
    """opening + income - spending must land exactly on the printed closing balance.

    This is what makes the CHF conversion trustworthy rather than approximate:
    foreign purchases are scaled against the conversions that funded them, and
    the proof is that the reference account still adds up to the centime.
    """
    classify_all(real_statement.transactions)
    analysis.annotate_chf(real_statement)

    reference = real_statement.reference_currency
    account = next(a for a in real_statement.accounts if a.currency == reference)
    net = (sum(t.amount_chf for t in analysis.income(real_statement))
           - sum(abs(t.amount_chf) for t in analysis.spending(real_statement)))

    assert account.opening_balance + net == pytest.approx(
        account.closing_balance, abs=0.01)


def test_categorisation_covers_almost_everything(real_statement):
    classify_all(real_statement.transactions)
    analysis.annotate_chf(real_statement)
    spend = analysis.spending(real_statement)
    unknown = sum(abs(t.amount_chf) for t in spend if t.category == UNCATEGORISED)
    total = sum(abs(t.amount_chf) for t in spend)
    assert unknown / total < 0.05


def test_conversions_are_excluded_from_spending(real_statement):
    classify_all(real_statement.transactions)
    analysis.annotate_chf(real_statement)
    assert not any(analysis.is_fx_leg(t) for t in analysis.spending(real_statement))


def test_custodian_markup_is_a_stable_margin(real_statement):
    """The gap between the printed rate and the charged amount is a tariff, not noise."""
    classify_all(real_statement.transactions)
    analysis.annotate_chf(real_statement)
    custodian = analysis.custodian_costs(real_statement)

    assert custodian["count"] > 0
    assert custodian["markup_chf"] > 0
    # Every meaningful conversion sits in a narrow band around 0.97%.
    material = [c for c in custodian["conversions"] if c["foreign_amount"] > 20]
    assert material
    assert all(0.8 < c["markup_pct"] < 1.2 for c in material)


def test_the_mode_is_taken_on_payments_not_on_daily_totals(real_statement):
    """The mode of a day's total is 0.00 -- the days you spent nothing -- and
    with 586 distinct totals over 731 days that distribution is near-continuous
    anyway. One payment repeated 107 times is a fact; that mode is an artefact."""
    import datetime as dt
    from collections import Counter

    classify_all(real_statement.transactions)
    analysis.annotate_chf(real_statement)
    spend = analysis.spending(real_statement)

    start, end = real_statement.period_start, real_statement.period_end
    days = analysis.daily_totals(spend)
    span = (end - start).days + 1
    daily = [round(days.get(start + dt.timedelta(days=i), {}).get("amount", 0.0), 2)
             for i in range(span)]
    assert Counter(daily).most_common(1)[0][0] == 0.0

    frequent = analysis.most_frequent_amount(spend)
    assert frequent is not None
    assert frequent["amount"] > 0
    assert frequent["count"] >= 3


def test_the_most_frequent_payment_names_who_it_goes_to(real_statement):
    classify_all(real_statement.transactions)
    analysis.annotate_chf(real_statement)
    spend = analysis.spending(real_statement)

    frequent = analysis.most_frequent_amount(spend)
    matching = [t for t in spend
                if round(abs(t.amount_chf), 2) == frequent["amount"]]
    assert frequent["count"] == len(matching)
    assert frequent["label_count"] <= frequent["count"]
    assert 0 < frequent["share"] <= 100


def test_no_frequent_payment_when_nothing_repeats(real_statement):
    """Two identical payments are a coincidence, not a habit."""
    classify_all(real_statement.transactions)
    analysis.annotate_chf(real_statement)
    spend = analysis.spending(real_statement)
    assert analysis.most_frequent_amount(spend[:2]) is None
    assert analysis.most_frequent_amount([]) is None
