"""Plumbing every view shares: the blueprint, the store, the view-mode
switches carried in the URL, and the table's filter and sort.

Nothing here knows about a particular page. The switches are validated here
and never echoed raw: an unknown value falls back to the default.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

from flask import Blueprint, current_app

from ... import benchmarks as benchmarks_module
from ... import categories as categories_module
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
    # "Zoom" (the y axis fitted to the values) is gone: the Swissquote line
    # dips near zero, so the fitted axis was the zero-anchored one -- a
    # button that changed nothing.
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


# Over the period, or per year. Per year only from a year on: under it, an
# annual rate is an extrapolation (one good month printed as over +100 %/an), so
# the period figure stays on screen and the panel says why.
RATES = {
    "period": {"label": "Période", "aria": "rendement sur la période affichée"},
    "annual": {"label": "Par an", "aria": "rendement annualisé, à partir d'un an d'historique"},
}


DEFAULT_RATE = "period"


# Which account the savings section focuses on -- the boxes are the
# selector. Everything else (curve, performance) adapts to the pick.
FOCUSES = ["total", "swissquote", "ibkr", "finpension", "crypto", "titres"]


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


def rate_mode(args) -> str:
    """Whether returns read over the period or per year -- validated."""
    mode = (args.get("rate") or "").strip()
    return mode if mode in RATES else DEFAULT_RATE


def bench_mode(args) -> tuple[str, ...]:
    """Which reference indices the savings compare with, in catalogue order.

    `?bench=sp500,smi` (or the key repeated, as checkboxes send it), `none`
    for none at all; absent, the default pair. Unknown keys are dropped,
    never echoed.
    """
    raw = []
    for value in args.getlist("bench") if hasattr(args, "getlist") else [args.get("bench")]:
        raw += [k.strip() for k in (value or "").split(",") if k.strip()]
    if not raw:
        return benchmarks_module.DEFAULT
    picked = {k for k in raw if k in benchmarks_module.KEYS}
    return tuple(k for k in benchmarks_module.KEYS if k in picked)


def titres_mode(args) -> bool:
    """Whether the savings count the unlisted shares (`holdings.py`):
    yes unless `?titres=0`."""
    return (args.get("titres") or "").strip() != "0"


def focus_mode(args) -> str:
    """Which account the savings section zooms into -- validated."""
    mode = (args.get("focus") or "").strip()
    return mode if mode in FOCUSES else DEFAULT_FOCUS


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
    low, high = _amount(args.get("amin")), _amount(args.get("amax"))
    account = args.get("acct")

    rows = window.transactions
    if account:
        # "principal" is the primary account, whose name is "".
        wanted = "" if account == PRIMARY else account
        rows = [t for t in rows if t.account == wanted]
    if low is not None:
        rows = [t for t in rows if abs(t.amount_chf) >= low]
    if high is not None:
        rows = [t for t in rows if abs(t.amount_chf) <= high]
    if args.get("fix") == "1":
        rows = [t for t in rows if t.overridden]
    if args.get("todo") == "1":
        rows = [t for t in rows if t.category in TODO]
    if category:
        rows = [t for t in rows if t.category == category]
    if bucket:
        rows = [t for t in rows if t.bucket == bucket]
    if direction == "out":
        rows = [t for t in rows if t.amount < 0]
    elif direction == "in":
        rows = [t for t in rows if t.amount >= 0]
    if needle:
        words = _fold(needle).split()
        rows = [t for t in rows if all(_hit(t, w) for w in words)]
    return rows


# The primary account in the URL (its own name is ""): `?acct=principal`.
PRIMARY = "principal"


def account_options(transactions, sources: list[dict]) -> list[dict]:
    """The accounts the rows come from, named by their bank: the primary
    one by the bank of its latest import (Swissquote, UBS, a camt.053
    bank), a secondary one by the bank that feeds it (Revolut) or its own
    name. Ordered as the ledger meets them, the primary first."""
    from ... import banks
    present = sorted({t.account for t in transactions}, key=lambda a: (a != "", a))
    by_account = {b.account: b.name for p, b in banks.BANKS.items() if b.account}
    out = []
    for account in present:
        if account:
            label = by_account.get(account, account)
        else:
            feeding = [s for s in sources if not s.get("account")]
            latest = max(feeding, key=lambda s: s.get("ingested_at") or "", default={})
            label = latest.get("bank") or ""
            if not label:
                # By its file's extension, as `news.late` reads it: an import
                # naming no file is the account's first bank's.
                suffix = Path(latest.get("file") or "").suffix.lower() or ".pdf"
                label = next((b.name for p, b in banks.BANKS.items()
                              if not b.account and Path(p).suffix.lower() == suffix), "Compte principal")
        out.append({"id": account or PRIMARY, "label": label})
    return out


# What is left to classify: no rule knows the payee, or the line names none.
TODO = (categories_module.UNCATEGORISED, categories_module.TWINT_UNKNOWN)


def _amount(raw) -> float | None:
    """An amount bound of the table's filter, in francs, either sign read as
    its size; anything unreadable is no bound rather than an error."""
    try:
        value = abs(float(str(raw).replace("'", "").replace("’", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return value if value == value and value != float("inf") else None


def _hit(t, word: str) -> bool:
    """A bare whole number is a figure, not a fragment: "20" means twenty
    francs, or the 20th, or a month, or a year -- matched as text it would
    find every row dated 2025 or 2026 and narrow nothing."""
    if word.isdigit():
        n = int(word)
        return (int(abs(t.amount)) == n
                or n in (t.date.day, t.date.month, t.date.year))
    return word in _haystack(t)


def _fold(text: str) -> str:
    """Lower case, accents dropped: "regie" finds "Régie", "zurich" "Zürich"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _haystack(t) -> str:
    """Everything a row can be searched by. Each word of the query must occur
    somewhere in it, in any order: "coop carouge" finds one shop of the chain,
    "twint 20.00" the 20-franc Twint payments. The amount is there as printed
    (1234.50 and 1'234.50) and the date as shown (14.10.2026)."""
    return _fold(" ".join([
        t.label, t.merchant, t.location, t.kind, " ".join(t.detail),
        t.category, t.subcategory, t.bucket, t.account,
        f"{abs(t.amount):.2f}", chf(abs(t.amount), 2), t.currency,
        t.date.strftime("%d.%m.%Y"),
    ]))


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

