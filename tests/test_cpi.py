"""The consumer price index kept current: a source is taken only if it gives
back the months already known, whatever its layout."""

from __future__ import annotations

import json

import pytest

from pms import cpi, swiss
from webhelpers import api

KNOWN = swiss.CPI_MONTHLY


def _levels(rates: dict[str, float], base: float = 100.0) -> dict[str, float]:
    """Index levels whose twelve-month change gives `rates` (2025-26)."""
    levels = {}
    for m in sorted(rates):
        year, month = m.split("-")
        before = f"{int(year) - 1}-{month}"
        levels.setdefault(before, base)
        levels[m] = levels[before] * (1 + rates[m] / 100)
    return levels


def test_a_semicolon_cube_with_a_sub_index_beside_the_total():
    lines = ['"CubeId";"plkopr"', '"PublishingDate";"2026-10-01 09:00"', "",
             '"Date";"D0";"Value"']
    for m, v in sorted(KNOWN.items()):
        lines.append(f'"{m}";"TOTAL";"{v}"')
        lines.append(f'"{m}";"CORE";"{v + 0.6:.1f}"')
    lines.append('"2026-10";"TOTAL";"1.1"')
    found = cpi.pick("\n".join(lines), KNOWN)
    assert found["2026-10"] == 1.1 and found["2025-04"] == 0.0


def test_index_levels_are_read_as_their_change_over_twelve_months():
    text = "observation_date,CHE\n" + "\n".join(f"{m}-01,{v:.4f}" for m, v in sorted(_levels(KNOWN).items()))
    found = cpi.pick(text, KNOWN)
    assert found is not None and all(found[m] == pytest.approx(KNOWN[m], abs=0.1) for m in KNOWN)


def test_a_series_that_does_not_give_back_the_known_months_is_refused(tmp_path):
    wrong = "DATE,X\n" + "\n".join(f"{m}-01,{v + 1:.1f}" for m, v in sorted(KNOWN.items()))
    assert cpi.pick(wrong, KNOWN) is None
    report = cpi.refresh(tmp_path / "cpi.json", fetch=lambda url: wrong)
    assert not report["ok"] and len(report["tried"]) == len(cpi.SOURCES)
    assert not (tmp_path / "cpi.json").exists()


def test_refresh_saves_the_first_source_that_checks_out(tmp_path):
    good = "DATE,X\n" + "\n".join(f"{m}-01,{v}" for m, v in sorted({**KNOWN, "2026-10": 1.2}.items()))

    def fetch(url):
        if url == cpi.SOURCES[0][1]:
            raise OSError("down")
        return good
    report = cpi.refresh(tmp_path / "cpi.json", fetch=fetch)
    assert report["ok"] and report["source"] == cpi.SOURCES[1][0] and report["last"] == "2026-10"
    held = cpi.load(tmp_path / "cpi.json")
    assert held["monthly"]["2026-10"] == 1.2


def test_the_page_reads_the_refreshed_months(client):
    path = client.application.extensions["pms_store"].path.with_name("cpi.json")
    path.write_text(json.dumps({"source": "Test", "url": "https://example.org", "fetched": "2026-11-02",
                                "monthly": {**KNOWN, "2026-10": 1.2}}), encoding="utf-8")
    try:
        inf = api(client, "/api/analyse")["inflation"]["cpi"]
        assert inf["latest"] == "2026-10" and inf["source"] == "Test" and inf["fetched"] == "2026-11-02"
    finally:
        path.unlink()
