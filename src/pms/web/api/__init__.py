"""The JSON the React front end reads, and the page that carries it.

Every number is still computed here, by the same analysis functions the
rest of the app uses; the browser lays out and draws. One endpoint per page,
each taking the same query string as the page's URL -- the window, the
grain, the view switches -- so a URL still determines a view entirely.

The front end is built by Vite into `static/spa/` and committed: `run.bat`
serves it without Node (frontend/README.md).
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, request, send_file

from . import encode

api = Blueprint("api", __name__)

SPA = Path(__file__).resolve().parents[1] / "static" / "spa"
# Vite names every asset by its content hash: a file at a given URL never
# changes, so the phone keeps it a year and never asks again.
IMMUTABLE = "public, max-age=31536000, immutable"

# The pages the router in the browser draws. Each is served the same
# document; the address says which view.
PAGES = ("/", "/transactions", "/epargne", "/analyse", "/previsions",
         "/corrections", "/corrections/tri", "/importer", "/assistant", "/jour/<iso>",
         "/a-venir", "/impots", "/projets", "/bilan", "/caviarder", "/aide")

# Addresses of the server-rendered app, kept alive for bookmarks and the
# phone's home-screen icon.
MOVED = {"/reclasser": "/corrections", "/reclasser/tri": "/corrections/tri"}


def payload(value) -> Response:
    return jsonify(encode.jsonable(value))


def index(status: int = 200) -> Response:
    """The single page. Revalidated on every load (no-cache), so a new build
    reaches the phone at once; its assets are immutable."""
    page = SPA / "index.html"
    if not page.exists():
        abort(503, description="Le front n'est pas construit : cd frontend && npm run build")
    response = send_file(page, mimetype="text/html", max_age=0)
    response.headers["Cache-Control"] = "no-cache"
    response.status_code = status
    return response


def _spa(**_):
    return index()


for _path in PAGES:
    api.add_url_rule(_path, f"page{_path.replace('/', '_').replace('<', '').replace('>', '')}", _spa)


def _with_query(path: str) -> str:
    query = request.query_string.decode()
    return f"{path}?{query}" if query else path


@api.route("/app/", defaults={"rest": ""})
@api.route("/app/<path:rest>")
def app_prefix(rest: str):
    """Where the new interface lived while the old one was still up."""
    return redirect(_with_query(f"/{rest}"), 301)


@api.route("/reclasser")
@api.route("/reclasser/tri")
def moved():
    return redirect(_with_query(MOVED[request.path]), 301)


@api.route("/day/<iso>")
def moved_day(iso: str):
    return redirect(_with_query(f"/jour/{iso}"), 301)


@api.after_app_request
def _cache_assets(response: Response) -> Response:
    if request.path.startswith("/static/spa/assets/") and response.status_code in (200, 304):
        response.headers["Cache-Control"] = IMMUTABLE
    return response


def store():
    return current_app.extensions["pms_store"]


from . import (  # noqa: E402,F401  (routes register on import)
    analyse, assist, corrections, dashboard, fetch, imports, previsions, savings, shell, transactions,
    projects, redaction, retro, taxes, upcoming, weekly,
)
