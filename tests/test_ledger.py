"""The re-import scenarios: full history, increment only, and overlapping mixes.

These slice the statement into fake "exports" and feed them to the ledger in
different combinations. The invariant under test: however the bank chooses to cut
the next PDF, the ledger converges on the same set of movements.
"""

from __future__ import annotations

import copy
import datetime as dt

import pytest

from pms.ledger import Ledger
from pms.models import Statement, Transaction


def slice_statement(statement: Statement, start: dt.date, end: dt.date) -> Statement:
    """A statement covering only [start, end] -- what a shorter export looks like."""
    rows = [t for t in statement.transactions if start <= t.date <= end]
    return Statement(
        holder=statement.holder,
        iban=statement.iban,
        client_number=statement.client_number,
        period_start=start,
        period_end=end,
        generated_on=statement.generated_on,
        reference_currency=statement.reference_currency,
        accounts=[],
        transactions=rows,
    )


def test_reimporting_the_same_export_adds_nothing(statement, tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")

    first = ledger.merge(statement)
    second = ledger.merge(statement)

    assert first["added"] == len(statement.transactions)
    assert second["added"] == 0
    assert second["already_known"] == len(statement.transactions)
    assert second["conflicts"] == 0
    assert len(ledger) == len(statement.transactions)


def test_increment_only_export(statement, tmp_path):
    """Next month's export contains just the new rows."""
    cut = statement.period_end - dt.timedelta(days=60)
    history = slice_statement(statement, statement.period_start, cut)
    increment = slice_statement(
        statement, cut + dt.timedelta(days=1), statement.period_end)

    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(history)
    report = ledger.merge(increment)

    assert report["added"] == len(increment.transactions)
    assert report["already_known"] == 0
    assert len(ledger) == len(statement.transactions)
    assert ledger.gaps() == []


def test_overlapping_export_contributes_only_new_rows(statement, tmp_path):
    """The realistic case: a rolling window that re-sends months you already have."""
    cut = statement.period_end - dt.timedelta(days=60)
    overlap_start = cut - dt.timedelta(days=90)

    history = slice_statement(statement, statement.period_start, cut)
    rolling = slice_statement(statement, overlap_start, statement.period_end)

    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(history)
    report = ledger.merge(rolling)

    already = [t for t in rolling.transactions if t.date <= cut]
    fresh = [t for t in rolling.transactions if t.date > cut]

    assert report["already_known"] == len(already)
    assert report["added"] == len(fresh)
    assert report["conflicts"] == 0
    assert len(ledger) == len(statement.transactions)
    assert ledger.gaps() == []


def test_import_order_does_not_matter(statement, tmp_path):
    """Newest-first or oldest-first, the ledger ends up identical."""
    cut = statement.period_end - dt.timedelta(days=120)
    old = slice_statement(statement, statement.period_start, cut)
    new = slice_statement(
        statement, cut + dt.timedelta(days=1), statement.period_end)

    forward = Ledger(tmp_path / "a.json")
    forward.merge(old)
    forward.merge(new)

    backward = Ledger(tmp_path / "b.json")
    backward.merge(new)
    backward.merge(old)

    assert [t.reference for t in forward.ordered()] == \
           [t.reference for t in backward.ordered()]


def test_a_missing_period_is_detected(statement, tmp_path):
    """Skipping the middle of the history must not pass silently."""
    start, end = statement.period_start, statement.period_end
    first = slice_statement(statement, start, start + dt.timedelta(days=200))
    last = slice_statement(statement, end - dt.timedelta(days=200), end)

    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(first)
    ledger.merge(last)

    gaps = ledger.gaps()
    assert gaps, "a hole in the history must be reported"
    assert any(g["currency"] == "CHF" for g in gaps)


def test_a_complete_history_reports_no_gap(ledger_of_statement, statement):
    assert ledger_of_statement.gaps() == []


def test_restated_row_is_flagged_not_overwritten(statement, tmp_path):
    """If the bank sends back a different amount for a known reference, say so."""
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(statement)

    # Deep-copy first: `statement` is session-scoped and shared, so
    # mutating its rows in place would corrupt every later test.
    tampered = copy.deepcopy(slice_statement(
        statement, statement.period_start, statement.period_end))
    victim = tampered.transactions[10]
    original = victim.amount
    victim.amount = original - 42.0

    report = ledger.merge(tampered)
    assert report["conflicts"] == 1
    # The stored value wins; the discrepancy is reported rather than applied.
    assert ledger.transactions[f"{victim.reference}:{victim.currency}"].amount == original


def test_rejects_a_different_account(statement, tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(statement)

    other = slice_statement(
        statement, statement.period_start, statement.period_end)
    other.iban = "CH00 0000 0000 0000 0000 0"

    with pytest.raises(ValueError, match="autre compte"):
        ledger.merge(other)


def test_roundtrips_through_disk(statement, tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    ledger.merge(statement)
    ledger.save()

    reloaded = Ledger.load(path)
    assert len(reloaded) == len(ledger)
    assert reloaded.gaps() == []

    before = ledger.ordered()
    after = reloaded.ordered()
    assert [t.reference for t in before] == [t.reference for t in after]
    assert [t.amount for t in before] == [t.amount for t in after]
    assert [t.seq for t in before] == [t.seq for t in after]


def test_rebuilt_statement_matches_the_original(ledger_of_statement, statement):
    rebuilt = ledger_of_statement.to_statement()
    assert len(rebuilt.transactions) == len(statement.transactions)

    original = {a.currency: a for a in statement.accounts}
    for account in rebuilt.accounts:
        source = original[account.currency]
        assert account.opening_balance == pytest.approx(source.opening_balance, abs=0.01)
        assert account.closing_balance == pytest.approx(source.closing_balance, abs=0.01)
        assert account.credit_total == pytest.approx(source.credit_total, abs=0.01)
        assert account.debit_total == pytest.approx(source.debit_total, abs=0.01)


# --- undoing a bad import ----------------------------------------------------

def _mini(n: int) -> Statement:
    """A tiny statement of n movements, for forget tests."""
    rows = [
        Transaction(date=dt.date(2025, 1, i + 1), reference=f"R{i + 1}",
                    currency="CHF", amount=-10.0 * (i + 1), value_date=None,
                    balance=None, kind="Paiement", merchant="")
        for i in range(n)
    ]
    return Statement(
        holder="Test", iban="CH00 0000 0000 0000 0000 0",
        period_start=dt.date(2025, 1, 1), period_end=dt.date(2025, 1, n),
        generated_on=dt.date(2025, 1, n), reference_currency="CHF",
        accounts=[], transactions=rows)


def test_merge_tags_new_rows_with_their_source(statement, tmp_path):
    source = tmp_path / "export.pdf"
    source.write_bytes(b"statement")
    ledger = Ledger(tmp_path / "ledger.json")
    report = ledger.merge(statement, source=source)
    assert report["sha256"]
    rows = list(ledger.transactions.values())
    assert rows and all(t.source == report["sha256"] for t in rows)


def test_already_known_rows_keep_their_first_import(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(b"statement-a")
    b.write_bytes(b"statement-b")
    ledger = Ledger(tmp_path / "ledger.json")
    report_a = ledger.merge(_mini(1), source=a)
    ledger.merge(_mini(2), source=b)   # R1 already known, R2 new

    rows = {t.reference: t for t in ledger.transactions.values()}
    assert rows["R1"].source == report_a["sha256"]
    assert rows["R2"].source != report_a["sha256"]


def test_forget_drops_rows_and_log_entry(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(b"statement-a")
    b.write_bytes(b"statement-b")
    ledger = Ledger(tmp_path / "ledger.json")
    report_a = ledger.merge(_mini(1), source=a)
    ledger.merge(_mini(2), source=b)

    removed = ledger.forget(report_a["sha256"])
    assert removed == {"file": "a.pdf", "rows": 1}
    assert [t.reference for t in ledger.transactions.values()] == ["R2"]
    assert len(ledger.sources) == 1
    assert ledger.sources[0]["sha256"] != report_a["sha256"]


def test_forget_unknown_digest_returns_none(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    assert ledger.forget("deadbeef") is None


def test_source_tag_survives_save_and_load(tmp_path):
    source = tmp_path / "export.pdf"
    source.write_bytes(b"statement")
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    report = ledger.merge(_mini(1), source=source)
    ledger.save()

    (row,) = Ledger.load(path).transactions.values()
    assert row.source == report["sha256"]


def test_cli_forget_removes_and_saves(tmp_path, capsys):
    from pms import cli
    source = tmp_path / "export.pdf"
    source.write_bytes(b"statement")
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    report = ledger.merge(_mini(2), source=source)
    ledger.save()

    code = cli.main(["--ledger", str(path), "--forget", report["sha256"]])
    assert code == 0
    assert len(Ledger.load(path)) == 0
    assert "oublié" in capsys.readouterr().out


def test_cli_forget_unknown_digest_fails(tmp_path, capsys):
    from pms import cli
    path = tmp_path / "ledger.json"
    code = cli.main(["--ledger", str(path), "--forget", "deadbeef"])
    assert code == 2
    assert "aucun import" in capsys.readouterr().err


# --- not re-reading what is already known ---------------------------------------

def _counting_parser(statement: Statement):
    calls: list[str] = []

    def parse(path):
        calls.append(path.name)
        return copy.deepcopy(statement)
    return parse, calls


def test_ingest_does_not_parse_a_known_file_again(tmp_path):
    """Parsing is the slow part of a launch; a file already in the import log
    could only bring rows the ledger holds."""
    from pms.ledger import ingest
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"statement-a")
    path = tmp_path / "ledger.json"
    parse, calls = _counting_parser(_mini(2))

    ingest([pdf], path, parse)[0].save()
    ledger, (report,) = ingest([pdf], path, parse)

    assert calls == ["a.pdf"]
    assert report["skipped"] and report["added"] == 0
    assert len(ledger) == 2


def test_reparse_reads_a_known_file_again(tmp_path):
    from pms.ledger import ingest
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"statement-a")
    path = tmp_path / "ledger.json"
    parse, calls = _counting_parser(_mini(2))

    ingest([pdf], path, parse)[0].save()
    _, (report,) = ingest([pdf], path, parse, reparse=True)

    assert calls == ["a.pdf", "a.pdf"]
    assert report["already_known"] == 2 and report["conflicts"] == 0


def test_a_changed_file_is_parsed(tmp_path):
    """The digest is of the bytes, not the name: next month's export saved
    over this month's is a new file."""
    from pms.ledger import ingest
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"statement-a")
    path = tmp_path / "ledger.json"
    parse, calls = _counting_parser(_mini(2))

    ingest([pdf], path, parse)[0].save()
    pdf.write_bytes(b"statement-a, one month later")
    ingest([pdf], path, parse)

    assert calls == ["a.pdf", "a.pdf"]


def test_a_forgotten_import_is_parsed_again(tmp_path):
    from pms.ledger import ingest
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"statement-a")
    path = tmp_path / "ledger.json"
    parse, calls = _counting_parser(_mini(2))

    ledger, (report,) = ingest([pdf], path, parse)
    ledger.forget(report["sha256"])
    ledger.save()
    ledger, (report,) = ingest([pdf], path, parse)

    assert calls == ["a.pdf", "a.pdf"]
    assert report["added"] == 2


def test_cli_says_a_known_file_was_not_read(tmp_path, capsys):
    from pms import cli
    from pms.ledger import ingest
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"not a real PDF: parsing it would fail")
    path = tmp_path / "ledger.json"
    parse, _ = _counting_parser(_mini(2))
    ingest([pdf], path, parse)[0].save()

    code = cli.main(["--ledger", str(path), "--pdf", str(pdf)])

    assert code == 0
    assert "déjà importé, non relu" in capsys.readouterr().out


def test_a_day_cut_by_an_earlier_export_is_ordered_by_the_later_one(statement, tmp_path):
    """An export downloaded during the day holds only part of that day, each
    row numbered within what it holds; the next export holds the whole day,
    numbered differently. Kept as each export numbered it, the day's rows
    interleaved and the balance broke inside the day ("entre le 22.08 et le
    22.08"). The export that holds every row of a day orders it."""
    by_day: dict = {}
    for t in statement.transactions:
        if t.currency == "CHF" and not t.account:
            by_day.setdefault(t.date, []).append(t)
    day = next(d for d, rows in sorted(by_day.items()) if len(rows) >= 3)
    rows = sorted(by_day[day], key=lambda t: t.seq)
    # The early export: everything before the day, and only the day's last
    # row -- booked first, so numbered 0 there.
    early_rows = [copy.deepcopy(t) for t in statement.transactions if t.date < day]
    cut = copy.deepcopy(rows[-1])
    cut.seq = 0
    early = slice_statement(statement, statement.period_start, day)
    early.transactions = early_rows + [cut]
    late = slice_statement(statement, day, statement.period_end)
    late.transactions = [copy.deepcopy(t) for t in late.transactions]

    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(early)
    ledger.merge(late)
    assert ledger.gaps() == []
    # And the other way round: an older, partial export arriving after the
    # whole day does not reorder it.
    ledger.merge(early)
    assert ledger.gaps() == []


def test_one_row_in_two_export_formats_is_one_movement(statement, tmp_path):
    """Revolut's fr-ch export writes a fee "0", its fr-fr one "0.00": the
    reference hashed from that text differs for the same row, which came in
    twice and broke the balance by its own amount. By account, currency,
    day, amount and balance after it, it is one row."""
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(statement, source=None)
    again = slice_statement(statement, statement.period_start, statement.period_end)
    again.transactions = [copy.deepcopy(t) for t in statement.transactions]
    for t in again.transactions:
        t.reference = f"other-{t.reference}"
    report = ledger.merge(again)
    assert report["added"] == 0 and report["already_known"] == len(statement.transactions)
    assert len(ledger) == len(statement.transactions) and ledger.gaps() == []


def test_a_twin_already_in_the_ledger_goes_at_the_next_load(statement, tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(statement)
    for t in ledger.transactions.values():
        t.source = "first-import"
    original = next(t for t in ledger.transactions.values() if t.balance is not None)
    twin = copy.deepcopy(original)
    twin.reference, twin.source = "twin-ref", "second-import"
    ledger.transactions["twin-ref|" + twin.currency] = twin
    assert ledger.dedupe() == 1
    assert len(ledger) == len(statement.transactions)
    # Two equal rows of one same export are two movements: kept.
    same = copy.deepcopy(original)
    same.reference = "same-export-twin"
    ledger.transactions["same|" + same.currency] = same
    assert ledger.dedupe() == 0
