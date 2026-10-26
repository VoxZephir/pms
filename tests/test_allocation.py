"""The target allocation, and the tax table as a workbook."""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from pms import allocation
from webhelpers import savings_snapshots


def test_a_split_must_add_up_to_100():
    targets, error = allocation.validate({"Cash": "20", "Actions": "80"})
    assert targets == {"Cash": 20.0, "Actions": 80.0} and error is None
    # Three thirds are a split; a missing tenth is not.
    assert allocation.validate({"Cash": "33.3", "Actions": "33.3", "Crypto": "33.3"})[1] is None
    assert "90 %" in allocation.validate({"Cash": "10", "Actions": "80"})[1]
    assert "virgule" in allocation.validate({"Cash": "12,5", "Actions": "87.5"})[1]
    assert allocation.validate({"Cash": "120"})[1]


def test_the_drift_says_what_to_move_and_the_moves_net_out():
    parts = [{"name": "Cash", "value": 6000.0}, {"name": "Actions", "value": 3000.0},
             {"name": "Autres", "value": 1000.0}]
    drift = allocation.drift(parts, {"Cash": 20.0, "Actions": 80.0})
    rows = {r["name"]: r for r in drift["rows"]}
    assert rows["Cash"]["gap"] == -4000.0 and rows["Actions"]["gap"] == 5000.0
    # A class the targets do not name is aimed at zero.
    assert rows["Autres"]["gap"] == -1000.0
    assert sum(r["gap"] for r in drift["rows"]) == pytest.approx(0.0)
    assert [r["name"] for r in drift["buy"]] == ["Actions"]
    assert [r["name"] for r in drift["sell"]] == ["Cash", "Autres"]
    assert allocation.drift(parts, {}) is None


def test_a_levered_fund_weighs_more_in_exposure_than_in_francs():
    # A return-stacked fund: 1'000 CHF carrying 1'000 of equity and 1'000 of
    # managed futures. The francs split it half and half.
    positions = [{"value": 1000.0, "exposure": 2.0, "asset_split": {"Actions": 50, "MF": 50}},
                 {"value": 500.0, "asset_class": "Actions"}]
    extra = allocation.leverage(positions)
    assert extra == {"Actions": 500.0, "Trend-Following": 500.0}
    parts = [{"name": "Cash", "value": 500.0}, {"name": "Actions", "value": 1000.0},
             {"name": "Trend-Following", "value": 500.0}]
    ex = allocation.exposure(parts, extra)
    assert ex["by_name"]["Actions"]["share"] == 75.0
    assert ex["by_name"]["Trend-Following"]["share"] == 50.0
    assert ex["by_name"]["Cash"]["share"] == 25.0
    assert ex["gross"] == 150.0
    # Nothing levered: the francs say it all.
    assert allocation.exposure(parts, allocation.leverage(positions[1:])) is None


def test_the_target_is_set_refused_and_cleared_from_the_panel(client):
    store_ = client.application.extensions["pms_store"]
    path = store_.path.with_name("allocation.json")
    paths = savings_snapshots(client)
    try:
        allocation_ = client.get("/api/savings?preset=all").get_json()["allocation"]
        assert allocation_["drift"] is None and allocation_["targets"] == {}

        refused = client.post("/api/allocation", json={"targets": {"Cash": "10", "Actions": "80"}})
        assert refused.status_code == 400 and not path.exists()
        assert "La répartition fait 90 %" in refused.get_json()["error"]

        saved = client.post("/api/allocation", json={"targets": {"Cash": "20", "Actions": "80"}})
        assert saved.status_code == 200 and path.exists()
        drift = client.get("/api/savings?preset=all").get_json()["allocation"]["drift"]
        assert drift["buy"] or drift["sell"]
        assert sum(r["gap"] for r in drift["rows"]) == pytest.approx(0.0, abs=0.05)

        client.post("/api/allocation", json={"action": "clear"})
        assert client.get("/api/savings?preset=all").get_json()["allocation"]["drift"] is None
    finally:
        for p in (path, *paths):
            p.unlink(missing_ok=True)


def test_the_tax_table_downloads_one_sheet_per_31_december(client):
    paths = savings_snapshots(client)
    try:
        response = client.get("/epargne/impots.xlsx")
        assert response.status_code == 200
        assert 'filename="pms-impots.xlsx"' in response.headers["Content-Disposition"]
        archive = zipfile.ZipFile(io.BytesIO(response.data))
        workbook = archive.read("xl/workbook.xml").decode()
        names = re.findall(r'<sheet name="([^"]+)"', workbook)
        # The year still running, if the statement reaches into it, is an
        # estimate at its last day -- named so, never a 31.12.
        assert names and all(re.fullmatch(r"(Estimation \d\d\.\d\d\.|31\.12\.)\d{4}", n)
                             for n in names)
        assert sum(n.startswith("Estimation") for n in names) <= 1
        assert names == sorted(names, key=lambda n: n[-4:], reverse=True)
        first = archive.read("xl/worksheets/sheet1.xml").decode()
        assert "Fortune imposable, ces comptes" in first
        # The page offers it exactly when it has a table to put in it.
        assert client.get("/api/savings?preset=all").get_json()["tax"]["years"]
    finally:
        for p in paths:
            p.unlink(missing_ok=True)
