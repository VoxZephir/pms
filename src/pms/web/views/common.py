"""Plumbing every page shares: the blueprint, the store, the view-mode
switches carried in the URL, and the table's filter and sort.

Nothing here knows about a particular page. `dash_url` and `page_url` are
template globals, so every template can build links that keep the window.
"""

from __future__ import annotations

import datetime as dt

from flask import Blueprint, current_app, request, url_for

from ... import buckets
from ...analysis import chf

bp = Blueprint("dashboard", __name__)


PAGE_SIZE = 60
# The dashboard's table is the last of fifteen panels: at 60 rows it was
# 4.7 screens on its own, a third of the page. It shows 20 and pages on;
# the Transactions page, which is only the table, keeps 60.
COMPACT_PAGE_SIZE = 20
PAGE_SIZES = (COMPACT_PAGE_SIZE, PAGE_SIZE)


def page_size(args, default: int = PAGE_SIZE) -> int:
    """?per=N, one of PAGE_SIZES -- validated like every other view switch."""
    try:
        size = int((args.get("per") or "").strip())
    except ValueError:
        return default
    return size if size in PAGE_SIZES else default


# Sortable columns. Text sorts case-insensitively so "aldi" and "Aldi" do not
# end up in different halves of the list; amounts sort by magnitude, because
# ranking a statement by signed value buries every large debit at the bottom.
SORT_KEYS = {
    "date": lambda t: (t.date, t.seq),
    "label": lambda t: (t.label.casefold(), t.date),
    "category": lambda t: (t.category.casefold(), t.subcategory.casefold(), t.date),
    "amount": lambda t: (abs(t.amount), t.date),
    "chf": lambda t: (abs(t.amount_chf), t.date),
}


BUCKET_FILL = {"Need": "var(--s0)", "Want": "var(--s1)",
               "Non classé": "var(--unsorted)", "Save": "var(--s2)"}


# How the timeline column is sliced. Both stack the same spending rows, so the
# columns keep their height and only the breakdown changes -- which is the whole
# point of offering the switch: it is one dataset seen two ways, not two charts.
STACKS = {
    "category": {"source": "categories", "label": "Catégories",
                 "aria": "empilées par catégorie"},
    "bucket": {"source": "buckets", "label": "Besoins / envies",
               "aria": "empilées par besoin, envie et épargne"},
}


DEFAULT_STACK = "category"


# How the savings panel splits the bar. Same money, three ways: by account
# (the default), by currency, or by asset class.
SPLITS = {
    "account": {"label": "Compte", "aria": "réparti par compte"},
    "currency": {"label": "Monnaie", "aria": "réparti par monnaie"},
    "asset": {"label": "Type d'actif", "aria": "réparti par type d'actif"},
    "geo": {"label": "Géographie", "aria": "réparti par zone géographique"},
    "fund": {"label": "Par fond", "aria": "réparti par fond"},
}


DEFAULT_SPLIT = "account"


# How the savings curve anchors its y axis: at zero (the default, so the
# bars stand for what they are), or fitted to the lowest value ("auto")
# when the shape of the change is what matters.
SCALES = {
    "zero": {"label": "Montants", "aria": "en francs, axe y ancré à zéro"},
    "auto": {"label": "Zoom", "aria": "en francs, axe y ajusté aux valeurs"},
    # Each line rebased to 100 at its first point, versements taken out:
    # the pockets' performance side by side instead of their sizes.
    "index": {"label": "Base 100", "aria": "chaque ligne en base 100, versements retirés"},
}


DEFAULT_SCALE = "zero"


# Which return the savings section reports. Time-weighted: what the
# investments did, whatever was deposited when. Money-weighted: what the
# owner's money did, deposits weighted by how long they were invested.
PERFS = {
    "twr": {"label": "TWR", "aria": "rendement pondéré par le temps"},
    "mwr": {"label": "MWR", "aria": "rendement pondéré par les capitaux"},
}


DEFAULT_PERF = "twr"


# Which account the savings section focuses on -- the boxes are the
# selector. Everything else (curve, performance) adapts to the pick.
FOCUSES = ["total", "swissquote", "ibkr", "finpension"]


DEFAULT_FOCUS = "total"


def store():
    return current_app.extensions["pms_store"]


def stack_mode(args) -> str:
    """Which breakdown the timeline stacks -- validated, never echoed raw."""
    mode = (args.get("stack") or "").strip()
    return mode if mode in STACKS else DEFAULT_STACK


def split_mode(args) -> str:
    """Which breakdown the savings bar shows -- validated, never echoed raw."""
    mode = (args.get("split") or "").strip()
    return mode if mode in SPLITS else DEFAULT_SPLIT


def scale_mode(args) -> str:
    """How the savings curve anchors its y axis -- validated, never echoed."""
    mode = (args.get("scale") or "").strip()
    return mode if mode in SCALES else DEFAULT_SCALE


def perf_mode(args) -> str:
    """Which return the savings section reports -- validated."""
    mode = (args.get("perf") or "").strip()
    return mode if mode in PERFS else DEFAULT_PERF


def focus_mode(args) -> str:
    """Which account the savings section zooms into -- validated."""
    mode = (args.get("focus") or "").strip()
    return mode if mode in FOCUSES else DEFAULT_FOCUS


def shares_mode(args) -> str | None:
    """The denominator of the shares-over-time chart, or None when nobody
    asked for it. Its presence is also what renders the panel unfolded: the
    options inside are real links, and a swap that re-rendered it folded
    would close it under the reader's pointer at every click."""
    mode = (args.get("shares") or "").strip()
    return mode if mode in buckets.SHARE_BASES else None


def smooth_mode(args) -> int:
    """The rolling window of the shares chart, in months. Enums fall back."""
    try:
        months = int((args.get("smooth") or "").strip())
    except ValueError:
        return 1
    return months if months in buckets.SMOOTHING else 1


@bp.app_template_global()
def page_url(endpoint: str, **params) -> str:
    """A link to another page that carries the current window along.

    The window lives in the URL, so leaving the dashboard for the previsions
    page and coming back must not silently reset it to the default. The
    destination ignores the parameters it does not use, and its own "back"
    links read the same query string -- the round trip keeps the window
    with no session state. Only the window keys ride along, never the full
    query (that would drag `fragment=1` into every link).
    """
    for key in ("from", "to", "grain"):
        value = request.args.get(key)
        if value:
            params[key] = value
    return url_for(endpoint, **params)


@bp.app_template_global()
def dash_url(**params) -> str:
    """A dashboard link that carries the display options the user picked.

    Only the one whitelisted key rides along. Re-injecting `request.args` whole
    would drag `fragment=1` into every link, and the fragment and the full page
    would stop rendering identical markup.
    """
    params.setdefault("stack", stack_mode(request.args))
    if params["stack"] == DEFAULT_STACK:
        del params["stack"]  # the default never needs saying
    params.setdefault("split", split_mode(request.args))
    if params["split"] == DEFAULT_SPLIT:
        del params["split"]
    params.setdefault("scale", scale_mode(request.args))
    if params["scale"] == DEFAULT_SCALE:
        del params["scale"]
    params.setdefault("focus", focus_mode(request.args))
    if params["focus"] == DEFAULT_FOCUS:
        del params["focus"]
    params.setdefault("perf", perf_mode(request.args))
    if params["perf"] == DEFAULT_PERF:
        del params["perf"]
    # `shares` is kept even at its default value: its presence is the
    # unfolded state, which should survive a change of period.
    params.setdefault("shares", shares_mode(request.args))
    if params["shares"] is None:
        del params["shares"]
    params.setdefault("smooth", smooth_mode(request.args))
    if params["smooth"] == 1:
        del params["smooth"]
    return url_for("dashboard.dashboard", **params)


def _filtered(window, args) -> list:
    """Rows matching the table's filters, unsorted and unpaged.

    Shared with the bulk endpoint so that "everything matching the filter"
    means exactly what the screen was showing -- one implementation, no drift
    between what you see and what a bulk edit touches.
    """
    needle = (args.get("q") or "").strip().lower()
    category = args.get("category") or ""
    bucket = args.get("bucket") or ""
    direction = args.get("dir") or ""

    rows = window.transactions
    if category:
        rows = [t for t in rows if t.category == category]
    if bucket:
        rows = [t for t in rows if t.bucket == bucket]
    if direction == "out":
        rows = [t for t in rows if t.amount < 0]
    elif direction == "in":
        rows = [t for t in rows if t.amount >= 0]
    if needle:
        rows = [t for t in rows
                if needle in f"{t.label} {t.location} {t.kind} "
                             f"{t.category} {t.subcategory}".lower()]
    return rows


def _sorted(rows: list, args) -> list:
    """The table's ordering, applied server-side.

    Sorting has to happen here rather than in the browser: the table is paged,
    and a client-side sort would only reorder the 60 rows currently on screen --
    which looks right and is wrong. Shared with the export so that the file you
    download comes out in the order you were looking at.
    """
    sort = args.get("sort") or "date"
    descending = (args.get("dir_sort") or "desc") == "desc"
    return sorted(rows, key=SORT_KEYS.get(sort, SORT_KEYS["date"]),
                  reverse=descending)


@bp.app_template_filter("chf")
def _chf(value, decimals=2):
    return chf(value or 0.0, decimals)


@bp.app_template_filter("fr_date")
def _fr_date(value: dt.date):
    return value.strftime("%d.%m.%Y") if value else ""
