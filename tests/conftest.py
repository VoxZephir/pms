"""Shared fixtures.

Two sources of transactions:

- `statement` is made up (tests/synthetic.py): shaped like a real export,
  invented from end to end. Every test about the app runs on it, so the suite
  runs on a clone that has no bank statement in inbox/.
- `real_statement` is the PDF in inbox/, parsed once per session -- 104 pages,
  about 15 seconds. The parser tests need it, and a few smoke tests render the
  app on real data, for the edge cases nobody thought to invent. Skipped when
  the file is absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

STATEMENT = ROOT / "inbox" / "transactionStatement.pdf"


@pytest.fixture(scope="session")
def statement():
    """The invented statement, classified and converted to CHF once, the way
    the app's Store does. Done here rather than by whichever test happened to
    run first: under `pytest -n` the order changes, and a test reading
    `amount_chf` on a statement nobody had annotated saw no income at all."""
    import synthetic

    from pms import analysis
    from pms.categories import classify_all
    built = synthetic.build()
    classify_all(built.transactions)
    analysis.annotate_chf(built)
    return built


@pytest.fixture(scope="session")
def real_statement():
    if not STATEMENT.exists():
        pytest.skip(f"{STATEMENT} not present")
    from pms.parser import parse_statement
    return parse_statement(STATEMENT)


def _ledger_on_disk(statement, path: Path) -> Path:
    from pms.ledger import Ledger
    ledger = Ledger(path)
    ledger.merge(statement)
    ledger.save()
    return path


@pytest.fixture
def ledger_of_statement(statement, tmp_path):
    from pms.ledger import Ledger
    ledger = Ledger(tmp_path / "ledger.json")
    ledger.merge(statement)
    return ledger


@pytest.fixture(scope="session")
def ledger_file(statement, tmp_path_factory):
    """A ledger on disk, for the web app to read."""
    return _ledger_on_disk(statement,
                           tmp_path_factory.mktemp("web") / "ledger.json")


@pytest.fixture(scope="session")
def real_ledger_file(real_statement, tmp_path_factory):
    """The same, from the real statement."""
    return _ledger_on_disk(real_statement,
                           tmp_path_factory.mktemp("real") / "ledger.json")


@pytest.fixture(scope="session")
def bounds(statement):
    dates = [t.date for t in statement.transactions]
    return min(dates), max(dates)


@pytest.fixture(scope="module")
def client(ledger_file):
    from pms.web import create_app
    app = create_app(ledger_file)
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c
