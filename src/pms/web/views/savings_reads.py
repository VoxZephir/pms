"""The savings page's readings beyond the headline and the table: where the
change came from, each pocket's line in a few points, the months one by one,
and the falls from a high. All of them read the same `SavingsBook`, so the
bridge adds up to the headline and the months chain to the TWR of the table
(`docs/epargne.md`, « La page se lit de haut en bas »).
"""

from __future__ import annotations

import datetime as dt

from .savings import SavingsBook

# The pockets that earn a return of their own; the current account's
# "return" is its interest, nil on a Swissquote account.
INVESTED = ("ibkr", "finpension", "crypto", "titres")

# Each pocket's hue: the one its line takes on the curve (`_split_series`).
SLOTS = {"swissquote": 0, "total": 1, "ibkr": 2, "finpension": 3, "titres": 4, "crypto": 5}

# Points of a pocket card's sparkline: enough for a shape, light enough to
# ship one per pocket.
SPARK_POINTS = 48

# The drawdown curve is daily; past this many points, every n-th day is
# kept, the deepest point of each stretch included (`drawdown`).
DRAWDOWN_POINTS = 420


def pockets_of(book: SavingsBook) -> list[str]:
    """The pockets this book holds, in the page's order."""
    return book.pockets()


def bridge(book: SavingsBook, start: dt.date, end: dt.date) -> dict:
    """From the total at the window's start to the total at its end, one step
    per cause: the money set aside (what came in less what was spent, the
    total's net flow), then what each pocket earned. Every pocket is read
    over the same window, so the steps add up to the end exactly; a
    transfer between two pockets is out of one and into the other, and
    never a step."""
    first, last = book.value("total", start), book.value("total", end)
    steps = [{"key": "saved", "label": "Mis de côté", "amount": round(book.flow("total", start, end), 2)}]
    for pocket in pockets_of(book):
        gain = book.value(pocket, end) - book.value(pocket, start) - book.flow(pocket, start, end)
        label = "Intérêts Swissquote" if pocket == "swissquote" else f"Rendement {_short(pocket)}"
        steps.append({"key": pocket, "label": label, "amount": round(gain, 2)})
    return {"start": round(first, 2), "end": round(last, 2), "steps": steps}


def spark(book: SavingsBook, pocket: str, start: dt.date, end: dt.date,
          points: int = SPARK_POINTS) -> list[float]:
    """The pocket's value at evenly spaced days of the window, both ends
    included: the shape of its line, for a card."""
    days = (end - start).days
    if days <= 0:
        return [round(book.value(pocket, end), 2)]
    n = min(points, days + 1)
    return [round(book.value(pocket, start + dt.timedelta(days=round(i * days / (n - 1)))), 2)
            for i in range(n)]


def monthly_returns(book: SavingsBook, pocket: str, start: dt.date,
                    end: dt.date) -> dict | None:
    """The pocket's time-weighted return month by month, read off the daily
    index the risk table uses -- the months of a year chain to its year,
    the years to the window's TWR. A month the window cuts is marked
    partial: its figure covers only the days shown."""
    first = book.start_of(pocket, start)
    if (end - first).days < 1:
        return None
    index = book.index(pocket, first, end)
    level = dict(index)
    by_year: dict[int, dict] = {}
    cursor, prev = first, 100.0
    while cursor <= end:
        nxt = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        close = min(nxt - dt.timedelta(days=1), end)
        value = level[close]
        partial = (cursor.day != 1 and cursor == first) or close < nxt - dt.timedelta(days=1)
        row = by_year.setdefault(cursor.year, {"year": cursor.year, "months": [None] * 12,
                                               "partial": [False] * 12, "open": prev})
        row["months"][cursor.month - 1] = _clean(value / prev - 1) if prev else None
        row["partial"][cursor.month - 1] = partial
        row["close"] = value
        prev, cursor = value, nxt
    years = []
    for row in by_year.values():
        years.append({"year": row["year"], "months": row["months"], "partial": row["partial"],
                      "rate": _clean(row["close"] / row["open"] - 1) if row["open"] else None})
    whole = [(y["year"], m, r) for y in years for m, r in enumerate(y["months"])
             if r is not None and not y["partial"][m]]
    best = max(whole, key=lambda x: x[2], default=None)
    worst = min(whole, key=lambda x: x[2], default=None)

    def month(entry):
        return {"year": entry[0], "month": entry[1] + 1, "rate": entry[2]} if entry else None
    return {"pocket": pocket, "name": book.name(pocket), "since": first if first > start else None,
            "years": years, "best": month(best), "worst": month(worst),
            "up": sum(1 for _, _, r in whole if r > 0), "count": len(whole)}


def drawdown(book: SavingsBook, pocket: str, start: dt.date, end: dt.date) -> dict | None:
    """How far the pocket stood below its last high, day by day, on the
    time-weighted index -- deposits taken out, so a withdrawal is not a
    fall. The deepest fall says when it peaked, when it bottomed, and when
    (if) it was made good."""
    first = book.start_of(pocket, start)
    if (end - first).days < 7:
        return None
    index = book.index(pocket, first, end)
    peak, peak_day = index[0][1], index[0][0]
    rows, worst = [], None
    for day, level in index:
        if level >= peak:
            peak, peak_day = level, day
        dd = _clean(level / peak - 1) if peak else 0.0
        rows.append((day, dd))
        if worst is None or dd < worst["depth"]:
            worst = {"depth": dd, "peak": peak_day, "trough": day, "peak_level": peak}
    if worst and worst["depth"] < -1e-4:
        worst["recovered"] = next((day for day, level in index
                                   if day > worst["trough"] and level >= worst["peak_level"]), None)
        worst["days"] = ((worst["recovered"] or end) - worst["peak"]).days
    else:
        worst = None
    if worst:
        worst.pop("peak_level")
    stride = max(1, -(-len(rows) // DRAWDOWN_POINTS))
    kept = []
    for i in range(0, len(rows), stride):
        chunk = rows[i:i + stride]
        kept.append(min(chunk, key=lambda r: r[1]) if stride > 1 else chunk[0])
    if kept[-1][0] != rows[-1][0]:
        kept.append(rows[-1])
    return {"pocket": pocket, "name": book.name(pocket), "since": first if first > start else None,
            "rows": [{"date": day, "dd": round(dd, 5)} for day, dd in kept],
            "worst": worst, "current": rows[-1][1]}


def readings(book: SavingsBook, start: dt.date, end: dt.date) -> dict:
    """Everything above, for each invested pocket and the total: the page
    switches between them without asking the server again."""
    measured = [p for p in INVESTED if p in pockets_of(book)] + ["total"]
    return {
        "slots": {p: SLOTS[p] for p in [*pockets_of(book), "total"]},
        "bridge": bridge(book, start, end),
        "sparks": {p: spark(book, p, start, end) for p in [*pockets_of(book), "total"]},
        "months": {p: m for p in measured if (m := monthly_returns(book, p, start, end))},
        "drawdowns": {p: d for p in measured if (d := drawdown(book, p, start, end))},
    }


def _clean(rate: float) -> float:
    """A rate without the float dust of a chained index: -5e-16 is 0, and
    would otherwise paint a month red."""
    return 0.0 if abs(rate) < 1e-9 else rate


def _short(pocket: str) -> str:
    return {"ibkr": "IBKR", "finpension": "3a", "crypto": "crypto", "titres": "titres"}.get(pocket, pocket)
