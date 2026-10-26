"""The way out: CSV and xlsx.

The xlsx writer is hand-rolled OOXML, so these tests read the archive back
rather than trusting that it was written: every part has to be well-formed XML,
declared in the content types, and reachable from a relationship. A workbook
that fails any of those opens with a repair prompt, which is exactly the kind of
breakage no other test would catch.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from pms import buckets, export
from pms.categories import classify_all

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@pytest.fixture(scope="module")
def rows(statement):
    from pms import analysis
    classify_all(statement.transactions)
    analysis.annotate_chf(statement)
    buckets.annotate(statement.transactions)
    return statement.transactions


def read_csv(payload: bytes) -> list[list[str]]:
    text = payload.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline="")))


# --- CSV --------------------------------------------------------------------

def test_csv_starts_with_a_bom_so_excel_reads_the_accents(rows):
    payload = export.to_csv(rows[:10])
    assert payload.startswith(b"\xef\xbb\xbf")
    assert "Bénéficiaire" in payload.decode("utf-8-sig").splitlines()[0]


def test_csv_holds_one_line_per_transaction_plus_the_header(rows):
    table = read_csv(export.to_csv(rows))
    assert table[0] == export.HEADERS
    assert len(table) == len(rows) + 1


def test_csv_amounts_are_machine_readable_not_swiss_formatted(rows):
    """The apostrophe separator belongs on screen; a CSV has to parse."""
    table = read_csv(export.to_csv(rows))
    amounts = [row[export.HEADERS.index("Montant CHF")] for row in table[1:]]
    assert all("’" not in value for value in amounts)
    total = sum(float(value) for value in amounts)
    # Each row is written to the centime, so the total may drift by up to half
    # a centime per row. Demanding an exact match would be demanding that
    # rounding not exist.
    assert total == pytest.approx(sum(t.amount_chf for t in rows),
                                  abs=0.005 * len(rows))


def test_csv_dates_are_iso_so_they_sort_as_text(rows):
    table = read_csv(export.to_csv(rows[:50]))
    dates = [dt.date.fromisoformat(row[0]) for row in table[1:]]
    assert dates == [t.date for t in rows[:50]]


def test_csv_says_which_rows_were_corrected_by_hand(rows):
    table = read_csv(export.to_csv(rows))
    flags = [row[export.HEADERS.index("Corrigé")] for row in table[1:]]
    assert set(flags) <= {"oui", "non"}
    assert flags.count("oui") == sum(1 for t in rows if t.overridden)


def test_a_separator_in_a_merchant_name_does_not_shift_the_columns():
    """Quoting is the whole job of a CSV writer; check it on a hostile name."""
    from pms.models import Transaction
    txn = Transaction(date=dt.date(2025, 1, 1), reference="1", currency="CHF",
                      amount=-1.0, value_date=None, balance=None,
                      kind="Achat", merchant='Chez "Bob", SA')
    txn.amount_chf = -1.0
    table = read_csv(export.to_csv([txn]))
    assert len(table[1]) == len(export.HEADERS)
    assert table[1][1] == 'Chez "Bob", SA'


# --- xlsx -------------------------------------------------------------------

def test_every_xlsx_part_is_well_formed_and_declared(rows):
    payload = export.to_xlsx(rows[:100])
    archive = zipfile.ZipFile(io.BytesIO(payload))

    names = set(archive.namelist())
    assert "[Content_Types].xml" in names
    for name in names:
        ET.fromstring(archive.read(name))  # raises if malformed

    types = archive.read("[Content_Types].xml").decode()
    for part in ("/xl/workbook.xml", "/xl/worksheets/sheet1.xml", "/xl/styles.xml"):
        assert f'PartName="{part}"' in types


def test_xlsx_relationships_point_at_parts_that_exist(rows):
    archive = zipfile.ZipFile(io.BytesIO(export.to_xlsx(rows[:10])))
    names = set(archive.namelist())
    for rels, base in (("_rels/.rels", ""), ("xl/_rels/workbook.xml.rels", "xl/")):
        tree = ET.fromstring(archive.read(rels))
        targets = [node.get("Target") for node in tree]
        assert targets
        for target in targets:
            assert base + target in names, f"{rels} points at a missing {target}"


def _cells(archive) -> dict[str, str]:
    sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    out = {}
    for cell in sheet.iter(f"{NS}c"):
        inline = cell.find(f"{NS}is/{NS}t")
        value = cell.find(f"{NS}v")
        out[cell.get("r")] = (inline.text if inline is not None
                              else (value.text if value is not None else ""))
    return out


def test_xlsx_dates_and_amounts_are_values_not_text(rows):
    """A column of text that looks like money does not sum."""
    archive = zipfile.ZipFile(io.BytesIO(export.to_xlsx(rows[:5])))
    sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    body = [row for row in sheet.iter(f"{NS}row") if row.get("r") != "1"]

    for line, txn in zip(body, rows[:5]):
        cells = {cell.get("r")[0]: cell for cell in line}
        assert cells["A"].get("t") is None  # numeric: an Excel date serial
        assert (dt.date(1899, 12, 30)
                + dt.timedelta(days=int(cells["A"].find(f"{NS}v").text))) == txn.date
        assert float(cells["H"].find(f"{NS}v").text) == pytest.approx(
            txn.amount_chf, abs=0.005)


def test_xlsx_header_row_names_the_same_columns_as_the_csv(rows):
    archive = zipfile.ZipFile(io.BytesIO(export.to_xlsx(rows[:3])))
    cells = _cells(archive)
    header = [cells[f"{letter}1"] for letter in "ABCDEFGHIJ"]
    assert header == export.HEADERS


def test_an_empty_window_still_produces_a_readable_file():
    """Exporting a filter that matches nothing must give a header, not a crash."""
    archive = zipfile.ZipFile(io.BytesIO(export.to_xlsx([])))
    cells = _cells(archive)
    assert cells["A1"] == "Date"
    assert not any(ref.endswith("2") for ref in cells)


def test_markup_in_a_merchant_name_cannot_break_the_sheet():
    from pms.models import Transaction
    txn = Transaction(date=dt.date(2025, 1, 1), reference="1", currency="CHF",
                      amount=-1.0, value_date=None, balance=None,
                      kind="Achat", merchant="A & B <Sàrl>")
    archive = zipfile.ZipFile(io.BytesIO(export.to_xlsx([txn])))
    assert _cells(archive)["B2"] == "A & B <Sàrl>"


def test_the_same_window_exports_byte_identical_files(rows):
    """No clock in the output, so an export can be diffed against the last one."""
    assert export.to_xlsx(rows[:200]) == export.to_xlsx(rows[:200])


def test_sheet_name_stays_within_what_excel_accepts():
    name = export.sheet_name(dt.date(2024, 7, 30), dt.date(2026, 7, 30))
    assert len(name) <= 31
    assert not set(name) & set("\\/*?:[]")


# --- the analysis export ----------------------------------------------------

SAMPLE_PROFILE = [
    {"label": "Janvier", "raw_median": 6300.0,
     "seasonal": [{"category": "Santé", "amount": 3400.0,
                   "years": [2024, 2025]}],
     "stripped_median": 2900.0, "years": [2024, 2025], "iqr": 812.5},
    {"label": "Mai", "raw_median": 9200.0, "seasonal": [],
     "stripped_median": 9100.0, "years": [2024, 2025, 2026], "iqr": 600.0},
]

SAMPLE_CATEGORIES = [
    {"category": "Santé", "median": 402.25, "peak_month_label": "Janvier",
     "peak": 3400.0,
     "seasonal": {"month_label": "Mai", "amount": 9100.0,
                  "years": [2025, 2026]},
     "trend": 2.22},
    {"category": "Logement", "median": 1831.5, "peak_month_label": "Janvier",
     "peak": 1900.0, "seasonal": None, "trend": -3.0},
    {"category": "Épargne", "median": 500.0, "peak_month_label": "Mai",
     "peak": 500.0, "seasonal": None, "trend": 0.0},
    {"category": "Transport", "median": 210.75, "peak_month_label": "Mai",
     "peak": 240.0, "seasonal": None, "trend": None},
]


def test_analysis_csv_roundtrips():
    """Two blocks in one file: the monthly profile, a blank line, then the
    per-category stats -- all readable back with the csv module."""
    payload = export.to_analysis_csv(SAMPLE_PROFILE, SAMPLE_CATEGORIES)
    assert payload.startswith(b"\xef\xbb\xbf")
    table = read_csv(payload)
    assert table[0] == export.ANALYSIS_PROFILE_HEADERS
    assert table[1] == ["Janvier", "6300.00",
                        "~3400.00 · Santé (2024, 2025)",
                        "2900.00", "812.50", "2024, 2025"]
    assert table[2] == ["Mai", "9200.00", "—", "9100.00", "600.00",
                        "2024, 2025, 2026"]
    assert table[3] == []  # the blank line between the two blocks
    assert table[4] == export.ANALYSIS_CATEGORY_HEADERS
    assert table[5] == ["Santé", "402.25", "Janvier", "3400.00",
                        "+2.22 %", "chaque Mai · ~9100.00 (2025, 2026)"]
    assert table[6] == ["Logement", "1831.50", "Janvier", "1900.00",
                        "-3.00 %", "—"]
    assert table[7] == ["Épargne", "500.00", "Mai", "500.00",
                        "0.00 %", "—"]
    assert table[8] == ["Transport", "210.75", "Mai", "240.00",
                        "—", "—"]


def test_analysis_xlsx_has_two_sheets():
    """Both tables get their own sheet, declared in the content types and
    backed by their own armed filter."""
    archive = zipfile.ZipFile(
        io.BytesIO(export.to_analysis_xlsx(SAMPLE_PROFILE, SAMPLE_CATEGORIES)))
    names = set(archive.namelist())
    assert "xl/worksheets/sheet1.xml" in names
    assert "xl/worksheets/sheet2.xml" in names

    types = archive.read("[Content_Types].xml").decode()
    assert 'PartName="/xl/worksheets/sheet1.xml"' in types
    assert 'PartName="/xl/worksheets/sheet2.xml"' in types

    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    tabs = [node.get("name")
            for node in workbook.findall(f"{NS}sheets/{NS}sheet")]
    assert tabs == ["Profil mensuel", "Par catégorie"]
    filters = workbook.findall(f"{NS}definedNames/{NS}definedName")
    assert [node.get("name") for node in filters] == [
        "_xlnm._FilterDatabase", "_xlnm._FilterDatabase"]
    assert [node.get("localSheetId") for node in filters] == ["0", "1"]


def test_analysis_xlsx_amounts_are_numbers_not_text():
    """A column that looks like money has to sum."""
    archive = zipfile.ZipFile(
        io.BytesIO(export.to_analysis_xlsx(SAMPLE_PROFILE, SAMPLE_CATEGORIES)))
    sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    first = next(row for row in sheet.iter(f"{NS}row") if row.get("r") == "2")
    cells = {cell.get("r")[0]: cell for cell in first}
    assert cells["A"].find(f"{NS}is/{NS}t").text == "Janvier"
    assert cells["B"].get("t") is None  # numeric, not inline text
    assert float(cells["B"].find(f"{NS}v").text) == pytest.approx(6300.0)


def test_analysis_xlsx_parts_are_well_formed_and_declared():
    """The two sheets and the document title all have to be declared, or the
    file opens with a repair prompt."""
    archive = zipfile.ZipFile(
        io.BytesIO(export.to_analysis_xlsx(SAMPLE_PROFILE, SAMPLE_CATEGORIES)))
    names = set(archive.namelist())
    for name in names:
        ET.fromstring(archive.read(name))  # raises if malformed
    assert "docProps/core.xml" in names
    types = archive.read("[Content_Types].xml").decode()
    assert 'PartName="/docProps/core.xml"' in types
    assert "<dc:title>Analyse</dc:title>" in archive.read(
        "docProps/core.xml").decode()


def test_analysis_xlsx_relationships_point_at_parts_that_exist():
    archive = zipfile.ZipFile(
        io.BytesIO(export.to_analysis_xlsx(SAMPLE_PROFILE, SAMPLE_CATEGORIES)))
    names = set(archive.namelist())
    for rels, base in (("_rels/.rels", ""), ("xl/_rels/workbook.xml.rels", "xl/")):
        tree = ET.fromstring(archive.read(rels))
        targets = [node.get("Target") for node in tree]
        assert targets
        for target in targets:
            assert base + target in names, f"{rels} points at a missing {target}"


def test_analysis_xlsx_is_byte_identical_between_runs():
    """No clock in the output, so an export can be diffed against the last
    one -- same promise as the transaction export."""
    assert (export.to_analysis_xlsx(SAMPLE_PROFILE, SAMPLE_CATEGORIES)
            == export.to_analysis_xlsx(SAMPLE_PROFILE, SAMPLE_CATEGORIES))


# --- writing to disk --------------------------------------------------------

def test_write_picks_the_format_from_the_extension(rows, tmp_path):
    csv_path = export.write(rows[:5], tmp_path / "a.csv")
    xlsx_path = export.write(rows[:5], tmp_path / "b.xlsx")
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert zipfile.is_zipfile(xlsx_path)


def test_an_unknown_extension_is_refused_rather_than_guessed(rows, tmp_path):
    with pytest.raises(ValueError):
        export.write(rows[:5], tmp_path / "c.txt")


def test_the_filename_carries_the_window(rows):
    name = export.filename(dt.date(2025, 1, 1), dt.date(2025, 12, 31), "csv")
    assert name == "pms-2025-01-01_2025-12-31.csv"
