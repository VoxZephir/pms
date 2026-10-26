"""Projects: transactions gathered under a name -- a trip, a move, a
wedding -- and what they really cost once the friends paid back their share
(`docs/projets.md`).

A project is a list of movement keys (`overrides.key_of`, the identity that
survives re-ingestion), kept in `data/projects.json` beside the ledger,
never in it: like a correction, it is the owner's decision, not the bank's.
A stay abroad the statement already shows is proposed as a project; nothing
is gathered without a click.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from . import analysis, twint
from . import categories as categories_module
from .overrides import key_of

# Around a stay, what belongs to it: the flight and the hotel are booked
# weeks before, the friends pay their share back in the two weeks after.
BOOKED_BEFORE_DAYS = 90
PAID_BACK_DAYS = 14
BOOKINGS = {("Transport", "Avion & car longue distance"), ("Loisirs & voyages", "Hébergement")}
# A Twint or a transfer coming in after the stay is a share paid back only
# from this amount -- under it, a coffee repaid.
PAYBACK_MIN = 20.0
# Settling up after a trip (a Tricount): a Twint or a transfer of a few
# hundred francs to a person, during the stay or in the three weeks after.
SETTLE_MIN = 100.0
SETTLE_DAYS = 21
TO_PEOPLE = {categories_module.TWINT_UNKNOWN, "Transferts P2P"}

# Proof of being there: payments that need a body in the country.
ON_SITE = {"Restaurants & bars", "Alimentation", "Loisirs & voyages", "Transport", "Santé & assurance"}
MIN_ON_SITE = 2

MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")


def _slug(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:48] or "projet"


class Projects:
    """The named groups, loaded from and saved to one JSON file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.items: list[dict] = []
        self.dismissed: list[str] = []
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: Path | str) -> "Projects":
        store = cls(path)
        try:
            raw = json.loads(store.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return store
        store.items = [p for p in raw.get("projects", [])
                       if isinstance(p, dict) and p.get("id") and p.get("name")]
        for p in store.items:
            p["keys"] = [k for k in p.get("keys", []) if isinstance(k, str)]
        store.dismissed = [d for d in raw.get("dismissed", []) if isinstance(d, str)]
        return store

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"version": 1, "projects": self.items, "dismissed": self.dismissed},
                                            ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(self.path)

    def get(self, project_id: str) -> dict | None:
        return next((p for p in self.items if p["id"] == project_id), None)

    def create(self, name: str, keys: list[str], kind: str = "projet",
               start: dt.date | None = None, end: dt.date | None = None) -> dict:
        name = name.strip()[:80]
        if not name:
            raise ValueError("Un projet a besoin d'un nom.")
        base, n = _slug(name), 2
        project_id = base
        while self.get(project_id):
            project_id, n = f"{base}-{n}", n + 1
        project = {"id": project_id, "name": name, "kind": kind, "keys": list(dict.fromkeys(keys)),
                   "created": dt.datetime.now().isoformat(timespec="seconds")}
        if start and end:
            # An empty project still knows where to look for its movements.
            project["around"] = [min(start, end).isoformat(), max(start, end).isoformat()]
        self.items.append(project)
        return project

    def restore(self, project: dict) -> None:
        """Put a project back as it was (an undo)."""
        self.items = [p for p in self.items if p["id"] != project["id"]] + [project]

    def delete(self, project_id: str) -> dict | None:
        project = self.get(project_id)
        self.items = [p for p in self.items if p["id"] != project_id]
        return project


def _row(t, slots) -> dict:
    return {"key": key_of(t), "date": t.date, "label": t.label, "amount": round(t.amount_chf, 2),
            "category": t.category, "subcategory": t.subcategory,
            "slot": slots.get(t.category), "country": analysis.country_of(t)
            if t.kind.startswith(twint.CARD_KIND) else None}


def summary(project: dict, by_key: dict, slots: dict) -> dict:
    """What a project cost: spent, paid back, the net, by category, per day."""
    rows = [by_key[k] for k in project["keys"] if k in by_key]
    spent = -sum(t.amount_chf for t in rows if t.amount_chf < 0)
    back = sum(t.amount_chf for t in rows if t.amount_chf > 0)
    cats: dict[str, float] = defaultdict(float)
    for t in rows:
        if t.amount_chf < 0:
            cats[t.category] += -t.amount_chf
    # The days of the project itself: a flight booked in May does not make
    # a July week last two months, nor does a share paid back a week later.
    core = sorted(t.date for t in rows if t.amount_chf < 0 and (t.category, t.subcategory) not in BOOKINGS) \
        or sorted(t.date for t in rows)
    days = core
    span = (days[-1] - days[0]).days + 1 if days else 0
    countries = sorted({c for t in rows if t.kind.startswith(twint.CARD_KIND)
                        for c in [analysis.country_of(t)] if c and c != twint.HOME and not c.isdigit()})
    return {
        "id": project["id"], "name": project["name"], "kind": project.get("kind", "projet"),
        "count": len(rows), "missing": len(project["keys"]) - len(rows),
        "start": days[0] if days else None, "end": days[-1] if days else None, "days": span,
        "spent": round(spent, 2), "back": round(back, 2), "net": round(spent - back, 2),
        "per_day": round((spent - back) / span, 2) if span else None,
        "categories": [{"category": c, "amount": round(a, 2), "slot": slots.get(c),
                        "share": a / spent * 100 if spent else 0.0}
                       for c, a in sorted(cats.items(), key=lambda kv: -kv[1])],
        "countries": countries,
    }


def _stay_name(countries: list[str], start: dt.date) -> str:
    return f"{' · '.join(countries)}, {MONTHS[start.month - 1]} {start.year}"


def stay_id(start: dt.date, countries: list[str]) -> str:
    """A proposal's identity, stable across reloads: what a dismissal keeps."""
    return f"{start.isoformat()}:{'+'.join(sorted(countries))}"


def _on_site(t) -> bool:
    """A payment that needs a body in the country: a meal, a room, groceries,
    a taxi -- not a website that happens to bill from abroad."""
    return t.category in ON_SITE and (t.category, t.subcategory) != ("Transport", "Avion & car longue distance")


def suggestions(statement, taken: set[str], dismissed: set[str] = frozenset(), slots=None) -> list[dict]:
    """Every stay abroad the statement shows (`twint.Context`), as the
    project it would make, each line with the reason it is there: bought
    on site during the stay, a flight or hotel booked in the weeks before,
    a share paid back after. A stay needs proof of presence -- at least
    two payments on site (a meal, a room, groceries), in a country that is
    kept only if such proof exists there: websites billing from abroad
    (subscriptions, online shops) made a "trip" of anyone's October. A stay
    already in a project, or dismissed, is not proposed again."""
    ctx = twint.Context(statement)
    slots = slots or {}
    # Who pays in every month (an employer) does not pay back a trip.
    paid_in = Counter(t.label for t in statement.transactions
                      if t.amount_chf > 0 and t.category == "Revenus" and t.subcategory == "Virement entrant")
    regular = {label for label, n in paid_in.items() if n >= 3}
    out = []
    for stay in ctx.stays:
        start, end = stay["start"], stay["end"]
        lo, hi = start - dt.timedelta(days=1), end + dt.timedelta(days=1)
        abroad = [t for t in statement.transactions
                  if t.amount_chf < 0 and lo <= t.date <= hi and t.kind.startswith(twint.CARD_KIND)
                  and analysis.country_of(t) in stay["countries"]]
        proof = [t for t in abroad if _on_site(t)]
        countries = sorted({analysis.country_of(t) for t in proof})
        if len(proof) < MIN_ON_SITE:
            continue
        sid = stay_id(start, countries)
        if sid in dismissed:
            continue
        picked: list[tuple] = []
        for t in abroad:
            if analysis.country_of(t) in countries:
                picked.append((t, f"sur place · {analysis.country_of(t)}"))
        for t in statement.transactions:
            if analysis.is_internal(t) or t.category == categories_module.INTERNAL:
                continue
            if (t.amount_chf < 0 and (t.category, t.subcategory) in BOOKINGS
                    and start - dt.timedelta(days=BOOKED_BEFORE_DAYS) <= t.date < lo):
                picked.append((t, f"réservé {(start - t.date).days} jours avant le départ"))
            elif (t.amount_chf >= PAYBACK_MIN and end < t.date <= end + dt.timedelta(days=PAID_BACK_DAYS)
                  and (t.kind in categories_module.PEER_KINDS
                       or (t.category == "Revenus" and t.subcategory == "Virement entrant"
                           and t.label not in regular))):
                picked.append((t, f"reçu {(t.date - end).days} jours après le retour : une part remboursée"))
            elif (t.amount_chf <= -SETTLE_MIN and t.category in TO_PEOPLE
                  and lo <= t.date <= end + dt.timedelta(days=SETTLE_DAYS)):
                when = "pendant le séjour" if t.date <= hi else f"{(t.date - end).days} jours après le retour"
                picked.append((t, f"envoyé à quelqu'un {when} : une part réglée (Tricount ?)"))
        picked.sort(key=lambda p: p[0].date)
        keys = [key_of(t) for t, _ in picked]
        if any(k in taken for k in keys):
            continue
        spent = -sum(t.amount_chf for t, _ in picked if t.amount_chf < 0)
        back = sum(t.amount_chf for t, _ in picked if t.amount_chf > 0)
        merchants = len({t.label for t in proof})
        days = len({t.date for t in proof})
        out.append({
            "id": sid, "name": _stay_name(countries, start), "start": start, "end": end,
            "countries": countries, "keys": keys, "count": len(keys),
            "spent": round(spent, 2), "back": round(back, 2), "net": round(spent - back, 2),
            "why": (f"{len(proof)} paiements sur place ({merchants} commerçants, {days} jours) "
                    f"en {', '.join(countries)} du {start:%d.%m} au {end:%d.%m.%Y}"),
            "rows": [{**_row(t, slots), "reason": why} for t, why in picked],
        })
    return sorted(out, key=lambda s: s["start"], reverse=True)


def candidates(statement, project: dict, slots: dict, margin_days: int = 30) -> list[dict]:
    """The movements around a project not in it yet: what can be added."""
    inside = set(project["keys"])
    days = [t.date for t in statement.transactions if key_of(t) in inside]
    if not days and project.get("around"):
        days, margin_days = [dt.date.fromisoformat(d) for d in project["around"]], 0
    if not days:
        return []
    low = min(days) - dt.timedelta(days=margin_days)
    high = max(days) + dt.timedelta(days=margin_days)
    middle = low + (high - low) / 2
    rows = [t for t in statement.transactions
            if low <= t.date <= high and key_of(t) not in inside
            and not analysis.is_internal(t) and t.category != categories_module.INTERNAL]
    # The closest to the project first: what belongs to it is near it.
    return [_row(t, slots) for t in sorted(rows, key=lambda t: (abs((t.date - middle).days), t.date))]
