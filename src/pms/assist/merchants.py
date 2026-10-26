"""B. A category for the payees no rule recognises -- with what the web
says about a name the model does not know (DeepSeek's search; Claude
searches by itself)."""

from __future__ import annotations

import datetime as dt
import json
import re
import statistics
from collections import Counter, defaultdict

from .. import ai, analysis
from .. import categories as categories_module
from ..models import Statement, Transaction
from .common import LANG, _r

# --- B. payees no rule recognises ----------------------------------------------

# A transfer names a person or a company. Only a company is worth sending: a
# person's name tells a model nothing, and is exactly what must not leave.
COMPANY = re.compile(r"\b(AG|SA|S\.A\.|SÀRL|SARL|S[àa]rl|GmbH|Ltd|Inc|SE|KG|LLC|BV|NV|"
                     r"Genossenschaft|Coop[ée]rative|Fondation|Stiftung|Verein|Association)\b",
                     re.I)
MERCHANT_BATCH = 40
# Searches per batch with DeepSeek: billed per call from November 2026.
SEARCHED_PER_BATCH = 15


def _city(location: str) -> str:
    """The town of a card payment's place ("Rue 1, 1630 Bulle, Suisse"),
    without its postcode."""
    parts = [x.strip() for x in (location or "").split(",") if x.strip()]
    town = parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")
    return re.sub(r"^[A-Z]{0,2}-?\d{4,5}\s+", "", town)


def _towns_by_day(statement: Statement) -> dict[dt.date, Counter]:
    """Where the card was used, day by day: the towns the bank printed."""
    out: dict[dt.date, Counter] = defaultdict(Counter)
    for t in statement.transactions:
        if ai.is_card(t) and t.location and _city(t.location):
            out[t.date][_city(t.location)] += 1
    return out


def _probable_town(rows: list[Transaction], towns: dict[dt.date, Counter]) -> str:
    """A payment printed without a place -- Revolut's export has none -- most
    likely happened where the card was used the same day, or the day around:
    a hint for the search, never shown as a fact."""
    seen: Counter = Counter()
    for t in rows:
        for shift in (-1, 0, 1):
            seen.update(towns.get(t.date + dt.timedelta(days=shift), Counter()))
    return seen.most_common(1)[0][0] if seen else ""


def search_query(payee: dict) -> str:
    """The exact name, quoted -- a person-like shop name alone found
    a footballer with a close name -- and the town: the printed one, else the probable one."""
    town = _city(payee["location"]) or payee.get("near", "")
    return " ".join(x for x in (f'"{payee["label"]}"', town) if x)


def uncategorised_payees(statement: Statement) -> tuple[list[dict], int]:
    """The payees still "Non catégorisé", grouped, with what a model may see,
    and how many were held back as private names."""
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in statement.transactions:
        if t.category == categories_module.UNCATEGORISED and t.amount < 0 \
                and t.label and not analysis.is_internal(t):
            groups[t.label].append(t)
    out, private = [], 0
    towns = _towns_by_day(statement)
    for label, rows in sorted(groups.items(), key=lambda kv: -sum(abs(t.amount_chf) for t in kv[1])):
        card = any(ai.is_card(t) for t in rows)
        if not card and not COMPANY.search(label):
            private += 1
            continue
        out.append({"label": label, "kind": "carte" if card else rows[0].kind,
                    "location": (location := next((t.location for t in rows if t.location), "")),
                    "near": "" if location else _probable_town(rows, towns),
                    "count": len(rows), "total": _r(sum(abs(t.amount_chf) for t in rows)),
                    "median": _r(statistics.median(abs(t.amount_chf) for t in rows)),
                    "last": max(t.date for t in rows).isoformat(),
                    "key": f"{rows[-1].reference}:{rows[-1].currency}"})
    return out, private


MERCHANT_SCHEMA = ai.strict({"type": "object", "properties": {
    "suggestions": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"},
        "category": {"type": ["string", "null"]},
        "subcategory": {"type": "string"},
        "confidence": {"type": "string", "enum": ["haute", "moyenne", "basse"]},
        "why": {"type": "string"},
    }}},
}})


def suggest_merchants(config: ai.Config, payees: list[dict], choices: dict,
                      fresh: bool = False) -> dict[str, dict]:
    """A category per payee, from the owner's own list, or none when the
    name does not say. Keyed by label; answers outside the list dropped."""
    categories = [c for c in choices["categories"]
                  if c not in (categories_module.UNCATEGORISED, categories_module.TWINT_UNKNOWN)]
    vocab = {c: choices["subcategories"].get(c, []) for c in categories}
    system = (LANG + "Tu classes des commerçants d'un relevé bancaire suisse dans les "
              "catégories de l'utilisateur, et seulement celles-là. Si le nom ne permet "
              "pas de savoir, mets category à null : mieux vaut ne rien proposer qu'une "
              "catégorie au hasard. « recherche_web », quand il est là, dit ce que le web sait du "
              "nom : appuie-toi dessus, mais écarte une page qui parle d'un autre nom (un nom "
              "voisin, une personne célèbre). « lieu_probable » : la ville où la carte a servi "
              "ce jour-là, une piste, pas une certitude. Si tu peux chercher sur le web, cherche un nom que tu ne "
              "connais pas avec son lieu (un camping, un artisan, une petite enseigne) avant de "
              "décider. « why » : une demi-phrase, ce que le nom indique ou ce que tu as trouvé "
              "(« camping à Gruyères »).")
    out: dict[str, dict] = {}
    for start in range(0, len(payees), MERCHANT_BATCH):
        batch = payees[start:start + MERCHANT_BATCH]
        # DeepSeek: what its search says about the name, kept to show beside
        # the answer. Claude searches by itself (`web=True`).
        web: dict[int, list[dict]] = {
            i: _search(config, p) for i, p in enumerate(batch)
            if config.provider == "deepseek" and i < SEARCHED_PER_BATCH}
        user = json.dumps({
            "categories": vocab,
            "commercants": [{"id": i, "nom": p["label"], "lieu": p["location"],
                             "type": p["kind"], "passages": p["count"],
                             "montant_median": p["median"],
                             **({"lieu_probable": p["near"]} if p.get("near") else {}),
                             **({"recherche_web": web[i]} if i in web else {})}
                            for i, p in enumerate(batch)],
        }, ensure_ascii=False)
        answer = ai.ask_json(config, "merchants", system, user, MERCHANT_SCHEMA, web=True,
                             cache=not fresh)
        for i, payee in enumerate(batch):
            if i in web:
                out[payee["label"]] = {"category": None, "subcategory": "", "confidence": "basse",
                                       "why": "", "searched": len(web[i]),
                                       "pages": [{"titre": w["titre"], "url": w["url"]}
                                                 for w in web[i] if w["url"]][:2]}
        for s in answer["suggestions"]:
            if not 0 <= s["id"] < len(batch):
                continue
            payee = batch[s["id"]]
            category = s["category"]
            if category not in vocab:
                category = None
            sub = s["subcategory"] if category and s["subcategory"] in vocab[category] else ""
            out[payee["label"]] = {**out.get(payee["label"], {}),
                                   "category": category, "subcategory": sub,
                                   "confidence": s["confidence"], "why": s["why"].strip()}
    return out


def _search(config: ai.Config, payee: dict) -> list[dict]:
    """The quoted name first; the bare words when the quotes find nothing."""
    found = ai.search_snippets(config, search_query(payee))
    if found:
        return found
    town = _city(payee["location"]) or payee.get("near", "")
    return ai.search_snippets(config, " ".join(x for x in (payee["label"], town) if x))
