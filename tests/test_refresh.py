"""What moves without a statement, fetched again (`refresh.py`): each step
on its own, its words kept, the day marked done only when all went through;
and the savings page's button that runs it in the background
(`/api/fetch`). Steps are stand-ins: nothing here reaches the network."""

from __future__ import annotations

import datetime as dt
import time

import pytest
from webhelpers import api

from pms import refresh


def _steps(outcomes):
    def make(ledger_path, inbox):
        out = []
        for name, ok in outcomes:
            def step(name=name, ok=ok):
                print(f"{name} : lu")
                if ok == "raise":
                    raise OSError("site down")
                return 0 if ok else 1
            out.append((name, step))
        return out
    return make


def test_a_failed_step_does_not_stop_the_others_nor_mark_the_day(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setattr(refresh, "steps", _steps([("IBKR", True), ("repères", "raise"), ("inflation", True)]))
    record = refresh.run(ledger, tmp_path)
    steps = {s["name"]: s for s in record["last"]["steps"]}
    assert steps["IBKR"]["ok"] and steps["inflation"]["ok"] and steps["repères"]["ok"] is False
    assert "échec (OSError)" in steps["repères"]["said"][-1]
    assert "at" not in record and refresh.due(tmp_path)


def test_a_full_run_marks_the_day(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setattr(refresh, "steps", _steps([("repères", True)]))
    record = refresh.run(ledger, tmp_path)
    # IBKR without its Flex file is said, not failed.
    assert record["last"]["steps"][0]["name"] == "IBKR" and record["last"]["steps"][0]["ok"] is None
    assert not refresh.due(tmp_path)
    later = dt.datetime.fromisoformat(record["at"]) + refresh.EVERY
    assert refresh.due(tmp_path, now=later)


def test_the_button_runs_it_in_the_background(client, monkeypatch):
    monkeypatch.setattr(refresh, "steps", _steps([("IBKR", True), ("repères", True)]))
    path = client.application.extensions["pms_store"].path.with_name(refresh.STAMP)
    path.unlink(missing_ok=True)
    r = client.post("/api/fetch")
    assert r.status_code in (200, 202)
    for _ in range(50):
        state = api(client, "/api/fetch")
        if not state["running"]:
            break
        time.sleep(0.05)
    else:
        pytest.fail("le rafraîchissement ne s'est pas terminé")
    assert [s["name"] for s in state["last"]["steps"]] == ["IBKR", "repères"]
    assert state["at"] and not state["due"] and state["error"] == ""
    path.unlink(missing_ok=True)
