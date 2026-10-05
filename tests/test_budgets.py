"""Monthly spending goals: a declared per-category amount, outside the ledger."""

from __future__ import annotations

import json

from pms.budgets import Budgets


def test_missing_file_is_empty(tmp_path):
    store = Budgets.load(tmp_path / "budgets.json")
    assert store.amounts == {}


def test_corrupt_file_is_empty(tmp_path):
    path = tmp_path / "budgets.json"
    path.write_text("{not json", encoding="utf-8")
    assert Budgets.load(path).amounts == {}


def test_roundtrip(tmp_path):
    path = tmp_path / "budgets.json"
    store = Budgets(path)
    store.set_budget("Alimentation", 400.0)
    store.set_budget("Restaurants", 150.0)
    store.save()

    loaded = Budgets.load(path)
    assert loaded.amounts == {"Alimentation": 400.0, "Restaurants": 150.0}


def test_invalid_entries_are_skipped(tmp_path):
    path = tmp_path / "budgets.json"
    path.write_text(json.dumps({
        "version": 1,
        "budgets": {"Bouffe": 400.0, "Rien": -5.0, "Nul": "abc", "": 10.0},
    }), encoding="utf-8")
    assert Budgets.load(path).amounts == {"Bouffe": 400.0}


def test_remove(tmp_path):
    path = tmp_path / "budgets.json"
    store = Budgets(path)
    store.set_budget("Bouffe", 400.0)
    assert store.remove("Bouffe") is True
    assert store.remove("Bouffe") is False
    assert store.amounts == {}


def test_save_is_clean_json(tmp_path):
    path = tmp_path / "budgets.json"
    Budgets(path).save()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1, "budgets": {}}
