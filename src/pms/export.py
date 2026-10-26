"""Get the data back out: the current view as CSV or as a spreadsheet.

Everything upstream of this module parses, reconciles, categorises and corrects
-- and then keeps the result to itself. This is the way out, and it exports the
*enriched* rows: category, subcategory, bucket and CHF amount, not the raw lines
the bank printed. `python -m pms --json` already dumps those.

Two formats on purpose, because they answer to different readers:

* **CSV** is the interchange format, so it is written to the letter of RFC 4180
  -- comma-separated, ISO dates, a dot for decimals -- and parses identically in
  pandas, R or another script. It carries a UTF-8 BOM, which is the one
  concession to Excel: without it Excel reads the accents as mojibake.
* **xlsx** is the one you actually open. It carries real dates and real numbers,
  so a column sums without being cleaned up first.

The xlsx writer is a few hundred lines of stdlib rather than a dependency. The
format needed here is a fraction of OOXML -- any number of sheets, inline
strings, four cell formats -- and the alternative was to pull in a spreadsheet
library for a file this program only ever writes, never reads. The analysis
tables of `/analyse` go out the same door: one CSV with two blocks, or a
two-sheet workbook (`to_analysis_csv` / `to_analysis_xlsx`).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile
from pathlib import Path

from .models import Transaction

# The columns, in order. Each is (header, extractor, kind), where `kind` drives
# both the CSV rendering and the spreadsheet cell format.
COLUMNS: list[tuple[str, object, str]] = [
    ("Date", lambda t: t.date, "date"),
    ("Bénéficiaire", lambda t: t.label, "text"),
    ("Catégorie", lambda t: t.category, "text"),
    ("Sous-catégorie", lambda t: t.subcategory, "text"),
    ("Besoin/envie/épargne", lambda t: t.bucket, "text"),
    ("Montant", lambda t: t.amount, "amount"),
    ("Devise", lambda t: t.currency, "text"),
    ("Montant CHF", lambda t: t.amount_chf, "amount"),
    ("Corrigé", lambda t: "oui" if t.overridden else "non", "text"),
    ("Compte", lambda t: t.account.capitalize() if t.account else "Principal", "text"),
]

HEADERS = [name for name, _, _ in COLUMNS]


def table(transactions: list[Transaction]) -> list[list]:
    """The rows as native Python values -- dates and floats, not strings.

    Formatting is left to each writer: the spreadsheet wants a real date so the
    column sorts chronologically, and the CSV wants ISO text so it survives a
    round trip through any other tool.
    """
    return [[get(txn) for _, get, _ in COLUMNS] for txn in transactions]


def filename(start: dt.date | None, end: dt.date | None, suffix: str) -> str:
    """`pms-2025-01-01_2025-12-31.csv` -- the window is part of the name.

    An export detached from its period is a file you cannot identify three
    months later.
    """
    window = f"{start.isoformat()}_{end.isoformat()}" if start and end else "tout"
    return f"pms-{window}.{suffix.lstrip('.')}"


# --- CSV --------------------------------------------------------------------

def _csv_writer(buffer: io.StringIO) -> csv.writer:
    """RFC 4180: comma separator, quoted as needed, CRLF lines."""
    return csv.writer(buffer, delimiter=",", quotechar='"',
                      quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")


def _csv_value(value) -> str:
    """One cell: ISO dates, a dot for decimals, `—` for a missing number.

    Deliberately *not* localised: Swiss apostrophes and comma decimals belong
    on screen, not in an interchange format.
    """
    if value is None:
        return "—"
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.2f}"
    return value


def _csv_block(writer: csv.writer, headers: list[str], rows: list[list]) -> None:
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_csv_value(value) for value in row])


def to_csv(transactions: list[Transaction]) -> bytes:
    """RFC 4180, UTF-8 with a BOM.

    The file parses the same everywhere: a comma separator and a dot for
    decimals. The xlsx export is there for whoever just wants to double-click
    it.
    """
    buffer = io.StringIO(newline="")
    _csv_block(_csv_writer(buffer), HEADERS, table(transactions))
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


# --- xlsx -------------------------------------------------------------------

# Excel counts days from 1899-12-30 (the 1900 leap-year bug is baked into the
# epoch, so this offset is the one that makes every date after 1900-03-01 land
# right).
EXCEL_EPOCH = dt.date(1899, 12, 30)

# XML forbids most control characters outright; no escape exists for them.
ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Cell format indices into the `cellXfs` list built in `_styles`.
STYLE_TEXT, STYLE_HEADER, STYLE_DATE, STYLE_AMOUNT = 0, 1, 2, 3

COLUMN_WIDTHS = [12, 34, 22, 24, 20, 13, 8, 13, 9]


def _escape(value: str) -> str:
    value = ILLEGAL_XML.sub("", str(value))
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _column_name(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def _cell(ref: str, value, kind: str, style: int) -> str:
    if kind == "date" and isinstance(value, dt.date):
        return f'<c r="{ref}" s="{style}"><v>{(value - EXCEL_EPOCH).days}</v></c>'
    if kind == "amount" and isinstance(value, (int, float)):
        return f'<c r="{ref}" s="{style}"><v>{value:.2f}</v></c>'
    if value in ("", None):
        return f'<c r="{ref}" s="{style}"/>'
    return (f'<c r="{ref}" s="{style}" t="inlineStr">'
            f'<is><t xml:space="preserve">{_escape(value)}</t></is></c>')


def _sheet(headers: list[str], kinds: list[str],
           widths: list[float], rows: list[list]) -> str:
    """One worksheet part, built from a sheet's own columns.

    `kinds` aligns with `headers`, and each value in a row is written
    according to its column's kind: "date" as an Excel date serial, "amount"
    as a two-decimal number, anything else as text.
    """
    columns = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{width}" customWidth="1"/>'
        for i, width in enumerate(widths[:len(headers)]))

    last = _column_name(len(headers) - 1)
    body = ["".join(
        _cell(f"{_column_name(i)}1", name, "text", STYLE_HEADER)
        for i, name in enumerate(headers))]
    for number, row in enumerate(rows, start=2):
        cells = []
        for i, (value, kind) in enumerate(zip(row, kinds)):
            style = {"date": STYLE_DATE, "amount": STYLE_AMOUNT}.get(kind, STYLE_TEXT)
            cells.append(_cell(f"{_column_name(i)}{number}", value, kind, style))
        body.append("".join(cells))

    lines = "".join(f'<row r="{i + 1}">{cells}</row>'
                    for i, cells in enumerate(body))

    # The header is frozen and the filter is armed: this file exists to be
    # sliced, and scrolling a two-thousand-row sheet without column names is
    # the first thing anyone would have had to fix by hand.
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last}{len(rows) + 1}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        f'<cols>{columns}</cols>'
        f'<sheetData>{lines}</sheetData>'
        f'<autoFilter ref="A1:{last}{len(rows) + 1}"/>'
        '</worksheet>'
    )


def _styles() -> str:
    """Four cell formats: plain, bold header, date, amount.

    Excel is strict about this part -- the first two fills must be `none` and
    `gray125` and every list must declare its own count, or the file opens with
    a repair prompt.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="2">'
        '<numFmt numFmtId="164" formatCode="dd\\.mm\\.yyyy"/>'
        '<numFmt numFmtId="165" formatCode="#,##0.00"/>'
        '</numFmts>'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="2">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="4">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '</cellXfs>'
        # The "Normal" style. Readers warn about a workbook without one and
        # substitute their own default, which is a difference of opinion this
        # file does not need to provoke.
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def _content_types(sheet_count: int, with_core_props: bool) -> str:
    """One worksheet override per sheet, plus workbook, styles and -- when
    the workbook carries a title -- the core properties part."""
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, sheet_count + 1))
    core = ('<Override PartName="/docProps/core.xml"'
            ' ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            if with_core_props else "")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f'{sheets}'
        f'{core}'
        '<Override PartName="/xl/styles.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )


def _root_rels(with_core_props: bool) -> str:
    core = ('<Relationship Id="rId2"'
            ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/core-properties"'
            ' Target="docProps/core.xml"/>' if with_core_props else "")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
        ' Target="xl/workbook.xml"/>'
        f'{core}'
        '</Relationships>'
    )


def _workbook_rels(sheet_count: int) -> str:
    """One worksheet relationship per sheet, then the shared styles."""
    sheets = "".join(
        f'<Relationship Id="rId{i}"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"'
        f' Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, sheet_count + 1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{sheets}'
        f'<Relationship Id="rId{sheet_count + 1}"'
        ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"'
        ' Target="styles.xml"/>'
        '</Relationships>'
    )


def _defined_name(index: int, name: str, headers: list[str],
                  rows: list[list]) -> str:
    quoted = "'" + _escape(name).replace("'", "''") + "'"
    last = _column_name(len(headers) - 1)
    return (
        f'<definedName name="_xlnm._FilterDatabase" localSheetId="{index}" hidden="1">'
        f'{quoted}!$A$1:${last}${len(rows) + 1}'
        '</definedName>'
    )


def _workbook(sheets: list[tuple]) -> str:
    """The workbook part, plus one defined name per auto-filter.

    `_xlnm._FilterDatabase` is what Excel itself writes next to an
    `autoFilter`, and declaring it here -- with the local sheet id of each
    sheet -- is what makes the filters come back armed when the file is
    reopened rather than merely drawn.
    """
    sheet_tags = "".join(
        f'<sheet name="{_escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, _, _, _, _) in enumerate(sheets, start=1))
    defined = "".join(
        _defined_name(i - 1, name, headers, rows)
        for i, (name, headers, _, _, rows) in enumerate(sheets, start=1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{sheet_tags}</sheets>'
        '<definedNames>'
        f'{defined}'
        '</definedNames>'
        '</workbook>'
    )


def _core_props(title: str) -> str:
    """The document title, so the workbook is identifiable outside its tabs."""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties'
        ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:dcterms="http://purl.org/dc/terms/"'
        ' xmlns:dcmitype="http://purl.org/dc/dcmitype/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{_escape(title)}</dc:title>'
        '</cp:coreProperties>'
    )


def _package(sheets: list[tuple], title: str | None = None) -> bytes:
    """Zip any number of sheets into one workbook.

    Each sheet is (name, headers, kinds, widths, rows). Timestamps are fixed
    rather than taken from the clock so that exporting the same data twice
    produces byte-identical files -- which is what makes the output diffable
    and the tests deterministic. A `title` additionally names the workbook in
    its core properties.
    """
    parts = {
        "[Content_Types].xml": _content_types(len(sheets), title is not None),
        "_rels/.rels": _root_rels(title is not None),
        "xl/workbook.xml": _workbook(sheets),
        "xl/_rels/workbook.xml.rels": _workbook_rels(len(sheets)),
        "xl/styles.xml": _styles(),
    }
    if title is not None:
        parts["docProps/core.xml"] = _core_props(title)
    for i, (_, headers, kinds, widths, rows) in enumerate(sheets, start=1):
        parts[f"xl/worksheets/sheet{i}.xml"] = _sheet(headers, kinds, widths, rows)

    buffer = io.BytesIO()
    stamp = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()


# Excel rejects these in a sheet name, and silently truncates past 31 characters.
SHEET_NAME_BAN = re.compile(r"[\\/*?:\[\]]")


def sheet_name(start: dt.date | None, end: dt.date | None) -> str:
    if start and end:
        return SHEET_NAME_BAN.sub("-", f"{start.isoformat()} → {end.isoformat()}")[:31]
    return "Transactions"


def to_xlsx(transactions: list[Transaction],
            title: str = "Transactions") -> bytes:
    """A single-sheet workbook, written straight into a zip.

    Timestamps are fixed rather than taken from the clock so that exporting the
    same window twice produces byte-identical files -- which is what makes the
    output diffable and the tests deterministic.
    """
    return _package([(
        title,
        HEADERS,
        [kind for _, _, kind in COLUMNS],
        COLUMN_WIDTHS,
        table(transactions),
    )])


def to_xlsx_sheets(sheets: list[tuple], title: str = "Analyse") -> bytes:
    """A workbook of any number of sheets, written straight into a zip.

    `sheets` is one tuple per sheet: `(name, headers, kinds, widths, rows)`.

    * `name` -- the tab title. It is made Excel-safe the way `sheet_name()`
      makes one: banned characters become dashes, 31 characters max.
    * `headers` -- the column titles, in order.
    * `kinds` -- the kind of each column, aligned with `headers`: "date" is
      written as an Excel date serial, "amount" as a two-decimal number,
      anything else as text.
    * `widths` -- one column width per column, in the same order.
    * `rows` -- the body, one list per line, values already prepared (floats
      for "date" and "amount" columns, strings otherwise).

    Each sheet gets the frozen header and the armed auto-filter. `title`
    names the workbook in its core properties.
    """
    if not sheets:
        raise ValueError("au moins une feuille est requise")
    sanitised = [
        (SHEET_NAME_BAN.sub("-", name)[:31], headers, kinds, widths, rows)
        for name, headers, kinds, widths, rows in sheets
    ]
    return _package(sanitised, title)


# --- the analysis tables ----------------------------------------------------

ANALYSIS_PROFILE_HEADERS = [
    "Mois", "Médiane brute", "Pics saisonniers retirés",
    "Médiane hors saisonnier", "Dispersion (Q3−Q1)", "Années",
]

ANALYSIS_CATEGORY_HEADERS = [
    "Catégorie", "Médiane mensuelle", "Mois de pointe",
    "Médiane au pic", "Tendance", "Saisonnier",
]

_PROFILE_KINDS = ["text", "amount", "text", "amount", "amount", "text"]
_PROFILE_WIDTHS = [10, 14, 44, 18, 14, 18]
_CATEGORY_KINDS = ["text", "amount", "text", "amount", "text", "text"]
_CATEGORY_WIDTHS = [24, 16, 14, 14, 16, 40]


def _years_text(years: list[int]) -> str:
    """`[2024, 2025]` -> `2024, 2025`."""
    return ", ".join(str(year) for year in years)


def _pics_text(pics: list[dict]) -> str:
    """The seasonal one-offs of a month, `~3400.00 · Santé (2024, 2025)`,
    joined by "; ". A month with nothing seasonal says so with a dash."""
    if not pics:
        return "—"
    return "; ".join(
        f"~{pic['amount']:.2f} · {pic['category']} ({_years_text(pic['years'])})"
        for pic in pics)


def _trend_text(trend: float | None) -> str:
    """`2.22` -> `+2.22 %`, `-3.0` -> `-3.00 %`, `0` -> `0.00 %`; a missing
    trend says so with a dash."""
    if trend is None:
        return "—"
    if trend == 0:
        return "0.00 %"
    return f"{trend:+.2f} %"


def _seasonal_text(seasonal: dict | None) -> str:
    """`{month_label, amount, years}` -> `chaque Mai · ~9100.00 (2025, 2026)`."""
    if seasonal is None:
        return "—"
    return (f"chaque {seasonal['month_label']} · "
            f"~{seasonal['amount']:.2f} ({_years_text(seasonal['years'])})")


def _profile_rows(profile: list[dict]) -> list[list]:
    """One row per month; amounts stay numbers, text is already formatted, so
    the same rows serve both the CSV and the spreadsheet."""
    return [[
        month["label"], month["raw_median"], _pics_text(month["seasonal"]),
        month["stripped_median"], month["iqr"], _years_text(month["years"]),
    ] for month in profile]


def _category_rows(categories: list[dict]) -> list[list]:
    """One row per category; median and peak stay numbers, the trend and the
    seasonal one-off are already formatted text."""
    return [[
        cat["category"], cat["median"], cat["peak_month_label"], cat["peak"],
        _trend_text(cat["trend"]), _seasonal_text(cat["seasonal"]),
    ] for cat in categories]


def to_analysis_csv(profile: list[dict], categories: list[dict]) -> bytes:
    """The two analysis tables in one RFC 4180 file: the monthly profile,
    then the per-category stats, separated by a blank line. Same conventions
    as `to_csv` -- BOM, CRLF, dot decimals, no Swiss apostrophes.

    The dicts are the shape `web.api.analyse.analysis_data` returns:
    profile entries carry `label`, `raw_median`, `seasonal` (a list of
    {category, amount, years}), `stripped_median`, `years`, `iqr`; category
    entries carry `category`, `median`, `peak_month_label`, `peak`,
    `seasonal` (None or {month_label, amount, years}), `trend`.
    """
    buffer = io.StringIO(newline="")
    writer = _csv_writer(buffer)
    _csv_block(writer, ANALYSIS_PROFILE_HEADERS, _profile_rows(profile))
    writer.writerow([])  # the blank line that separates the two blocks
    _csv_block(writer, ANALYSIS_CATEGORY_HEADERS, _category_rows(categories))
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def to_analysis_xlsx(profile: list[dict], categories: list[dict]) -> bytes:
    """The two analysis tables as a two-sheet workbook, with the same columns
    as the CSV: « Profil mensuel » then « Par catégorie ». Amounts are real
    numbers, so a column sums without being cleaned up first.

    Same dict shape as `to_analysis_csv` -- the one `web.api.analyse.
    analysis_data` returns, month labels already spelled out.
    """
    return to_xlsx_sheets([
        ("Profil mensuel", ANALYSIS_PROFILE_HEADERS,
         _PROFILE_KINDS, _PROFILE_WIDTHS, _profile_rows(profile)),
        ("Par catégorie", ANALYSIS_CATEGORY_HEADERS,
         _CATEGORY_KINDS, _CATEGORY_WIDTHS, _category_rows(categories)),
    ])


# --- the tax return ---------------------------------------------------------

TAX_HEADERS = ["Poste", "Montant (CHF)", "Détail"]


def to_tax_xlsx(years: list[dict]) -> bytes:
    """The savings panel's « Pour la déclaration d'impôts », one sheet per
    31 December, newest first: each account, then the year's brokerage
    income and the 3a. The year-end dicts are `fiscal.year_end`'s.

    The figures are the app's (broker NAV, market closes, the statement's
    exchange rates), not the tax authority's year-end rates -- the detail
    column says so where it matters.
    """
    sheets = []
    for year in sorted(years, key=lambda y: -y["year"]):
        # The year still running: its figures at the statement's last day,
        # an estimate of the next return, said on the sheet and in its rows.
        at = year["day"].strftime("%d.%m.%Y")
        rows = [[r["name"], r["value"], r["detail"]] for r in year["rows"]]
        rows += [
            ["Fortune imposable, ces comptes", year["taxable"],
             f"estimation au {at} : le 31.12 n'est pas encore passé" if year.get("partial")
             else "valeurs de l'app, proches des cours de fin d'année de l'AFC, pas identiques"],
            ["Dividendes IBKR", year["dividends"], ""],
            ["Intérêts IBKR", year["interest"], ""],
            ["Impôt à la source US retenu", year["withheld"],
             "récupérable via la déclaration (formulaire DA-1)"],
            ["3a : versé dans l'année", year["pillar3a_paid"],
             "déductible du revenu ; l'attestation de la fondation fait foi"],
            [f"3a : valeur au {at[:5]}", year["pillar3a_value"], "hors fortune imposable"],
        ]
        sheets.append((f"Estimation {at}" if year.get("partial") else at, TAX_HEADERS,
                       ["text", "amount", "text"], [36, 16, 70], rows))
    return to_xlsx_sheets(sheets, title="Déclaration d'impôts")


RETURN_HEADERS = ["Rubrique", "Relevé (CHF)", "Déductible estimé (CHF)", "Où dans la déclaration", "Règle"]
LINES_HEADERS = ["Date", "Rubrique", "Libellé", "Montant (CHF)"]


def to_return_xlsx(data: dict) -> bytes:
    """The `/impots` page for one year (`taxes.return_items`): a summary
    sheet, rubric by rubric with its rule, then every line behind each
    rubric -- the figures the return is filled from, beside the
    certificates that remain the authority."""
    year = data["year"]
    net = data["net"]
    canton = data.get("canton")
    summary = [[f"Salaire versé : {p['label']}", p["amount"], None, "Revenus · activité salariée",
                "net versé ; le certificat de salaire donne le brut à déclarer"] for p in data["salaries"]]
    summary.append(["Revenu net retenu pour les seuils", net["value"], None, "",
                    "estimé : salaire versé moins le 3a" if net["estimated"] else "déclaré sur la page"])
    for item in data["items"]:
        summary.append([item["title"], item["amount"], item["deductible"], item["form"], item["rule"]])
        if canton and item.get("canton"):
            summary.append([f"   {canton['name']} (ICC)", None, item["canton"]["deductible"], item["form"],
                            item["canton"]["rule"]])
    summary += [
        ["Déductions repérées, impôt fédéral", None, data["deducted"], "", "estimation"],
        *([[f"Déductions repérées, {canton['name']}", None, data["deducted_canton"], "", "estimation"]] if canton else []),
        ["Intérêts bancaires", data["interest"]["bank"], None, "Revenus · intérêts", ""],
        ["Dividendes IBKR", data["interest"]["dividends"], None, "État des titres", ""],
        ["Intérêts IBKR", data["interest"]["broker"], None, "État des titres", ""],
        ["Impôt à la source US retenu", data["interest"]["withheld"], None, "Formulaire DA-1", "récupérable"],
        *[[f"Dividende brut : {s['name']}", s["dividends"]["gross"], None, "État des titres",
           f"net reçu {s['dividends']['net']:.2f}, impôt anticipé {s['dividends']['withheld']:.2f} récupérable"
           if s["withholding"] else "sans impôt anticipé"] for s in data.get("securities", []) if s["dividends"]["net"]],
        ["Fortune au 31.12, ces comptes", data["wealth"]["taxable"], None, "Fortune",
         "valeurs de l'app, proches des cours de fin d'année de l'AFC"],
        [f"Impôts {year} payés en {data['paid']['year']}" if data["paid"]["later"] else "Impôts payés dans l'année",
         data["paid"]["out"], None, "", "acomptes et décomptes"],
        ["Impôts remboursés", data["paid"]["back"], None, "", ""],
    ]
    lines = []
    for item in data["items"]:
        for row in item["rows"]:
            lines.append([row["date"], item["title"], row["label"], row["amount"]])
    for row in data["paid"]["rows"]:
        lines.append([row["date"], "Impôts payés", row["label"], row["amount"]])
    return to_xlsx_sheets([
        (f"Déclaration {year}", RETURN_HEADERS, ["text", "amount", "amount", "text", "text"],
         [34, 14, 18, 44, 80], summary),
        ("Lignes", LINES_HEADERS, ["date", "text", "text", "amount"], [12, 26, 44, 14], lines),
    ], title=f"Déclaration d'impôts {year}")


# --- writing to disk --------------------------------------------------------

FORMATS = {".csv": "csv", ".xlsx": "xlsx"}


def write(transactions: list[Transaction], path: Path,
          start: dt.date | None = None, end: dt.date | None = None) -> Path:
    """Write the export, picking the format from the file extension."""
    path = Path(path)
    kind = FORMATS.get(path.suffix.lower())
    if kind is None:
        raise ValueError(
            f"format inconnu : {path.suffix or path.name} "
            f"(attendu {' ou '.join(sorted(FORMATS))})")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (to_csv(transactions) if kind == "csv"
               else to_xlsx(transactions, sheet_name(start, end)))
    path.write_bytes(payload)
    return path
