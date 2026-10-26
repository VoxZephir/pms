"""A target split of the savings, declared in `data/allocation.json`.

The composition bar says what the savings are; a target says what they
should be, and the gap in francs what to move where. Declared like the
budgets: a decision, outside the ledger, edited from the panel.

By asset class -- the classes the composition bar already uses -- rather
than by account: the question is how much risk, not which bank. The 3a is
in it like the rest; it is the slowest money to move, and a target that
leaves it out would misstate the equity share.
"""

from __future__ import annotations

import json
from pathlib import Path

VERSION = 1
CLASSES = ("Cash", "Actions", "Obligations", "Trend-Following", "Crypto")
# A split that does not add up to 100 % is refused, to the half point:
# 33.3 three times is a split, 90 is not.
TOLERANCE = 0.5


class Allocation:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.targets: dict[str, float] = {}

    @classmethod
    def load(cls, path: Path | str) -> "Allocation":
        store = cls(path)
        if not store.path.exists():
            return store
        try:
            raw = json.loads(store.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return store
        for name, pct in (raw.get("targets") or {}).items():
            try:
                value = float(pct)
            except (TypeError, ValueError):
                continue
            if name in CLASSES and value > 0:
                store.targets[name] = round(value, 2)
        return store

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": VERSION, "targets": self.targets}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        temporary.replace(self.path)
        return self.path


def validate(form: dict[str, str]) -> tuple[dict[str, float], str | None]:
    """The targets typed in the form, or why they are refused."""
    targets = {}
    for name in CLASSES:
        text = (form.get(name) or "").strip().replace("%", "")
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            return {}, f"« {text} » n'est pas un pourcentage (point décimal, pas de virgule)."
        if not 0 <= value <= 100:
            return {}, f"{name} : entre 0 et 100 %."
        if value:
            targets[name] = round(value, 2)
    total = sum(targets.values())
    if abs(total - 100) > TOLERANCE:
        return {}, f"La répartition fait {total:g} % : il faut 100 %."
    return targets, None


def leverage(positions: list[dict]) -> dict[str, float]:
    """The exposure each class carries beyond its francs, by class.

    The composition splits a fund's value across its classes, so the bar
    adds up to the wealth. A return-stacked fund breaks the equivalence
    between francs and risk: RSST's franc carries a franc of S&P 500 *and*
    a franc of managed futures (`exposure: 2`), but the bar gives it half
    to each. What the bar leaves out is (exposure − 1) × the value, spread
    by the same split.
    """
    extra: dict[str, float] = {}
    for position in positions:
        surplus = float(position.get("exposure") or 1.0) - 1.0
        if surplus <= 0:
            continue
        split = position.get("asset_split") or {position.get("asset_class") or "Autres": 100}
        total_pct = sum(split.values()) or 100.0
        for name, pct in split.items():
            name = {"MF": "Trend-Following"}.get(name, name)
            extra[name] = extra.get(name, 0.0) + position["value"] * surplus * pct / total_pct
    return extra


def exposure(parts: list[dict], extra: dict[str, float]) -> dict | None:
    """Each class's gross exposure, as a share of the wealth.

    The shares add up to more than 100 % when a fund is levered -- that
    excess is the point: it is the risk the value split does not show.
    None when nothing is levered, the value split then says it all.
    """
    if not any(v >= 0.5 for v in extra.values()):
        return None
    current: dict[str, float] = {}
    for part in parts:
        current[part["name"]] = current.get(part["name"], 0.0) + part["value"]
    total = sum(current.values())
    if total <= 0:
        return None
    names = [*CLASSES, *(n for n in {**current, **extra} if n not in CLASSES)]
    rows = [{"name": n, "value": round(current.get(n, 0.0) + extra.get(n, 0.0), 2),
             "share": (current.get(n, 0.0) + extra.get(n, 0.0)) / total * 100}
            for n in names if current.get(n, 0.0) + extra.get(n, 0.0) >= 0.5]
    return {"rows": rows, "by_name": {r["name"]: r for r in rows},
            "gross": sum(r["value"] for r in rows) / total * 100}


def drift(parts: list[dict], targets: dict[str, float]) -> dict | None:
    """Each class's value against its target, and the francs to move.

    `parts` is the composition by asset class ({"name", "value"}); a class
    the targets do not name ("Autres") is aimed at zero, so the moves still
    add up to nothing -- what one class gains, another gives.
    """
    if not targets:
        return None
    current: dict[str, float] = {}
    for part in parts:
        current[part["name"]] = current.get(part["name"], 0.0) + part["value"]
    total = sum(current.values())
    if total <= 0:
        return None
    names = [*CLASSES, *(n for n in current if n not in CLASSES)]
    rows = []
    for name in names:
        value, target = current.get(name, 0.0), targets.get(name, 0.0)
        if value < 0.5 and not target:
            continue
        rows.append({"name": name, "value": round(value, 2),
                     "share": value / total * 100, "target": target,
                     "gap": round(target / 100 * total - value, 2)})
    return {"rows": rows, "total": round(total, 2),
            "buy": [r for r in sorted(rows, key=lambda r: -r["gap"]) if r["gap"] >= 0.5],
            "sell": [r for r in sorted(rows, key=lambda r: r["gap"]) if r["gap"] <= -0.5]}
