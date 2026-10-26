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
    python -m pms --backup [DOSSIER] # zip and encrypt data/ and inbox/ (default: OneDrive)
    python -m pms --restore ARCHIVE  # decrypt a backup back into data/ and inbox/
    python -m pms --ibkr             # IBKR from its Flex Web Service (data/ibkr_flex.json)
    python -m pms --refresh [--daily] # IBKR, public prices, crypto -- run.bat, once a day

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

from . import analysis, banks, buckets, export
from .categories import UNCATEGORISED, classify_all
from .ledger import Ledger, ingest, primary_start
from .parser import reconcile

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
    return banks.discover(INBOX)


def _twint_report(ledger_path: Path) -> int:
    """The analysis behind the triage's suggestions, on the ledger as the app
    sees it (corrections applied). Aggregates only: safe to paste anywhere."""
    from . import twint
    from .web.store import Store

    if not ledger_path.exists():
        print(f"error: pas de ledger à {ledger_path}", file=sys.stderr)
        return 2
    twint.print_report(Store(ledger_path).statement)
    return 0


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
    ap.add_argument("--twint-report", action="store_true",
                    help="the Twints sorted by hand, by amount and day, and how often the "
                         "triage's suggestions would have been right")
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
    ap.add_argument("--crypto", action="store_true",
                    help="lire le relevé crypto Revolut (inbox/revolut/crypto/) et "
                         "le valoriser aux cours publics (data/crypto.json)")
    ap.add_argument("--benchmarks", action="store_true",
                    help="capturer les indices de référence publics (S&P 500, "
                         "Nasdaq, or…) en CHF dans data/benchmarks.json")
    ap.add_argument("--ibkr", action="store_true",
                    help="mettre à jour data/ibkr.json depuis le service Flex d'IBKR "
                         "(jeton et requête dans data/ibkr_flex.json)")
    ap.add_argument("--refresh", action="store_true",
                    help="IBKR (Flex), repères, indices du 3a et crypto, chacun "
                         "indépendamment ; un échec n'arrête pas les autres")
    ap.add_argument("--daily", action="store_true",
                    help="avec --refresh : seulement si le dernier date de plus de 20 h")
    ap.add_argument("--crypto-qty", metavar="ETH=Q,SOL=Q",
                    help="avec --crypto : quantités lues dans l'app Revolut, pour caler "
                         "les récompenses de staking")
    ap.add_argument("--3a-value", dest="finp_value", type=float, metavar="CHF",
                    help="enregistrer une valeur 3a lue dans l'app finpension")
    ap.add_argument("--on", type=dt.date.fromisoformat, metavar="AAAA-MM-JJ",
                    help="date de --3a-value (défaut : aujourd'hui)")
    ap.add_argument("--backup", nargs="?", const="", metavar="DOSSIER",
                    help="zipper et chiffrer data/ et inbox/ vers DOSSIER (défaut : "
                         "OneDrive/PMS-sauvegardes) ; rien n'est écrit si rien "
                         "n'a changé depuis la dernière copie")
    ap.add_argument("--keep", type=int, default=10, metavar="N",
                    help="avec --backup : nombre de copies gardées (défaut 10)")
    ap.add_argument("--restore", type=Path, metavar="ARCHIVE",
                    help="déchiffrer une sauvegarde (.zip.enc) et redéposer data/ et "
                         "inbox/, sans rien écraser ; la clé est lue dans "
                         "data/backup.key, ou demandée")
    ap.add_argument("--into", type=Path, metavar="DOSSIER",
                    help="avec --restore : où redéposer (défaut : la racine du dépôt)")
    ap.add_argument("--redact", type=Path, nargs="+", metavar="PDF",
                    help="caviarder des PDF (IBAN, noms propres, adresses) vers "
                         "output/caviarde/ : le texte est retiré du fichier, pas masqué")
    ap.add_argument("--also", default="", metavar="TERMES",
                    help="avec --redact : d'autres termes à retirer, séparés par des virgules")
    ap.add_argument("--spare", default="", metavar="TERMES",
                    help="avec --redact : des termes à laisser (le nom de la banque…)")
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

    if args.twint_report:
        return _twint_report(args.ledger)

    if args.forget:
        return _forget(args.ledger, args.forget)

    if args.redact:
        return _redact(args.redact, None, args.also, args.spare)

    if args.backup is not None:
        return _backup(args.ledger.parent, args.backup, args.keep)

    if args.restore:
        return _restore(args.ledger.parent, args.restore, args.into)

    if args.finpension:
        return _finpension(args.ledger)

    if args.capture or args.finp_value is not None:
        return _capture(args)

    if args.ibkr_journal:
        return _ibkr_journal(args.ledger)

    if args.crypto:
        return _crypto(args.ledger, args.crypto_qty)

    if args.benchmarks:
        return _benchmarks(args.ledger)

    if args.ibkr:
        return _ibkr_flex(args.ledger)

    if args.refresh:
        return _refresh(args.ledger, args.daily)

    sources = _statements(args)
    if not sources:
        print(f"error: aucun relevé dans {INBOX}", file=sys.stderr)
        return 2
    missing = [p for p in sources if not p.exists()]
    if missing:
        print(f"error: {missing[0]} not found", file=sys.stderr)
        return 2

    problems: list[str] = []

    if args.no_ledger:
        statement = banks.parser_for(sources[0])(sources[0])
        problems = reconcile(statement)
        if args.start or args.end:
            print("note : --from/--to sont ignorés avec --no-ledger", file=sys.stderr)
        print(f"{sources[0].name}: {len(statement.transactions)} transactions")
    else:
        ledger, imports = ingest(sources, args.ledger, reparse=args.reparse, strict=False)
        for entry in imports:
            if entry.get("refused"):
                print(f"{entry['file']}: REFUSÉ — {entry['refused']} "
                      f"Retirez-le d'inbox/.", file=sys.stderr)
                continue
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
        if ledger.deduped:
            print(f"  {ledger.deduped} doublon(s) retiré(s) : le même mouvement importé deux fois "
                  f"sous deux formats d'export")
        statement = ledger.to_statement(args.start, args.end)
        if args.start or args.end:
            print(f"  période retenue : {statement.period_start} → {statement.period_end} "
                  f"({len(statement.transactions)} mouvements)")

    classify_all(statement.transactions, holder=statement.holder)
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
        # Not "python -m pms.web": the system's Python does not know pms,
        # only the project's .venv does -- and run.bat starts it.
        print("  ouvrez l'app :  .\\run.bat  (sans option)")

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


def _benchmarks(ledger_path: Path) -> int:
    """The public indices, recaptured whole; the 3a's proxies, extended."""
    from . import benchmarks, snapshots
    data_dir = ledger_path.parent
    snap = benchmarks.capture(data_dir / "benchmarks.json", dt.date(2023, 1, 1))
    for key, series in snap["series"].items():
        print(f"  {benchmarks.label(key):28} {len(series)} jours, "
              f"{series[0][0]} → {series[-1][0]}")
    code = 0
    if snap["failed"]:
        print("  échec : " + ", ".join(snap["failed"]), file=sys.stderr)
        code = 1
    finp = data_dir / "finpension.json"
    if finp.exists():
        raw = json.loads(finp.read_text(encoding="utf-8"))
        ends = [s[-1][0] for s in (raw.get("proxy_series") or {}).values() if s]
        start = (dt.date.fromisoformat(min(ends)) - dt.timedelta(days=7) if ends
                 else dt.date.today() - dt.timedelta(days=30))
        try:
            # Sessions that closed: today's bar is still moving, and an
            # appended point is never rewritten.
            points = benchmarks.proxies(start, dt.date.today() - dt.timedelta(days=1))
            added = snapshots.merge({"proxy_series": points}, data_dir / "ibkr.json",
                                    finp)["proxy_series"]
            print("  indices du 3a : " + " · ".join(f"{name} +{n}" for name, n in added.items()))
        except (OSError, KeyError, ValueError, TypeError) as exc:
            print(f"  indices du 3a non prolongés ({type(exc).__name__})", file=sys.stderr)
            code = 1
    return code


def _ibkr_flex(ledger_path: Path) -> int:
    from . import flex
    try:
        report = flex.refresh(ledger_path.parent / "ibkr_flex.json",
                              ledger_path.parent / "ibkr.json")
    except flex.FlexError as exc:
        print(f"IBKR : {exc}", file=sys.stderr)
        return 2
    journal = report.get("journal")
    print(f"IBKR : {report['value']:.2f} CHF au {report['end']} · NAV +{report['nav']} jour(s), "
          f"cours +{report['nav_daily']}, frais +{report['costs']}"
          + (f", versements +{journal['flows']}, revenus +{journal['income']}" if journal
             else " · versements lus dans le relevé bancaire (historique IBKR jamais importé)"))
    if report.get("sold"):
        print(f"  vendu depuis la dernière fois : {', '.join(report['sold'])}")
    if journal and journal["gap"]:
        print(f"  ! jours non lus entre le {journal['gap'][0]} et le {journal['gap'][1]} : "
              f"allonger la période de la requête Flex, ou réimporter l'historique "
              f"(--ibkr-journal)", file=sys.stderr)
    return 0


def _cpi(ledger_path: Path) -> int:
    from . import cpi
    report = cpi.refresh(ledger_path.parent / "cpi.json")
    for line in report["tried"]:
        print(f"inflation : {line}")
    if report["ok"]:
        print(f"inflation : {report['source']}, jusqu'à {report['last']}")
        return 0
    print("inflation : aucune source vérifiée, les chiffres de l'app restent", file=sys.stderr)
    return 0


def _refresh(ledger_path: Path, daily: bool) -> int:
    """What moves without a bank statement: IBKR (Flex), the public prices
    (indices and the 3a's proxies), the inflation, the crypto (`refresh.py`,
    shared with the savings page's button). Each step on its own: one that
    fails says so and the others still run -- run.bat calls this at launch,
    and a site that is down must not keep the app from starting. The day is
    marked done only when every step went through, so a failed one is
    retried at the next launch."""
    from . import refresh
    data_dir = ledger_path.parent
    if daily and not refresh.due(data_dir):
        last = dt.datetime.fromisoformat(refresh.load(data_dir)["at"])
        print(f"cours et IBKR rafraîchis le {last:%d.%m à %H:%M} : rien à faire")
        return 0
    record = refresh.run(ledger_path, INBOX, echo=True)
    failed = [r["name"] for r in record["last"]["steps"] if r["ok"] is False]
    if failed:
        print(f"à réessayer au prochain lancement : {', '.join(failed)}", file=sys.stderr)
    return 0


def _redact(sources: list[Path], folder: Path | None, also: str, spare: str) -> int:
    from . import redact
    if not redact.available():
        print("Le caviardage demande PyMuPDF (groupe dev) : lancer `uv sync --extra web --inexact`, "
              "ou caviarder.bat qui le fait.")
        return 1
    folder = folder or redact.OUTPUT
    failed = 0
    for source in sources:
        if not source.is_file() or source.suffix.lower() != ".pdf":
            print(f"{source.name} : pas un PDF, ignoré.")
            failed += 1
            continue
        target = folder / f"{source.stem}-caviarde.pdf"
        try:
            report = redact.redact(source, target, redact.terms(also), redact.terms(spare))
        except Exception as exc:
            print(f"{source.name} : ÉCHEC — {exc}")
            target.unlink(missing_ok=True)
            failed += 1
            continue
        kinds = report.by_kind()
        print(f"{source.name} → {target}")
        print(f"  {report.pages} page(s), {len(report.found)} passage(s) retiré(s) : "
              + (", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "rien trouvé"))
        names = sorted({f.text for f in report.found if f.kind != "IBAN"})
        if names:
            print("  dont : " + ", ".join(redact.mask(n) for n in names[:12])
                  + (f" et {len(names) - 12} autre(s)" if len(names) > 12 else ""))
        print("  relu après coup : aucun passage retiré n'est encore lisible. "
              "Parcourir le PDF avant de l'envoyer reste la dernière vérification.")
    return 1 if failed else 0


def _backup(data_dir: Path, folder: str, keep: int) -> int:
    from . import backup
    now = dt.datetime.now()
    status = backup.read_status(data_dir)

    def failed(message: str) -> int:
        print(f"sauvegarde : {message}", file=sys.stderr)
        backup.write_status(data_dir, {**status, "ran_at": now.isoformat(timespec="seconds"),
                                       "ok": False, "error": message})
        return 2

    dest = Path(folder) if folder else backup.default_destination()
    if dest is None:
        return failed("OneDrive introuvable — python -m pms --backup DOSSIER")
    try:
        key, created = backup.ensure_key(data_dir)
        if created:
            # The key is never printed: the console is where screenshots
            # come from. The user opens the file and copies it.
            print(f"sauvegarde : clé de chiffrement créée, {backup.key_path(data_dir)} — "
                  "copie son contenu dans ton gestionnaire de mots de passe : "
                  "sans elle, aucune sauvegarde ne se relit")
        done = backup.backup({"data": data_dir, "inbox": INBOX}, dest, keep, key=key,
                             repo=ROOT, exclude={backup.key_path(data_dir),
                                                 backup.status_path(data_dir)})
    except (ValueError, OSError) as exc:
        return failed(str(exc))
    if done["skipped"]:
        print(f"sauvegarde : rien n'a changé depuis {done['path'].name} ({dest})")
    else:
        print(f"sauvegarde : {done['path'].name}, {done['files']} fichiers chiffrés, "
              f"{done['bytes'] / 1e6:.1f} Mo → {dest} · {done['kept']} copie(s) gardée(s)"
              + (f", {len(done['removed'])} ancienne(s) retirée(s)" if done["removed"] else ""))
    if done["plain"]:
        print(f"sauvegarde : {len(done['plain'])} copie(s) d'avant le chiffrement, lisibles "
              f"par quiconque ouvre {dest} — à supprimer une fois la clé rangée")
    status = {**status, "ran_at": now.isoformat(timespec="seconds"), "ok": True, "error": "",
              "copy": done["path"].name, "dest": str(dest)}
    # A copy just written is always read back; an unchanged one once a week.
    if not done["skipped"] or backup.due(status, done["path"], now):
        try:
            count = backup.verify(done["path"], key)
        except ValueError as exc:
            return failed(f"la copie ne se relit pas — {exc}")
        print(f"sauvegarde : {done['path'].name} relue en entier, {count} fichiers intacts")
        status.update(verified_at=now.isoformat(timespec="seconds"),
                      verified_copy=done["path"].name, files=count)
    backup.write_status(data_dir, status)
    return 0


def _restore(data_dir: Path, archive: Path, into: Path | None) -> int:
    """Decrypt a backup back into place. The key comes from data/backup.key,
    or -- on a fresh clone, after a lost disk -- from the password manager,
    typed without echo."""
    from getpass import getpass

    from . import backup
    target = Path(into) if into else ROOT
    if target.resolve() != ROOT.resolve() and backup._inside(target, ROOT):
        # Outside data/ and inbox/, the restored statements would not be
        # git-ignored.
        print(f"restauration : {target} est dans le dépôt sans en être la racine — "
              "data/ et inbox/ n'y seraient pas exclus de git", file=sys.stderr)
        return 2
    try:
        key = backup.load_key(data_dir)
        if key is None:
            key = backup.check_key(getpass("Clé de sauvegarde (gestionnaire de mots "
                                           "de passe) : ").encode("ascii", "replace"))
        restored = backup.restore(archive, key, target)
    except (ValueError, OSError, EOFError) as exc:
        print(f"restauration : {exc}", file=sys.stderr)
        return 2
    print(f"restauration : {len(restored)} fichiers de {archive.name} → {target}")
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


def _crypto(ledger_path: Path, quantities: str | None = None) -> int:
    from . import crypto
    exports = sorted((INBOX / "revolut" / "crypto").glob("*.csv"),
                     key=lambda p: p.stat().st_mtime)
    if not exports:
        print(f"error: aucun relevé dans {INBOX / 'revolut' / 'crypto'}", file=sys.stderr)
        return 2
    actual = None
    if quantities:
        today = dt.date.today()
        try:
            actual = {k.strip().upper(): (today, float(v))
                      for k, v in (pair.split("=") for pair in quantities.split(","))}
        except ValueError:
            print("error: --crypto-qty attend ETH=0.5,SOL=10", file=sys.stderr)
            return 2
    snap = crypto.capture(exports[-1], ledger_path.parent / "crypto.json", ledger_path,
                          actual=actual)
    for p in snap["positions"]:
        value = f"{p['value_chf']:.2f}" if p["value_chf"] is not None else "sans cours"
        rewards = p.get("rewards") or {}
        note = ""
        if rewards:
            note = (f" · dont {rewards['quantity']:.6f} de récompenses "
                    f"({rewards['count']}, {'calées sur l’app' if rewards['calibrated'] else 'estimées'})")
        print(f"  {p['symbol']:5} {p['quantity']:.8f}  valeur {value} CHF · coût {p['cost_chf']:.2f}{note}")
    print(f"crypto : {snap['value_chf']:.2f} CHF pour {snap['cost_chf']:.2f} CHF de coût, "
          f"{len(snap['daily'])} jours valorisés → {ledger_path.parent / 'crypto.json'}")
    if snap["unread"]:
        print("  sans quantité lisible (récompenses « Apprendre ») : " + ", ".join(snap["unread"]))
    return 0


def _status(ledger_path: Path) -> int:
    ledger = Ledger.load(ledger_path)
    if not len(ledger):
        print(f"ledger vide ({ledger_path})")
        return 0
    rows = ledger.ordered()
    print(f"ledger : {len(ledger)} mouvements, {rows[0].date} → {rows[-1].date}")
    print(f"compte : {ledger.account.get('iban')} · {ledger.account.get('holder')}")
    first = primary_start(rows)
    for account in sorted({t.account for t in rows if t.account}):
        own = [t for t in rows if t.account == account]
        early = [t for t in own if first and t.date < first]
        print(f"  + {account} : {len(own)} mouvements, {own[0].date} → {own[-1].date}"
              + (f" · {len(early)} antérieurs au compte principal ({first}), "
                 f"gardés hors analyse" if early else ""))
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
        print(f"  {gap.get('account') + ' ' if gap.get('account') else ''}{gap['currency']} entre {gap['after']} et {gap['before']} : "
              f"{gap['missing']:+.2f}")
    from . import snapshots
    savings = snapshots.describe(ledger_path.parent / "ibkr.json",
                                 ledger_path.parent / "finpension.json")
    savings += _market_status(ledger_path.parent)
    if savings:
        print("épargne :")
        for line in savings:
            print(f"  {line}")
    return 0


def _market_status(data_dir: Path) -> list[str]:
    """Where the public-price snapshots stop: the crypto pocket and the
    reference indices, both recaptured without the IBKR connector."""
    from . import benchmarks, crypto
    lines = []
    snap = crypto.load(data_dir / "crypto.json")
    if snap and snap.get("daily_series"):
        lines.append(f"crypto : cours jusqu'au {snap['daily_series'][-1][0]} "
                     f"(--crypto){' · staking calé sur l’app' if snap.get('calibration') else ''}")
    raw = benchmarks.load_raw(data_dir / "benchmarks.json")
    if raw and raw.get("series"):
        ends = {key: series[-1][0] for key, series in raw["series"].items() if series}
        bases = raw.get("bases") or {}
        price = [k for k in ends if bases.get(k) != benchmarks.BASIS]
        lines.append(f"repères : {len(ends)} indices jusqu'au {min(ends.values())} "
                     f"(--benchmarks)"
                     + (f" · prix seuls : {', '.join(price)}" if price else ""))
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
