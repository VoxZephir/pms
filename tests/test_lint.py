"""The linter runs with the suite, so its rules hold without anyone
remembering to run it. The rule set lives in pyproject.toml."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_ruff_finds_nothing():
    if importlib.util.find_spec("ruff") is None:
        pytest.skip("ruff not installed (pip install -r requirements-dev.txt)")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "src", "tests"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
