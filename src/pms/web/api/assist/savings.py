"""The savings in words, and a question in French (A)."""

from __future__ import annotations

import datetime as dt

from flask import request

from .... import ai, assist
from ... import periods
from ...views.previsions import _plan
from .. import api, payload, store
from ..savings import pocket_summaries
from . import _body, _config, _failed, _folder


# --- the savings, in words -----------------------------------------------------

@api.route("/api/ai/savings", methods=["GET", "POST"])
def ai_savings():
    """What moved the savings over the window (and the pocket chosen), in
    two or three sentences, from the figures the savings page shows. GET
    reads the answer kept for these figures; POST asks (`again` past it)."""
    data = store()
    if data.empty:
        return payload({"error": "Aucun relevé importé."}), 404
    period = periods.resolve(request.args, *data.bounds)
    focus = request.args.get("focus") or "total"
    summaries = pocket_summaries(data, period["start"], period["end"], focus)
    if not summaries:
        return payload({"error": "Aucune donnée d'épargne."}), 404
    facts, _ = assist.savings_facts(summaries, period["start"], period["end"])
    key = f"savings:{assist._hash(facts)}"
    answer = ai.memo_get(_folder(), key)
    again = bool(_body().get("again")) if request.method == "POST" else False
    if (answer is None or again) and request.method == "POST":
        config, refused = _config()
        if refused:
            return refused
        try:
            answer = assist.explain_savings(config, facts, fresh=again)
        except ai.AIError as e:
            return _failed(e)
        ai.memo_put(_folder(), key, answer)
    return payload({"ai": ai.status(_folder()), "answer": answer})


# --- A. a question -------------------------------------------------------------

@api.route("/api/ai/ask", methods=["POST"])
def ai_ask():
    config, refused = _config()
    if refused:
        return refused
    body = _body()
    question = str(body.get("question") or "").strip()[:300]
    # The last exchanges, for a follow-up ("et l'année d'avant ?"): only
    # what the page itself showed, trimmed.
    history = [{"question": str(h.get("question") or "")[:300], "reponse": str(h.get("answer") or "")[:600]}
               for h in (body.get("history") or [])[-2:] if isinstance(h, dict)]
    if not question:
        return payload({"error": "La question est vide."}), 400
    data = store()
    if data.empty:
        return payload({"error": "Aucun relevé importé."}), 404
    low, high = data.bounds
    categories = sorted({t.category for t in data.statement.transactions if t.category},
                        key=str.casefold)
    try:
        query = assist.plan_question(config, question, dt.date.today(), low, high,
                                     categories, history)
        if not query["supported"]:
            return payload({"answer": query["note"] or "L'app ne sait pas répondre à cette question.",
                            "supported": False, "follow_ups": []})
        facts, names, view, table = assist.run_query(
            data.statement, query, _plan(),
            savings=lambda start, end: pocket_summaries(data, start, end))
        answer = assist.answer_question(config, question, facts, names, query["focus"])
    except ai.AIError as e:
        return _failed(e)
    window = (f"{query['months']} prochains mois" if query["focus"] == "prevision"
              else f"au {query['to'].strftime('%d.%m.%Y')}" if query["focus"] == "solde"
              else f"{query['from'].strftime('%d.%m.%Y')} → {query['to'].strftime('%d.%m.%Y')}")
    # The title names the subject (a category, a search, the kind of
    # question); the scope says only when.
    scope = window
    subject = query["category"] or (f"« {query['search']} »" if query["search"] else None) \
        or assist.FOCUS_TITLE[query["focus"]]
    return payload({**answer, "supported": True, "view": view, "table": table,
                    "title": subject,
                    "sources": assist.FOCUS_SOURCES.get(query["focus"],
                                                        ["relevé", "même durée juste avant", "un an avant"]),
                    "focus": query["focus"], "measure_label": assist.FOCUS[query["focus"]],
                    "scope": scope})
