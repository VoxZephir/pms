"""The analysis (`/api/analyse`): the ordinary month, its year modes, the
category drill, and the export that holds what the page showed."""

from __future__ import annotations

import io
import zipfile

import pytest

from webhelpers import api


def test_the_ordinary_month_and_the_categories(client):
    data = api(client, "/api/analyse")
    assert len(data["profile"]) == 12 and data["baseline"] > 0
    for month in data["profile"]:
        assert {"raw_median", "stripped_median", "seasonal_median", "years"} <= month.keys()
    # At least one category is detected seasonal, and says when.
    seasonal = [c for c in data["categories"] if c["seasonal"]]
    assert seasonal and all(c["seasonal"]["month_label"] for c in seasonal)
    # A seasonal category has no trend: its median mixes the bill and the rest.
    assert all(c["trend"] is None for c in seasonal)


def test_a_year_replaces_the_median_and_is_validated(client):
    """One observed year at a time, so a rise shows raw; an unknown year falls
    back, and thousands of digits must not blow up `int()` before it does."""
    data = api(client, "/api/analyse?year=2025")
    assert data["year"] == "2025"
    assert [y["id"] for y in data["years"]][0] == "median"
    assert data["profile"] != api(client, "/api/analyse")["profile"]
    assert api(client, "/api/analyse?year=9999")["year"] == "median"
    assert api(client, "/api/analyse?year=" + "9" * 5000)["year"] == "median"


def test_a_category_drills_into_its_real_months(client):
    data = api(client, "/api/analyse?cat=Imp%C3%B4ts")
    drill = data["drill"]
    assert drill["category"] == "Impôts"
    assert drill["rows"] and all(r["amount"] > 0 for r in drill["rows"])
    assert drill["median"] > 0
    assert api(client, "/api/analyse?cat=Inventée")["drill"] is None


def test_the_drill_obeys_the_year_in_the_url(client):
    """?year=2025&cat=X shows 2025's months only, like the profile."""
    drill = api(client, "/api/analyse?year=2025&cat=Imp%C3%B4ts")["drill"]
    assert drill["rows"] and all(r["key"].startswith("2025-") for r in drill["rows"])


def test_the_csv_export_holds_both_tables(client):
    response = client.get("/analyse/export.csv")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    body = response.get_data(as_text=True)
    assert body.startswith("﻿")
    for probe in ("Médiane brute", "Médiane hors saisonnier", "Tendance", "Saisonnier"):
        assert probe in body


def test_the_export_follows_the_year(client):
    assert client.get("/analyse/export.csv?year=2025").data != client.get("/analyse/export.csv").data


def test_the_xlsx_export_has_two_sheets(client):
    response = client.get("/analyse/export.xlsx")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.data))
    assert {"xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"} <= set(archive.namelist())
    workbook = archive.read("xl/workbook.xml").decode("utf-8")
    assert "Profil mensuel" in workbook and "Par catégorie" in workbook
    assert workbook.count("_xlnm._FilterDatabase") == 2


def test_an_unknown_export_format_is_a_404(client):
    assert client.get("/analyse/export.txt").status_code == 404


def test_the_page_reads_the_past_several_ways(client):
    """The four figures, the year's change, the rhythm and the weekdays ride
    with the page; each category carries its line and its hue, the tail none."""
    data = api(client, "/api/analyse")
    h = data["headline"]
    assert h["spending"] > 0 and h["income"] > 0 and h["year"] == data["change"]["total"]
    assert data["rhythm"]["median"] and data["weekdays"]["rows"]
    slots = [c["slot"] for c in data["categories"]]
    named = [s for s in slots if s is not None]
    assert len(named) == len(set(named)) and all(0 <= s < 8 for s in named)
    assert all(c["spark"] and c["kind"] for c in data["categories"])
    drill = api(client, "/api/analyse?cat=Alimentation")["drill"]
    assert drill["merchants"] and drill["years"]


def test_ones_own_inflation_weighs_the_fixed_prices(client):
    a = api(client, "/api/analyse")
    inf = a["inflation"]
    labels = {r["label"] for r in inf["rows"]}
    assert "Assura-Basis SA" in labels and "Administration fiscale cantonale" not in labels
    assert inf["pct"] == pytest.approx((inf["yearly_now"] / inf["yearly_before"] - 1) * 100)
    assert sum(r["contribution"] for r in inf["rows"]) == pytest.approx(inf["pct"])
    assert inf["cpi"]["month"] == "2026-07" and inf["cpi"]["source"]


def test_the_month_against_the_swiss_household(client):
    h = api(client, "/api/analyse")["households"]
    assert h["months"] == 12 and h["source"]
    rent = next(r for r in h["rows"] if r["label"].startswith("Logement"))
    assert rent["mine"] > 1650 and rent["person"] == pytest.approx(1449 / 2.07, abs=0.01)
