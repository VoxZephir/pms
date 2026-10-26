"""The assisted features: a model reads what the app computed.

Every route here answers the same way when no model is configured -- 503
with the reason -- so a page shows its button greyed with the sentence that
says how to switch it on, instead of failing. A GET returns what was already
asked (kept in `data/ai_cache.json`); only a POST calls the model, so opening
a page never costs anything.

One module per feature (`settings`, `merchants`, `month`, `savings`,
`scenario`); the helpers every route shares are here.
"""

from __future__ import annotations

from flask import request

from .... import ai
from .. import api, payload, store


def _folder():
    return store().path.parent


def _config():
    """The configured model, or the (payload, status) to answer with."""
    try:
        config = ai.load(_folder())
    except ai.AIError as e:
        return None, (payload({"error": str(e), "ai": ai.status(_folder())}), 503)
    if config is None:
        return None, (payload({"error": ai.status(_folder())["reason"],
                               "ai": ai.status(_folder())}), 503)
    return config, None


def _failed(e: ai.AIError):
    return payload({"error": str(e)}), 502


def _body() -> dict:
    return request.get_json(silent=True) or {}


@api.route("/api/ai")
def ai_status():
    return payload(ai.status(_folder()))


from . import merchants, month, rates, savings, scenario, settings  # noqa: E402,F401  (routes register on import)
