"""Projects (`/projets`): transactions gathered under a name, at their net
cost, and the stays abroad proposed as projects (`projects.py`). Every write
answers with the undo that puts things back."""

from __future__ import annotations

import datetime as dt

from flask import request

from ... import analysis
from ... import projects as projects_module
from ...overrides import key_of
from ..palette import colour_map
from . import api, payload, store


def _day(raw) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(raw or ""))
    except ValueError:
        return None


def projects_path():
    return store().path.with_name("projects.json")


def projects_data(args) -> dict:
    data = store()
    if data.empty:
        return {"empty": True}
    statement = data.statement
    book = projects_module.Projects.load(projects_path())
    by_key = {key_of(t): t for t in statement.transactions}
    # The hues go to the categories the projects spend on, not the ledger's.
    gathered = [by_key[k] for p in book.items for k in p["keys"] if k in by_key and by_key[k].amount_chf < 0]
    slots, legend = colour_map(analysis.by_category(gathered or analysis.spending(statement)))
    rows = [projects_module.summary(p, by_key, slots) for p in book.items]
    rows.sort(key=lambda r: (r["start"] is None, r["start"]), reverse=True)
    taken = {k for p in book.items for k in p["keys"]}
    out = {"projects": rows, "legend": legend,
           "suggestions": projects_module.suggestions(statement, taken, set(book.dismissed), slots)}
    chosen = book.get(str(args.get("p") or ""))
    if chosen:
        out["detail"] = {
            **projects_module.summary(chosen, by_key, slots),
            "rows": sorted((projects_module._row(by_key[k], slots) for k in chosen["keys"] if k in by_key),
                           key=lambda r: r["date"]),
            "candidates": projects_module.candidates(statement, chosen, slots),
        }
    return out


@api.route("/api/projets")
def projects_page():
    return payload(projects_data(request.args))


@api.route("/api/projets", methods=["POST"])
def projects_edit():
    """create (name, keys), rename (id, name), add / remove (id, keys),
    delete (id), restore (project): each answers with its undo."""
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    book = projects_module.Projects.load(projects_path())
    keys = [str(k) for k in body.get("keys") or []]
    try:
        if action == "create":
            project = book.create(str(body.get("name") or ""), keys, str(body.get("kind") or "projet"),
                                  _day(body.get("start")), _day(body.get("end")))
            undo = {"action": "delete", "id": project["id"]}
        elif action in ("dismiss", "undismiss"):
            sid = str(body.get("id") or "")
            if not sid:
                raise ValueError("Proposition inconnue.")
            if action == "dismiss":
                book.dismissed = [*book.dismissed, sid]
            else:
                book.dismissed = [d for d in book.dismissed if d != sid]
            book.save()
            return payload({"ok": True, "id": sid,
                            "undo": {"action": "undismiss" if action == "dismiss" else "dismiss", "id": sid}})
        elif action == "restore":
            project = dict(body.get("project") or {})
            if not project.get("id") or not project.get("name"):
                raise ValueError("Projet incomplet.")
            book.restore(project)
            undo = {"action": "delete", "id": project["id"]}
        else:
            project = book.get(str(body.get("id") or ""))
            if project is None:
                return payload({"error": "Projet introuvable."}), 404
            before = {**project, "keys": list(project["keys"])}
            if action == "delete":
                book.delete(project["id"])
            elif action == "rename":
                name = str(body.get("name") or "").strip()[:80]
                if not name:
                    raise ValueError("Un projet a besoin d'un nom.")
                project["name"] = name
            elif action == "add":
                project["keys"] = list(dict.fromkeys([*project["keys"], *keys]))
            elif action == "remove":
                project["keys"] = [k for k in project["keys"] if k not in set(keys)]
            else:
                raise ValueError("Action inconnue.")
            undo = {"action": "restore", "project": before}
    except ValueError as error:
        return payload({"error": str(error)}), 400
    book.save()
    return payload({"ok": True, "id": project["id"], "undo": undo})


@api.route("/api/projets/liste")
def projects_for_movement():
    """The project names, and which hold the movement `key` -- for the
    transaction sheet, without the page's summaries and suggestions."""
    key = str(request.args.get("key") or "")
    book = projects_module.Projects.load(projects_path())
    return payload({"projects": [{"id": p["id"], "name": p["name"], "member": key in p["keys"]}
                                 for p in reversed(book.items)]})
