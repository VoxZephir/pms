"""A saved scenario, its transfers to the brokerage account smoothed into one
monthly standing order -- the same low point of cash, a constant amount.

The app does the same from Prévisions › Scénarios (« Lisser les virements
IBKR »); this is its command-line twin, on `plans.smooth_taxable`.

    .venv/Scripts/python tools/lisser_ibkr.py "Loyer 1'960"            # 1 year
    .venv/Scripts/python tools/lisser_ibkr.py "Loyer 1'960" --months 24 --dry-run

The result is saved as a new scenario beside the original, which is left as
it was, and the plan on screen does not change. plans.json is copied to
plans.json.bak first.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pms import plans  # noqa: E402
from pms.analysis import chf  # noqa: E402
from pms.web.store import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scenario", help="le nom du scénario à lisser, tel que l'app l'affiche")
    ap.add_argument("--months", type=int, default=12, help="horizon vérifié, en mois (défaut 12)")
    ap.add_argument("--step", type=int, default=50, help="arrondi du versement, en CHF (défaut 50)")
    ap.add_argument("--in-months", default="", help="mois de l'année seulement, ex. 5,6,7,8,9,10,11,12")
    ap.add_argument("--name", help="nom du nouveau scénario (défaut : « <scénario> — IBKR mensuel »)")
    ap.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger.json")
    ap.add_argument("--dry-run", action="store_true", help="calculer et montrer, sans rien écrire")
    args = ap.parse_args()

    store = Store(args.ledger)
    path = args.ledger.with_name("plans.json")
    plan = plans.Plan.load(path)
    if args.scenario not in plan.plan_scenarios:
        names = ", ".join(f"« {n} »" for n in plan.plan_scenarios) or "aucun"
        print(f"Pas de scénario « {args.scenario} ». Scénarios : {names}.")
        return 1

    result = plans.smooth_taxable(store.statement, plan.scenario_plan(args.scenario),
                                  months=args.months, step=args.step, in_months=args.in_months)
    if result is None:
        print("Même sans aucun virement vers le placement, le cash descend plus bas que dans "
              "le scénario : rien à lisser.")
        return 1
    b, a = result["before"], result["after"]
    name = (args.name or f"{args.scenario} — IBKR mensuel").strip()
    print(f"« {args.scenario} », sur {args.months} mois")
    print(f"  avant : point bas {chf(b['low'])} CHF ({b['low_label']}), {chf(b['moved'])} CHF vers le placement")
    print(f"  après : {chf(result['amount'])} CHF par mois ({result['in_months_label']}), point bas "
          f"{chf(a['low'])} CHF ({a['low_label']}), {chf(a['moved'])} CHF vers le placement "
          f"({chf(a['moved'] - b['moved'])})")
    print()
    print(f"  {'mois':<16}{'cash avant':>12}{'cash après':>12}")
    for r in result["rows"]:
        print(f"  {r['label']:<16}{chf(r['before']):>12}{chf(r['after']):>12}")
    if args.dry_run:
        print("\n--dry-run : rien n'est écrit.")
        return 0

    shutil.copy(path, path.with_name("plans.json.bak"))
    plan.plan_scenarios[name] = result["declarations"]
    plan.save()
    print(f"\nScénario « {name} » enregistré (copie de l'ancien fichier : plans.json.bak). "
          "Il est dans Prévisions › Scénarios ; le plan affiché n'a pas changé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
