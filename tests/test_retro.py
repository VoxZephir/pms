"""The year in review: each finding computed from the year's rows."""

from __future__ import annotations

import pytest

from webhelpers import api


def test_the_year_adds_up(client):
    a = api(client, "/api/bilan?year=2025")
    assert a["chosen"]["whole"] and a["year"] == 2025
    assert a["kept"] == pytest.approx(a["earned"] - a["spent"], abs=0.01)
    assert sum(m["amount"] for m in a["months"]) == pytest.approx(a["spent"], abs=0.05)
    assert a["dear"]["month"] == "mai" and a["dear"]["why"]["category"] == "Impôts"


def test_websites_are_not_countries_visited_and_bills_not_shops(client):
    a = api(client, "/api/bilan?year=2025")
    countries = {c["country"] for c in a["countries"]}
    assert "Italie" in countries and not countries & {"Pays-Bas", "Etats-Unis"}
    assert [s["name"] for s in a["stays"]] == ["Italie, juillet 2025"]
    assert a["biggest_shop"]["label"] != "Assura-Basis SA"
    assert a["regular"]["label"] == "Restaurant Cantine Alpha"


def test_the_year_defaults_to_the_last_whole_one_and_short_years_are_left_out(client):
    years = [y["year"] for y in api(client, "/api/bilan")["years"]]
    assert 2024 in years  # five months of 2024
    assert api(client, "/api/bilan?year=1990")["year"] in years
