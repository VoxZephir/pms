"""C and E. The month in words: its review in three sentences, and why it
cost more (or less) than usual."""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from .. import ai, analysis, plans, review
from ..models import Statement, Transaction
from .common import LANG, NUMBERS, _Names, _ask_checked, _hash, _pct, _r, _shift_year, _spend, period_facts

# --- C. the month's review in words ----------------------------------------------

REVIEW_SCHEMA = ai.strict({"type": "object", "properties": {
    "headline": {"type": "string"},
    "points": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
}})


def review_facts(statement: Statement, r: dict) -> tuple[dict, _Names]:
    names = _Names(statement)
    history = review._whole_months(statement, r["first"])[-12:]
    month = period_facts(statement, r["first"], r["last"], names)
    usual_income = statistics.median(m["income"] for m in history) if history else 0.0
    usual_net = statistics.median(m["income"] - m["spending"] for m in history) if history else 0.0
    ytd_start = r["first"].replace(month=1, day=1)
    ytd = sum(abs(t.amount_chf) for t in _spend(statement, ytd_start, r["last"]))
    ytd_before = (sum(abs(t.amount_chf) for t in _spend(statement, _shift_year(ytd_start),
                                                        _shift_year(r["last"])))
                  if _shift_year(ytd_start) >= statement.period_start else None)
    by_cat = {c["categorie"]: c["montant"] for c in month["categories"]}
    medians = []
    for c in {c for m in history for c in m.get("categories", {})} | set(by_cat):
        median = statistics.median(m.get("categories", {}).get(c, 0.0) for m in history)
        now = by_cat.get(c, 0.0)
        medians.append({"categorie": c, "ce_mois": _r(now), "mediane": _r(median),
                        "ecart": _r(now - median), "ecart_pct": _pct(now, median)})
    medians.sort(key=lambda m: -abs(m["ecart"]))
    facts = {
        "mois": r["label"], "en_cours": r["partial"],
        "au": r["last"].isoformat() if r["partial"] else None,
        "depense": _r(r["spent"]), "mediane_mensuelle": _r(r["median"]),
        "ecart_a_la_mediane": _r(r["spent"] - r["median"]),
        "ecart_pct": round(r["delta_pct"]) if r["delta_pct"] is not None else None,
        "mois_compares": r["history_months"],
        "revenus": month.get("revenus"), "revenus_habituels": _r(usual_income),
        "net": month.get("net"), "net_habituel": _r(usual_net),
        "taux_epargne_pct": month.get("taux_epargne_pct"),
        "depuis_janvier": _r(ytd),
        "depuis_janvier_an_passe": _r(ytd_before) if ytd_before is not None else None,
        "depuis_janvier_ecart_pct": _pct(ytd, ytd_before) if ytd_before else None,
        "categories_face_a_leur_mediane": medians[:6],
        "plus_grosses_lignes": month["plus_grosses_lignes"],
        "beneficiaires": month["beneficiaires"][:4],
        "prix_changes": [{"nom": names.of(p["label"]), "avant": _r(p["before"]),
                          "maintenant": _r(p["now"]), "pct": round(p["pct"], 1)}
                         for p in r["prices"]],
        "nouveaux_beneficiaires": [{"nom": names.of(p["label"]), "montant": _r(p["amount"])}
                                   for p in r["new_payees"]],
        "debits_doubles": [{"nom": names.of(d["label"]), "montant": _r(d["amount"])}
                           for d in r["duplicates"]],
    }
    return facts, names


def review_summary(config: ai.Config, statement: Statement, r: dict, fresh: bool = False) -> dict:
    facts, names = review_facts(statement, r)
    system = (LANG + NUMBERS + " Tu fais le bilan d'un mois pour son titulaire. "
              "« headline » : une phrase qui dit l'essentiel (dépensé, face à l'habitude, et "
              "ce qu'il reste à la fin du mois si les revenus sont connus). « points » : trois à "
              "cinq constats courts et concrets, du plus important au moins important : quelles "
              "catégories ont bougé et de combien, quelle ligne pèse, comment se situe l'année "
              "depuis janvier, l'épargne du mois face à l'habitude, et ce qui mérite un coup "
              "d'œil (un prix qui a changé, un débit doublé, un nouveau bénéficiaire). Pas de "
              "généralité ni de conseil vague : chaque point cite au moins un chiffre. Un mois "
              "en cours n'est pas fini : ne conclus pas sur son total ni sur son épargne.")
    answer = _ask_checked(config, "review", system, facts, facts, REVIEW_SCHEMA,
                          lambda a: [a["headline"], *a["points"]], fresh=fresh)
    return {"headline": names.restore(answer["headline"].strip()),
            "points": [names.restore(p.strip()) for p in answer["points"] if p.strip()]}


def review_memo_key(statement: Statement, r: dict) -> str:
    facts, _ = review_facts(statement, r)
    return f"review2:{r['first'].isoformat()}:{_hash(facts)}"


# --- E. why this month -----------------------------------------------------------

WHY_LINES = 8
WHY_HISTORY = 12
WHY_SCHEMA = ai.strict({"type": "object", "properties": {
    "text": {"type": "string"},
    "lines": {"type": "array", "items": {"type": "integer"}, "maxItems": 4},
    "nature": {"type": "string", "enum": ["ponctuel", "récurrent", "mixte", "ordinaire"]},
}})


def month_facts(statement: Statement, first: dt.date, last: dt.date
                ) -> tuple[dict, _Names, list[Transaction]] | None:
    """The month against the median of the whole months before it (up to a
    year): by category, and its largest lines. None without three months
    of history, like the review."""
    history = review._whole_months(statement, first)[-WHY_HISTORY:]
    if len(history) < review.HISTORY_MIN_MONTHS:
        return None
    spend = [t for t in analysis.spending(statement) if first <= t.date <= last]
    names = _Names(statement)
    by_cat: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for t in spend:
        by_cat[t.category] += abs(t.amount_chf)
        count[t.category] += 1
    cats = set(by_cat) | {c for m in history for c in m.get("categories", {})}
    rows = []
    for c in cats:
        past = [abs(m.get("categories", {}).get(c, 0.0)) for m in history]
        median = statistics.median(past)
        rows.append({"categorie": c, "ce_mois": _r(by_cat.get(c, 0.0)), "lignes": count.get(c, 0),
                     "mediane": _r(median), "ecart": _r(by_cat.get(c, 0.0) - median)})
    rows.sort(key=lambda row: -abs(row["ecart"]))
    top = sorted(spend, key=lambda t: t.amount_chf)[:WHY_LINES]
    total = sum(abs(t.amount_chf) for t in spend)
    median_total = statistics.median(m["spending"] for m in history)
    facts = {
        "mois": plans.month_label(first.strftime("%Y-%m")).capitalize(),
        "en_cours": last < analysis.bucket_bounds(first, "month")[1],
        "total": _r(total), "mediane_mensuelle": _r(median_total),
        "ecart": _r(total - median_total), "mois_compares": len(history),
        "categories": rows[:6],
        "mois_precedents": [{"mois": m["start"].strftime("%Y-%m"), "total": _r(m["spending"])}
                            for m in history],
        "lignes": [{"id": i, "date": t.date.isoformat(), "nom": names.label(t),
                    "categorie": t.category, "montant": _r(abs(t.amount_chf))}
                   for i, t in enumerate(top)],
    }
    return facts, names, top


def explain_month(config: ai.Config, facts: dict, names: _Names) -> dict:
    system = (LANG + NUMBERS + " Tu expliques en deux ou trois phrases pourquoi ce mois "
              "a coûté plus (ou moins) que d'habitude, à partir des écarts par catégorie et "
              "des plus grosses lignes. Dis si l'écart tient à quelques lignes ponctuelles "
              "(un voyage, une facture annuelle) ou à une habitude qui dérive. « lines » : "
              "les id des lignes qui portent l'écart (quatre au plus). « nature » : ponctuel, "
              "récurrent, mixte, ou ordinaire si le mois est dans sa norme.")
    answer = _ask_checked(config, "why", system, facts, facts, WHY_SCHEMA, lambda a: [a["text"]])
    ids = [i for i in answer["lines"] if 0 <= i < len(facts["lignes"])]
    return {"text": names.restore(answer["text"].strip()),
            "lines": list(dict.fromkeys(ids)), "nature": answer["nature"]}
