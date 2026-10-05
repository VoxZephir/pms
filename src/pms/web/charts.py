"""Chart geometry: coordinates in Python, plain SVG in the template.

No chart library and no CDN, so every number below is one a reader can check --
and the page stays a single self-contained document.

These charts are *drillable*. Each bar carries the date range of the bucket it
represents, so clicking it navigates to that window one grain finer. That link
is a real href, built server-side: the drill-down works with JavaScript
disabled, and the browser's back button undoes it.

The geometry used to live in a `report.py` that rendered a static HTML page,
with the web calling into it. That page was a draft and has been deleted; the
geometry moved here, which is where its only consumer is.
"""

from __future__ import annotations

import datetime as dt
import math

from .. import analysis
from ..analysis import OTHER
from ..models import Statement

# The eight validated categorical slots (contrast and colour-blindness checked
# in both themes; the values themselves live in app.css). Colour follows the
# entity: the mapping is fixed once, by total spend, and reused by every chart
# so a category keeps its hue everywhere. Never cycle -- a ninth hue would be
# indistinguishable from the first.
MAX_SLOTS = 8

WIDTH = 1000
HEIGHT = 320
PAD_LEFT = 62
PAD_RIGHT = 14
PAD_TOP = 18
PAD_BOTTOM = 48


def _labels_every(count: int) -> int:
    """Show at most ~16 x-axis labels, so they never collide."""
    return max(1, -(-count // 16))


def _log_ticks(vmin: float, vmax: float, limit: int = 5) -> list[float]:
    """Tick values in [vmin, vmax] on a 1-2-5 x 10^k grid, at most `limit`."""
    ticks: list[float] = []
    exp = math.floor(math.log10(vmin))
    while 10.0 ** exp <= vmax:
        for mantissa in (1, 2, 5):
            value = mantissa * 10.0 ** exp
            if value > vmax:
                break
            if value >= vmin:
                ticks.append(value)
        exp += 1
    if len(ticks) <= limit:
        return ticks
    step = (len(ticks) - 1) / (limit - 1)
    return [ticks[round(i * step)] for i in range(limit)]


GRAIN_FR = {"year": "année", "month": "mois", "week": "semaine", "day": "jour"}


def drill_target(rows: list[dict], grain: str) -> tuple[str | None, str]:
    """Where clicking a column actually lands, and how to say it.

    The link hands the window to the same auto-grain logic the rest of the app
    uses, so the destination is whatever `suggest_grain` picks for a bucket that
    size -- clicking a month goes straight to days, not to weeks. The label has
    to be derived from that same call rather than from "one grain finer", or the
    hint promises a level the click does not deliver.
    """
    if grain == "day":
        return "detail", "ouvrir le détail de la journée"
    if not rows:
        return None, ""
    sample = rows[len(rows) // 2]
    target = analysis.suggest_grain(sample["start"], sample["end"])
    if target == grain:
        target = analysis.finer_grain(grain) or grain
    if target == grain:
        return None, "niveau le plus fin"
    return target, f"cliquez une colonne pour descendre au niveau {GRAIN_FR[target]}"


def timeline(rows: list[dict], fills: dict[str, str], grain: str,
             drill: str | None, source: str = "categories") -> dict:
    """Stacked columns per bucket, each one a link one level deeper.

    `source` names which breakdown of the same money to stack -- "categories" or
    "buckets" -- and `fills` is the colour each slice gets, keyed by name. The
    geometry does not care which one it is drawing: both partition the very same
    rows, so the column heights are identical and only the slicing changes.

    Anything `fills` does not name folds into `Autres`, which is what keeps the
    category stack down to eight validated hues. The bucket stack names all four
    of its slices, so nothing folds there.
    """
    if not rows:
        return {}

    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    plot_h = HEIGHT - PAD_TOP - PAD_BOTTOM
    top = nice_ceiling(max(max(r["spending"] for r in rows),
                            max(r["income"] for r in rows)))
    band = plot_w / len(rows)
    bar_w = min(26.0, band * 0.6)
    gap = 2.0
    baseline = PAD_TOP + plot_h

    fallback = OTHER if OTHER in fills else None

    columns = []
    for i, row in enumerate(rows):
        x = PAD_LEFT + band * i + (band - bar_w) / 2

        folded: dict[str, float] = {}
        for name, amount in row.get(source, {}).items():
            key = name if name in fills or fallback is None else fallback
            folded[key] = folded.get(key, 0.0) + amount

        y = baseline
        segments = []
        for name, amount in sorted(folded.items(), key=lambda kv: -kv[1]):
            height = amount / top * plot_h
            if height <= 0:
                continue
            y -= height
            segments.append({
                "name": name, "fill": fills.get(name, "var(--axis)"),
                "amount": amount,
                "x": round(x, 2), "y": round(y, 2),
                "w": round(bar_w, 2), "h": round(max(height - gap, 0.6), 2),
            })

        # Income sits as a thin marker above the column rather than as a second
        # stack: same axis, same unit, but it is a different quantity and must
        # not read as part of the spending total.
        income_y = baseline - row["income"] / top * plot_h

        columns.append({
            "key": row["key"], "label": row["label"],
            "start": row["start"], "end": row["end"],
            "spending": row["spending"], "income": row["income"],
            "net": row["net"], "count": row["count"],
            "segments": segments,
            "x": round(x, 2), "w": round(bar_w, 2),
            "band_x": round(PAD_LEFT + band * i, 2), "band_w": round(band, 2),
            "income_y": round(income_y, 2),
            "income_x1": round(x - 3, 2), "income_x2": round(x + bar_w + 3, 2),
            "drillable": bool(drill) and row["count"] > 0,
            "detail": drill == "detail",
            "parts": sorted(folded.items(), key=lambda kv: -kv[1]),
        })

    return {
        "width": WIDTH, "height": HEIGHT, "plot_h": plot_h,
        "pad_left": PAD_LEFT, "pad_top": PAD_TOP, "baseline": baseline,
        "columns": columns,
        # Enough for the brush to turn a pixel range back into a date range:
        # each band's x extent plus the calendar span it stands for.
        "bands": [{"x": c["band_x"], "w": c["band_w"],
                   "from": c["start"].isoformat(), "to": c["end"].isoformat()}
                  for c in columns],
        "plot": {"x": PAD_LEFT, "y": PAD_TOP,
                 "w": WIDTH - PAD_LEFT - PAD_RIGHT, "h": plot_h},
        "ticks": [{"value": top * f, "y": round(PAD_TOP + plot_h * (1 - f), 2)}
                  for f in (0, 0.25, 0.5, 0.75, 1.0)],
        "label_every": _labels_every(len(rows)),
        "grain": grain, "drill": drill, "source": source,
        "max": top,
    }


INCOME_BAND_H = 74


def income_band(rows: list[dict], fills: dict[str, str]) -> dict:
    """A strip across time, coloured by who was paying.

    Each column is the full height of the band and is split by each payer's
    *share* of that period, not by the amount. That is deliberate: the question
    this answers is "who was paying me, and when did that change", and scaling
    by amount would let a large month drown out the transition that matters. How
    much came in is already on the timeline above, as the income marker line.

    A period with no income at all is drawn hollow rather than filled with a
    neutral grey -- the same convention the calendar uses for a day with no
    spending, and for the same reason: an empty column has to be unmistakably
    empty, not a shade that could be read as a small amount.
    """
    if not rows:
        return {}

    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    band = plot_w / len(rows)
    gap = 1.0 if band > 6 else 0.0

    columns = []
    for i, row in enumerate(rows):
        x = PAD_LEFT + band * i
        total = row["total"]
        segments = []
        if total > 0:
            y = PAD_TOP
            ordered = sorted(row["sources"].items(), key=lambda kv: -kv[1])
            for j, (name, amount) in enumerate(ordered):
                height = amount / total * INCOME_BAND_H
                if height <= 0:
                    continue
                # The last slice takes whatever rounding left over, so the
                # column always reaches the bottom edge exactly.
                if j == len(ordered) - 1:
                    height = PAD_TOP + INCOME_BAND_H - y
                segments.append({
                    "name": name, "fill": fills.get(name, "var(--axis)"),
                    "amount": amount,
                    "share": amount / total * 100,
                    "x": round(x, 2), "y": round(y, 2),
                    "w": round(max(band - gap, 1.0), 2),
                    "h": round(height, 2),
                })
                y += height

        columns.append({
            "key": row["key"], "label": row["label"],
            "start": row["start"], "end": row["end"],
            "total": total,
            "segments": segments,
            "empty": total <= 0,
            "x": round(x, 2), "w": round(max(band - gap, 1.0), 2),
            "parts": sorted(row["sources"].items(), key=lambda kv: -kv[1]),
        })

    return {
        "width": WIDTH, "height": PAD_TOP + INCOME_BAND_H + 26,
        "pad_left": PAD_LEFT, "pad_top": PAD_TOP,
        "band_h": INCOME_BAND_H,
        "baseline": PAD_TOP + INCOME_BAND_H,
        "columns": columns,
        "label_every": _labels_every(len(rows)),
        "gap_count": sum(1 for c in columns if c["empty"]),
    }


def sparkline(rows: list[dict], width: int = 132, height: int = 34) -> dict:
    """A bare 12-point trend for a stat tile."""
    values = [r["spending"] for r in rows]
    if len(values) < 2:
        return {}
    top = max(values) or 1.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{round(i * step, 2)},{round(height - v / top * (height - 3) - 1.5, 2)}"
        for i, v in enumerate(values)
    )
    return {"width": width, "height": height, "points": points,
            "last_x": round((len(values) - 1) * step, 2),
            "last_y": round(height - values[-1] / top * (height - 3) - 1.5, 2)}


def day_strip(rows: list[dict], start: dt.date, end: dt.date) -> dict:
    """A one-row calendar for windows short enough to show every day."""
    if not rows or (end - start).days > 92:
        return {}
    amounts = sorted(r["spending"] for r in rows if r["spending"] > 0)
    if not amounts:
        return {}
    cuts = [amounts[int(len(amounts) * q)] for q in (0.25, 0.5, 0.75, 0.92)]

    def level(amount: float) -> int:
        if amount <= 0:
            return 0
        for i, cut in enumerate(cuts, start=1):
            if amount <= cut:
                return i
        return 5

    return {
        "cells": [{"key": r["key"], "label": r["label"], "start": r["start"],
                   "end": r["end"], "amount": r["spending"], "count": r["count"],
                   "level": level(r["spending"])} for r in rows],
        "cuts": cuts,
    }


def category_bars(categories: list[dict]) -> list[dict]:
    top = max((c["amount"] for c in categories), default=0) or 1.0
    return [{**c, "pct": c["amount"] / top * 100} for c in categories]


def colour_map(categories: list[dict]) -> tuple[dict[str, int], list[dict]]:
    """Fixed hue per category for this view; the tail folds into `Autres`.

    Recomputed per window on purpose: a category that does not appear in the
    window should not hold a slot. The cost is that a hue can mean a different
    category in a different window, which is why the legend is always present.
    """
    named = [c["category"] for c in categories][:MAX_SLOTS - 1]
    slots = {name: i for i, name in enumerate(named)}
    slots[OTHER] = len(named)
    legend = [{"name": n, "slot": slots[n]} for n in named + [OTHER]]
    return slots, legend


# --- panels shared with every window -----------------------------------------

def nice_ceiling(value: float) -> float:
    """Round a max up to a clean axis bound (2'500 -> 3'000)."""
    if value <= 0:
        return 1.0
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        bound = magnitude * step
        if bound >= value:
            return bound
    return magnitude * 10


def auto_ceiling(value: float) -> float:
    """The top of an auto-fitted axis: the max rounded up to two
    significant figures. `nice_ceiling`'s round bound would leave a wide
    band above the line (57'000 of data on a 100'000 axis); auto hugs the
    data instead."""
    if value <= 0:
        return 1.0
    factor = 10 ** (len(str(int(value))) - 2)
    return -(-int(value) // factor) * factor


def month_label(key: str) -> str:
    year, month = key.split("-")
    return f"{analysis.MONTH_SHORT[int(month) - 1]} {year[2:]}"


def balance_chart(statement: Statement) -> dict:
    """The CHF running balance over the whole period, as a 2px line."""
    points = [(t.date, t.balance) for t in statement.transactions
              if t.currency == "CHF" and t.balance is not None]
    if not points:
        return {}

    width, height = 980, 200
    pad_left, pad_right, pad_top, pad_bottom = 58, 12, 16, 30
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    start, end = points[0][0], points[-1][0]
    span = max((end - start).days, 1)
    top = nice_ceiling(max(b for _, b in points))

    coords = []
    for date, balance in points:
        x = pad_left + (date - start).days / span * plot_w
        y = pad_top + plot_h * (1 - balance / top)
        coords.append((round(x, 2), round(y, 2)))

    # Thin the polyline: 2166 points is more than the pixels can show.
    step = max(1, len(coords) // 900)
    thinned = coords[::step] + [coords[-1]]

    peak = max(points, key=lambda p: p[1])
    peak_x = pad_left + (peak[0] - start).days / span * plot_w
    peak_y = pad_top + plot_h * (1 - peak[1] / top)

    return {
        "width": width, "height": height,
        "pad_left": pad_left, "pad_top": pad_top, "plot_h": plot_h,
        "baseline": pad_top + plot_h,
        "line": " ".join(f"{x},{y}" for x, y in thinned),
        "area": f"{pad_left},{pad_top + plot_h} "
                + " ".join(f"{x},{y}" for x, y in thinned)
                + f" {thinned[-1][0]},{pad_top + plot_h}",
        "ticks": [{"value": top * f, "y": round(pad_top + plot_h * (1 - f), 2)}
                  for f in (0, 0.5, 1.0)],
        "start": start, "end": end,
        "peak": {"x": round(peak_x, 2), "y": round(peak_y, 2),
                 "value": peak[1], "date": peak[0]},
        "last": {"x": thinned[-1][0], "y": thinned[-1][1], "value": points[-1][1]},
        # Payload for the crosshair: x, y and the value to print at each step.
        "series": {0: {"name": "Solde", "slot": 0,
                       "pts": [[x, y, round(points[min(i * step, len(points) - 1)][1], 2)]
                               for i, (x, y) in enumerate(thinned)]}},
        "dates": [points[min(i * step, len(points) - 1)][0].strftime("%d.%m.%Y")
                  for i in range(len(thinned))],
        "geom": {"width": width, "padLeft": pad_left, "plotW": plot_w},
    }


def projection_chart(projection: dict) -> dict:
    """The forecast: end-of-month balance, month by month, dashed.

    Every point is an estimate -- the ledger ends at the starting cash and
    the rest is arithmetic -- so the line is dashed where the observed
    balance chart is solid. The low point is drawn and labelled: it is the
    answer the page exists for ("will there be enough cash in May?").
    """
    rows = projection["rows"]
    if not rows:
        return {}

    width, height = 980, 200
    pad_left, pad_right, pad_top, pad_bottom = 58, 12, 16, 30
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    values = [projection["cash"]] + [r["end"] for r in rows]
    vmax = nice_ceiling(max(values))
    vmin = min(0.0, min(values))
    if vmin == vmax:
        vmax = vmin + 1

    def y_of(value: float) -> float:
        return pad_top + plot_h * (1 - (value - vmin) / (vmax - vmin))

    n = len(values)
    points = []
    for i, value in enumerate(values):
        x = pad_left + (i / (n - 1)) * plot_w
        if i == 0:
            label = "aujourd'hui"
        else:
            label = rows[i - 1]["label"]
        points.append({"x": round(x, 2), "y": round(y_of(value), 2),
                       "value": value, "label": label})

    low_index = min(range(n), key=lambda i: values[i])
    low = points[low_index]

    zero_y = y_of(0.0)
    line = " ".join(f"{p['x']},{p['y']}" for p in points)

    return {
        "width": width, "height": height,
        "pad_left": pad_left, "pad_top": pad_top, "plot_h": plot_h,
        "baseline": round(y_of(vmin), 2),
        "line": line,
        "points": points,
        # A long horizon would crowd the x labels: print one out of N, keeping
        # the ends pinned -- the same thinning the timeline uses.
        "label_every": _labels_every(len(points)),
        "ticks": [{"value": round(vmin + (vmax - vmin) * f, 2),
                   "y": round(y_of(vmin + (vmax - vmin) * f), 2)}
                  for f in (0, 0.5, 1.0)],
        "zero_y": round(zero_y, 2) if vmin < 0 < vmax else None,
        "low": low,
        "low_index": low_index,
        # Payload for the crosshair: x, y and the value at each step, plus
        # the label the tooltip prints for that step.
        "series": {0: {"name": "Solde", "slot": 0,
                       "pts": [[p["x"], p["y"], p["value"]] for p in points]}},
        "labels": [p["label"] for p in points],
        "geom": {"width": width, "padLeft": pad_left, "plotW": plot_w},
    }


def wealth_chart(observed: list[dict], projected: dict,
                 scale: str = "zero", yscale: str = "linear") -> dict:
    """Net worth on one axis, observed then projected, joined at today.

    The two halves are the same quantity measured two ways, so they belong on
    one line rather than in two panels: the question is "where does this end
    up", and an eye cannot carry a level across a gap between charts. What
    separates them is how they are drawn -- solid for what happened, dashed
    past the `today` rule for what is assumed, plus the ±1σ band. The join is
    a shared point, not two coincident ones: the last observed level *is* the
    projection's starting level, and drawing it twice would invite them to
    disagree by a rounding step. Hoisting that join into the band lists gives
    the polygon, the axis and the tooltip one set of edges, so the tooltip
    cannot disagree with the drawn band.

    Zero-anchored by default, like the savings curve; `scale="auto"` fits both
    ends, which is what makes the band legible when it is small next to the
    total.

    `yscale="log"` draws a log axis -- the mode a multi-decade horizon needs.
    It applies only when every drawn value (totals and band edges) is strictly
    positive: the total of a pocket can be zero or negative, and log of a
    non-positive number is undefined, so the geometry falls back to linear and
    says so rather than inventing a floor. `scale` is ignored in log mode --
    the axis is the data's own decades.
    """
    rows = projected.get("rows") or []
    if len(observed) < 2 or not rows:
        return {}

    width, height = 980, 240
    pad_left, pad_right, pad_top, pad_bottom = 58, 12, 16, 30
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    seen = [o["total"] for o in observed]
    join = seen[-1]
    band_high = [join] + [r["high"] for r in rows]
    band_low = [join] + [r["low"] for r in rows]
    values = seen + band_high + band_low + [r["total"] for r in rows]

    log_mode = yscale == "log" and all(v > 0 for v in values)
    if log_mode:
        vmin = min(values)
        vmax = max(values)
        if vmax <= vmin:
            vmax = vmin * 10          # a flat series gets one decade
        log_span = math.log(vmax) - math.log(vmin)

        def y_of(value: float) -> float:
            return pad_top + plot_h * (
                1 - (math.log(value) - math.log(vmin)) / log_span)

        ticks = [{"value": round(v, 2), "y": round(y_of(v), 2)}
                 for v in _log_ticks(vmin, vmax)]
        if len(ticks) < 2:
            # A range narrower than a decade can fall between the 1-2-5 grid
            # values: the axis then has no reference at all, so the ends
            # themselves become the ticks -- the linear branch never renders
            # without references, neither should this one.
            ticks = [{"value": round(vmin, 2), "y": round(y_of(vmin), 2)},
                     {"value": round(vmax, 2), "y": round(y_of(vmax), 2)}]
    else:
        if scale == "auto":
            vmax = auto_ceiling(max(values))
            vmin = min(values)
            vmin = vmin - (vmax - vmin) * 0.08
        else:
            vmax = nice_ceiling(max(values))
            vmin = min(0.0, min(values))
        if vmin >= vmax:
            vmax = vmin + 1

        def y_of(value: float) -> float:
            return pad_top + plot_h * (1 - (value - vmin) / (vmax - vmin))

        ticks = [{"value": round(vmin + (vmax - vmin) * f, 2),
                  "y": round(y_of(vmin + (vmax - vmin) * f), 2)}
                 for f in (0, 0.5, 1.0)]

    # One slot per point, observed and projected sharing the axis. The join
    # counts once, so the projection's first month sits one slot after the
    # last observed month -- the spacing stays one month everywhere.
    n = len(observed) + len(rows)
    def x_of(i: int) -> float:
        return pad_left + (i / (n - 1)) * plot_w

    past = [{"x": round(x_of(i), 2), "y": round(y_of(o["total"]), 2),
             "value": o["total"], "label": o["label"]}
            for i, o in enumerate(observed)]
    future = [{"x": round(x_of(len(observed) + i), 2),
               "y": round(y_of(r["total"]), 2),
               "value": r["total"], "label": r["label"],
               # The band edges ride with the value so the tooltip can print
               # them -- the same numbers the polygon is drawn from.
               "low": lo, "high": hi}
              for i, (r, lo, hi) in enumerate(zip(rows, band_low[1:],
                                                  band_high[1:]))]

    # The dashed line starts on the last observed point, so the curve is
    # continuous and the eye reads one quantity rather than two segments.
    joined = [past[-1]] + future
    band = ([(p["x"], round(y_of(v), 2))
             for p, v in zip(joined, band_high)]
            + [(p["x"], round(y_of(v), 2))
               for p, v in zip(reversed(joined), reversed(band_low))])

    return {
        "width": width, "height": height,
        "pad_left": pad_left, "pad_top": pad_top, "plot_h": plot_h,
        "baseline": round(y_of(vmin), 2),
        "observed_line": " ".join(f"{p['x']},{p['y']}" for p in past),
        "projected_line": " ".join(f"{p['x']},{p['y']}" for p in joined),
        "band": " ".join(f"{x},{y}" for x, y in band)
                if projected.get("vol") else "",
        "today": {"x": past[-1]["x"], "y": past[-1]["y"],
                  "value": past[-1]["value"]},
        "final": {"x": future[-1]["x"], "y": future[-1]["y"],
                  "value": future[-1]["value"]},
        "ticks": ticks,
        "yscale": "log" if log_mode else "linear",
        # Keyed by the slot, not by 0: the crosshair looks the series up as
        # series[dot.dataset.slot], and this chart's dot carries data-slot=1.
        # A series the dot cannot reach renders a tooltip without its value.
        # Observed points carry no band (three fields); projected ones carry
        # low/high, and their absence *is* the "no band here" signal.
        "series": {1: {"name": "Patrimoine", "slot": 1,
                       "pts": [([p["x"], p["y"], p["value"]]
                                if p.get("low") is None
                                else [p["x"], p["y"], p["value"],
                                      p["low"], p["high"]])
                               for p in past + future]}},
        "labels": [p["label"] for p in past + future],
        "geom": {"width": width, "padLeft": pad_left, "plotW": plot_w},
    }


def evolution_chart(rows: list[dict], scale: str = "zero",
                    focus: str = "total",
                    spec: list[dict] | None = None) -> dict:
    """The savings picture over the window, one line per part of the chosen
    breakdown -- the same parts as the split bar, so the curve and the bar
    never disagree. The 3a only prints yearly values, so its series is a
    staircase: flat between known points, `None` before the first -- a gap
    is drawn as a break, never filled by carrying a value into a past the
    account did not have. Zero-anchored by default (`scale="zero"`), so
    the bars stand for what they are; `scale="auto"` fits both ends of the
    axis to the data. An explicit `spec` names every line to draw -- a
    split view, or a focused pocket's own breakdown; the focus filter only
    applies to the default spec, where it shows that pocket alone.
    """
    if len(rows) < 2:
        return {}

    default_spec = [
        {"key": "swiss", "name": "Swissquote", "slot": 0},
        {"key": "ibkr", "name": "IBKR", "slot": 2},
        {"key": "finp", "name": "3a finpension", "slot": 3},
        {"key": "total", "name": "Épargne totale", "slot": 1},
    ]
    if spec is None:
        spec = default_spec
        focus_key = {"swissquote": "swiss", "ibkr": "ibkr",
                     "finpension": "finp"}.get(focus)
        active = [s for s in spec if focus_key is None or s["key"] == focus_key]
    else:
        # An explicit spec names every line to draw -- the caller picked
        # them (a split view, or a focused pocket's own breakdown). The
        # focus filter only applies to the default spec, or a focused
        # pocket's currency lines would be filtered out as "no ibkr key".
        active = spec

    width, height = 980, 200
    pad_left, pad_right, pad_top, pad_bottom = 58, 12, 16, 30
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    start, end = rows[0]["date"], rows[-1]["date"]
    span = max((end - start).days, 1)

    values = [r[s["key"]] for r in rows for s in active
              if r.get(s["key"]) is not None]
    if not values:
        return {}
    # Base 100 fits the axis like "auto": the lines all start at 100, and
    # an axis from zero would flatten a 10 % move into a hairline.
    vmin = 0.0 if scale == "zero" else min(values)
    # Zero anchors both ends on clean bounds; auto fits the top to the
    # data as well, not just the bottom.
    vmax = nice_ceiling(max(values)) if scale == "zero" \
        else auto_ceiling(max(values))
    if vmax <= vmin:
        vmax = vmin + 1

    draw = []
    pts = {}
    for s in active:
        key, slot = s["key"], s["slot"]
        width_px = 2.5 if key == "total" else 2
        coords = []
        current = []
        for row in rows:
            value = row.get(key)
            if value is None:
                coords.append(None)
                if current:
                    draw.append({"points": " ".join(f"{x},{y}" for x, y in current),
                                 "slot": slot, "width": width_px, "key": key})
                    current = []
                continue
            x = pad_left + (row["date"] - start).days / span * plot_w
            y = pad_top + plot_h * (1 - (value - vmin) / (vmax - vmin))
            coords.append((round(x, 2), round(y, 2)))
            current.append(coords[-1])
        if current:
            draw.append({"points": " ".join(f"{x},{y}" for x, y in current),
                         "slot": slot, "width": width_px, "key": key})
        # A reference index is drawn dashed and thinner: a yardstick, not
        # one of the pockets.
        if s.get("dash"):
            for d in draw:
                if d["key"] == key:
                    d["dash"], d["width"] = True, 1.5
        pts[key] = [None if c is None
                    else [c[0], c[1], round(row[key], 2)]
                    for c, row in zip(coords, rows)]

    return {
        "width": width, "height": height,
        "pad_left": pad_left, "pad_top": pad_top, "plot_h": plot_h,
        "baseline": pad_top + plot_h,
        "draw": draw,
        "ticks": [{"value": round(vmin + (vmax - vmin) * f, 2),
                   "y": round(pad_top + plot_h * (1 - f), 2)}
                  for f in (0, 0.5, 1.0)],
        "start": start, "end": end,
        # Keyed by the slot, so a focused series keeps its own dot and hue.
        "series": {s["slot"]: {"name": s["name"], "slot": s["slot"],
                               "pts": pts[s["key"]]}
                   for s in active},
        "legend": [{"name": s["name"], "slot": s["slot"], "key": s["key"],
                    "dash": bool(s.get("dash"))}
                   for s in active],
        "dots": [{"slot": s["slot"], "key": s["key"]} for s in active],
        "labels": [r["date"].strftime("%d.%m.%Y") for r in rows],
        "geom": {"width": width, "padLeft": pad_left, "plotW": plot_w,
                 "padTop": pad_top, "plotH": plot_h},
        # What the hover prints after a value: francs, or an index level.
        "unit": "" if scale == "index" else "CHF",
    }


def custodian_chart(conversions: list[dict]) -> dict:
    """Cumulative FX markup in CHF -- the cost as it actually accrued."""
    if not conversions:
        return {}

    width, height = 980, 200
    pad_left, pad_right, pad_top, pad_bottom = 58, 12, 16, 30
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    start = conversions[0]["date"]
    end = conversions[-1]["date"]
    span = max((end - start).days, 1)
    total = sum(c["markup_chf"] for c in conversions)
    top = nice_ceiling(total)

    running = 0.0
    coords = []
    for conv in conversions:
        running += conv["markup_chf"]
        x = pad_left + (conv["date"] - start).days / span * plot_w
        y = pad_top + plot_h * (1 - running / top)
        coords.append((round(x, 2), round(y, 2), running, conv))

    return {
        "width": width, "height": height,
        "pad_left": pad_left, "pad_top": pad_top, "plot_h": plot_h,
        "baseline": pad_top + plot_h,
        "line": " ".join(f"{x},{y}" for x, y, _, _ in coords),
        "dots": [{"x": x, "y": y, "running": r, "conv": c}
                 for x, y, r, c in coords],
        "ticks": [{"value": top * f, "y": round(pad_top + plot_h * (1 - f), 2)}
                  for f in (0, 0.5, 1.0)],
        "start": start, "end": end, "total": total,
        "last": {"x": coords[-1][0], "y": coords[-1][1]},
    }


def weekday_chart(weekdays: list[dict]) -> dict:
    top = nice_ceiling(max(d["amount"] for d in weekdays))
    return {
        "top": top,
        "rows": [{**d, "pct": d["amount"] / top * 100} for d in weekdays],
    }


def calendar_chart(days: dict, start, end) -> dict:
    """One strip per calendar year: weeks across, weekdays down.

    A sequential ramp carries magnitude, so it is one hue light-to-dark with a
    scale legend. The bins are quantiles rather than equal widths -- daily
    spending is heavily skewed (a rent payment is 100x a coffee), and equal
    widths would put every ordinary day in the lightest bin.
    """
    if not days:
        return {}

    amounts = sorted(v["amount"] for v in days.values())
    cuts = [amounts[int(len(amounts) * q)] for q in (0.25, 0.5, 0.75, 0.92)]

    def level(amount: float) -> int:
        for i, cut in enumerate(cuts, start=1):
            if amount <= cut:
                return i
        return 5

    cell, pitch = 9, 11.5
    label_w, strip_h = 30, 7 * pitch

    years = []
    for year in range(start.year, end.year + 1):
        first = dt.date(year, 1, 1)
        # Column 0 holds the week containing 1 January.
        origin = first - dt.timedelta(days=first.weekday())
        cells, months = [], []
        day = max(first, start)
        last = min(dt.date(year, 12, 31), end)
        seen_month = set()
        while day <= last:
            index = (day - origin).days
            column, row = index // 7, index % 7
            entry = days.get(day)
            cells.append({
                "x": round(label_w + column * pitch, 2),
                "y": round(row * pitch, 2),
                "level": level(entry["amount"]) if entry else 0,
                "date": day,
                "amount": entry["amount"] if entry else 0.0,
                "count": entry["count"] if entry else 0,
            })
            if day.month not in seen_month and day.day <= 7:
                seen_month.add(day.month)
                months.append({"x": round(label_w + column * pitch, 2),
                               "label": analysis.MONTH_SHORT[day.month - 1][:1].upper()
                                        + analysis.MONTH_SHORT[day.month - 1][1:3]})
            day += dt.timedelta(days=1)
        if cells:
            years.append({"year": year, "cells": cells, "months": months,
                          "width": max(c["x"] for c in cells) + cell + 4})

    return {
        "years": years, "cell": cell, "pitch": pitch,
        "label_w": label_w, "strip_h": strip_h,
        "width": max((y["width"] for y in years), default=700),
        "cuts": cuts,
        "days": ["L", "M", "M", "J", "V", "S", "D"],
    }


def fixed_chart(fixed: dict) -> dict:
    """Monthly columns split into the contractual floor and everything else."""
    months = fixed["months"]
    if not months:
        return {}

    width, height = 980, 280
    pad_left, pad_top, pad_bottom = 58, 16, 46
    plot_w = width - pad_left - 12
    plot_h = height - pad_top - pad_bottom

    top = nice_ceiling(max(m["fixed"] + m["variable"] for m in months))
    band = plot_w / len(months)
    bar_w = min(24.0, band * 0.62)
    gap = 2.0

    columns = []
    for i, month in enumerate(months):
        x = pad_left + band * i + (band - bar_w) / 2
        fixed_h = month["fixed"] / top * plot_h
        variable_h = month["variable"] / top * plot_h
        base = pad_top + plot_h
        columns.append({
            "key": month["month"], "label": month_label(month["month"]),
            "x": round(x, 2), "w": round(bar_w, 2),
            "band_x": round(pad_left + band * i, 2), "band_w": round(band, 2),
            "fixed": month["fixed"], "variable": month["variable"],
            "fixed_y": round(base - fixed_h, 2),
            "fixed_h": round(max(fixed_h, 0.6), 2),
            "variable_y": round(base - fixed_h - variable_h, 2),
            "variable_h": round(max(variable_h - gap, 0.6), 2),
        })

    floor_y = pad_top + plot_h * (1 - fixed["monthly_floor"] / top)
    return {
        "width": width, "height": height, "plot_h": plot_h,
        "pad_left": pad_left, "pad_top": pad_top,
        "baseline": pad_top + plot_h, "columns": columns,
        "ticks": [{"value": top * f, "y": round(pad_top + plot_h * (1 - f), 2)}
                  for f in (0, 0.25, 0.5, 0.75, 1.0)],
        "label_every": max(1, len(months) // 12),
        "floor_y": round(floor_y, 2), "floor": fixed["monthly_floor"],
    }


def country_chart(geo: dict) -> dict:
    """Nominal categories, so every bar takes the same hue -- length is the encoding."""
    rows = geo["rows"][:10]
    if not rows:
        return {}
    top = rows[0]["amount"]
    return {"rows": [{**r, "pct": r["amount"] / top * 100} for r in rows]}


def year_chart(series: list[dict]) -> dict:
    """Cumulative spend by day-of-year, one line per year, on a single axis."""
    series = [s for s in series if s["points"]]
    if not series:
        return {}

    width, height = 980, 260
    pad_left, pad_top, pad_bottom = 58, 16, 40
    plot_w = width - pad_left - 44
    plot_h = height - pad_top - pad_bottom
    top = nice_ceiling(max(s["total"] for s in series))

    lines = []
    crosshair: dict[int, dict] = {}
    for i, entry in enumerate(series):
        coords = [(round(pad_left + (day - 1) / 365 * plot_w, 2),
                   round(pad_top + plot_h * (1 - value / top), 2), round(value, 2))
                  for day, value in entry["points"]]
        step = max(1, len(coords) // 400)
        thinned = coords[::step] + [coords[-1]]
        lines.append({
            "year": entry["year"], "slot": i, "total": entry["total"],
            "points": " ".join(f"{x},{y}" for x, y, _ in thinned),
            "end": {"x": thinned[-1][0], "y": thinned[-1][1]},
            "partial": entry["first_day"] > 15 or entry["last_day"] < 350,
        })
        # The crosshair samples by fraction of the axis, so every series is
        # resampled onto the same 0..365 grid -- otherwise a partial year would
        # be read at the wrong date.
        grid = []
        pos = 0
        for day in range(1, 367):
            while pos + 1 < len(coords) and coords[pos + 1][0] <= \
                    pad_left + (day - 1) / 365 * plot_w:
                pos += 1
            x = round(pad_left + (day - 1) / 365 * plot_w, 2)
            if day < entry["first_day"] or day > entry["last_day"]:
                # Outside the days actually observed for this year. Padding the
                # ends -- with 0 before the first day, or the last total after
                # the last -- would read as "spent nothing" and "spent this much
                # by August", when the truth is that there is no data there.
                grid.append(None)
            else:
                grid.append([x, coords[pos][1], coords[pos][2]])
        crosshair[i] = {"name": str(entry["year"]), "slot": i, "pts": grid}

    month_x = []
    for month in range(1, 13):
        day = dt.date(2025, month, 1).timetuple().tm_yday
        month_x.append({"x": round(pad_left + (day - 1) / 365 * plot_w, 2),
                        "label": analysis.MONTH_SHORT[month - 1][:1].upper()
                                 + analysis.MONTH_SHORT[month - 1][1:3]})

    return {
        "width": width, "height": height, "plot_h": plot_h,
        "pad_left": pad_left, "pad_top": pad_top,
        "baseline": pad_top + plot_h, "lines": lines, "months": month_x,
        "ticks": [{"value": top * f, "y": round(pad_top + plot_h * (1 - f), 2)}
                  for f in (0, 0.5, 1.0)],
        "series": crosshair,
        "geom": {"width": width, "padLeft": pad_left, "plotW": plot_w},
    }


SHARE_FLOOR, SHARE_CEILING = -100.0, 200.0


def shares_chart(rows: list[dict], names: list[str], fills: dict[str, str],
                 base: str, smooth: int, targets: dict[str, float]) -> dict:
    """Need / Want / Save shares month by month, one 2px line each.

    The lines are the smoothed values; when smoothing is on, the raw monthly
    shares stay drawn faintly behind them, so the smoothing never hides the
    data it smooths. On the income base the axis is capped: one month with
    almost no income reads -2500 %, and an axis stretched to hold it would
    flatten every other month into a line. A point beyond the cap is drawn on
    the edge as a hollow mark, and the tooltip still says its true value.
    """
    if len(rows) < 2:
        return {}
    width, height = 980, 280
    pad_left, pad_right, pad_top, pad_bottom = 58, 92, 16, 36
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    drawn = [r[kind][n] for r in rows for n in names for kind in ("raw", "smooth")
             if r[kind][n] is not None]
    if base == "spending":
        lo, hi = 0.0, 100.0
    else:
        lo = max(SHARE_FLOOR, math.floor(min([0.0, *drawn]) / 25) * 25)
        hi = min(SHARE_CEILING, math.ceil(max([100.0, *drawn]) / 25) * 25)

    def y_of(value: float) -> tuple[float, bool]:
        kept = min(max(value, lo), hi)
        return round(pad_top + plot_h * (1 - (kept - lo) / (hi - lo)), 2), kept != value

    n = len(rows)
    xs = [round(pad_left + i / (n - 1) * plot_w, 2) for i in range(n)]

    def segments(values: list[float | None]) -> list[str]:
        """Runs of consecutive points: a None breaks the line, it never
        bridges it."""
        runs, current = [], []
        for x, value in zip(xs, values):
            if value is None:
                if len(current) > 1:
                    runs.append(" ".join(current))
                current = []
                continue
            current.append(f"{x},{y_of(value)[0]}")
        if len(current) > 1:
            runs.append(" ".join(current))
        return runs

    lines, series = [], {}
    for name in names:
        values = [r["smooth"][name] for r in rows]
        raw = [r["raw"][name] for r in rows]
        if not any(values) and not any(raw):
            continue  # a bucket that never held a franc here is not a line
        points = [(x, *y_of(v), v) for x, v in zip(xs, values) if v is not None]
        slot = len(series)
        lines.append({
            "name": name, "fill": fills[name], "slot": slot,
            "segments": segments(values),
            "raw_segments": segments(raw) if smooth > 1 else [],
            "offscale": [{"x": x, "y": y} for x, y, off, _ in points if off],
            "end": ({"x": points[-1][0], "y": points[-1][1]} if points else None),
        })
        series[slot] = {"name": name, "slot": slot, "fill": fills[name],
                        "pts": [[x, y_of(v)[0], round(v, 1)] if v is not None
                                else None for x, v in zip(xs, values)]}

    # End labels: lines often finish a few points apart (Want at 9 %, Non
    # classé at 6 %), and two names printed on top of each other read as
    # neither. Stack them at least a line apart, top to bottom.
    floor = -math.inf
    for line in sorted((line for line in lines if line["end"]),
                       key=lambda line: line["end"]["y"]):
        line["end"]["label_y"] = round(max(line["end"]["y"] + 4, floor + 12), 2)
        floor = line["end"]["label_y"]

    step = 25 if hi - lo <= 150 else 50
    ticks = []
    value = lo
    while value <= hi + 1e-9:
        ticks.append({"value": value, "y": y_of(value)[0]})
        value += step
    every = _labels_every(n)
    shown = {line["name"] for line in lines}

    return {
        "width": width, "height": height, "pad_left": pad_left,
        "pad_top": pad_top, "plot_h": plot_h, "plot_right": pad_left + plot_w,
        "baseline": pad_top + plot_h, "lo": lo, "hi": hi,
        "capped": bool(drawn) and (min(drawn) < lo or max(drawn) > hi),
        "ticks": ticks,
        "zero_y": y_of(0.0)[0] if lo < 0 < hi else None,
        "targets": ([{"name": name, "value": target, "fill": fills[name],
                      "y": y_of(target)[0]}
                     for name, target in targets.items()
                     if name in shown and lo <= target <= hi]
                    if base == "income" else []),
        "lines": lines,
        "xlabels": [{"x": x, "label": r["label"]}
                    for i, (x, r) in enumerate(zip(xs, rows)) if i % every == 0],
        "series": series,
        "labels": [r["label"] for r in rows],
        "geom": {"width": width, "padLeft": pad_left, "plotW": plot_w},
    }


def category_month_chart(rows: list[dict], median: float) -> dict:
    """One bar per observed month of a single category -- the drill-down
    from the analysis page, so a category's shape is seen raw, not through
    its medians. The dashed rule is the category's own median month, so a
    spike reads against the category, not against nothing.
    """
    if not rows:
        return {}
    width, height = 980, 280
    pad_left, pad_top, pad_bottom = 58, 16, 46
    plot_w = width - pad_left - 12
    plot_h = height - pad_top - pad_bottom

    top = nice_ceiling(max(r["amount"] for r in rows))
    band = plot_w / len(rows)
    bar_w = min(24.0, band * 0.62)
    base = pad_top + plot_h

    columns = []
    for i, month in enumerate(rows):
        x = pad_left + band * i + (band - bar_w) / 2
        h = month["amount"] / top * plot_h
        columns.append({
            "key": month["key"], "label": month["label"],
            "x": round(x, 2), "w": round(bar_w, 2),
            "band_x": round(pad_left + band * i, 2), "band_w": round(band, 2),
            "amount": month["amount"],
            "y": round(base - h, 2), "h": round(max(h, 0.6), 2),
        })

    labels = [c["label"] for c in columns]
    series = [{"name": "Dépense mensuelle", "slot": 0,
               "pts": [[round(c["x"] + c["w"] / 2, 2), round(c["y"], 2),
                        round(c["amount"], 2)] for c in columns]}]
    return {
        "width": width, "height": height, "plot_h": plot_h,
        "pad_left": pad_left, "pad_top": pad_top,
        "baseline": base, "median": round(median, 2),
        "median_y": (round(pad_top + plot_h * (1 - median / top), 2)
                     if median > 0 else None),
        "columns": columns, "labels": labels, "series": series,
        "geom": {"width": width, "padLeft": pad_left, "plotW": plot_w},
        "label_every": max(1, len(columns) // 12),
        "ticks": [{"value": top * f, "y": round(pad_top + plot_h * (1 - f), 2)}
                  for f in (0, 0.25, 0.5, 0.75, 1.0)],
    }


def season_chart(rows: list[dict]) -> dict:
    top = max((r["average"] for r in rows), default=0) or 1.0
    return {"rows": [{**r, "label": analysis.MONTH_SHORT[r["month"] - 1],
                      "pct": r["average"] / top * 100} for r in rows]}


def monthly_season_chart(profile: list[dict], baseline: float) -> dict:
    """The ordinary month, one bar per observed calendar month.

    Each bar is the *median* of the observed months of that name (not the
    mean: the same argument as the baseline -- December's insurance would
    stretch a mean, and the median is what the projection already uses).
    The stripped remainder is the solid lower segment, the seasonal spike
    the translucent upper one, so the eye reads "this is what December
    ordinarily costs" without losing which part is the annual bill. The
    dashed rule is the global baseline -- the median over *all* adjusted
    months, the KPI's number -- drawn only while it falls inside the plot,
    so a horizon of nothing-but-spikes does not pin it outside the frame.
    """
    if not profile:
        return {}
    width, height = 980, 280
    pad_left, pad_top, pad_bottom = 58, 16, 46
    plot_w = width - pad_left - 12
    plot_h = height - pad_top - pad_bottom

    top = nice_ceiling(max(p["raw_median"] for p in profile))
    band = plot_w / len(profile)
    bar_w = min(30.0, band * 0.6)
    gap = 2.0
    base = pad_top + plot_h

    columns = []
    for i, month in enumerate(profile):
        x = pad_left + band * i + (band - bar_w) / 2
        stripped_h = month["stripped_median"] / top * plot_h
        seasonal_h = month["seasonal_median"] / top * plot_h
        columns.append({
            "key": f"m{month['month']:02d}", "label": month["short"],
            "x": round(x, 2), "w": round(bar_w, 2),
            "band_x": round(pad_left + band * i, 2), "band_w": round(band, 2),
            "raw_median": month["raw_median"],
            "stripped_median": month["stripped_median"],
            "seasonal_median": month["seasonal_median"],
            "years": month["years"],
            "stripped_y": round(base - stripped_h, 2),
            "stripped_h": round(max(stripped_h, 0.6), 2),
            "seasonal_y": round(base - stripped_h - seasonal_h, 2),
            "seasonal_h": round(max(seasonal_h - gap, 0.6), 2)
            if seasonal_h > 0 else 0.0,
        })

    floor_y = (round(pad_top + plot_h * (1 - baseline / top), 2)
               if 0 < baseline <= top else None)

    # One point per bar, for the crosshair. The "Médiane brute" dot rides
    # the height that raw_median actually draws (not the top of the drawn
    # bar: stripped and seasonal are two medians taken separately, and the
    # median of a sum is not the sum of medians -- the dot and the tooltip
    # must agree on the number, the bar is the illustration).
    labels = [c["label"] for c in columns]
    series = [
        {"name": "Médiane brute", "slot": 0,
         "pts": [[round(c["x"] + c["w"] / 2, 2),
                  round(base - c["raw_median"] / top * plot_h, 2),
                  round(c["raw_median"], 2)] for c in columns]},
        {"name": "Médiane hors saisonnier", "slot": 1,
         "pts": [[round(c["x"] + c["w"] / 2, 2), round(c["stripped_y"], 2),
                  round(c["stripped_median"], 2)] for c in columns]},
    ]
    return {
        "width": width, "height": height, "plot_h": plot_h,
        "pad_left": pad_left, "pad_top": pad_top,
        "baseline": base, "floor": baseline, "floor_y": floor_y,
        "columns": columns, "labels": labels, "series": series,
        "geom": {"width": width, "padLeft": pad_left, "plotW": plot_w},
        "ticks": [{"value": top * f, "y": round(pad_top + plot_h * (1 - f), 2)}
                  for f in (0, 0.25, 0.5, 0.75, 1.0)],
    }
