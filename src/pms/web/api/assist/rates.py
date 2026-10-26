"""A market hypothesis in words: a sentence becomes a barème of annual
returns and, when it speaks of risk, a volatility -- previewed with the
app's own arithmetic, applied only on a click (docs/assistant.md)."""

from __future__ import annotations

import json

from flask import request

from .... import ai, assist
from .... import plans as plans_module
from ...views.previsions import _plan, months_ahead
from .. import api, payload, store
from . import _body, _config, _failed

RATES_SCHEMA = ai.strict({"type": "object", "properties": {
    "supported": {"type": "boolean"},
    "name": {"type": "string"},
    "note": {"type": "string"},
    # Whether the figures are the sentence's, or proposed by the model for a
    # sentence that names a kind of market without numbers.
    "source": {"type": "string", "enum": ["phrase", "propose"]},
    "segments": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
        "months": {"type": "integer"},
        "rate_pct": {"type": "number"},
    }}},
    "vol_pct": {"type": ["number", "null"]},
    "horizon_months": {"type": ["integer", "null"]},
}})

SYSTEM = (assist.LANG + "Tu traduis une phrase en hypothèse de marché pour une projection "
          "de patrimoine : un barème de rendements annuels, période par période à partir "
          "d'aujourd'hui (months = durée en mois, rate_pct = rendement annuel en %, négatif "
          "pour une baisse ; après la dernière période, son taux continue). vol_pct : la "
          "volatilité annuelle en %, seulement si la phrase parle de risque, de volatilité ou "
          "d'écart ; sinon null (l'app garde la sienne). horizon_months : seulement si la "
          "phrase donne une durée de projection (« sur 10 ans » = 120) ; sinon null. "
          "source = phrase si les chiffres viennent de la phrase ; si la phrase nomme une "
          "sorte de marché sans chiffres (« prudent », « un krach », « comme en 2008 »), "
          "propose des chiffres ronds, source = propose, et note dit en une phrase ce que tu "
          "as supposé. Un krach se dit en baisse sur sa durée : « −30 % sur un an » = "
          "rate_pct −30 pendant 12 mois. Rendements entre −60 et +40 % par an, durées de 1 à "
          "480 mois. Si la phrase ne décrit pas un marché (une dépense, un salaire), "
          "supported = false et note dit pourquoi. name : un nom court.")


def _clean(answer: dict) -> tuple[list[tuple[int, float]], float | None, int | None, str | None]:
    """The barème as the plan stores it, or why it is refused -- the model's
    numbers checked against the same bounds the form enforces."""
    segments = []
    for s in answer.get("segments") or []:
        months, rate = int(s.get("months") or 0), float(s.get("rate_pct") or 0)
        if not 1 <= months <= 480 or not -60 <= rate <= 40:
            return [], None, None, "Le barème proposé sort des bornes (1 à 480 mois, −60 à +40 % par an)."
        segments.append((months, round(rate / 100, 4)))
    if not segments:
        return [], None, None, "Aucune période de rendement dans la réponse."
    vol = answer.get("vol_pct")
    if vol is not None and not 0 <= float(vol) <= 100:
        return [], None, None, "La volatilité proposée sort de 0 à 100 %."
    horizon = answer.get("horizon_months")
    horizon = int(horizon) if horizon and 1 <= int(horizon) <= 480 else None
    return segments, (round(float(vol) / 100, 4) if vol is not None else None), horizon, None


@api.route("/api/ai/rates", methods=["POST"])
def ai_rates():
    data = store()
    if data.empty:
        return payload({"error": "Aucun relevé importé."}), 404
    config, refused = _config()
    if refused:
        return refused
    sentence = str(_body().get("sentence") or "").strip()[:300]
    if not sentence:
        return payload({"error": "La phrase est vide."}), 400
    plan = _plan()
    context = {"phrase": sentence,
               "bareme_actuel": [{"months": m, "rate_pct": round(r * 100, 2)} for m, r in plan.rate_segments]}
    try:
        answer = ai.ask_json(config, "rates", SYSTEM, json.dumps(context, ensure_ascii=False), RATES_SCHEMA)
    except ai.AIError as e:
        return _failed(e)
    if not answer["supported"]:
        return payload({"supported": False, "note": answer["note"] or "Cette phrase ne décrit pas un marché."})
    segments, vol, horizon, problem = _clean(answer)
    if problem:
        return payload({"supported": False, "note": problem}), 422
    # The preview runs over the horizon the sentence gave, else the page's,
    # and at least into the last period: every period is seen.
    span = max(horizon or months_ahead(request.args), sum(m for m, _ in segments[:-1]) + 12)
    return payload({
        "supported": True,
        "name": answer["name"][:60] or "Hypothèse",
        "note": answer["note"],
        "source": answer["source"],
        "segments": [{"months": m, "rate": r} for m, r in segments],
        "vol": vol,
        "horizon": horizon,
        "summary": plans_module.scenario_summary(segments, vol, horizon or 0),
        "path": plans_module.growth_path(segments, span),
        "current": plans_module.growth_path(plan.rate_segments, span),
    })
