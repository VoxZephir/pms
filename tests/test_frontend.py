"""The front end's own checks, run from the suite: its types, its unit tests,
and that the committed build is the one its sources produce.

The build is committed so `run.bat` needs no Node; the price is that an edit
to frontend/src without a rebuild would leave the phone on the old app. Vite
names every file by its content hash, so a fresh build into a scratch folder
must produce exactly the committed file names. Skipped without Node or
without `npm install` in frontend/.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from conftest import ROOT

FRONT = ROOT / "frontend"
BUILT = ROOT / "src" / "pms" / "web" / "static" / "spa"


def _npx(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    npx = shutil.which("npx")
    if npx is None or not (FRONT / "node_modules").exists():
        pytest.skip("Node or frontend/node_modules missing")
    return subprocess.run([npx, *args], cwd=FRONT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def test_the_types_hold():
    result = _npx("tsc", "--noEmit")
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_unit_tests_pass():
    result = _npx("vitest", "run")
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]


def test_the_committed_build_matches_the_sources(tmp_path):
    out = tmp_path / "spa"
    result = _npx("vite", "build", "--outDir", str(out), "--emptyOutDir")
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    fresh = sorted(p.name for p in (out / "assets").iterdir())
    committed = sorted(p.name for p in (BUILT / "assets").iterdir())
    assert fresh == committed, "frontend/src changed: cd frontend && npm run build, then commit static/spa"
