"""C and E. The month in words: its review, and why it cost what it did."""

from __future__ import annotations


from flask import request
from werkzeug.datastructures import MultiDict

from .... import ai, analysis, assist
from .... import review as review_module
from ... import periods
from .. import api, payload, store
from . import _body, _config, _failed, _folder


# --- C and E. the month, in words ---------------------------------------------

def _month(data):
    """The one calendar month the query string names (the month in progress
    included), or None -- the same condition as the review panel."""
    low, high = data.bounds
    period = periods.resolve(request.args if request.method == "GET" else
                             MultiDict(_body()), low, high)
    start, end = period["start"], period["end"]
    month_end = analysis.bucket_bounds(start, "month")[1]
    if start.day == 1 and (end == month_end or (end == high and end < month_end)):
        return start, end
    return None


@api.route("/api/ai/review", methods=["GET", "POST"])
def ai_review():
    data = store()
    month = _month(data)
    r = review_module.month_review(data.statement, *month) if month else None
    if r is None:
        return payload({"error": "Pas de revue pour cette fenêtre."}), 404
    key = assist.review_memo_key(data.statement, r)
    summary = ai.memo_get(_folder(), key)
    again = request.method == "POST" and bool(_body().get("again"))
    if request.method == "GET" or (summary is not None and not again):
        return payload({"ai": ai.status(_folder()), "summary": summary, "moved": _moved(data, r)})
    config, refused = _config()
    if refused:
        return refused
    try:
        summary = assist.review_summary(config, data.statement, r, fresh=again)
    except ai.AIError as e:
        return _failed(e)
    ai.memo_put(_folder(), key, summary)
    return payload({"ai": ai.status(_folder()), "summary": summary, "moved": _moved(data, r)})


def _moved(data, r) -> list[dict]:
    """The categories furthest from their median this month, drawn under the
    summary: the same figures the model was given."""
    facts, _ = assist.review_facts(data.statement, r)
    return [{"category": c["categorie"], "now": c["ce_mois"], "median": c["mediane"],
             "delta": c["ecart"]} for c in facts["categories_face_a_leur_mediane"][:5]
            if abs(c["ecart"]) >= 1]


@api.route("/api/ai/why", methods=["GET", "POST"])
def ai_why():
    data = store()
    month = _month(data)
    found = assist.month_facts(data.statement, *month) if month else None
    if found is None:
        return payload({"error": "Pas assez d'historique pour comparer ce mois."}), 404
    facts, names, rows = found
    key = f"why:{month[0].isoformat()}:{assist._hash(facts)}"
    answer = ai.memo_get(_folder(), key)
    if answer is None and request.method == "POST":
        config, refused = _config()
        if refused:
            return refused
        try:
            answer = assist.explain_month(config, facts, names)
        except ai.AIError as e:
            return _failed(e)
        ai.memo_put(_folder(), key, answer)
    if answer is None:
        return payload({"ai": ai.status(_folder()), "answer": None})
    return payload({"ai": ai.status(_folder()), "answer": {
        **answer, "rows": [rows[i] for i in answer["lines"]],
        "total": facts["total"], "median": facts["mediane_mensuelle"],
        "months": [*facts["mois_precedents"],
                   {"mois": month[0].strftime("%Y-%m"), "total": facts["total"], "current": True}],
        "delta": facts["ecart"], "label": facts["mois"],
        # The categories above their median, beside the lines: a habit that
        # drifts reads here, a one-off in the lines.
        "drift": [{"category": c["categorie"], "count": c["lignes"], "delta": c["ecart"]}
                  for c in facts["categories"] if c["ecart"] > 0][:3]}})
