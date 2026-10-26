"""What every endpoint shares: Python values turned into JSON a browser can
parse, and the window resolved like everywhere else."""

from __future__ import annotations

import datetime as dt
import json
import math
from collections import Counter

from webhelpers import api

from pms.web.api.encode import jsonable


def test_a_value_that_is_not_a_number_becomes_null():
    """JSON has no NaN: the browser refuses the whole payload over one."""
    out = jsonable({"ratio": math.nan, "big": math.inf, "fine": 1.5})
    assert out == {"ratio": None, "big": None, "fine": 1.5}
    json.dumps(out, allow_nan=False)


def test_dates_counters_and_keys_become_strings():
    out = jsonable({dt.date(2025, 5, 1): Counter({"a": 2}), "t": (dt.datetime(2025, 5, 1, 8, 30),)})
    assert out == {"2025-05-01": {"a": 2}, "t": ["2025-05-01T08:30:00"]}


def test_a_statement_is_never_shipped_whole(statement):
    out = jsonable({"window": statement})
    assert out["window"]["count"] == len(statement.transactions)
    assert "transactions" not in out["window"]


def test_a_transaction_is_a_flat_row_with_its_identity(statement):
    row = jsonable(statement.transactions[0])
    assert row["key"] == f"{statement.transactions[0].reference}:{statement.transactions[0].currency}"
    assert {"date", "label", "category", "bucket", "amount", "currency", "chf"} <= row.keys()


def test_the_period_is_resolved_like_everywhere_else(client):
    period = api(client, "/api/period?from=2025-05-01&to=2025-05-31")
    assert (period["start"], period["end"], period["title"]) == ("2025-05-01", "2025-05-31", "Mai 2025")
    assert period["bounds"]["low"] <= period["start"]


def test_a_rolling_window_is_named_by_its_preset(client):
    assert api(client, "/api/period?preset=12m")["title"] == "12 derniers mois"
    assert api(client, "/api/period?preset=all")["title"] == "Tout l'historique"


def test_every_endpoint_answers_on_the_test_ledger(client):
    for url in ("/api/meta", "/api/choices", "/api/corrections", "/api/triage",
                "/api/ai", "/api/ai/merchants",
                "/api/imports", "/api/analyse", "/api/previsions", "/api/savings",
                "/api/dashboard?preset=all", "/api/transactions?preset=all"):
        api(client, url)
