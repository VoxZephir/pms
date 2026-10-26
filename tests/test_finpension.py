"""The 3a journal and reports: a second statement, with the same captured
snapshot pattern as the brokerage. All numbers here are made up."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from pms import finpension

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "inbox" / "finpension" / "rapport_de_transactions.csv"
REPORT = ROOT / "inbox" / "finpension" / "rapport_de_performance_2025.pdf"


def _write_journal(tmp_path, rows: str) -> Path:
    path = tmp_path / "journal.csv"
    path.write_text("Date;Category;\"Asset Name\";ISIN;\"Number of Shares\";"
                    "\"Asset Currency\";\"Currency Rate\";\"Asset Price in CHF\";"
                    "\"Cash Flow\";Balance\n" + rows, encoding="utf-8")
    return path


def test_parse_journal_summarizes(tmp_path):
    path = _write_journal(tmp_path, (
        "2024-05-23;Deposit;;;;CHF;1.0000000000;;7000.000000;7000.000000\n"
        "2024-05-28;Buy;\"Fonds Test\";CH123;1.000000;CHF;1.0;1704.63;-630.71;6425.29\n"
        "2025-01-07;Interests;;;;CHF;1.0;;0.17;6425.46\n"
        "2025-07-07;\"Flat-rate administrative fee\";;;;CHF;1.0;;-7.19;6418.27\n"
        "2025-05-22;Dividend;\"Fonds Test\";CH123;;CHF;1.0;;40.57;6458.84\n"))
    journal = finpension.parse_journal(path)
    assert journal["deposits"] == 7000.0
    assert journal["dividends"] == 40.57
    assert journal["interests"] == 0.17
    assert journal["fees"] == 7.19
    assert journal["deposits_by_year"] == {"2024": 7000.0}
    assert journal["first"] == "2024-05-23"
    assert journal["last"] == "2025-07-07"
    assert len(journal["entries"]) == 5
    assert journal["entries"][0]["category"] == "Deposit"


def test_parse_journal_empty_file(tmp_path):
    path = tmp_path / "journal.csv"
    path.write_text("Date;Category;\"Asset Name\";ISIN;\"Number of Shares\";"
                    "\"Asset Currency\";\"Currency Rate\";\"Asset Price in CHF\";"
                    "\"Cash Flow\";Balance\n", encoding="utf-8")
    journal = finpension.parse_journal(path)
    assert journal["entries"] == []
    assert journal["first"] is None


def test_load_snapshot(tmp_path):
    path = tmp_path / "finpension.json"
    path.write_text(json.dumps({
        "value": 8300.0, "value_as_of": "2025-12-31", "deposits": 7000.0,
        "dividends": 90.0, "fees": 40.0,
        "holdings": {"CH123": 3.849},
        "first": "2024-05-23", "last": "2026-07-07",
        "yearly": [["2025-12-31", 8300.0], ["2024-12-31", 7800.0]],
    }), encoding="utf-8")
    data = finpension.load(path)
    assert data["value"] == 8300.0
    assert data["deposits"] == 7000.0
    assert data["gains"] == 1300.0
    assert data["holdings"] == {"CH123": 3.849}
    assert data["first"] == "2024-05-23"
    assert data["yearly"][0][0].isoformat() == "2024-12-31"  # sorted


def test_regenerate_from_documents(tmp_path):
    """The update flow: new documents dropped in inbox/finpension/, then
    `python -m pms --finpension` rebuilds the snapshot."""
    journal = tmp_path / "rapport_de_transactions.csv"
    journal.write_text(
        "Date;Category;\"Asset Name\";ISIN;\"Number of Shares\";"
        "\"Asset Currency\";\"Currency Rate\";\"Asset Price in CHF\";"
        "\"Cash Flow\";Balance\n"
        "2024-05-23;Deposit;;;;CHF;1.0;;7000.0;7000.0\n"
        "2024-05-28;Buy;\"Fonds Test\";CH123;1.0;CHF;1.0;1704.63;-630.71;6425.29\n"
        "2025-07-07;\"Flat-rate administrative fee\";;;;CHF;1.0;;-7.19;6418.1\n",
        encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    snapshot_path = tmp_path / "finpension.json"

    snapshot = finpension.regenerate(journal, reports, snapshot_path)
    assert snapshot["deposits"] == 7000.0
    assert snapshot["fees"] == 7.19
    holding = snapshot["holdings"]["CH123"]
    assert holding["shares"] == 1.0
    assert holding["price"] == 1704.63
    assert holding["name"] == "Fonds Test"
    assert snapshot["cash"] == 6418.1
    assert snapshot["first"] == "2024-05-23"
    assert snapshot["value"] == 0.0  # no report, no reconstruction yet
    assert snapshot_path.exists()


def test_fund_class():
    assert finpension.fund_class("UBS (CH) Index Equity Fund EM NT CHF") == "Actions"
    assert finpension.fund_class("UBS Index Fund - Equities World") == "Actions"
    assert finpension.fund_class("Global Bond Fund") == "Obligations"
    assert finpension.fund_class("Money Market Fund CHF") == "Cash"
    assert finpension.fund_class("Produit exotique") == "Autres"


def test_regenerate_keeps_a_newer_reconstruction(tmp_path):
    journal = tmp_path / "rapport_de_transactions.csv"
    journal.write_text(
        "Date;Category;\"Asset Name\";ISIN;\"Number of Shares\";"
        "\"Asset Currency\";\"Currency Rate\";\"Asset Price in CHF\";"
        "\"Cash Flow\";Balance\n"
        "2024-05-23;Deposit;;;;CHF;1.0;;7000.0;7000.0\n",
        encoding="utf-8")
    snapshot_path = tmp_path / "finpension.json"
    snapshot_path.write_text(json.dumps({
        "value": 9400.0, "value_as_of": "2026-08-03", "deposits": 7000.0,
        "dividends": 0.0, "interests": 0.0, "fees": 0.0, "yearly": [],
        "proxy_series": {"SMI": [["2026-08-03", 14371.7]]},
    }), encoding="utf-8")

    snapshot = finpension.regenerate(journal, tmp_path / "nope", snapshot_path)
    # The reconstruction (03.08.2026) is newer than any annual report (31.12),
    # so the session-captured value survives a regeneration -- and so do the
    # captured proxy series, which no document can rebuild.
    assert snapshot["value"] == 9400.0
    assert snapshot["value_as_of"] == "2026-08-03"
    assert snapshot["proxy_series"] == {"SMI": [["2026-08-03", 14371.7]]}


def test_load_missing_or_corrupt(tmp_path):
    assert finpension.load(tmp_path / "nope.json") is None
    path = tmp_path / "finpension.json"
    path.write_text("{not json", encoding="utf-8")
    assert finpension.load(path) is None


def test_value_at_is_a_staircase(tmp_path):
    path = tmp_path / "finpension.json"
    path.write_text(json.dumps({
        "value": 9400.0, "value_as_of": "2026-08-03", "deposits": 0.0,
        "dividends": 0.0, "interests": 0.0, "fees": 0.0,
        "yearly": [["2024-12-31", 7811.45], ["2025-12-31", 8300.0]],
    }), encoding="utf-8")
    data = finpension.load(path)

    assert finpension.value_at(data, dt.date(2024, 6, 1)) is None
    assert finpension.value_at(data, dt.date(2024, 12, 31)) == 7811.45
    assert finpension.value_at(data, dt.date(2025, 6, 1)) == 7811.45
    assert finpension.value_at(data, dt.date(2025, 12, 31)) == 8300.0
    assert finpension.value_at(data, dt.date(2026, 8, 3)) == 9400.0
    assert finpension.value_at(data, dt.date(2026, 8, 4)) == 9400.0


def test_value_at_reconstructs_daily_between_anchors(tmp_path):
    """Between two observed values the curve follows the blended proxies --
    daily when the captured series is daily -- and meets the anchors
    exactly. The proxies mapping is what ties each holding to its proxy;
    without it the reconstruction is a silent staircase."""
    path = tmp_path / "finpension.json"
    path.write_text(json.dumps({
        "value": 9500.0, "value_as_of": "2026-08-03", "deposits": 0.0,
        "dividends": 0.0, "interests": 0.0, "fees": 0.0,
        "yearly": [["2026-06-30", 9350.0]],
        "holdings": {"CH123": {"shares": 1.0, "price": 100.0,
                               "name": "Fonds", "class": "Actions"}},
        "proxies": {"CH123": "SMI"},
        "proxy_series": {"SMI": [["2026-06-30", 100.0], ["2026-07-01", 101.0],
                                 ["2026-07-02", 99.5], ["2026-07-03", 102.0]]},
    }), encoding="utf-8")
    data = finpension.load(path)
    assert finpension.value_at(data, dt.date(2026, 6, 30)) == 9350.0
    assert finpension.value_at(data, dt.date(2026, 7, 1)) == 9443.5
    assert finpension.value_at(data, dt.date(2026, 7, 2)) == 9303.25
    assert finpension.value_at(data, dt.date(2026, 7, 3)) == 9537.0


def test_parse_report_value_on_the_real_report():
    """The overview page's last amount is the portfolio value. Only runs
    where the finpension reports were actually dropped in inbox/."""
    if not REPORT.exists():
        import pytest
        pytest.skip("finpension reports not present")
    value = finpension.parse_report_value(REPORT)
    assert value and value > 5000


def test_regenerate_keeps_the_declared_fund_fields_and_dates_the_fees(tmp_path):
    """Geography and short name are declared by hand, in no document: a
    `--finpension` used to wipe them, and the geographic split with them.
    The fees come back dated, so a window can say what it cost."""
    journal = _write_journal(tmp_path, (
        "2024-05-23;Deposit;;;;CHF;1.0;;7000.0;7000.0\n"
        "2024-05-28;Buy;\"Fonds Test\";CH123;1.0;CHF;1.0;1704.63;-630.71;6425.29\n"
        "2025-04-07;\"Flat-rate administrative fee\";;;;CHF;1.0;;-1.955;6423.335\n"
        "2025-07-07;\"Flat-rate administrative fee\";;;;CHF;1.0;;-7.19;6416.145\n"))
    snapshot_path = tmp_path / "finpension.json"
    snapshot_path.write_text(json.dumps({
        "value": 1.0, "yearly": [],
        "holdings": {"CH123": {"shares": 9.0, "geography": {"Suisse": 100},
                               "short": "Test CH"}},
    }), encoding="utf-8")

    snapshot = finpension.regenerate(journal, tmp_path / "nope", snapshot_path)
    holding = snapshot["holdings"]["CH123"]
    assert holding["geography"] == {"Suisse": 100}
    assert holding["short"] == "Test CH"
    assert holding["shares"] == 1.0  # the journal still wins on the numbers
    assert snapshot["fee_entries"] == [["2025-04-07", 1.96], ["2025-07-07", 7.19]]
    # The total from the unrounded flows, not the sum of rounded entries.
    assert snapshot["fees"] == 9.14
    loaded = finpension.load(snapshot_path)
    assert loaded["fee_entries"] == [(dt.date(2025, 4, 7), 1.96),
                                     (dt.date(2025, 7, 7), 7.19)]
