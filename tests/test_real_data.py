"""The app on the real statement: smoke tests.

The rest of the suite runs on a made-up statement (tests/synthetic.py) so that
it runs anywhere. This file is what the made-up data cannot replace: the edge
cases nobody thought to invent -- a month with almost no income, a payee
printed five ways, more categories than hues. Every page must render on them,
and the invariants the synthetic tests check must hold here too. Skipped when
inbox/ holds no statement.
"""

from __future__ import annotations

import re

import pytest

from pms.web import create_app

PAGES = [
    "/?preset=all", "/?preset=12m", "/?preset=all&stack=bucket",
    "/?preset=all&shares=income&smooth=6", "/?preset=12m&shares=spending",
    "/?from=2026-05-01&to=2026-05-31",  # a month with a review to show
    "/?from=2025-05-01&to=2025-05-31", "/?from=2025-05-01&to=2025-05-31&grain=day",
    "/transactions", "/transactions?dir=out&sort=chf", "/reclasser",
    "/previsions", "/analyse", "/analyse?year=2025",
]
EMPTY_COORDINATE = re.compile(r'\b(x|y|cx|cy|x1|y1|x2|y2|width|height)=""')


@pytest.fixture(scope="module")
def real_client(real_ledger_file):
    app = create_app(real_ledger_file)
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client


@pytest.mark.parametrize("url", PAGES)
def test_every_page_renders_on_real_data(real_client, url):
    response = real_client.get(url)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert not EMPTY_COORDINATE.search(body)
    assert "var(--s)" not in body and "var(--h)" not in body


@pytest.mark.parametrize("url", ["/?from=2025-05-01&to=2025-05-31",
                                 "/previsions", "/analyse"])
def test_fragment_and_full_page_agree_on_real_data(real_client, url):
    joiner = "&" if "?" in url else "?"
    full = real_client.get(url).get_data(as_text=True)
    fragment = real_client.get(f"{url}{joiner}fragment=1").get_data(as_text=True)
    assert fragment.strip() in full


def test_the_real_ledger_has_no_balance_break(real_ledger_file):
    from pms.ledger import Ledger
    assert Ledger.load(real_ledger_file).gaps() == []
