"""The transactions table, as a page and as a file."""

from __future__ import annotations

from flask import Response, abort, redirect, render_template, request, url_for

from ... import export as export_module
from .. import periods
from .common import PAGE_SIZE, _filtered, _sorted, bp, page_size, store


def _transactions(window, period, args, default_size: int = PAGE_SIZE) -> dict:
    """Filtered, sorted and paged rows plus everything the table needs.

    Shared by the dashboard's first paint and the /transactions fragment, so the
    two render identical markup and the filters survive a page reload.
    """
    needle = (args.get("q") or "").strip().lower()
    category = args.get("category") or ""
    bucket = args.get("bucket") or ""
    direction = args.get("dir") or ""
    sort = args.get("sort") or "date"
    descending = (args.get("dir_sort") or "desc") == "desc"
    rows = _sorted(_filtered(window, args), args)
    size = page_size(args, default_size)
    # Said in the links only when it differs from the Transactions page's
    # own default: the dashboard's panel pages on at 20 rows, not at 60.
    per = size if size != PAGE_SIZE else None

    try:
        page = max(int(args.get("page", 1) or 1), 1)
    except ValueError:
        page = 1
    total = len(rows)
    pages = max(-(-total // size), 1)
    page = min(page, pages)

    # The active filters as removable chips: each one links back to the same
    # window without that parameter, so a filter comes off with one click --
    # and the whole row with "effacer les filtres". The same window the rest
    # of the panel uses, so the chips and the count can never disagree.
    base = {"from": period["start"].isoformat(), "to": period["end"].isoformat(),
            "q": (args.get("q") or "").strip(),
            "category": category, "bucket": bucket, "dir": direction,
            "per": per}
    chip_defs = [("Recherche", base["q"], "q"), ("Catégorie", category, "category"),
                 ("Besoin / envie", bucket, "bucket"),
                 ("Sens", {"out": "Sorties", "in": "Entrées"}.get(direction, ""),
                  "dir")]
    filter_chips = [
        {"label": label, "value": value,
         "href": url_for("dashboard.transactions",
                         **{k: v for k, v in base.items() if k != drop})}
        for label, value, drop in chip_defs if value]
    clear_filters = (url_for("dashboard.transactions",
                             **{"from": base["from"], "to": base["to"],
                                "per": per})
                     if filter_chips else None)

    return {
        "period": period,
        "rows": rows[(page - 1) * size: page * size],
        "total": total, "page": page, "pages": pages,
        "page_size": size,
        "filter_chips": filter_chips,
        "clear_filters": clear_filters,
        "debit_total": sum(abs(t.amount_chf) for t in rows if t.amount_chf < 0),
        # Deliberately NOT "categories": _context() spreads this dict over its
        # own, and "categories" there is the rich by_category() list the charts
        # and the drop palette read. Colliding on the name silently replaced it
        # with plain strings and emptied every category drop zone.
        "filter_categories": sorted({t.category for t in window.transactions}),
        "query": {"q": needle, "category": category,
                  "bucket": bucket, "dir": direction, "per": per,
                  "sort": sort, "dir_sort": "desc" if descending else "asc"},
        "columns": [
            {"key": "date", "label": "Date", "numeric": False},
            {"key": "label", "label": "Bénéficiaire", "numeric": False},
            {"key": "category", "label": "Catégorie", "numeric": False},
            {"key": "amount", "label": "Montant", "numeric": True},
            {"key": "chf", "label": "En CHF", "numeric": True},
        ],
    }


@bp.route("/transactions")
def transactions():
    """The transaction panel on its own, for in-place filtering and paging.

    Without JavaScript this is a normal page: the filter form submits here and
    the browser lands on a standalone list scoped to the same window.
    """
    data = store()
    low, high = data.bounds
    period = periods.resolve(request.args, low, high)
    window = data.window(period["start"], period["end"])

    # A shared URL may carry ?page=99 for a filter that no longer matches it,
    # or a hand-edited ?page=0 / ?page=abc. Rendering the clamped page would
    # leave the address bar lying; send the browser to the same query with
    # page=1 (the fragment flag rides along, or the in-place swap would
    # replace the panel with a full page).
    raw_page = request.args.get("page")
    if raw_page is not None:
        try:
            raw_num = int(raw_page or 1)
        except ValueError:
            raw_num = 0
        pages = max(-(-len(_sorted(_filtered(window, request.args),
                                   request.args))
                     // page_size(request.args)), 1)
        if raw_num != min(max(raw_num, 1), pages):
            params = {k: v for k, v in request.args.items() if k != "page"}
            params["page"] = "1"
            if request.args.get("fragment"):
                params["fragment"] = "1"
            return redirect(url_for("dashboard.transactions", **params))

    context = _transactions(window, period, request.args)

    if request.args.get("fragment"):
        return render_template("partials/transactions.html.j2", **context)
    return render_template("transactions.html.j2", window=window, **context)


@bp.route("/export.<fmt>")
def export(fmt: str):
    """Download the current view -- window and filters included.

    It goes through `_filtered` and `_sorted`, the same two functions the table
    itself uses, so the file holds exactly the rows that were on screen, in the
    order they were in, and not just the page you happened to be looking at.
    """
    if fmt not in ("csv", "xlsx"):
        abort(404)

    data = store()
    low, high = data.bounds
    period = periods.resolve(request.args, low, high)
    window = data.window(period["start"], period["end"])
    rows = _sorted(_filtered(window, request.args), request.args)

    if fmt == "csv":
        payload = export_module.to_csv(rows)
        mime = "text/csv"  # Flask appends the charset; spelling it out doubles it
    else:
        payload = export_module.to_xlsx(
            rows, export_module.sheet_name(period["start"], period["end"]))
        mime = ("application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet")

    name = export_module.filename(period["start"], period["end"], fmt)
    return Response(payload, mimetype=mime, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Content-Length": str(len(payload)),
    })
