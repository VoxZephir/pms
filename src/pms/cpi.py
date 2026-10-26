"""The Swiss consumer price index, kept current by `--refresh`
(`docs/analyse.md`, « Contre la Suisse »): the change of each month against
the same month a year before, %, in `data/cpi.json`.

The published series are tried in turn, and one is taken only if it gives
back the months already known (`swiss.CPI_MONTHLY`, read from the OFS
releases): a file whose layout changed, or a column that turns out to be a
sub-index, must not slip a plausible but wrong inflation into the page. A
source that does not check out is said so, and the figures already held stay.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import urllib.request
from pathlib import Path

from . import swiss

# Where the index is published as data. Each is read by the same tolerant
# parser; the check decides, not the URL.
SOURCES = [
    ("BNS, indice des prix à la consommation", "https://data.snb.ch/api/cube/plkopr/data/csv/fr"),
    ("BNS, inflation selon l'IPC", "https://data.snb.ch/api/cube/plkoprinfla/data/csv/fr"),
    ("OCDE via FRED, IPC Suisse", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPALTT01CHM659N"),
]
# A series must agree with the months already known: this many of them, each
# within this many points (the releases round to a tenth).
MIN_OVERLAP = 10
TOLERANCE = 0.15
MONTH = re.compile(r"^(\d{4})-?(\d{2})")


def _month(text: str) -> str | None:
    match = MONTH.match(text.strip().strip('"'))
    return f"{match.group(1)}-{match.group(2)}" if match else None


def _number(text: str) -> float | None:
    try:
        return float(text.strip().strip('"').replace(",", "."))
    except ValueError:
        return None


def series(text: str) -> dict[str, dict[str, float]]:
    """Every series a CSV holds, keyed by its non-date, non-value columns:
    {key: {"2025-01": value}}. Semicolons or commas; leading metadata lines
    and a header are skipped -- a row counts when its first cell is a month
    and its last a number."""
    delimiter = ";" if text.count(";") > text.count(",") else ","
    out: dict[str, dict[str, float]] = {}
    for row in csv.reader(io.StringIO(text), delimiter=delimiter):
        if len(row) < 2:
            continue
        month, value = _month(row[0]), _number(row[-1])
        if month is None or value is None:
            continue
        key = "/".join(cell.strip() for cell in row[1:-1]) or "série"
        out.setdefault(key, {})[month] = value
    return out


def _shift(month: str, years: int) -> str:
    year, m = month.split("-")
    return f"{int(year) + years}-{m}"


def readings(values: dict[str, float]) -> list[dict[str, float]]:
    """What a series may be: changes already, or index levels whose change
    over twelve months is the inflation."""
    as_levels = {m: round((v / values[_shift(m, -1)] - 1) * 100, 1)
                 for m, v in values.items() if values.get(_shift(m, -1))}
    return [dict(values), as_levels]


def check(candidate: dict[str, float], known: dict[str, float]) -> float | None:
    """The largest gap to the known months, or None when too few overlap."""
    shared = [m for m in known if m in candidate]
    if len(shared) < MIN_OVERLAP:
        return None
    return max(abs(candidate[m] - known[m]) for m in shared)


def pick(text: str, known: dict[str, float]) -> dict[str, float] | None:
    """The one reading of one series that gives back the known months."""
    best, best_gap = None, None
    for values in series(text).values():
        for reading in readings(values):
            gap = check(reading, known)
            if gap is not None and gap <= TOLERANCE and (best_gap is None or gap < best_gap):
                best, best_gap = reading, gap
    return best


def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def refresh(path: Path, fetch=_get, today: dt.date | None = None) -> dict:
    """Try each source until one checks out; save its months from 2015 on.
    Returns what happened, for the console."""
    known = swiss.CPI_MONTHLY
    tried = []
    for name, url in SOURCES:
        try:
            text = fetch(url)
        except Exception as exc:  # a site down is one source less, not a crash
            tried.append(f"{name} : injoignable ({type(exc).__name__})")
            continue
        found = pick(text, known)
        if not found:
            tried.append(f"{name} : ne redonne pas les mois connus, écartée")
            continue
        months = {m: v for m, v in sorted(found.items()) if m >= "2015-01"}
        Path(path).write_text(json.dumps({
            "source": name, "url": url,
            "fetched": (today or dt.date.today()).isoformat(),
            "monthly": months,
        }, indent=1), encoding="utf-8")
        return {"ok": True, "source": name, "last": max(months), "tried": tried}
    return {"ok": False, "tried": tried}


def load(path: Path) -> dict | None:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    months = {m: float(v) for m, v in (raw.get("monthly") or {}).items() if _month(m)}
    return {**raw, "monthly": months} if months else None
