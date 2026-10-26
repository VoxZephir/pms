"""Period resolution and breadcrumbs: the window shown is the window asked for."""

from __future__ import annotations

import datetime as dt

from pms import analysis
from pms.web import periods

# --- period resolution ------------------------------------------------------

class Args(dict):
    """Stand-in for Flask's request.args."""


def test_default_window_is_the_month_in_progress(bounds):
    """What the app is opened for: this month so far, and its review."""
    low, high = bounds
    resolved = periods.resolve(Args(), low, high)
    assert resolved["end"] == high
    assert resolved["start"] == high.replace(day=1)


def test_presets_anchor_on_the_last_day_held_not_today(bounds):
    """A statement is always a little stale; anchoring on today would show an
    empty window."""
    low, high = bounds
    for preset in periods.presets(low, high):
        assert preset["end"] <= high
        assert preset["start"] >= low


def test_explicit_window_wins_and_is_clamped(bounds):
    low, high = bounds
    resolved = periods.resolve(
        Args({"from": "1990-01-01", "to": "2099-01-01"}), low, high)
    assert resolved["start"] == low
    assert resolved["end"] == high


def test_reversed_dates_are_swapped_not_rejected(bounds):
    low, high = bounds
    resolved = periods.resolve(
        Args({"from": "2025-12-31", "to": "2025-01-01"}), low, high)
    assert resolved["start"] < resolved["end"]


def test_garbage_dates_fall_back_to_the_default(bounds):
    low, high = bounds
    resolved = periods.resolve(Args({"from": "pas-une-date"}), low, high)
    assert low <= resolved["start"] <= resolved["end"] <= high


def test_grain_is_chosen_to_keep_the_axis_readable(bounds):
    low, high = bounds
    for days, expected in [(20, "day"), (120, "week"), (400, "month")]:
        start = high - dt.timedelta(days=days - 1)
        assert analysis.suggest_grain(start, high) == expected


def test_explicit_grain_overrides_the_suggestion(bounds):
    low, high = bounds
    resolved = periods.resolve(
        Args({"from": low.isoformat(), "to": high.isoformat(), "grain": "day"}),
        low, high)
    assert resolved["grain"] == "day"
    assert resolved["auto_grain"] is False


# --- breadcrumbs ------------------------------------------------------------

def test_breadcrumb_names_the_calendar_unit_being_shown(bounds):
    low, high = bounds
    start, end = analysis.bucket_bounds(dt.date(2025, 5, 15), "month")
    trail = periods.crumbs(start, end, low, high)
    labels = [c["label"] for c in trail]
    assert labels[0] == "Tout"
    assert "Année 2025" in labels
    assert labels[-1] == "Mai 2025"
    assert trail[-1]["current"] is True


def test_breadcrumb_omits_a_unit_the_window_straddles(bounds):
    """A window spanning two months gets no month crumb -- picking one would
    misdescribe what is on screen."""
    low, high = bounds
    trail = periods.crumbs(dt.date(2025, 5, 20), dt.date(2025, 6, 10), low, high)
    assert not any(c["label"].startswith("Mai") for c in trail)
    assert trail[-1]["current"] is True


def test_full_history_has_a_single_crumb(bounds):
    low, high = bounds
    assert len(periods.crumbs(low, high, low, high)) == 1


def test_twelve_months_start_on_the_first():
    """Twelve calendar months, the current one included: a mid-month start
    opened every chart on a near-empty column."""
    low, high = dt.date(2020, 1, 1), dt.date(2026, 7, 30)
    p = next(x for x in periods.presets(low, high) if x["id"] == "12m")
    assert p["start"] == dt.date(2025, 8, 1) and p["end"] == high
    jan = next(x for x in periods.presets(low, dt.date(2026, 1, 15)) if x["id"] == "12m")
    assert jan["start"] == dt.date(2025, 2, 1)
