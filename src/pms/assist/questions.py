"""A. A question in French becomes a query the app runs (`run_query`),
then a sentence about its result: spending, balances, the forecast, the
investments."""

from __future__ import annotations

import datetime as dt
import json
import math
import statistics

from .. import ai, analysis, plans
from ..models import Statement
from .common import LANG, NUMBERS, TOP, _Names, _ask_checked, _fr, _matches, _pct, _r, _shift_year, _spend, period_facts
from .savings import savings_facts

# --- A. a question in French ------------------------------------------------------

# The answer card's title: what the question was about.
FOCUS_TITLE = {
    "total": "Dépenses", "categories": "Par catégorie", "beneficiaires": "Bénéficiaires",
    "grosses_lignes": "Plus grosses dépenses", "par_mois": "Mois par mois",
    "epargne": "Épargne", "jours": "Par jour de la semaine", "abonnements": "Abonnements",
    "comparaison": "Comparaison", "solde": "Solde", "prevision": "Prévision de cash",
    "placements": "Placements",
}
# Where the answer's numbers come from, as the card says under it.
FOCUS_SOURCES = {
    "prevision": ["projection des Prévisions", "plan déclaré", "médianes de l'historique"],
    "solde": ["soldes imprimés par la banque"],
    "abonnements": ["relevé · bénéficiaires payés au moins six mois à montant stable"],
    "epargne": ["relevé · revenus et dépenses par mois"],
    "comparaison": ["relevé · les deux périodes"],
    "placements": ["Épargne · valeurs et versements de chaque poche"],
}

FOCUS = {
    "total": "combien, au total, et face aux périodes comparables",
    "categories": "où va l'argent, par catégorie",
    "beneficiaires": "chez qui (commerces, bénéficiaires)",
    "grosses_lignes": "les plus grosses dépenses",
    "par_mois": "l'évolution mois par mois",
    "epargne": "revenus, épargne, ce qu'il reste",
    "jours": "la répartition par jour de la semaine",
    "abonnements": "les dépenses récurrentes, abonnements",
    "comparaison": "deux périodes comparées",
    "solde": "combien il y a sur les comptes, aujourd'hui ou à une date passée",
    "prevision": "l'avenir : le cash des prochains mois selon le plan, un seuil à ne pas "
                 "franchir, le point le plus bas",
    "placements": "les placements : valeur, versements, gains et rendement d'IBKR, du 3a, "
                  "de la crypto",
}
QUESTION_SCHEMA = ai.strict({"type": "object", "properties": {
    "supported": {"type": "boolean"},
    "focus": {"type": "string", "enum": list(FOCUS)},
    "from": {"type": "string"},
    "to": {"type": "string"},
    "compare_from": {"type": ["string", "null"]},
    "compare_to": {"type": ["string", "null"]},
    "category": {"type": ["string", "null"]},
    "search": {"type": ["string", "null"]},
    "threshold": {"type": ["number", "null"]},
    "months": {"type": ["integer", "null"]},
    "note": {"type": "string"},
}})
ANSWER_SCHEMA = ai.strict({"type": "object", "properties": {
    "answer": {"type": "string"},
    "follow_ups": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
}})


def _day(value, low: dt.date, high: dt.date) -> dt.date | None:
    try:
        day = dt.date.fromisoformat(value) if value else None
    except ValueError:
        raise ai.AIError("Le modèle a donné une période illisible.") from None
    return min(max(day, low), high) if day else None


def plan_question(config: ai.Config, question: str, today: dt.date,
                  low: dt.date, high: dt.date, categories: list[str],
                  history: list[dict] | None = None) -> dict:
    """The question as a query the app knows how to run. The model chooses;
    the app validates every field and computes. `history` is the last
    questions and answers, so "et l'année d'avant ?" means something."""
    system = (LANG + "Tu traduis une question sur un relevé bancaire en requête. "
              f"focus, ce que la question veut savoir : {json.dumps(FOCUS, ensure_ascii=False)}. "
              "from et to : dates ISO (AAAA-MM-JJ) de la fenêtre ; sans période dite, les "
              "douze derniers mois du relevé ; « cette année » = depuis le 1er janvier. "
              "compare_from et compare_to : une deuxième fenêtre seulement si la question "
              "compare deux périodes précises, sinon null. category : une des catégories "
              "fournies (le mot le plus proche : « restos » = Restaurants & bars), ou null. "
              "search : un nom de commerce ou d'enseigne à chercher, ou null. Pour une question "
              "sur l'avenir (focus prevision) : threshold = le seuil de cash cité en CHF (15k = "
              "15000) ou null, months = l'horizon en mois (12 par défaut, 60 au plus) ; from et "
              "to restent la fin du relevé. Pour le solde (focus solde), to = la date voulue. "
              "Une question de "
              "suivi reprend la période et la catégorie de l'échange précédent sauf si elle les "
              "change. Si la question ne porte pas sur ces dépenses et revenus, supported = "
              "false et note dit en une phrase ce que l'app ne sait pas dire.")
    user = json.dumps({"question": question, "aujourdhui": today.isoformat(),
                       "releve_du": low.isoformat(), "releve_au": high.isoformat(),
                       "categories": categories, "echanges_precedents": history or []},
                      ensure_ascii=False)
    plan = ai.ask_json(config, "ask-plan", system, user, QUESTION_SCHEMA)
    start, end = _day(plan["from"], low, high), _day(plan["to"], low, high)
    if start is None or end is None:
        raise ai.AIError("Le modèle n'a pas donné de période.")
    start, end = min(start, end), max(start, end)
    c_start, c_end = _day(plan["compare_from"], low, high), _day(plan["compare_to"], low, high)
    compare = (min(c_start, c_end), max(c_start, c_end)) if c_start and c_end else None
    category = plan["category"] if plan["category"] in categories else None
    search = (plan["search"] or "").strip()[:60] or None
    threshold = plan["threshold"] if isinstance(plan["threshold"], (int, float)) \
        and plan["threshold"] > 0 else None
    months = min(max(int(plan["months"] or 12), 1), 60)
    return {"supported": plan["supported"], "focus": plan["focus"], "from": start,
            "to": end, "compare": compare, "category": category, "search": search,
            "threshold": threshold, "months": months, "note": plan["note"].strip()}


def forecast_facts(statement: Statement, plan, months: int, threshold: float | None) -> tuple[dict, dict]:
    """The cash ahead, from the same projection as the Prévisions page: the
    plan as declared, else the history's medians. Whether and when it goes
    under the threshold, and how much a month could go to savings (or must
    come back from them) while staying above it, are worked out here --
    never by the model.

    Transfers to the 3a or the investment pocket are savings, not spending:
    they sit among the projection's one-offs (a programmed series is one),
    and the first version handed them over mixed with the bills, so the
    answer to "how much can I save?" missed the monthly transfers already
    programmed."""
    projection = plans.project(statement, plan, months_ahead=months)
    rows = projection["rows"]
    under = next((r for r in rows if threshold is not None and r["end"] < threshold), None)

    def saved(r):
        return _r(sum(o["amount"] for o in r["one_offs"] if o.get("transfer")))

    def bills(r):
        return _r(sum(o["amount"] for o in r["one_offs"] if not o.get("transfer")))

    capacity = None
    if threshold is not None and rows:
        # A constant amount from the first projected month: month k carries k
        # of them, so the tightest month decides.
        k, tightest = min(((i, r) for i, r in enumerate(rows, 1)),
                          key=lambda ir: (ir[1]["end"] - threshold) / ir[0])
        per_month = (tightest["end"] - threshold) / k
        step = 10 * math.floor(abs(per_month) / 10) if per_month >= 0 \
            else 10 * math.ceil(abs(per_month) / 10)
        capacity = {
            "sens": "marge" if per_month >= 0 else "manque",
            "par_mois": float(step),
            "mois_qui_decide": tightest["label"],
            "nombre_de_mois_jusqua_ce_mois": k,
            "solde_ce_mois": tightest["end"],
            "explication": ("montant constant, chaque mois dès maintenant, qui garde toutes les "
                            "fins de mois au-dessus du seuil : à ajouter à l'épargne si « marge », "
                            "à retirer de l'épargne ou des dépenses si « manque »"),
        }
    transfers = [saved(r) for r in rows]
    facts = {
        "cash_aujourdhui": projection["cash"], "au": statement.period_end.isoformat(),
        "horizon_mois": months,
        "revenu_mensuel": projection["income"],
        "revenu_source": "déclaré dans le plan" if projection["income_source"] == "declared"
        else "médiane de l'historique",
        "depense_mensuelle_de_base": projection["baseline"],
        "depense_source": "déclarée dans le plan" if projection["baseline_source"] == "declared"
        else "médiane de l'historique, pics saisonniers retirés",
        "point_bas": {"montant": projection["low"]["amount"], "mois": projection["low"]["label"]},
        "fin_horizon": rows[-1]["end"] if rows else projection["cash"],
        "seuil": threshold,
        "sous_le_seuil": ({"mois": under["label"], "solde": under["end"],
                           "manque": _r(threshold - under["end"])} if under else None),
        "marge_au_point_bas": _r(projection["low"]["amount"] - threshold) if threshold else None,
        "capacite_sous_le_seuil": capacity,
        "epargne_versee": {
            "total_sur_l_horizon": _r(sum(transfers)),
            "mois_habituel": _r(statistics.median(transfers)) if transfers else 0.0,
            "versements": [{"libelle": c.get("pocket") and plans.DESTINATION_LABELS.get(c["pocket"], c["pocket"]),
                            "montant": c["amount"], "cadence": plans.CONTRIBUTION_LABELS.get(c["every"], c["every"])}
                           for c in getattr(plan, "contributions", [])],
        },
        "depenses_ponctuelles": sorted(
            ({"mois": r["label"], "libelle": o["label"], "montant": o["amount"]}
             for r in rows for o in r["one_offs"] if not o.get("transfer")),
            key=lambda o: -o["montant"])[:10],
        "versements_ponctuels_vers_l_epargne": [
            {"mois": r["label"], "libelle": o["label"], "montant": o["amount"]}
            for r in rows for o in r["one_offs"] if o.get("transfer")
            and not o["label"].startswith("Versement programmé")][:6],
        "par_mois": [{"mois": r["label"], "solde_fin": r["end"], "epargne_versee": saved(r),
                      "depenses_ponctuelles": bills(r)} for r in rows],
    }
    table = {"columns": ["Mois", "Solde prévu", "Épargne versée", "Dépenses ponctuelles"],
             "rows": [[r["label"], r["end"], saved(r), bills(r)] for r in rows]}
    return facts, table


def run_query(statement: Statement, query: dict, plan=None,
              savings=None) -> tuple[dict, "_Names", dict, dict | None]:
    """The facts for a planned question, computed by the app; the view that
    shows them; and the table the page prints under the answer -- the same
    numbers, laid out by the app, not by the model. `plan` is the declared
    plan, for a question about the future; `savings(start, end)` the
    pockets' summaries, for one about the investments (None without them)."""
    names = _Names(statement)
    if query["focus"] == "placements":
        start, end = query["from"], query["to"]
        summaries = savings(start, end) if savings else None
        view = {"path": "/epargne", "from": start, "to": end}
        if not summaries:
            return {"erreur": "aucune donnée d'épargne capturée"}, names, view, None
        facts, table = savings_facts(summaries, start, end)
        return facts, names, view, table
    if query["focus"] == "prevision":
        facts, table = forecast_facts(statement, plan, query["months"], query["threshold"])
        return facts, names, {"path": "/previsions", "months": query["months"]}, table
    if query["focus"] == "solde":
        day = query["to"]
        points = analysis.cash_points([t for t in statement.transactions if t.date <= day])
        balance = points[-1][1] if points else 0.0
        year_before = [p for p in points if p[0] <= _shift_year(day)]
        facts = {"date": day.isoformat(), "solde_chf": _r(balance),
                 "un_an_avant": _r(year_before[-1][1]) if year_before else None,
                 "ecart_sur_un_an": _r(balance - year_before[-1][1]) if year_before else None,
                 "fin_du_releve": statement.period_end.isoformat()}
        table = {"columns": ["", "CHF"], "rows": [[f"Au {_fr(day)}", facts["solde_chf"]]]
                 + ([["Un an avant", facts["un_an_avant"]]] if year_before else [])}
        return facts, names, {"path": "/", "from": _shift_year(day), "to": day}, table
    start, end = query["from"], query["to"]
    cat, search, focus = query["category"], query["search"], query["focus"]
    facts = period_facts(statement, start, end, names, cat, search)
    view = {"path": "/transactions", "from": start, "to": end, "category": cat, "q": search}
    table = None
    spend = _spend(statement, start, end, cat, search)

    if focus == "comparaison" and query["compare"]:
        other = period_facts(statement, *query["compare"], names, cat, search)
        facts["autre_periode"] = other
        facts["ecart_entre_periodes"] = _r(facts["depense"] - other["depense"])
        facts["ecart_entre_periodes_pct"] = _pct(facts["depense"], other["depense"])
        mine = {c["categorie"]: c["montant"] for c in facts["categories"]}
        theirs = {c["categorie"]: c["montant"] for c in other["categories"]}
        rows = sorted(set(mine) | set(theirs), key=lambda c: -max(mine.get(c, 0), theirs.get(c, 0)))
        facts["categories_comparees"] = [
            {"categorie": c, "periode": mine.get(c, 0.0), "autre": theirs.get(c, 0.0),
             "ecart": _r(mine.get(c, 0.0) - theirs.get(c, 0.0))} for c in rows[:TOP]]
        table = {"columns": ["", f"{_fr(start)} → {_fr(end)}",
                             f"{_fr(query['compare'][0])} → {_fr(query['compare'][1])}"],
                 "rows": [["Total", facts["depense"], other["depense"]]]
                 + [[c["categorie"], c["periode"], c["autre"]] for c in facts["categories_comparees"]]}
        view = {"path": "/", "from": min(start, query["compare"][0]),
                "to": max(end, query["compare"][1])}
    elif focus == "categories":
        table = {"columns": ["Catégorie", "CHF", "Part", "Période d'avant"],
                 "rows": [[c["categorie"], c["montant"], f"{c['part_pct']} %", c["periode_precedente"]]
                          for c in facts["categories"]]}
        view = {"path": "/", "from": start, "to": end}
    elif focus == "beneficiaires":
        table = {"columns": ["Bénéficiaire", "CHF", "Passages"],
                 "rows": [[names.restore(b["nom"]), b["montant"], b["passages"]]
                          for b in facts["beneficiaires"]]}
    elif focus == "grosses_lignes":
        table = {"columns": ["Date", "Bénéficiaire", "CHF"],
                 "rows": [[_fr(dt.date.fromisoformat(t["date"])), names.restore(t["nom"]), t["montant"]]
                          for t in facts["plus_grosses_lignes"]]}
        view["sort"] = "amount"
    elif focus == "par_mois" and facts.get("par_mois"):
        table = {"columns": ["Mois", "CHF"],
                 "rows": [[plans.month_label(m["mois"]), m["montant"]] for m in facts["par_mois"]]}
        view = {"path": "/", "from": start, "to": end, "grain": "month"}
    elif focus == "epargne":
        facts.update(period_facts(statement, start, end, names))
        months = []
        day = start.replace(day=1)
        while day <= end:
            last = analysis.bucket_bounds(day, "month")[1]
            a, b = max(day, start), min(last, end)
            spent = sum(abs(t.amount_chf) for t in _spend(statement, a, b))
            earned = sum(t.amount_chf for t in analysis.income(statement) if a <= t.date <= b)
            months.append({"mois": day.strftime("%Y-%m"), "revenus": _r(earned),
                           "depense": _r(spent), "net": _r(earned - spent)})
            day = last + dt.timedelta(days=1)
        facts["epargne_par_mois"] = months
        table = {"columns": ["Mois", "Revenus", "Dépensé", "Net"],
                 "rows": [[plans.month_label(m["mois"]), m["revenus"], m["depense"], m["net"]]
                          for m in months[-12:]]}
        view = {"path": "/", "from": start, "to": end}
    elif focus == "jours":
        profile = analysis.weekday_profile(spend)
        facts["par_jour_de_semaine"] = [{"jour": d["day"], "montant": _r(d["amount"]),
                                         "lignes": d["count"]} for d in profile]
        table = {"columns": ["Jour", "CHF", "Lignes"],
                 "rows": [[d["day"], _r(d["amount"]), d["count"]] for d in profile]}
    elif focus == "abonnements":
        recurring = sorted(analysis.recurring_labels(
            [t for t in analysis.spending(statement) if t.date <= end
             and _matches(t, cat, search)]).values(), key=lambda r: -r["average"])[:10]
        facts["recurrents"] = [{"nom": names.of(r["label"]), "categorie": r["category"],
                                "montant_moyen": _r(r["average"]), "mois": r["months"],
                                "par_an_estime": _r(r["average"] * 12 * r["count"] / max(r["months"], 1))}
                               for r in recurring]
        facts["recurrents_par_an_total"] = _r(sum(r["par_an_estime"] for r in facts["recurrents"]))
        table = {"columns": ["Bénéficiaire", "Montant moyen", "Par an (estimé)"],
                 "rows": [[names.restore(r["nom"]), r["montant_moyen"], r["par_an_estime"]]
                          for r in facts["recurrents"]]}
    else:
        rows = [["Dépensé", facts["depense"]]]
        for key in ("periode_precedente", "un_an_avant"):
            if facts.get(key):
                rows.append([facts[key]["periode"].capitalize(), facts[key]["total"]])
        table = {"columns": ["", "CHF"], "rows": rows}
    return facts, names, view, table



def answer_question(config: ai.Config, question: str, facts: dict, names: "_Names",
                    focus: str) -> dict:
    system = (LANG + NUMBERS + " Tu réponds à une question sur les dépenses du titulaire, à "
              "partir des seuls résultats fournis, calculés par l'app. Réponds d'abord "
              "directement à la question, puis donne en deux ou trois phrases ce qui l'éclaire : "
              "la comparaison avec la période d'avant ou l'an passé, ce qui pèse le plus, ce "
              "qui a changé. Quatre phrases au plus, pas de conseil générique. L'app affiche "
              "un tableau des chiffres sous ta réponse : ne les énumère pas tous. Si la période "
              "commence avant le relevé (plus_bas_du_releve), dis-le. « follow_ups » : deux ou "
              "trois questions de suivi courtes, utiles, que l'app sait traiter (par catégorie, "
              f"bénéficiaire, mois, comparaison, épargne, prévision, solde). Pour l'avenir : les "
              "versements vers le 3a ou le placement sont de l'épargne, pas des dépenses ; à "
              "« combien épargner / dépenser de plus sans passer sous le seuil », réponds avec "
              "capacite_sous_le_seuil (sa marge ou son manque par mois, et le mois qui décide), "
              "en rappelant l'épargne déjà versée. Une prévision est une "
              "estimation : dis en une demi-phrase sur quoi elle repose (revenu et dépense de base, "
              f"et leur source). Focus de la question : {FOCUS[focus]}.")
    answer = _ask_checked(config, "ask-answer", system, {"question": question, "resultats": facts},
                          facts, ANSWER_SCHEMA, lambda a: [a["answer"]])
    return {"answer": names.restore(answer["answer"].strip()),
            "follow_ups": [q.strip()[:120] for q in answer["follow_ups"] if q.strip()][:3]}
