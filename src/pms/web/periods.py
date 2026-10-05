"""Period selection, drill-down and breadcrumbs.

The whole temporal navigation is derived from two dates in the query string.
There is no session state and no hidden trail: a window plus a grain fully
determines the view, so every drill-down step is a plain URL you can bookmark,
share, or reach with the browser's back button.

The breadcrumb is *reconstructed* from the window rather than accumulated. If
the window happens to be exactly one calendar month, the trail reads
"Tout › 2025 › mai 2025". That keeps navigation honest -- the crumb reflects
what is actually being shown, not the path you happened to take to get there.
"""

from __future__ import annotations

import datetime as dt

from .. import analysis

MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def presets(low: dt.date, high: dt.date) -> list[dict]:
    """Ready-made windows, all anchored on the last day we hold data for.

    Anchoring on `high` rather than on today matters: a statement is always a
    little stale, and "30 derniers jours" counted from today would silently show
    an empty or half-empty window. For the same reason "à ce jour" means "up to
    the last movement on the statement", not up to the wall clock.
    """
    def clamp(start: dt.date) -> dt.date:
        return max(start, low)

    quarter_start = dt.date(high.year, 3 * ((high.month - 1) // 3) + 1, 1)

    return [
        # To-date windows: from the start of the current calendar unit.
        {"id": "mtd", "group": "À ce jour", "label": "Mois",
         "start": clamp(high.replace(day=1)), "end": high},
        {"id": "qtd", "group": "À ce jour", "label": "Trimestre",
         "start": clamp(quarter_start), "end": high},
        {"id": "ytd", "group": "À ce jour", "label": "Année",
         "start": clamp(dt.date(high.year, 1, 1)), "end": high},

        # Rolling windows: a fixed span back from the last movement.
        {"id": "30d", "group": "Glissant", "label": "30 jours",
         "start": clamp(high - dt.timedelta(days=29)), "end": high},
        {"id": "90d", "group": "Glissant", "label": "3 mois",
         "start": clamp(high - dt.timedelta(days=89)), "end": high},
        {"id": "180d", "group": "Glissant", "label": "6 mois",
         "start": clamp(high - dt.timedelta(days=179)), "end": high},
        {"id": "12m", "group": "Glissant", "label": "12 mois",
         "start": clamp(high - dt.timedelta(days=364)), "end": high},

        {"id": "prev_year", "group": "Complet", "label": f"{high.year - 1}",
         "start": clamp(dt.date(high.year - 1, 1, 1)),
         "end": min(dt.date(high.year - 1, 12, 31), high)},
        {"id": "all", "group": "Complet", "label": "Tout",
         "start": low, "end": high},
    ]


def preset_groups(low: dt.date, high: dt.date, start: dt.date,
                  end: dt.date) -> list[dict]:
    """Presets bundled into their button groups, with the active one marked."""
    # The key is "buttons", not "items": in Jinja, `group.items` resolves to the
    # dict's own .items() method rather than the key, and iterating it silently
    # blows up at render time.
    groups: list[dict] = []
    for preset in presets(low, high):
        active = (preset["start"], preset["end"]) == (start, end)
        if not groups or groups[-1]["name"] != preset["group"]:
            groups.append({"name": preset["group"], "buttons": []})
        groups[-1]["buttons"].append({**preset, "active": active})
    return groups


def describe(start: dt.date, end: dt.date) -> str:
    """A human title for the window, naming the calendar unit when it is one."""
    if start == end:
        return f"{start.day} {MONTHS_FR[start.month - 1]} {start.year}"

    month_start, month_end = analysis.bucket_bounds(start, "month")
    if (start, end) == (month_start, month_end):
        return f"{MONTHS_FR[start.month - 1].capitalize()} {start.year}"
    if start == month_start and end < month_end:
        # The month in progress -- the default view -- reads as the month,
        # not as two dates.
        return (f"{MONTHS_FR[start.month - 1].capitalize()} {start.year}, "
                f"jusqu'au {end.day}")

    year_start, year_end = analysis.bucket_bounds(start, "year")
    if (start, end) == (year_start, year_end):
        return f"Année {start.year}"

    week_start, week_end = analysis.bucket_bounds(start, "week")
    if (start, end) == (week_start, week_end):
        _, week, _ = start.isocalendar()
        return (f"Semaine {week} · {start.day} au {end.day} "
                f"{MONTHS_FR[end.month - 1]} {end.year}")

    return (f"{start.strftime('%d.%m.%Y')} → {end.strftime('%d.%m.%Y')}")


def crumbs(start: dt.date, end: dt.date, low: dt.date, high: dt.date) -> list[dict]:
    """The nesting chain from the full history down to the current window.

    Each level is included only if the current window fits inside that calendar
    unit -- so a window spanning two months yields no month crumb, which is the
    honest answer rather than an arbitrary pick.
    """
    trail = [{"label": "Tout", "start": low, "end": high,
              "current": (start, end) == (low, high)}]
    if (start, end) == (low, high):
        return trail

    for grain in ("year", "month", "week", "day"):
        unit_start, unit_end = analysis.bucket_bounds(start, grain)
        if not (unit_start <= start and end <= unit_end):
            break
        clipped = (max(unit_start, low), min(unit_end, high))
        label = describe(*analysis.bucket_bounds(start, grain))
        trail.append({
            "label": label,
            "start": clipped[0], "end": clipped[1],
            "current": (start, end) in ((unit_start, unit_end), clipped),
        })
        if (start, end) in ((unit_start, unit_end), clipped):
            return trail

    if not trail[-1]["current"]:
        trail.append({"label": describe(start, end),
                      "start": start, "end": end, "current": True})
    return trail


def neighbours(start: dt.date, end: dt.date, low: dt.date,
               high: dt.date) -> dict | None:
    """The previous/next window.

    A calendar unit (day, week, month, year) steps by that unit, so the arrow
    after April is May and not "30 days later". The month in progress -- the
    default view, from the 1st to the last movement -- steps back to the whole
    previous month. Any other window steps by its own length: that is not a
    guess, it is the same window, one length earlier -- and without it the
    arrows, and ←/→, did nothing on most views.
    """
    span = (end - start).days + 1
    prev_end = next_end = None
    month_end = _last_of_month(start)
    if start.day == 1 and end == high and end < month_end \
            and (end.year, end.month) == (start.year, start.month):
        prev = _shift_month(start, -1)
        prev_end = _last_of_month(prev)
        next_ = month_end + dt.timedelta(days=1)
        return {
            "label": "month",
            "prev": {"start": prev, "end": prev_end, "available": prev_end >= low},
            "next": {"start": next_, "end": _last_of_month(next_),
                     "available": False},
            "prev_label": describe(prev, prev_end),
            "next_label": describe(next_, _last_of_month(next_)),
        }
    if start == end:
        unit = "day"
        prev, next_ = start - dt.timedelta(days=1), start + dt.timedelta(days=1)
        prev_end, next_end = prev, next_
    else:
        unit_start, unit_end = analysis.bucket_bounds(start, "week")
        if (start, end) == (unit_start, unit_end) and span == 7:
            unit = "week"
            prev, next_ = start - dt.timedelta(days=7), end + dt.timedelta(days=1)
        elif start.day == 1 and end == _last_of_month(start) and span <= 31:
            unit = "month"
            prev = _shift_month(start, -1)
            next_ = _shift_month(start, 1)
            # The neighbour is the calendar month itself, not a 31-day shift:
            # 01.04 + 30 days = 01.05, which is not April. The month is the
            # unit the arrows get used on, so the off-by-one would show.
            prev_end = _last_of_month(prev)
            next_end = _last_of_month(next_)
        elif (start.month == 1 and start.day == 1 and end.month == 12
              and end.day == 31):
            unit = "year"
            prev = start.replace(year=start.year - 1)
            next_ = start.replace(year=start.year + 1)
        else:
            step = dt.timedelta(days=span)
            prev, next_ = start - step, start + step
            return {
                "label": "même durée",
                "prev": {"start": prev, "end": start - dt.timedelta(days=1),
                         "available": start > low},
                "next": {"start": next_, "end": end + step,
                         "available": end < high},
                # Dates would make a very wide button; the title carries them.
                "prev_label": "Précédente",
                "next_label": "Suivante",
            }

    if prev_end is None:
        prev_end = prev + (end - start)
    if next_end is None:
        next_end = next_ + (end - start)
    return {
        "label": unit,
        "prev": {"start": prev, "end": prev_end,
                 "available": prev_end >= low},
        "next": {"start": next_, "end": next_end,
                 "available": next_ <= high},
        # The neighbouring window is one calendar unit, so describe() names
        # it ("Juin 2025") -- the arrow buttons announce where they go.
        "prev_label": describe(prev, prev_end),
        "next_label": describe(next_, next_end),
    }


def _last_of_month(day: dt.date) -> dt.date:
    following = (day.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    return following - dt.timedelta(days=1)


def _shift_month(day: dt.date, delta: int) -> dt.date:
    index = day.year * 12 + (day.month - 1) + delta
    year, month = index // 12, index % 12 + 1
    last = _last_of_month(dt.date(year, month, 1))
    return dt.date(year, month, min(day.day, last.day))


def resolve(args, low: dt.date, high: dt.date) -> dict:
    """Turn query parameters into a concrete window and grain."""
    preset_id = args.get("preset")
    start = parse_date(args.get("from"))
    end = parse_date(args.get("to"))

    if preset_id:
        chosen = next((p for p in presets(low, high) if p["id"] == preset_id), None)
        if chosen:
            start, end = chosen["start"], chosen["end"]

    if start is None and end is None:
        # The month in progress: what the app is opened for is "where am I
        # this month", and its monthly review is there. Twelve months are one
        # click away.
        default = next(p for p in presets(low, high) if p["id"] == "mtd")
        start, end = default["start"], default["end"]

    start = max(start or low, low)
    end = min(end or high, high)
    if end < start:
        start, end = end, start

    grain = args.get("grain")
    auto = grain in (None, "", "auto")
    if auto:
        grain = analysis.suggest_grain(start, end)
    if grain not in analysis.GRAINS:
        grain = analysis.suggest_grain(start, end)

    return {
        "start": start,
        "end": end,
        "grain": grain,
        "auto_grain": auto,
        "title": describe(start, end),
        "days": (end - start).days + 1,
        "crumbs": crumbs(start, end, low, high),
        "presets": [
            {**p, "active": (p["start"], p["end"]) == (start, end)}
            for p in presets(low, high)
        ],
        "preset_groups": preset_groups(low, high, start, end),
        "is_full": (start, end) == (low, high),
    }
