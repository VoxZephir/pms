"""The weekly summary and its push: what the week says, when it is due,
and that the topic never leaks into an error."""

from __future__ import annotations

import datetime as dt

import pytest

from pms import notify, weekly
from webhelpers import api

ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture
def held(client):
    return client.application.extensions["pms_store"].statement


def test_the_week_is_the_statements_last_seven_days(held):
    s = weekly.summary(held, dt.date(2026, 8, 2))
    assert (s["start"], s["end"]) == (dt.date(2026, 7, 24), dt.date(2026, 7, 30))
    week = [t for t in held.transactions if s["start"] <= t.date <= s["end"]
            and t.amount_chf < 0 and t.category != "Virement interne"]
    assert s["spent"] == pytest.approx(sum(-t.amount_chf for t in week if not t.kind.startswith("Transfert")), abs=0.01)
    assert s["ordinary"] and s["vs_ordinary"] == pytest.approx(s["spent"] - s["ordinary"], abs=0.01)
    assert "CHF dépensés du 24.07 au 30.07" in s["lines"][0]


def test_the_message_names_no_payee(held):
    s = weekly.summary(held, dt.date(2026, 8, 2))
    payees = {t.label for t in held.transactions if t.label}
    assert s["due"], "rent and premium fall in the week ahead"
    assert not any(p in s["text"] for p in payees if len(p) > 4)


def test_the_slot_is_the_chosen_day_and_hour():
    settings = {**notify.DEFAULTS, "enabled": True, "topic": "pms-x", "weekday": 6, "hour": 19}
    monday = dt.datetime(2026, 10, 19, 9)
    assert notify.slot(settings, monday) == dt.datetime(2026, 10, 18, 19)
    assert notify.due(settings, monday)
    assert not notify.due({**settings, "last_sent": "2026-10-18T19:02:00"}, monday)
    # A failed try waits an hour before the next.
    assert not notify.due({**settings, "last_try": "2026-10-19T08:30:00"}, monday)
    assert notify.due({**settings, "last_try": "2026-10-19T07:30:00"}, monday)
    assert not notify.due({**settings, "enabled": False}, monday)


def test_the_clock_sends_once_and_keeps_the_error(tmp_path):
    path = tmp_path / "notify.json"
    notify.save(path, {**notify.DEFAULTS, "enabled": True, "topic": "pms-secret"})
    sent = []
    clock = notify.Clock(path, lambda: {"title": "T", "text": "x"}, sender=lambda s, t, x: sent.append(t))
    now = dt.datetime(2026, 10, 19, 9)
    assert clock.tick(now) and not clock.tick(now + dt.timedelta(minutes=5))
    assert sent == ["T"]

    def broken(settings, title, text):
        raise RuntimeError("serveur injoignable (gaierror)")
    notify.save(path, {**notify.DEFAULTS, "enabled": True, "topic": "pms-secret"})
    notify.Clock(path, lambda: {"title": "T", "text": "x"}, sender=broken).tick(now)
    saved = notify.load(path)
    assert saved["last_error"] and "pms-secret" not in saved["last_error"] and saved["last_sent"] is None


def test_the_page_saves_draws_a_topic_and_tests(client, monkeypatch):
    path = client.application.extensions["pms_store"].path.with_name("notify.json")
    sent = []
    monkeypatch.setattr(notify, "send", lambda s, t, x: sent.append((s["topic"], t)))
    try:
        a = api(client, "/api/semaine")
        assert a["summary"]["lines"] and a["settings"]["enabled"] is False
        r = client.post("/api/semaine", json={"action": "save", "enabled": True, "weekday": 6, "hour": 19,
                                              "server": "https://ntfy.sh"}, headers=ORIGIN).get_json()
        topic = r["settings"]["topic"]
        assert topic.startswith("pms-") and r["settings"]["next"]
        assert client.post("/api/semaine", json={"action": "test"}, headers=ORIGIN).status_code == 200
        assert sent and sent[0][0] == topic
        other = client.post("/api/semaine", json={"action": "topic"}, headers=ORIGIN).get_json()
        assert other["settings"]["topic"] != topic
        assert client.post("/api/semaine", json={"action": "save", "server": "ftp://x"},
                           headers=ORIGIN).status_code == 400
    finally:
        path.unlink(missing_ok=True)


def test_the_cash_floor_and_the_3a_room_close_the_message(held):
    s = weekly.summary(held, dt.date(2026, 11, 20), floor="Cash projeté sous ton seuil.",
                       pillar="3a : 1'000 CHF de plafond encore libres.")
    at = s["lines"].index("⚠ Cash projeté sous ton seuil.")
    assert s["lines"][at + 1] == "3a : 1'000 CHF de plafond encore libres."
