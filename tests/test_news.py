"""A statement that just arrived: which month it completes, and for how long to say so."""

from __future__ import annotations

import datetime as dt

import pytest
from webhelpers import api

from pms.web import news

NOW = dt.datetime(2026, 9, 22, 20, 0)


def _source(minutes_ago: float, added: int = 94, **extra) -> dict:
    when = NOW - dt.timedelta(minutes=minutes_ago)
    return {"file": "releve.pdf", "sha256": "abc123", "added": added,
            "ingested_at": when.isoformat(timespec="seconds"), **extra}


def test_the_month_to_open_is_the_last_one_the_ledger_covers_whole():
    assert news.last_whole_month(dt.date(2026, 9, 21)) == \
        (dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    assert news.last_whole_month(dt.date(2026, 8, 31)) == \
        (dt.date(2026, 8, 1), dt.date(2026, 8, 31))


def test_the_notice_lasts_a_week():
    assert news.news([_source(60 * 24 * 6)], dt.date(2026, 9, 21), NOW)
    assert news.news([_source(60 * 24 * 8)], dt.date(2026, 9, 21), NOW) is None


def test_an_import_that_added_nothing_is_not_news():
    assert news.news([_source(2, added=0)], dt.date(2026, 9, 21), NOW) is None


def test_a_reparse_is_maintenance_not_news():
    assert news.news([_source(2, reimported=1)], dt.date(2026, 9, 21), NOW) is None


# --- a statement due ----------------------------------------------------------------

TODAY = dt.date(2026, 10, 15)


def _until(day: str, account: str = "") -> dict:
    return {"file": "x", "period_end": day, "account": account,
            "ingested_at": "2026-10-01T10:00:00"}


def test_a_bank_is_late_two_weeks_after_its_newest_statement():
    assert news.late([_until("2026-10-01")], TODAY) == []          # 14 days: not yet
    late = news.late([_until("2026-09-01"), _until("2026-09-30")], TODAY)
    assert [(item["bank"], item["until"], item["days"]) for item in late] == \
        [("Swissquote", dt.date(2026, 9, 30), 15)]
    assert late[0]["url"].startswith("https://")


def test_each_bank_by_the_account_it_feeds():
    """A fresh Revolut export says nothing about a late Swissquote one."""
    late = news.late([_until("2026-08-01"), _until("2026-10-10", "revolut")], TODAY)
    assert [item["bank"] for item in late] == ["Swissquote"]
    old_revolut = {**_until("2026-08-01", "revolut"), "ingested_at": "2026-08-02T08:00:00"}
    late = news.late([_until("2026-10-10"), old_revolut], TODAY)
    assert [item["bank"] for item in late] == ["Revolut"]


def test_an_export_without_a_period_covers_up_to_its_import():
    """Revolut's CSV prints no period: its last row was 22.08 because the
    account did not move, not because the export stopped. Imported on 05.10,
    it covers up to 05.10 -- seen on the real ledger, where the reminder
    first said Revolut was 54 days late."""
    quiet = {**_until("2026-08-22", "revolut"), "ingested_at": "2026-10-05T21:39:41"}
    assert news.late([_until("2026-10-12"), quiet], TODAY) == []
    # Swissquote prints its period: an old statement imported today is old.
    stale = {**_until("2026-08-01"), "ingested_at": "2026-10-15T09:00:00"}
    assert [item["bank"] for item in news.late([stale], TODAY)] == ["Swissquote"]


def test_a_bank_never_imported_is_not_late():
    assert [item["bank"] for item in news.late([_until("2026-01-01")], TODAY)] == ["Swissquote"]
    assert news.late([], TODAY) == []


# --- the notice on the dashboard ---------------------------------------------------

def test_the_app_asks_for_a_late_statement(client):
    """The test statement stops on 30.07.2026: by any later today, it is late.
    Said with where to fetch it."""
    if dt.date.today() <= dt.date(2026, 7, 30) + dt.timedelta(days=news.LATE_DAYS):
        pytest.skip("the test statement is not late yet")
    (late,) = api(client, "/api/meta")["late"]
    assert late["bank"] == "Swissquote" and late["url"] == "https://www.swissquote.com/"
    assert late["until"] == "2026-07-30"


def test_the_app_announces_a_fresh_statement_and_its_month(client):
    """The test ledger was just built: its one import is news. It ends on
    30.07.2026, so the month it completes is June -- the window the notice
    opens, where the monthly review is."""
    fresh = api(client, "/api/meta")["news"]
    assert fresh["label"] == "juin 2026"
    assert (fresh["start"], fresh["end"]) == ("2026-06-01", "2026-06-30")
    assert api(client, "/api/dashboard?from=2026-06-01&to=2026-06-30")["review"]
