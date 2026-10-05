"""Keeping the savings snapshots current: merge a capture, say how old they are.

`data/ibkr.json` and `data/finpension.json` are captures made in a Claude
Code session with the IBKR connector (see `docs/epargne.md`). Refreshing
them was a hand-written script each time, and the first one made the two
mistakes this module exists to prevent:

* **rewriting history.** A capture only ever *appends* the points after the
  snapshot's last date; the curve already captured stays as it was.
* **dropping the previous 3a reading.** `finpension.observe()` moves it into
  the observations before writing the new one -- see there.

`python -m pms --status` prints `describe()`, so a session knows from which
date to fetch; `python -m pms --capture FILE` applies `merge()`.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import finpension


def _last(series: list) -> str:
    return series[-1][0] if series else ""


def append_after(series: list, points: list) -> int:
    """Append the points dated after the series' last one, in date order.
    Returns how many were added; a point on or before the last is ignored,
    so re-running the same capture changes nothing."""
    last = _last(series)
    fresh = sorted([str(day), value] for day, value in points if str(day) > last)
    series.extend(fresh)
    return len(fresh)


def _merge_ibkr(raw: dict, capture: dict) -> dict:
    for key in ("captured_at", "fx_chf_per_usd", "account", "cash"):
        if key in capture:
            raw[key] = capture[key]
    if "performance" in capture:
        raw.setdefault("performance", {}).update(capture["performance"])

    # A position keeps what the connector does not report (asset split,
    # geography, exposure were declared by hand); only the prices move.
    by_name = {pos["name"]: pos for pos in raw.setdefault("positions", [])}
    for pos in capture.get("positions", []):
        if pos["name"] in by_name:
            by_name[pos["name"]].update(pos)
        else:
            raw["positions"].append(pos)

    # Costs are matched whole, not by date: two commissions can share a day,
    # and re-running a capture must not count either of them twice.
    if "costs_known_from" in capture and not raw.get("costs_known_from"):
        raw["costs_known_from"] = capture["costs_known_from"]
    known = {(c["date"], c.get("label"), c["amount_chf"])
             for c in raw.setdefault("costs", [])}
    fresh = [c for c in capture.get("costs", [])
             if (c["date"], c.get("label"), c["amount_chf"]) not in known]
    raw["costs"].extend(fresh)
    raw["costs"].sort(key=lambda c: c["date"])

    # `flows`: deposits that did not come from Swissquote -- those are read
    # from the ledger and must not be declared twice.
    report = {key: append_after(raw.setdefault(key, []), capture.get(key, []))
              for key in ("nav", "nav_daily", "flows")}
    report["costs"] = len(fresh)
    # Reference indices for the comparison, appended like the NAV.
    benchmarks = raw.setdefault("benchmarks", {})
    for name, points in (capture.get("benchmarks") or {}).items():
        report[f"benchmark {name}"] = append_after(benchmarks.setdefault(name, []),
                                                   points)
    # Weekly closes per instrument (and USD.CHF), for the value rebuilt from
    # the transaction history before the broker's daily NAV.
    prices = raw.setdefault("prices", {})
    for symbol, points in (capture.get("prices") or {}).items():
        report[f"prices {symbol}"] = append_after(prices.setdefault(symbol, []),
                                                  points)
    return report


def merge(capture: dict, ibkr_path: Path, finpension_path: Path) -> dict:
    """Apply one capture to the snapshots next to the ledger.

    The capture is a JSON object with any of three keys:

    * `ibkr` -- `captured_at`, `fx_chf_per_usd`, `account`, `cash`,
      `performance`, `positions` (matched by name), and the `nav` /
      `nav_daily` points to append;
    * `proxy_series` -- `{"SMI": [[date, level], ...], ...}`, appended;
    * `finpension_value` -- `{"value": 10000.0, "on": "2026-09-22"}`, a value
      read in the finpension app.

    Returns what changed, per series.
    """
    report: dict = {}
    if "ibkr" in capture:
        raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
        report["ibkr"] = _merge_ibkr(raw, capture["ibkr"])
        ibkr_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    if "proxy_series" in capture:
        raw = json.loads(finpension_path.read_text(encoding="utf-8"))
        known = set(finpension.PROXY_KEYS.values())
        unknown = set(capture["proxy_series"]) - known
        if unknown:
            # A typo would create a series nothing reads, and the 3a would
            # stay frozen while the capture reported success.
            raise ValueError(f"série inconnue : {', '.join(sorted(unknown))} "
                             f"(attendu : {', '.join(sorted(known))})")
        series = raw.setdefault("proxy_series", {})
        report["proxy_series"] = {
            name: append_after(series.setdefault(name, []), points)
            for name, points in capture["proxy_series"].items()}
        finpension_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    if "finpension_value" in capture:
        entry = capture["finpension_value"]
        finpension.observe(finpension_path, float(entry["value"]),
                           dt.date.fromisoformat(entry["on"]))
        report["finpension_value"] = entry

    return report


def merge_journal(path: Path, ibkr_path: Path) -> dict:
    """Store the exported transaction history in the IBKR snapshot.

    The journal replaces what the connector could not see: the flows and
    the costs since the opening. It is rewritten whole on each import -- the
    export is cumulative, from the first day -- unlike the captures, which
    only ever append.
    """
    from . import ibkr_history
    journal = ibkr_history.journal(path)
    if not journal:
        raise ValueError(f"aucune transaction lue dans {path.name}")
    raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
    raw["journal"] = journal
    raw["costs"] = journal["costs"]
    raw["costs_known_from"] = journal["first"]
    ibkr_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return journal


def describe(ibkr_path: Path, finpension_path: Path) -> list[str]:
    """One line per snapshot series: where each one stops."""
    lines = []
    if ibkr_path.exists():
        raw = json.loads(ibkr_path.read_text(encoding="utf-8"))
        lines.append(f"IBKR : capturé {raw.get('captured_at', '?')[:10]} · "
                     f"nav jusqu'au {_last(raw.get('nav', [])) or '—'} · "
                     f"nav_daily jusqu'au {_last(raw.get('nav_daily', [])) or '—'}")
        journal = raw.get("journal") or {}
        if journal:
            lines.append(f"IBKR : historique {journal.get('source')} "
                         f"({journal.get('first')} → {journal.get('last')})"
                         + "".join(f" · cours {s} jusqu'au {_last(p)}"
                                   for s, p in (raw.get("prices") or {}).items()))
    if finpension_path.exists():
        raw = json.loads(finpension_path.read_text(encoding="utf-8"))
        proxies = " · ".join(f"{name} jusqu'au {_last(points) or '—'}"
                             for name, points
                             in (raw.get("proxy_series") or {}).items())
        lines.append(f"3a : {raw.get('value')} CHF relevés le "
                     f"{raw.get('value_as_of') or '?'}"
                     + (f" · {proxies}" if proxies else ""))
    return lines
