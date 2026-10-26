"""Dev server entry point: python -m pms.web

Run under Werkzeug's reloader by default. Two things follow from that, and both
are the point:

* editing a source file restarts the server on its own, so an app left open
  while the backend changes is not quietly serving the code it booted with;
* the ⟳ button can perform a *real* restart, by exiting with the code the
  supervisor treats as "bring me back" (see `views.system.RESTART_EXIT_CODE`).

`--no-reload` turns the supervisor off, and with it both of those.

The serving process also watches the Downloads folder: a statement downloaded
on this PC is ingested within a minute (`watcher`, docs/releves.md).

The phone reaches this server through `tailscale serve`, never directly: the
server stays on 127.0.0.1 (`guard.bind_problem` refuses the rest), and when
Tailscale runs here the banner prints the address to open on the phone
(docs/acces-distant.md).
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

from ..cli import _utf8_console
from . import DEFAULT_LEDGER, create_app, guard, watcher


def _is_serving_process() -> bool:
    """True in the child the reloader supervises, false in the supervisor."""
    return os.environ.get("WERKZEUG_RUN_MAIN") == "true"


def _stay_awake() -> bool:
    """Keep Windows from sleeping on idle while this process runs.

    A phone cannot reach a laptop that dozed off after fifteen minutes. This
    is the request a video player makes: it lasts as long as the process,
    changes no setting, and does not fight a closed lid. False where it does
    not apply (not Windows) or did not take.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED))


def main() -> int:
    _utf8_console()  # Windows consoles are cp1252 and cannot print → or é
    ap = argparse.ArgumentParser(prog="pms.web")
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--host", default="127.0.0.1",
                    help="loopback (défaut) ou une adresse Tailscale ; jamais le réseau local")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    ap.add_argument("--no-reload", action="store_true",
                    help="do not restart when a source file changes "
                         "(also disables the ⟳ button's restart)")
    ap.add_argument("--allow-host", action="append", default=[], metavar="NOM",
                    help="un autre nom sous lequel l'app est servie (le nom Tailscale "
                         "est lu tout seul)")
    ap.add_argument("--allow-sleep", action="store_true",
                    help="laisser Windows se mettre en veille même quand Tailscale "
                         "rend l'app joignable depuis le téléphone")
    ap.add_argument("--watch", type=Path, metavar="DOSSIER",
                    help="dossier où les relevés téléchargés sont ramassés "
                         "(défaut : Téléchargements)")
    ap.add_argument("--no-watch", action="store_true",
                    help="ne pas ramasser les relevés téléchargés")
    ap.add_argument("--no-update-check", action="store_true",
                    help="ne pas chercher de mise à jour (git fetch, une fois par heure)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    problem = guard.bind_problem(args.host, args.debug)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    # No ledger yet is a first launch, not an error: the app opens on an
    # empty page whose one button is "Importer un relevé".

    tailnet = guard.tailnet_name()
    app = create_app(args.ledger, [*args.allow_host, *([tailnet] if tailnet else [])])
    url = f"http://{args.host}:{args.port}/"
    # The update button: a `git fetch` now and then, in the serving app only.
    app.config["PMS_UPDATES"] = not args.no_update_check

    # The watcher lives in the process that serves: under the reloader that
    # is the child, and the supervisor -- which never serves -- must not run
    # a second one beside it.
    downloads = None if args.no_watch else (args.watch or watcher.downloads_folder())
    if downloads is not None and not downloads.is_dir():
        print(f"error: {downloads} n'est pas un dossier", file=sys.stderr)
        return 2
    if downloads is not None and (args.no_reload or _is_serving_process()):
        from .views import system as system_views
        watch = watcher.Watcher(downloads, system_views.INBOX,
                                app.extensions["pms_store"])
        app.extensions["pms_watcher"] = watch
        watch.start()

    # The weekly summary's clock, in the serving process too (`notify.py`).
    if args.no_reload or _is_serving_process():
        from .. import notify
        from .api import weekly as weekly_api
        store_ = app.extensions["pms_store"]
        notify.Clock(weekly_api.notify_path(store_), lambda: weekly_api.compose(store_)).start()

    # Only the supervisor announces itself and opens the browser. It runs once;
    # the serving child is replaced on every restart, and opening a tab from
    # there would mean a new tab each time a file is saved.
    if not _is_serving_process():
        print(f"PMS  →  {url}   (Ctrl+C pour arrêter)")
        if downloads is not None:
            print(f"Relevés téléchargés ramassés dans {downloads} (--no-watch pour ne pas)")
        if tailnet:
            # `tailscale serve` answers on 443 and forwards here; the name is
            # what the certificate is issued for.
            print(f"Téléphone  →  https://{tailnet}/   (via `tailscale serve --bg {args.port}`)")
            if not args.allow_sleep and _stay_awake():
                print("Veille de Windows suspendue tant que l'app tourne "
                      "(--allow-sleep pour la laisser faire)")
        if not args.no_open and not args.debug:
            # "/" is the month in progress; a fresh statement's whole month
            # is one click away, announced on the page itself.
            Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, debug=args.debug,
            use_reloader=not args.no_reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
