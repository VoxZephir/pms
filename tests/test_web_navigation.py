"""Where everything is: the pages the browser's router draws, the addresses
kept from the old app, the window and its neighbours, the crumbs.

How the pages look and behave -- labels, focus, the tab bar, the period
picker -- is driven in a real browser (test_browser.py)."""

from __future__ import annotations

import pytest
from webhelpers import api

from pms.web.api import SPA

PAGES = ["/", "/transactions", "/epargne", "/analyse", "/previsions",
         "/corrections", "/corrections/tri", "/importer", "/jour/2025-05-15", "/a-venir", "/impots", "/projets", "/bilan", "/aide"]


@pytest.fixture
def built():
    if not (SPA / "index.html").exists():
        pytest.skip("front end not built")


@pytest.mark.parametrize("path", PAGES)
def test_every_page_serves_the_app(client, built, path):
    response = client.get(f"{path}?preset=all")
    assert response.status_code == 200
    assert b'<div id="root">' in response.data
    # Revalidated on every load, so a new build reaches the phone at once.
    assert response.headers["Cache-Control"] == "no-cache"


def test_the_built_assets_are_cached_for_good(client, built):
    asset = next((SPA / "assets").glob("*.js"))
    response = client.get(f"/static/spa/assets/{asset.name}")
    assert response.status_code == 200
    assert "immutable" in response.headers["Cache-Control"]


@pytest.mark.parametrize("old, new", [
    ("/reclasser", "/corrections"),
    ("/reclasser/tri?at=3", "/corrections/tri?at=3"),
    ("/day/2025-05-15", "/jour/2025-05-15"),
    ("/app/transactions?q=coop", "/transactions?q=coop"),
    ("/app/", "/"),
])
def test_the_old_addresses_still_lead_somewhere(client, old, new):
    """Bookmarks and the phone's home-screen icon point at the old app."""
    response = client.get(old)
    assert response.status_code == 301
    assert response.headers["Location"] == new


def test_an_unknown_page_is_the_app_saying_so(client, built):
    """The router draws "Page introuvable" with the way back; the status
    still says 404."""
    response = client.get("/pas-une-page")
    assert response.status_code == 404
    assert b'<div id="root">' in response.data


def test_an_unknown_endpoint_answers_in_json(client):
    response = client.get("/api/pas-un-endpoint")
    assert response.status_code == 404
    assert response.get_json()["error"]


# --- the window ---------------------------------------------------------------

def test_a_calendar_unit_steps_by_that_unit(client):
    """The arrow after April is May, not "30 days later"."""
    n = api(client, "/api/period?from=2025-05-01&to=2025-05-31")["neighbours"]
    assert (n["prev"]["start"], n["prev"]["end"]) == ("2025-04-01", "2025-04-30")
    assert (n["next"]["start"], n["next"]["end"]) == ("2025-06-01", "2025-06-30")
    assert n["prev_label"] == "Avril 2025"


def test_any_other_window_steps_by_its_own_length(client):
    n = api(client, "/api/period?from=2025-05-10&to=2025-06-10")["neighbours"]
    assert (n["prev"]["start"], n["prev"]["end"]) == ("2025-04-08", "2025-05-09")
    assert (n["next"]["start"], n["next"]["end"]) == ("2025-06-11", "2025-07-12")


def test_the_month_in_progress_steps_back_to_the_whole_previous_month(client):
    """The default view runs from the 1st to the last movement; its left
    arrow is last month, whole, and there is nothing to its right yet."""
    period = api(client, "/api/period")
    assert period["title"].startswith("Juillet 2026")
    n = period["neighbours"]
    assert (n["prev"]["start"], n["prev"]["end"]) == ("2026-06-01", "2026-06-30")
    assert not n["next"]["available"]


def test_the_crumbs_climb_back_out(client):
    crumbs = api(client, "/api/period?from=2025-05-01&to=2025-05-31")["crumbs"]
    assert [c["label"] for c in crumbs] == ["Tout", "Année 2025", "Mai 2025"]
    assert [c["current"] for c in crumbs] == [False, False, True]


def test_a_hand_typed_window_matches_no_preset(client):
    assert not any(p["active"] for p in api(client, "/api/period?from=2025-05-15&to=2025-05-20")["presets"])
    assert [p["id"] for p in api(client, "/api/period?preset=12m")["presets"] if p["active"]] == ["12m"]


def test_a_window_with_no_movement_is_said_so(client, statement, bounds):
    """The page offers the way back to twelve months; the data says empty."""
    import datetime as dt
    days = {t.date for t in statement.transactions}
    low, high = bounds
    empty = next(low + dt.timedelta(days=i) for i in range((high - low).days + 1)
                 if low + dt.timedelta(days=i) not in days)
    data = api(client, f"/api/dashboard?from={empty}&to={empty}&grain=day")
    assert data["count"] == 0


def test_an_out_of_range_page_is_clamped(client):
    """A shared URL with ?page=99 for a filter that no longer matches."""
    data = api(client, "/api/transactions?from=2025-05-01&to=2025-05-31&page=99")
    assert data["page"] == data["pages"]
    assert api(client, "/api/transactions?preset=all&page=abc")["page"] == 1
