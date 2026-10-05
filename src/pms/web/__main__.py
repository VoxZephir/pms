"""Dev server entry point: python -m pms.web

Run under Werkzeug's reloader by default. Two things follow from that, and both
are the point:

* editing a source file restarts the server on its own, so an app left open
  while the backend changes is not quietly serving the code it booted with;
* the ⟳ button can perform a *real* restart, by exiting with the code the
  supervisor treats as "bring me back" (see `views.system.RESTART_EXIT_CODE`).

`--no-reload` turns the supervisor off, and with it both of those.
"""

from __future__ import annotations

import argparse
import os
import webbrowser
from pathlib import Path
from threading import Timer

from ..cli import _utf8_console
from . import DEFAULT_LEDGER, create_app


def _is_serving_process() -> bool:
    """True in the child the reloader supervises, false in the supervisor."""
    return os.environ.get("WERKZEUG_RUN_MAIN") == "true"


def main() -> int:
    _utf8_console()  # Windows consoles are cp1252 and cannot print → or é
    ap = argparse.ArgumentParser(prog="pms.web")
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    ap.add_argument("--no-reload", action="store_true",
                    help="do not restart when a source file changes "
                         "(also disables the ⟳ button's restart)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if not args.ledger.exists():
        print(f"error: {args.ledger} not found -- run `python -m pms` first")
        return 2

    app = create_app(args.ledger)
    url = f"http://{args.host}:{args.port}/"

    # Only the supervisor announces itself and opens the browser. It runs once;
    # the serving child is replaced on every restart, and opening a tab from
    # there would mean a new tab each time a file is saved.
    if not _is_serving_process():
        print(f"PMS  →  {url}   (Ctrl+C pour arrêter)")
        if not args.no_open and not args.debug:
            # "/" is the month in progress; a fresh statement's whole month
            # is one click away, announced on the page itself.
            Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, debug=args.debug,
            use_reloader=not args.no_reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
