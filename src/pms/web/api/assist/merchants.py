"""B. Categories proposed for the payees no rule recognises."""

from __future__ import annotations



from .... import ai, analysis, assist
from ...palette import colour_map
from ...views.corrections import _target_choices
from .. import api, payload, store
from . import _body, _config, _failed, _folder


# --- B. payees no rule recognises ---------------------------------------------

def _merchants_state(data) -> dict:
    payees, private = assist.uncategorised_payees(data.statement)
    # The category's hue, as the dashboard gives it over the whole ledger.
    slots, _ = colour_map(analysis.by_category(analysis.spending(data.statement)))
    for p in payees:
        p["suggestion"] = ai.memo_get(_folder(), "merchant:" + p["label"])
        if p["suggestion"] and p["suggestion"].get("category"):
            p["suggestion"] = {**p["suggestion"], "slot": slots.get(p["suggestion"]["category"])}
    return {"ai": ai.status(_folder()), "payees": payees, "private": private,
            "pending": sum(1 for p in payees if p["suggestion"] is None)}


@api.route("/api/ai/merchants")
def ai_merchants():
    return payload(_merchants_state(store()))


@api.route("/api/ai/merchants", methods=["POST"])
def ai_merchants_suggest():
    config, refused = _config()
    if refused:
        return refused
    data = store()
    payees, _ = assist.uncategorised_payees(data.statement)
    # `retry`: labels asked before without an answer -- asked again, past
    # the caches, now that a search may find what the name alone did not.
    retry = set(_body().get("retry") or [])
    # The ones asked again first: only the head of a batch is searched.
    todo = sorted((p for p in payees
                   if ai.memo_get(_folder(), "merchant:" + p["label"]) is None or p["label"] in retry),
                  key=lambda p: p["label"] not in retry)
    if todo:
        try:
            found = assist.suggest_merchants(config, todo, _target_choices(data.statement),
                                             fresh=bool(retry))
        except ai.AIError as e:
            return _failed(e)
        for p in todo:
            ai.memo_put(_folder(), "merchant:" + p["label"],
                        found.get(p["label"]) or {"category": None, "subcategory": "",
                                                  "confidence": "basse", "why": ""})
    return payload(_merchants_state(data))
