"""A saved scenario, its transfers to the brokerage account smoothed into one
monthly standing order -- the same low point of cash, a constant amount.

    .venv/Scripts/python tools/lisser_ibkr.py "Loyer 1'960"            # 1 year
    .venv/Scripts/python tools/lisser_ibkr.py "Loyer 1'960" --months 24 --dry-run

Every transfer the scenario sends to the taxable pocket (one-offs "vers le
placement" and series) is taken out; the 3a and everything else stay. The
highest whole amount paid each month from the first full month keeps the
lowest month-end cash at or above the original scenario's: the projection is
`plans.project`, the one the page draws, so the page shows the same numbers.
The result is saved as a new scenario beside the original, which is left as
it was, and the plan on screen does not change. plans.json is copied to
plans.json.bak first.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pms import plans  # noqa: E402
from pms.analysis import chf  # noqa: E402
from pms.web.store import Store  # noqa: E402


def lowest(statement, plan: plans.Plan, months: int) -> tuple[float, str, list[dict]]:
    rows = plans.project(statement, plan, months_ahead=months)["rows"]
    low = min(rows, key=lambda r: r["end"])
    return low["end"], low["label"], rows


def without_taxable(declarations: dict) -> dict:
    out = json.loads(json.dumps(declarations))
    out["one_offs"] = [e for e in out["one_offs"] if e.get("transfer") != plans.TAXABLE]
    out["contributions"] = [c for c in out["contributions"] if c["pocket"] != plans.TAXABLE]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scenario", help="le nom du scénario à lisser, tel que l'app l'affiche")
    ap.add_argument("--months", type=int, default=12, help="horizon vérifié, en mois (défaut 12)")
    ap.add_argument("--step", type=int, default=50, help="arrondi du versement, en CHF (défaut 50)")
    ap.add_argument("--name", help="nom du nouveau scénario (défaut : « <scénario> — IBKR mensuel »)")
    ap.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger.json")
    ap.add_argument("--dry-run", action="store_true", help="calculer et montrer, sans rien écrire")
    args = ap.parse_args()

    store = Store(args.ledger)
    statement = store.statement
    path = args.ledger.with_name("plans.json")
    plan = plans.Plan.load(path)
    if args.scenario not in plan.plan_scenarios:
        names = ", ".join(f"« {n} »" for n in plan.plan_scenarios) or "aucun"
        print(f"Pas de scénario « {args.scenario} ». Scénarios : {names}.")
        return 1

    source = plan.scenario_plan(args.scenario)
    original = source._declarations()
    target, target_label, before = lowest(statement, source, args.months)
    moved_before = sum(o["amount"] for r in before for o in r["one_offs"]
                       if o.get("transfer") == plans.TAXABLE)

    base = without_taxable(original)

    def candidate(amount: int) -> plans.Plan:
        spec = json.loads(json.dumps(base))
        if amount > 0:
            spec["contributions"].append({"pocket": plans.TAXABLE, "amount": float(amount),
                                          "every": "month", "months": args.months, "start": ""})
        return plans._detached(spec)

    if lowest(statement, candidate(0), args.months)[0] < target:
        print("Même sans aucun virement vers le placement, le cash descend plus bas que dans "
              "le scénario : rien à lisser.")
        return 1
    # The low point only falls as the amount rises: the highest amount that
    # keeps it is found by halving, on whole steps.
    lo, hi = 0, args.step
    while lowest(statement, candidate(hi), args.months)[0] >= target:
        lo, hi = hi, hi * 2
    while hi - lo > args.step:
        mid = (lo + hi) // 2 // args.step * args.step
        if mid in (lo, hi):
            break
        if lowest(statement, candidate(mid), args.months)[0] >= target:
            lo = mid
        else:
            hi = mid
    amount = lo
    smooth = candidate(amount)
    low_after, low_label, after = lowest(statement, smooth, args.months)
    moved_after = sum(o["amount"] for r in after for o in r["one_offs"]
                      if o.get("transfer") == plans.TAXABLE)

    name = (args.name or f"{args.scenario} — IBKR mensuel").strip()
    print(f"« {args.scenario} », sur {args.months} mois")
    print(f"  avant : point bas {chf(target)} CHF ({target_label}), "
          f"{chf(moved_before)} CHF vers le placement")
    print(f"  après : {chf(amount)} CHF chaque mois, point bas {chf(low_after)} CHF ({low_label}), "
          f"{chf(moved_after)} CHF vers le placement ({chf(moved_after - moved_before)})")
    print()
    print(f"  {'mois':<16}{'cash avant':>12}{'cash après':>12}")
    for b, a in zip(before, after):
        print(f"  {b['label']:<16}{chf(b['end']):>12}{chf(a['end']):>12}")
    if args.dry_run:
        print("\n--dry-run : rien n'est écrit.")
        return 0

    shutil.copy(path, path.with_name("plans.json.bak"))
    plan.plan_scenarios[name] = smooth._declarations()
    plan.save()
    print(f"\nScénario « {name} » enregistré (copie de l'ancien fichier : plans.json.bak). "
          "Il est dans Prévisions › Scénarios ; le plan affiché n'a pas changé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
