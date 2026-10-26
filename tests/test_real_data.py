"""The app on the real statement: smoke tests.

The rest of the suite runs on a made-up statement (tests/synthetic.py) so that
it runs anywhere. This file is what the made-up data cannot replace: the edge
cases nobody thought to invent -- a month with almost no income, a payee
printed five ways, more categories than hues. Every view's data must come
out on them, as JSON a browser can parse, and the invariants the synthetic
tests check must hold here too. Skipped when inbox/ holds no statement.
"""

from __future__ import annotations

import pytest
from webhelpers import api

from pms.web import create_app

VIEWS = [
    "/api/dashboard?preset=all", "/api/dashboard?preset=12m",
    "/api/dashboard?preset=all&stack=bucket",
    "/api/dashboard?preset=all&shares=income&smooth=6", "/api/dashboard?preset=12m&shares=spending",
    "/api/dashboard?from=2026-05-01&to=2026-05-31",  # a month with a review to show
    "/api/dashboard?from=2025-05-01&to=2025-05-31",
    "/api/dashboard?from=2025-05-01&to=2025-05-31&grain=day",
    "/api/transactions", "/api/transactions?dir=out&sort=chf",
    "/api/savings?preset=all", "/api/savings?preset=12m&scale=index&perf=mwr",
    "/api/savings?preset=all&split=asset", "/api/savings?preset=all&focus=ibkr&split=currency",
    "/api/corrections", "/api/triage", "/api/imports", "/api/ai", "/api/ai/merchants",
    "/api/previsions", "/api/previsions?months=480&yscale=log", "/api/previsions?wealth=taxable",
    "/api/analyse", "/api/analyse?year=2025",
]


@pytest.fixture(scope="module")
def real_client(real_ledger_file):
    app = create_app(real_ledger_file)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client


@pytest.mark.parametrize("url", VIEWS)
def test_every_view_answers_on_real_data(real_client, url):
    api(real_client, url)


def test_no_category_takes_a_ninth_hue_on_real_data(real_client):
    """More categories than validated hues: the tail folds into `Autres`."""
    data = api(real_client, "/api/dashboard?preset=all")
    assert {c["slot"] for c in data["categories"]} <= set(range(8))
    assert len(data["legend"]) <= 8


def test_the_real_ledger_has_no_balance_break(real_ledger_file):
    from pms.ledger import Ledger
    assert Ledger.load(real_ledger_file).gaps() == []


def test_the_watcher_knows_every_real_export_and_only_them():
    """What the Downloads watcher would make of each file in inbox/: every
    statement recognised by its own bank, the crypto statement by none."""
    from conftest import ROOT

    from pms import banks
    inbox = ROOT / "inbox"
    statements = sorted(inbox.glob("*.pdf"))
    if not statements:
        pytest.skip("no real statement in inbox/")
    assert [banks.recognise(p) for p in statements] == ["*.pdf"] * len(statements)
    for path in sorted((inbox / "revolut").glob("*.csv")):
        assert banks.recognise(path) == "revolut/*.csv", path.name
    for path in sorted((inbox / "revolut" / "crypto").glob("*.csv")):
        assert banks.recognise(path) is None, path.name
