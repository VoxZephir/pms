"""The reference indices: a public catalogue, picked in the URL."""

from __future__ import annotations

import datetime as dt

import pytest
from werkzeug.datastructures import MultiDict

from pms import benchmarks
from pms.web.views.common import bench_mode

D = dt.date


def _fake(key, start, end):
    if key == "gold":
        raise OSError("down")
    return [["2026-01-02", 100.0], ["2026-06-30", 110.0]]


def test_capture_keeps_what_failed_from_the_last_time(tmp_path):
    out = tmp_path / "benchmarks.json"
    first = benchmarks.capture(out, D(2026, 1, 1), D(2026, 7, 1), fetcher=_fake)
    assert first["failed"] == ["gold"] and "sp500" in first["series"]
    # Gold comes back once, then fails again: its old series stays.
    benchmarks.capture(out, D(2026, 1, 1), D(2026, 7, 1),
                       fetcher=lambda k, s, e: [["2026-01-02", 1.0]])
    again = benchmarks.capture(out, D(2026, 1, 1), D(2026, 7, 1), fetcher=_fake)
    assert again["series"]["gold"] == [["2026-01-02", 1.0]]


def test_the_catalogue_reinvests_dividends_and_the_3a_proxy_stands_in(tmp_path):
    """The 3a's MSCI World is a price series: ~1.8 % a year low next to an
    accumulating fund. It only stands in until the catalogue is captured,
    and then says what it is."""
    out = tmp_path / "benchmarks.json"
    finpension = {"proxy_series": {"URTHxCHF": [(D(2026, 1, 5), 50.0)]}}
    before = benchmarks.available(out, finpension)
    assert before["msci_world"]["series"] == [(D(2026, 1, 5), 50.0)]
    assert not before["msci_world"]["total_return"]
    assert "non compris" in before["msci_world"]["source"]

    benchmarks.capture(out, D(2026, 1, 1), D(2026, 7, 1), fetcher=_fake)
    offered = benchmarks.available(out, finpension)
    assert offered["msci_world"]["series"] == [(D(2026, 1, 2), 100.0),
                                               (D(2026, 6, 30), 110.0)]
    assert offered["msci_world"]["total_return"]
    assert "(URTH)" in offered["msci_world"]["source"]
    assert offered["sp500"]["name"] == "S&P 500 (CHF)"
    assert offered["smi"]["name"] == "SMI"  # quoted in francs: no suffix
    assert "gold" not in offered


def test_a_snapshot_from_before_the_switch_reads_as_prices(tmp_path):
    """Captured as price indices: never relabelled as total returns, and a
    failed recapture keeps the old label with the old series."""
    import json
    out = tmp_path / "benchmarks.json"
    out.write_text(json.dumps({"series": {"gold": [["2026-01-02", 1.0]]}}),
                   encoding="utf-8")
    assert not benchmarks.available(out, None)["gold"]["total_return"]
    benchmarks.capture(out, D(2026, 1, 1), D(2026, 7, 1), fetcher=_fake)
    offered = benchmarks.available(out, None)
    assert offered["gold"]["series"] == [(D(2026, 1, 2), 1.0)]
    assert not offered["gold"]["total_return"]
    assert offered["sp500"]["total_return"]


def test_the_dividend_adjusted_close_is_read_where_yahoo_gives_one():
    result = {"timestamp": [1, 2, 3],
              "indicators": {"quote": [{"close": [10.0, 10.0, None]}],
                             "adjclose": [{"adjclose": [9.5, 10.0, None]}]}}
    assert benchmarks.levels(result) == [(1, 9.5), (2, 10.0)]
    del result["indicators"]["adjclose"]  # an index: its close is the level
    assert benchmarks.levels(result) == [(1, 10.0), (2, 10.0)]


def test_the_pick_lives_in_the_url():
    assert bench_mode(MultiDict()) == benchmarks.DEFAULT
    # Checkboxes repeat the key; "none" rides along so an empty pick is not
    # read as the default; unknown keys are dropped.
    picked = bench_mode(MultiDict([("bench", "none"), ("bench", "gold"),
                                   ("bench", "sp500"), ("bench", "evil")]))
    assert picked == ("sp500", "gold")  # catalogue order
    assert bench_mode(MultiDict([("bench", "none")])) == ()


def test_the_panel_compares_with_what_was_picked(client):
    from webhelpers import api, savings_snapshots
    store_ = client.application.extensions["pms_store"]
    out = store_.path.with_name("benchmarks.json")
    paths = savings_snapshots(client)
    try:
        high = store_.bounds[1]
        benchmarks.capture(out, D(2020, 1, 1), high,
                           fetcher=lambda k, s, e: [[(high - dt.timedelta(days=400)).isoformat(), 100.0],
                                                    [high.isoformat(), 120.0]])
        data = api(client, "/api/savings?preset=all&bench=sp500")
        assert [b["name"] for b in data["bench"]] == ["S&P 500 (CHF)"]
        assert data["bench"][0]["total_return"]          # dividends reinvested
        assert data["bench"][0]["rate"] == pytest.approx(0.2)
        assert [o["key"] for o in data["bench_options"] if o["on"]] == ["sp500"]
        assert api(client, "/api/savings?preset=all&bench=none")["bench"] == []
    finally:
        for p in (out, *paths):
            p.unlink(missing_ok=True)
