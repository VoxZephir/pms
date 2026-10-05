"""A statement that just arrived: which month it completes, and for how long to say so."""

from __future__ import annotations

import datetime as dt

from webhelpers import text

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


# --- the notice on the dashboard ---------------------------------------------------

def test_the_dashboard_announces_a_fresh_statement_and_its_month(client):
    """The test ledger was just built: its one import is news. It ends on
    30.07.2026, so the month it completes is June."""
    body = text(client.get("/?preset=all"))
    assert "Nouveau relevé" in body
    assert "Voir la revue de juin 2026" in body
    assert "from=2026-06-01" in body and "to=2026-06-30" in body


def test_the_notice_goes_once_its_month_is_on_screen(client):
    body = text(client.get("/?from=2026-06-01&to=2026-06-30"))
    assert "Nouveau relevé" not in body
    assert 'id="p-review"' in body
