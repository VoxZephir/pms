"""Monthly spending goals, declared in `data/budgets.json`.

The 50/30/20 reference is a generic convention, not a goal. A budget is a
declared amount per category -- "max 400 CHF/month on restaurants" -- and
the only honest place for it is outside the ledger, like the overrides:
the ledger is what the bank printed, and a goal is a decision.

Missing or corrupt is not fatal: the monthly view runs without gauges.
"""

from __future__ import annotations

import json
from pathlib import Path

VERSION = 1


class Budgets:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.amounts: dict[str, float] = {}

    @classmethod
    def load(cls, path: Path | str) -> "Budgets":
        store = cls(path)
        if not store.path.exists():
            return store
        try:
            raw = json.loads(store.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return store
        for category, amount in (raw.get("budgets") or {}).items():
            try:
                value = float(amount)
            except (TypeError, ValueError):
                continue
            if value > 0 and category:
                store.amounts[str(category)] = round(value, 2)
        return store

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": VERSION, "budgets": self.amounts}
        # Write then move, so an interrupted save cannot leave a truncated file.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        temporary.replace(self.path)
        return self.path

    def set_budget(self, category: str, amount: float) -> None:
        self.amounts[category] = round(float(amount), 2)

    def remove(self, category: str) -> bool:
        return self.amounts.pop(category, None) is not None
