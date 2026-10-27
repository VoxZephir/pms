"""What is owned outside the statement and its brokerage: a share of an
unlisted company, received or bought (`data/holdings.json`, `docs/impots.md`,
« Titres hors relevé »). Declared by the owner -- its value each year is the
one the tax return asks for, not a market price -- and read for the wealth on
31 December, the dividends it paid into the account, and the net worth.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from pathlib import Path

from . import analysis

# A Swiss company pays its dividend net of the 35 % withholding tax, which the
# return gives back: the gross is the net over 0.65.
WITHHOLDING = 0.35

# What a holding is. A share is equity and may pay a dividend; anything else
# (a watch, a painting) only has a declared value: it counts in the wealth
# and the savings, never as equity in the allocation.
SHARE, OTHER = "share", "other"
KINDS = {SHARE: "Action non cotée", OTHER: "Autre bien"}


def kind_of(holding: dict) -> str:
    return holding.get("kind") if holding.get("kind") in KINDS else SHARE


def pocket_name(holdings: list[dict]) -> str:
    """The savings pocket's name: what it holds, said plainly."""
    return "Titres non cotés" if all(kind_of(h) == SHARE for h in holdings) else "Hors marché"


def load(path) -> list[dict]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for h in raw.get("holdings", []):
        if not isinstance(h, dict) or not h.get("name"):
            continue
        values = {}
        for year, value in (h.get("values") or {}).items():
            try:
                values[int(year)] = float(value)
            except (TypeError, ValueError):
                continue
        out.append({"id": str(h.get("id") or uuid.uuid4().hex[:8]), "name": str(h["name"]),
                    "kind": kind_of(h),
                    "quantity": float(h.get("quantity") or 1), "payer": str(h.get("payer") or ""),
                    "withholding": bool(h.get("withholding", True)), "since": h.get("since"),
                    "values": values})
    return out


def save(path, holdings: list[dict]) -> None:
    rows = [{**h, "values": {str(y): v for y, v in sorted(h["values"].items())}} for h in holdings]
    Path(path).write_text(json.dumps({"holdings": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


def clean(raw: dict) -> dict:
    """A holding as typed on the page, checked; ValueError with the reason."""
    name = str(raw.get("name") or "").strip()[:80]
    if not name:
        raise ValueError("Un titre a besoin d'un nom.")
    try:
        quantity = float(str(raw.get("quantity") or 1).replace("'", ""))
    except ValueError:
        raise ValueError("Nombre de titres invalide.") from None
    values = {}
    for year, value in (raw.get("values") or {}).items():
        text = str(value).replace("'", "").replace("’", "").strip()
        if not text:
            continue
        try:
            values[int(year)] = float(text)
        except ValueError:
            raise ValueError(f"Valeur {year} invalide.") from None
    if not values:
        raise ValueError("Donne au moins une valeur, celle d'une année.")
    since = raw.get("since") or None
    if since is not None:
        try:
            since = int(since)
        except (TypeError, ValueError):
            raise ValueError("Année d'entrée invalide.") from None
    kind = kind_of(raw)
    share = kind == SHARE
    return {"id": str(raw.get("id") or uuid.uuid4().hex[:8]), "name": name, "kind": kind, "quantity": quantity,
            # A dividend is a share's: another good has no payer.
            "payer": str(raw.get("payer") or "").strip()[:80] if share else "",
            "withholding": bool(raw.get("withholding", True)) and share, "since": since, "values": values}


def value_at(holding: dict, year: int) -> float | None:
    """The value per share declared for `year`, else the last one before
    it; nothing before the year the holding came in."""
    if holding.get("since") and year < holding["since"]:
        return None
    known = [y for y in holding["values"] if y <= year]
    return holding["values"][max(known)] if known else None


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


def dividends(statement, holding: dict, year: int) -> dict:
    """What the holding paid into the account in `year`: the net received,
    the gross the return declares and the withholding it gives back."""
    payer = _fold(holding.get("payer"))
    rows = [t for t in statement.transactions
            if payer and t.date.year == year and t.amount_chf > 0 and not analysis.is_internal(t)
            and payer in _fold(t.label)]
    net = sum(t.amount_chf for t in rows)
    gross = net / (1 - WITHHOLDING) if holding["withholding"] else net
    return {"net": round(net, 2), "gross": round(gross, 2), "withheld": round(gross - net, 2),
            "rows": [{"date": t.date, "label": t.label, "amount": round(t.amount_chf, 2),
                      "key": f"{t.reference}:{t.currency}"} for t in rows]}


def worth(holdings: list[dict], year: int) -> float:
    return round(sum((value_at(h, year) or 0.0) * h["quantity"] for h in holdings), 2)


# --- as a savings pocket ---------------------------------------------------

def start(holding: dict):
    """The day the holding enters the books: 1 January of the year it came
    in (or of its first declared value). A yearly tax value has no better
    date, and a revaluation lands on the 1st of January too."""
    year = holding.get("since") or min(holding["values"])
    return dt.date(int(year), 1, 1)


def value_on(owned: list[dict], day) -> float:
    """All holdings at their declared value of `day`'s year, from the day
    each came in."""
    return round(sum((value_at(h, day.year) or 0.0) * h["quantity"]
                     for h in owned if day >= start(h)), 2)


def pocket_flows(statement, owned: list[dict]) -> dict:
    """Money into (+) or out of (-) the holdings, by day: the value each
    arrived with (a gift or a purchase is money in, not a gain), and each
    dividend paid out to the current account (the holding's return leaving
    it -- the account counts it in, so the total nets it to a gain)."""
    flows: dict = {}
    for h in owned:
        day = start(h)
        flows[day] = flows.get(day, 0.0) + (value_at(h, day.year) or 0.0) * h["quantity"]
        payer = _fold(h.get("payer"))
        if not payer:
            continue
        for t in statement.transactions:
            if (t.amount_chf > 0 and t.date >= day and not analysis.is_internal(t)
                    and payer in _fold(t.label)):
                flows[t.date] = flows.get(t.date, 0.0) - t.amount_chf
    return flows
