"""What every assisted task shares: the voice and the numbers rule given
to the model, the redactor for names, the second chance on a number the
facts do not hold, and the facts of a period."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
import unicodedata
from collections import defaultdict

from .. import ai, analysis
from ..models import Statement, Transaction

LANG = ("Tu écris en français de Suisse romande, au tutoiement, sobrement : "
        "des phrases courtes, sans formule de politesse ni emphase. ")
NUMBERS = ("Les montants sont en CHF. Ne calcule rien : chaque chiffre que tu "
           "écris doit figurer tel quel dans les données fournies (tu peux "
           "l'arrondir au franc). Un chiffre absent des données fait rejeter ta réponse. "
           "Écris les milliers avec une apostrophe (1'234). Les noms entre crochets "
           "comme [P1] sont des personnes ou sociétés masquées : réutilise-les tels quels.")


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()[:16]


def _r(x: float) -> float:
    return round(float(x), 2)


def fold(text: str) -> str:
    """Case- and accent-free, as the table's own search compares."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def _label_kinds(statement: Statement) -> dict[str, str]:
    """A label's kind of payment: a payee ever paid by card is a shop."""
    kinds: dict[str, str] = {}
    for t in statement.transactions:
        if t.label and kinds.get(t.label) != ai.CARD_KIND:
            kinds[t.label] = ai.CARD_KIND if ai.is_card(t) else t.kind
    return kinds


class _Names(ai.Redactor):
    """The redactor for facts that carry labels without their rows."""

    def __init__(self, statement: Statement):
        super().__init__()
        self.kinds = _label_kinds(statement)

    def of(self, label: str) -> str:
        return label if self.kinds.get(label) == ai.CARD_KIND or not label else self.name(label)



# --- asking, with one second chance ------------------------------------------------

def _ask_checked(config: ai.Config, task: str, system: str, payload: dict, facts: dict,
                 schema: dict, texts, fresh: bool = False) -> dict:
    """`ask_json`, then every text `texts(answer)` returns is checked against
    `facts`. A number the facts do not hold -- most often one the model added
    up itself -- earns one more try, told which number it was; a second miss
    drops the answer."""
    user = json.dumps(payload, ensure_ascii=False)
    answer = ai.ask_json(config, task, system, user, schema, cache=not fresh)
    bad = [n for text in texts(answer) for n in ai.unsupported_numbers(text, facts)]
    if not bad:
        return answer
    retry = {**payload, "correction": (
        f"Ta réponse citait {', '.join(f'{n:g}' for n in bad[:3])}, absent des données : "
        "c'était sans doute un calcul. Réécris sans aucun chiffre qui ne figure pas tel quel "
        "dans les données.")}
    answer = ai.ask_json(config, task, system, json.dumps(retry, ensure_ascii=False), schema,
                         cache=False)
    for text in texts(answer):
        ai.checked_text(text, facts)
    return answer


# --- the facts of a period ---------------------------------------------------------

TOP = 6


def _pct(now: float, before: float) -> int | None:
    return round((now / before - 1) * 100) if before else None


def _shift_year(day: dt.date, years: int = 1) -> dt.date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day - dt.timedelta(days=365 * years)


def _spend(statement: Statement, start: dt.date, end: dt.date,
           category: str | None = None, search: str | None = None) -> list[Transaction]:
    return [t for t in analysis.spending(statement)
            if start <= t.date <= end and _matches(t, category, search)]


def _matches(t: Transaction, category: str | None, search: str | None) -> bool:
    if category and t.category != category:
        return False
    if search:
        hay = fold(" ".join([t.label, t.merchant, t.location]))
        return all(w in hay for w in fold(search).split())
    return True


def period_facts(statement: Statement, start: dt.date, end: dt.date, names: "_Names",
                 category: str | None = None, search: str | None = None) -> dict:
    """Everything a sentence about a period may need, computed here: the
    totals, the same period just before and a year before, what moved by
    category, where the money went, the largest lines, month by month.
    Every difference and percentage is already worked out -- the model
    only picks and says them."""
    spend = _spend(statement, start, end, category, search)
    total = sum(abs(t.amount_chf) for t in spend)
    days = (end - start).days + 1
    earn = [t for t in analysis.income(statement) if start <= t.date <= end
            and _matches(t, category, search)] if not (category or search) else []
    income = sum(t.amount_chf for t in earn)

    prev_end = start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=days - 1)
    year_start, year_end = _shift_year(start), _shift_year(end)
    covered = statement.period_start

    def compare(a: dt.date, b: dt.date, label: str) -> dict | None:
        if a < covered:
            return None
        rows = _spend(statement, a, b, category, search)
        amount = sum(abs(t.amount_chf) for t in rows)
        return {"periode": label, "du": a.isoformat(), "au": b.isoformat(),
                "total": _r(amount), "lignes": len(rows),
                "ecart": _r(total - amount), "ecart_pct": _pct(total, amount)}

    by_cat: dict[str, float] = defaultdict(float)
    for t in spend:
        by_cat[t.category] += abs(t.amount_chf)
    before: dict[str, float] = defaultdict(float)
    if prev_start >= covered:
        for t in _spend(statement, prev_start, prev_end, category, search):
            before[t.category] += abs(t.amount_chf)
    cats = [{"categorie": c, "montant": _r(v), "part_pct": round(v / total * 100) if total else 0,
             "periode_precedente": _r(before.get(c, 0.0)),
             "ecart": _r(v - before.get(c, 0.0))}
            for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1])]
    moved = sorted(cats, key=lambda c: -abs(c["ecart"]))[:4]

    facts = {
        "du": start.isoformat(), "au": end.isoformat(), "jours": days,
        "categorie": category, "recherche": search,
        "depense": _r(total), "lignes": len(spend),
        "depense_par_jour": _r(total / days) if days else 0.0,
        "plus_bas_du_releve": covered.isoformat(),
        "periode_precedente": compare(prev_start, prev_end, "même durée juste avant"),
        "un_an_avant": compare(year_start, year_end, "même période un an avant"),
        "categories": cats[:TOP] if not category else [],
        "plus_gros_changements": moved if not category else [],
        "beneficiaires": [{"nom": names.of(m["name"]), "montant": _r(m["amount"]),
                           "passages": m["count"], "mediane": _r(m["median"])}
                          for m in analysis.top_merchants(spend, TOP)],
        "plus_grosses_lignes": [{"date": t.date.isoformat(), "nom": names.label(t),
                                 "categorie": t.category, "montant": _r(abs(t.amount_chf))}
                                for t in sorted(spend, key=lambda t: t.amount_chf)[:5]],
    }
    if not (category or search):
        facts.update(revenus=_r(income), net=_r(income - total),
                     taux_epargne_pct=round((income - total) / income * 100) if income > 0 else None)
    if days > 45:
        months: dict[str, float] = defaultdict(float)
        for t in spend:
            months[t.date.strftime("%Y-%m")] += abs(t.amount_chf)
        values = [months[k] for k in sorted(months)]
        facts["par_mois"] = [{"mois": k, "montant": _r(months[k])} for k in sorted(months)]
        if values:
            facts["mois_median"] = _r(statistics.median(values))
            facts["mois_le_plus_cher"] = max(facts["par_mois"], key=lambda m: m["montant"])
    return facts



def _fr(day: dt.date) -> str:
    return day.strftime("%d.%m.%Y")
