"""Command line entry point: ingest, check, and get the data back out.

    python -m pms                    # ingest inbox/*.pdf and reconcile
    python -m pms --check            # same, and exit non-zero on a balance break
    python -m pms --reparse          # also re-read PDFs already imported
    python -m pms --no-ledger        # read one PDF without touching the ledger
    python -m pms --status           # what the ledger holds and where it came from
    python -m pms --forget <sha256>  # undo a bad import (digest shown by --status)
    python -m pms --export out.xlsx  # the classified transactions as CSV or xlsx
    python -m pms --capture c.json   # merge a savings capture (docs/epargne.md)
    python -m pms --3a-value 10000 --on 2026-09-22  # a 3a value read in the app

Reading the numbers is the web app's job (`python -m pms.web`). This side of the
program writes the ledger and proves it adds up.

Re-running is always safe: statements are merged into `data/ledger.json` by
(reference, currency), so re-importing the same export changes nothing while a
new or overlapping one contributes exactly its new rows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import analysis, buckets, export
from .categories import UNCATEGORISED, classify_all
from .ledger import Ledger, ingest
from .parser import parse_statement, reconcile

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "inbox"
DEFAULT_LEDGER = ROOT / "data" / "ledger.json"


def _utf8_console() -> None:
    """Windows consoles default to cp1252, which cannot print → or é."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _statements(args) -> list[Path]:
    if args.pdf:
        return [args.pdf]
    return sorted(p for p in INBOX.glob("*.pdf"))


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    ap = argparse.ArgumentParser(
        prog="pms", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, help="a single statement (default: every PDF in inbox/)")
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER, help="ledger file")
    ap.add_argument("--no-ledger", action="store_true",
                    help="read straight from the PDF without touching the ledger")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the running balance does not tie out")
    ap.add_argument("--reparse", action="store_true",
                    help="relire aussi les PDF déjà importés (après une "
                         "modification du parser)")
    ap.add_argument("--status", action="store_true", help="describe the ledger and exit")
    ap.add_argument("--forget", metavar="SHA256",
                    help="retirer les mouvements d'un import erroné (voir --status)")
    ap.add_argument("--finpension", action="store_true",
                    help="régénérer data/finpension.json depuis inbox/finpension/")
    ap.add_argument("--capture", type=Path, metavar="FICHIER.json",
                    help="fusionner une capture d'épargne (IBKR, cours du 3a, "
                         "valeur 3a) dans les snapshots — voir docs/epargne.md")
    ap.add_argument("--ibkr-journal", action="store_true",
                    help="lire l'historique des transactions IBKR "
                         "(inbox/ibkr/*TRANSACTIONS*.csv) dans le snapshot")
    ap.add_argument("--3a-value", dest="finp_value", type=float, metavar="CHF",
                    help="enregistrer une valeur 3a lue dans l'app finpension")
    ap.add_argument("--on", type=dt.date.fromisoformat, metavar="AAAA-MM-JJ",
                    help="date de --3a-value (défaut : aujourd'hui)")
    ap.add_argument("--json", type=Path, help="also dump transactions as JSON")
    ap.add_argument("--export", type=Path, metavar="FICHIER.csv|.xlsx",
                    help="also write the classified transactions as CSV or xlsx")
    ap.add_argument("--from", dest="start", type=dt.date.fromisoformat, metavar="AAAA-MM-JJ",
                    help="restrict the window to transactions on or after this date")
    ap.add_argument("--to", dest="end", type=dt.date.fromisoformat, metavar="AAAA-MM-JJ",
                    help="restrict the window to transactions on or before this date")
    args = ap.parse_args(argv)

    if args.status:
        return _status(args.ledger)

    if args.forget:
        return _forget(args.ledger, args.forget)

    if args.finpension:
        return _finpension(args.ledger)

    if args.capture or args.finp_value is not None:
        return _capture(args)

    if args.ibkr_journal:
        return _ibkr_journal(args.ledger)

    sources = _statements(args)
    if not sources:
        print(f"error: no PDF found in {INBOX}", file=sys.stderr)
        return 2
    missing = [p for p in sources if not p.exists()]
    if missing:
        print(f"error: {missing[0]} not found", file=sys.stderr)
        return 2

    problems: list[str] = []

    if args.no_ledger:
        statement = parse_statement(sources[0])
        problems = reconcile(statement)
        if args.start or args.end:
            print("note : --from/--to sont ignorés avec --no-ledger", file=sys.stderr)
        print(f"{sources[0].name}: {len(statement.transactions)} transactions")
    else:
        ledger, imports = ingest(sources, args.ledger, parse_statement,
                                 reparse=args.reparse)
        for entry in imports:
            if entry.get("skipped"):
                print(f"{entry['file']}: déjà importé, non relu "
                      f"(--reparse pour le relire)")
                continue
            print(f"{entry['file']}: {entry['rows']} lignes → "
                  f"{entry['added']} nouvelles, {entry['already_known']} déjà connues"
                  + (f", {entry['conflicts']} EN CONFLIT" if entry["conflicts"] else ""))
            for conflict in entry["conflict_detail"][:5]:
                print(f"    ! {conflict['key']}: stocké {conflict['stored']} "
                      f"vs reçu {conflict['incoming']}", file=sys.stderr)

        breaks = ledger.gaps()
        for gap in breaks:
            problems.append(
                f"{gap['currency']}: trou entre {gap['after']} et {gap['before']} "
                f"({gap['missing']:+.2f} manquants, réf {gap['between_refs']})"
            )
        ledger.save()
        print(f"ledger: {len(ledger)} mouvements, {len(ledger.sources)} import(s) "
              f"→ {args.ledger}")
        statement = ledger.to_statement(args.start, args.end)
        if args.start or args.end:
            print(f"  période retenue : {statement.period_start} → {statement.period_end} "
                  f"({len(statement.transactions)} mouvements)")

    classify_all(statement.transactions)
    analysis.annotate_chf(statement)

    if problems:
        print(f"  ! {len(problems)} rupture(s) de solde :", file=sys.stderr)
        for line in problems[:10]:
            print(f"    {line}", file=sys.stderr)
    else:
        print("  solde courant rapproché sur chaque ligne — aucun écart")

    unknown = [t for t in statement.transactions
               if t.category == UNCATEGORISED and t.amount_chf < 0]
    spend = sum(abs(t.amount_chf) for t in analysis.spending(statement))
    if unknown and spend:
        share = sum(abs(t.amount_chf) for t in unknown) / spend * 100
        print(f"  {len(unknown)} débits non catégorisés ({share:.1f}% des dépenses)")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps([t.to_dict() for t in statement.transactions],
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"  écrit {args.json}")

    if args.export:
        # Buckets are not part of the ingestion path -- the CLI never needed
        # them -- but they are one of the exported columns, so annotate here
        # rather than shipping a column that is always blank.
        buckets.annotate(statement.transactions)
        try:
            path = export.write(statement.transactions, args.export,
                                statement.period_start, statement.period_end)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"  écrit {path} ({len(statement.transactions)} lignes)")

    if not args.check and not args.json and not args.export:
        print("  ouvrez le tableau de bord :  python -m pms.web")

    # A balance break is a hard failure whether or not --check asked for it: the
    # exit code is what a scheduled run would look at.
    return 1 if problems else 0


def _finpension(ledger_path: Path) -> int:
    """Rebuild the 3a snapshot from the documents in inbox/finpension/."""
    from . import finpension
    source = ledger_path.parent / "finpension.json"
    snapshot = finpension.regenerate(
        INBOX / "finpension" / "rapport_de_transactions.csv",
        INBOX / "finpension", source)
    print(f"finpension : {snapshot['value']:.2f} CHF au {snapshot['value_as_of']} "
          f"(déposé {snapshot['deposits']:.2f}, frais {snapshot['fees']:.2f}) → {source}")
    return 0


def _capture(args) -> int:
    """Merge a savings capture, or record one 3a reading, next to the ledger."""
    from . import snapshots
    ibkr_path = args.ledger.parent / "ibkr.json"
    finp_path = args.ledger.parent / "finpension.json"
    capture: dict = {}
    if args.capture:
        try:
            capture = json.loads(args.capture.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: capture illisible : {exc}", file=sys.stderr)
            return 2
    if args.finp_value is not None:
        capture["finpension_value"] = {
            "value": args.finp_value,
            "on": (args.on or dt.date.today()).isoformat()}
    missing = [p.name for key, p in (("ibkr", ibkr_path),
                                     ("proxy_series", finp_path),
                                     ("finpension_value", finp_path))
               if key in capture and not p.exists()]
    if missing:
        print(f"error: snapshot absent : {', '.join(sorted(set(missing)))}",
              file=sys.stderr)
        return 2
    try:
        report = snapshots.merge(capture, ibkr_path, finp_path)
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for series, added in report.get("ibkr", {}).items():
        print(f"IBKR {series} : +{added} point(s)")
    for series, added in report.get("proxy_series", {}).items():
        print(f"3a {series} : +{added} point(s)")
    if "finpension_value" in report:
        entry = report["finpension_value"]
        print(f"3a : {entry['value']:.2f} CHF relevés le {entry['on']}")
    for line in snapshots.describe(ibkr_path, finp_path):
        print(f"  {line}")
    return 0


def _ibkr_journal(ledger_path: Path) -> int:
    """Read the newest IBKR transaction history export into the snapshot."""
    from . import snapshots
    exports = sorted((INBOX / "ibkr").glob("*TRANSACTIONS*.csv"),
                     key=lambda p: p.stat().st_mtime)
    ibkr_path = ledger_path.parent / "ibkr.json"
    if not exports:
        print(f"error: aucun export dans {INBOX / 'ibkr'}", file=sys.stderr)
        return 2
    if not ibkr_path.exists():
        print("error: snapshot absent : ibkr.json", file=sys.stderr)
        return 2
    try:
        journal = snapshots.merge_journal(exports[-1], ibkr_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    net = sum(amount for _, amount in journal["flows"])
    costs = sum(c["amount_chf"] for c in journal["costs"])
    print(f"IBKR : {exports[-1].name} — {journal['first']} → {journal['last']}, "
          f"{len(journal['flows'])} versements/retraits (net {net:.2f} CHF), "
          f"frais {costs:.2f} CHF")
    return 0


def _forget(ledger_path: Path, sha256: str) -> int:
    """Undo a bad import: drop its rows and its log entry, then save."""
    ledger = Ledger.load(ledger_path)
    removed = ledger.forget(sha256)
    if removed is None:
        print(f"error: aucun import avec le sha256 {sha256} "
              f"(voir --status)", file=sys.stderr)
        return 2
    ledger.save()
    print(f"oublié : {removed['file']} — {removed['rows']} mouvement(s) retirés")
    breaks = ledger.gaps()
    if breaks:
        print(f"  ! {len(breaks)} rupture(s) de solde restante(s) : réimporter "
              f"le bon relevé les fermera", file=sys.stderr)
        for gap in breaks[:5]:
            print(f"    {gap['currency']} entre {gap['after']} et {gap['before']} : "
                  f"{gap['missing']:+.2f}", file=sys.stderr)
    else:
        print("  chaîne des soldes intacte")
    return 0


def _status(ledger_path: Path) -> int:
    ledger = Ledger.load(ledger_path)
    if not len(ledger):
        print(f"ledger vide ({ledger_path})")
        return 0
    rows = ledger.ordered()
    print(f"ledger : {len(ledger)} mouvements, {rows[0].date} → {rows[-1].date}")
    print(f"compte : {ledger.account.get('iban')} · {ledger.account.get('holder')}")
    print("imports :")
    for source in ledger.sources:
        digest = source.get("sha256") or "?"
        print(f"  {source['ingested_at']}  {source['file']}  "
              f"[{source['period_start']} → {source['period_end']}]  "
              f"+{source['added']} / {source['rows']}  sha {digest}")
    print("pour oublier un import :  python -m pms --forget <sha>")
    breaks = ledger.gaps()
    print(f"intégrité : {'aucun trou détecté' if not breaks else str(len(breaks)) + ' rupture(s)'}")
    for gap in breaks[:10]:
        print(f"  {gap['currency']} entre {gap['after']} et {gap['before']} : "
              f"{gap['missing']:+.2f}")
    from . import snapshots
    savings = snapshots.describe(ledger_path.parent / "ibkr.json",
                                 ledger_path.parent / "finpension.json")
    if savings:
        print("épargne :")
        for line in savings:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
