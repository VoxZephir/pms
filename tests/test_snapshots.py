"""Refreshing the savings snapshots: captures append, readings accumulate."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from pms import cli, finpension, snapshots
from pms.web.views.savings import _stale_notes


def _ibkr(tmp_path):
    path = tmp_path / "ibkr.json"
    path.write_text(json.dumps({
        "captured_at": "2026-08-08T08:00:00",
        "account": {"net_liquidation": 9000.0},
        "positions": [{"name": "FUND", "market_value": 100.0,
                       "geography": {"Monde": 100}, "exposure": 2.0}],
        "performance": {"measure": "TWR", "ytd_pct": 5.0, "inception": "2025-08-07"},
        "nav": [["2026-08-07", 8900.0], ["2026-08-08", 9000.0]],
        "nav_daily": [["2026-08-07", 30.0], ["2026-08-08", 30.0]],
    }), encoding="utf-8")
    return path


def _finp(tmp_path):
    path = tmp_path / "finpension.json"
    path.write_text(json.dumps({
        "value": 9000.0, "value_as_of": "2026-08-08",
        "value_method": "relevé dans l'app finpension : le 08.08.2026 : 9000.00",
        "yearly": [["2025-12-31", 8000.0]],
        "holdings": {"CH1": {"shares": 1.0, "price": 9000.0}},
        "proxies": {"CH1": "SMI"},
        "proxy_series": {"SMI": [["2026-08-07", 100.0]]},
    }), encoding="utf-8")
    return path


def test_capture_appends_and_never_rewrites(tmp_path):
    ibkr_path, finp_path = _ibkr(tmp_path), _finp(tmp_path)
    capture = {
        "ibkr": {
            "captured_at": "2026-09-22T22:00:00",
            "account": {"net_liquidation": 9800.0},
            "performance": {"ytd_pct": 9.0},
            "positions": [{"name": "FUND", "market_value": 110.0}],
            # The first point overlaps the captured history with another
            # value: it must be ignored, not overwrite.
            "nav": [["2026-08-08", 1.0], ["2026-09-22", 9800.0],
                    ["2026-09-21", 9820.0]],
            "nav_daily": [["2026-09-22", 33.0]],
        },
        "proxy_series": {"SMI": [["2026-09-22", 104.0]]},
    }
    report = snapshots.merge(capture, ibkr_path, finp_path)
    assert report == {"ibkr": {"nav": 2, "nav_daily": 1, "flows": 0, "costs": 0},
                      "proxy_series": {"SMI": 1}}

    raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
    assert raw["nav"] == [["2026-08-07", 8900.0], ["2026-08-08", 9000.0],
                          ["2026-09-21", 9820.0], ["2026-09-22", 9800.0]]
    assert raw["account"]["net_liquidation"] == 9800.0
    # Only the reported fields move; the declared ones stay.
    assert raw["performance"] == {"measure": "TWR", "ytd_pct": 9.0,
                                  "inception": "2025-08-07"}
    assert raw["positions"] == [{"name": "FUND", "market_value": 110.0,
                                 "geography": {"Monde": 100}, "exposure": 2.0}]

    # Idempotent: the same capture again adds nothing.
    again = snapshots.merge(capture, ibkr_path, finp_path)
    assert again["ibkr"] == {"nav": 0, "nav_daily": 0, "flows": 0, "costs": 0}
    assert again["proxy_series"] == {"SMI": 0}


def test_capture_refuses_an_unknown_proxy_series(tmp_path):
    """A typo would create a series nothing reads, and the 3a would stay
    frozen while the capture reported success."""
    finp_path = _finp(tmp_path)
    before = finp_path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="URTH"):
        snapshots.merge({"proxy_series": {"URTH": [["2026-09-22", 1.0]]}},
                        tmp_path / "ibkr.json", finp_path)
    assert finp_path.read_text(encoding="utf-8") == before


def test_new_3a_reading_keeps_the_previous_one(tmp_path):
    """The reading being replaced joins the observations. Without that, every
    day between the two readings re-anchors on an older one and the curve
    jumps overnight when the new reading starts."""
    path = _finp(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["proxy_series"]["SMI"].append(["2026-09-21", 102.0])
    path.write_text(json.dumps(raw), encoding="utf-8")

    finpension.observe(path, 9300.0, dt.date(2026, 9, 22))
    snap = finpension.load(path)
    assert snap["value"] == 9300.0 and snap["value_as_of"] == "2026-09-22"
    assert (dt.date(2026, 8, 8), 9000.0) in snap["yearly"]
    # 21.09 is estimated from the 08.08 reading (+2 %), not from 31.12.
    assert finpension.value_at(snap, dt.date(2026, 9, 21)) == 9180.0
    assert "le 22.09.2026 : 9300.00" in snap["value_method"]

    # An older reading is an observation, never the newest value.
    finpension.observe(path, 8500.0, dt.date(2026, 3, 1))
    snap = finpension.load(path)
    assert snap["value_as_of"] == "2026-09-22"
    assert (dt.date(2026, 3, 1), 8500.0) in snap["yearly"]


def test_cli_records_a_3a_value(tmp_path, capsys):
    finp_path = _finp(tmp_path)
    ledger = tmp_path / "ledger.json"
    code = cli.main(["--ledger", str(ledger), "--3a-value", "9300",
                     "--on", "2026-09-22"])
    assert code == 0
    assert "9300.00 CHF relevés le 2026-09-22" in capsys.readouterr().out
    assert json.loads(finp_path.read_text(encoding="utf-8"))["value"] == 9300.0


def test_cli_capture_needs_the_snapshot(tmp_path, capsys):
    capture = tmp_path / "capture.json"
    capture.write_text(json.dumps({"ibkr": {"nav": []}}), encoding="utf-8")
    code = cli.main(["--ledger", str(tmp_path / "ledger.json"),
                     "--capture", str(capture)])
    assert code == 2
    assert "ibkr.json" in capsys.readouterr().err


def test_stale_notes_name_the_pocket_that_is_behind(tmp_path):
    from pms import ibkr as ibkr_module
    ibkr = ibkr_module.load(_ibkr(tmp_path))
    finp = finpension.load(_finp(tmp_path))

    # Within a week of the last point: nothing to say.
    assert _stale_notes(ibkr, finp, dt.date(2026, 8, 14)) == []
    # An old window is not stale either.
    assert _stale_notes(ibkr, finp, dt.date(2026, 3, 31)) == []

    notes = _stale_notes(ibkr, finp, dt.date(2026, 9, 21))
    assert notes == [
        "IBKR : chiffres arrêtés au 08.08.2026, 44 jours avant le 21.09.2026",
        "3a : valeur figée au 08.08.2026, 44 jours avant le 21.09.2026",
    ]

    # Prices carried to the 20th keep the 3a estimate moving: not stale.
    finp["proxy_series"]["SMI"].append((dt.date(2026, 9, 20), 101.0))
    assert len(_stale_notes(ibkr, finp, dt.date(2026, 9, 21))) == 1


def test_costs_are_matched_whole_so_a_rerun_adds_nothing(tmp_path):
    """Two commissions can share a day; matching by date (like the series)
    would drop the second, matching nothing would count both twice."""
    ibkr_path = _ibkr(tmp_path)
    costs = [{"date": "2026-09-28", "kind": "commission", "label": "A",
              "amount_chf": 0.83},
             {"date": "2026-09-28", "kind": "commission", "label": "B",
              "amount_chf": 1.66}]
    capture = {"ibkr": {"costs_known_from": "2025-10-01", "costs": costs}}
    assert snapshots.merge(capture, ibkr_path, tmp_path / "f.json")["ibkr"]["costs"] == 2
    assert snapshots.merge(capture, ibkr_path, tmp_path / "f.json")["ibkr"]["costs"] == 0
    from pms import ibkr
    snap = ibkr.load(ibkr_path)
    assert [c["amount_chf"] for c in snap["costs"]] == [0.83, 1.66]
    assert snap["costs_known_from"] == dt.date(2025, 10, 1)