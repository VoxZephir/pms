"""How tidy the ledger is, for `/corrections`: how much of the spending a
category explains, and the payees the bank spells several ways that one
merge would gather (`docs/corrections.md`, « La page Corrections »).

Nothing here writes: a suggestion is shown, and becomes a merge on a click.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

from . import analysis
from . import categories as categories_module

# Left to classify: no rule knows the payee, or the line names none.
TODO = (categories_module.UNCATEGORISED, categories_module.TWINT_UNKNOWN)

# First words that name a kind of place or of payment, not a business: two
# "Restaurant …" are two restaurants, two "Coop …" one chain.
GENERIC = {
    "paiement", "payment", "virement", "transfert", "transfer", "versement", "ordre",
    "achat", "debit", "credit", "retrait", "depot", "prelevement", "frais", "interets",
    "restaurant", "ristorante", "cafe", "bar", "boulangerie", "pharmacie", "apotheke",
    "garage", "hotel", "kiosk", "kiosque", "boucherie", "station", "parking", "taxi",
    "regie", "agence", "cabinet", "clinique", "ecole", "commune", "ville",
    "the", "le", "la", "les", "de", "du", "des", "sa", "ag", "gmbh", "sarl", "srl",
    "ste", "st", "saint", "st.", "dr", "monsieur", "madame", "mme", "m.", "herr", "frau",
}

# A merge suggestion needs this many spellings, and its spellings this share
# of their money in one category -- a chain sells one kind of thing.
MIN_SPELLINGS = 2
SAME_KIND = 0.8
SHOWN = 8


def coverage(statement) -> dict:
    """The share of the spending -- in lines and in francs -- that carries a
    category, and what is left: the Twints without a payee, the payees no
    rule knows."""
    spend = analysis.spending(statement)
    total = sum(-t.amount_chf for t in spend) or 1.0
    left = [t for t in spend if t.category in TODO]
    twint = [t for t in left if t.category == categories_module.TWINT_UNKNOWN]
    unknown = [t for t in left if t.category == categories_module.UNCATEGORISED]
    return {
        "lines": len(spend), "lines_done": len(spend) - len(left),
        "share_lines": (len(spend) - len(left)) / len(spend) * 100 if spend else 100.0,
        "share_amount": (1 - sum(-t.amount_chf for t in left) / total) * 100,
        "twint": len(twint), "twint_amount": round(sum(-t.amount_chf for t in twint), 2),
        "unknown": len(unknown), "unknown_amount": round(sum(-t.amount_chf for t in unknown), 2),
        "unknown_payees": len({t.label for t in unknown}),
    }


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _first(label: str) -> str | None:
    """A label's first word, folded: the key a chain's spellings share."""
    match = re.match(r"[^\W\d_]+", label.strip())
    return _fold(match.group(0)) if match else None


def _common(labels: list[str]) -> str | None:
    """The words every spelling starts with, as the first one prints them --
    "Coop" for "Coop-1045 Peseux" and "Coop City", "Régie du Centre" for its
    "SA" and "S.A." -- or None when those words name a kind of place rather
    than a business ("Restaurant Le" is two restaurants)."""
    words = [list(re.finditer(r"\w+", label)) for label in labels]
    k = 0
    while all(len(w) > k for w in words) and len({_fold(w[k].group(0)) for w in words}) == 1:
        k += 1
    if not k:
        return None
    named = [m.group(0) for m in words[0][:k]]
    if not any(len(w) >= 3 and not w.isdigit() and _fold(w) not in GENERIC for w in named):
        return None
    return labels[0][:words[0][k - 1].end()]


def merge_suggestions(transactions, overrides) -> list[dict]:
    """Payees that start with the same word, spend in the same category and
    are not merged yet: "Coop-1045 Peseux", "Coop Pronto Marin", "Coop City
    Neuchâtel" -- one chain, three names in every ranking. The biggest
    first, by the money they gather. A merge already covering a spelling
    (exact or by prefix) takes it out of its group."""
    groups: dict[str, dict] = defaultdict(lambda: {"labels": Counter(), "amount": 0.0,
                                                    "categories": Counter()})
    for t in transactions:
        if t.amount_chf >= 0 or analysis.is_internal(t) or not t.label:
            continue
        if overrides.canonical(t.label) != t.label or t.label in overrides.aliases.values():
            continue
        head = _first(t.label)
        if head is None:
            continue
        g = groups[head]
        g["labels"][t.label] += 1
        g["amount"] += -t.amount_chf
        g["categories"][t.category] += -t.amount_chf
    out = []
    for g in groups.values():
        if len(g["labels"]) < MIN_SPELLINGS:
            continue
        category, top = g["categories"].most_common(1)[0]
        if top < SAME_KIND * g["amount"]:
            continue
        labels = [label for label, _ in g["labels"].most_common()]
        prefix = _common(labels)
        if prefix is None:
            continue
        out.append({"prefix": prefix, "canonical": prefix.rstrip(" -.,"), "category": category,
                    "labels": labels,
                    "count": sum(g["labels"].values()), "amount": round(g["amount"], 2)})
    return sorted(out, key=lambda s: -s["amount"])[:SHOWN]
