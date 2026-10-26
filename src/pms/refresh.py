"""What moves without a bank statement, fetched again: IBKR (the Flex
service), the public indices and the 3a's proxies, the inflation, the crypto
(`docs/epargne.md`, « Rafraîchir »).

One list of steps for the two callers: `run.bat` at launch (`--refresh
--daily`, once a day) and the button on the savings page. Each step runs on
its own -- one that fails says so and the others still run -- and what it
prints is kept, step by step, so the page shows the console's own words.
None of them prints a token: the Flex one stays in its file.

`data/refresh.json` keeps `at`, the last time every step went through (the
daily run skips until it is 20 hours old), and `last`, the last attempt with
each step's outcome, whatever it was.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
from pathlib import Path

STAMP = "refresh.json"
EVERY = dt.timedelta(hours=20)
# A step's words on the page: its last lines, never a wall of them.
SHOWN_LINES = 3


def steps(ledger_path: Path, inbox: Path) -> list[tuple[str, object]]:
    """(name, callable returning an exit code) for what is configured."""
    from . import cli
    data_dir = Path(ledger_path).parent
    out = []
    if (data_dir / "ibkr_flex.json").exists():
        out.append(("IBKR", lambda: cli._ibkr_flex(ledger_path)))
    out.append(("repères", lambda: cli._benchmarks(ledger_path)))
    # The inflation is a nicety: a source that does not check out is said,
    # and does not hold back the day's refresh.
    out.append(("inflation", lambda: cli._cpi(ledger_path)))
    if any((Path(inbox) / "revolut" / "crypto").glob("*.csv")):
        out.append(("crypto", lambda: cli._crypto(ledger_path, None)))
    return out


def run(ledger_path: Path, inbox: Path, echo: bool = False) -> dict:
    """Every step, each one's outcome and words; saved in refresh.json.
    `echo` prints the words as they come too (the console)."""
    results = []
    for name, step in steps(ledger_path, inbox):
        buffer = io.StringIO()
        started = dt.datetime.now()
        try:
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                code = step()
        except Exception as exc:  # one step down must not stop the others
            buffer.write(f"{name} : échec ({type(exc).__name__})\n")
            code = 1
        said = [line.strip() for line in buffer.getvalue().splitlines() if line.strip()]
        if echo:
            print("\n".join(said))
        results.append({"name": name, "ok": not code, "said": said[-SHOWN_LINES:],
                        "seconds": round((dt.datetime.now() - started).total_seconds(), 1)})
    if not any(r["name"] == "IBKR" for r in results):
        unset = "service Flex pas configuré (docs/epargne.md) — recapture par /epargne"
        if echo:
            print(f"IBKR : {unset}")
        results.insert(0, {"name": "IBKR", "ok": None, "seconds": 0.0, "said": [unset]})
    record = load(Path(ledger_path).parent)
    now = dt.datetime.now().isoformat(timespec="seconds")
    record["last"] = {"at": now, "steps": results}
    if all(r["ok"] is not False for r in results):
        record["at"] = now
    (Path(ledger_path).parent / STAMP).write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
    return record


def load(data_dir: Path) -> dict:
    try:
        raw = json.loads((Path(data_dir) / STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def due(data_dir: Path, now: dt.datetime | None = None) -> bool:
    """Whether the daily run has work: nothing went through in 20 hours."""
    try:
        last = dt.datetime.fromisoformat(load(data_dir)["at"])
    except (KeyError, ValueError, TypeError):
        return True
    return (now or dt.datetime.now()) - last >= EVERY
