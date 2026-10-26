"""The savings in words: what moved them over a window -- the money put in
against what the markets did -- from the pocket table's own figures."""

from __future__ import annotations

import datetime as dt

from .. import ai
from .common import LANG, NUMBERS, _ask_checked, _r

# --- the savings, in words ----------------------------------------------------------

def savings_facts(summaries: list[dict], start: dt.date, end: dt.date) -> tuple[dict, dict]:
    """The pockets over a window, as the savings page computes them
    (`SavingsBook.summary`, passed in: this module does not reach into the
    web layer): what each held, what was put in, what the markets did. And
    the table printed under an answer."""
    def pct(rate):
        return round(rate * 100, 1) if rate is not None else None

    poches = [{"poche": s["name"], "valeur_debut": _r(s["start_value"]), "valeur_fin": _r(s["value"]),
               "verse": _r(s["put_in"]), "gain_marche": _r(s["gain"]),
               "rendement_twr_pct": pct(s["twr"]), "rendement_mwr_pct": pct(s["mwr"])}
              for s in summaries]
    facts = {"du": start.isoformat(), "au": end.isoformat(), "poches": poches,
             "note": "verse = argent entré dans la poche (versements moins retraits) ; "
                     "gain_marche = ce que la poche a gagné ou perdu en plus des versements ; "
                     "le compte Swissquote est du cash, sans rendement"}
    table = {"columns": ["", "Valeur", "Versé", "Gain", "TWR %"],
             "rows": [[p["poche"], p["valeur_fin"], p["verse"], p["gain_marche"],
                       p["rendement_twr_pct"] if p["rendement_twr_pct"] is not None else "—"]
                      for p in poches]}
    return facts, table


SAVINGS_SCHEMA = ai.strict({"type": "object", "properties": {"text": {"type": "string"}}})


def explain_savings(config: ai.Config, facts: dict, fresh: bool = False) -> dict:
    """Two or three sentences on what moved the savings over the window:
    the money put in, against what the markets did, and which pocket carried
    it. No advice, no forecast."""
    system = (LANG + NUMBERS + " Tu expliques en deux ou trois phrases ce qui a fait bouger "
              "l'épargne sur la période : la part des versements (verse) et celle des marchés "
              "(gain_marche), et la poche qui a porté le résultat. Le rendement TWR mesure les "
              "placements, versements retirés. Aucun conseil d'investissement, aucune prévision.")
    answer = _ask_checked(config, "savings", system, facts, facts, SAVINGS_SCHEMA,
                          lambda a: [a["text"]], fresh=fresh)
    return {"text": answer["text"].strip()}
