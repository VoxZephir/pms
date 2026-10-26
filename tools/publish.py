"""Publish the current tree to the public repository, for the people the app
is passed on to (README, « Passer l'app à quelqu'un »).

The private repository keeps its history; the public one gets the files as
they are now, as one commit on top of its own history -- none of the private
commits, their messages or their authors. A copy unzipped from the public
repository becomes a clone of it at first launch (`run.bat`, PMS_REPO), and
its "Mettre à jour" button follows it from then on.

Refused when the tree is not committed, when a file of data/, inbox/ or
output/ is tracked, or when the holder's name, IBAN or client number -- read
from the local ledger, never written here -- appears in a tracked file.

    python tools/publish.py            # publish
    python tools/publish.py --dry-run  # check only
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = "https://github.com/VoxZephir/pms.git"
BRANCH = "main"
# The public commits carry the account's GitHub no-reply address, never a
# personal one.
AUTHOR = ("VoxZephir", "174078106+VoxZephir@users.noreply.github.com")
PRIVATE_DIRS = ("data/", "inbox/", "output/")


def git(*args: str, env: dict | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    if done.returncode:
        raise SystemExit(f"git {args[0]} a échoué : {done.stderr.strip().splitlines()[-1] if done.stderr.strip() else done.returncode}")
    return done.stdout.strip()


def identifying() -> list[str]:
    """The holder's identifiers, from the local ledger (gitignored)."""
    try:
        account = json.loads((ROOT / "data" / "ledger.json").read_text(encoding="utf-8")).get("account", {})
    except (OSError, ValueError):
        return []
    out = []
    holder = (account.get("holder") or "").strip()
    if holder:
        out.append(holder)
    iban = (account.get("iban") or "").replace(" ", "")
    if iban:
        out += [iban, " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))]
    if account.get("client_number"):
        out.append(str(account["client_number"]))
    return out


def checks() -> list[str]:
    problems = []
    if git("status", "--porcelain"):
        problems.append("des changements ne sont pas commités : commiter d'abord")
    tracked = git("ls-files").splitlines()
    # The examples of data/ (the format, no data) are meant to be public.
    leaked = [f for f in tracked if f.startswith(PRIVATE_DIRS) and not f.endswith(".example.json")]
    if leaked:
        problems.append(f"{len(leaked)} fichier(s) de données suivis : {', '.join(leaked[:5])}")
    for value in identifying():
        found = subprocess.run(["git", "grep", "-I", "-l", "-i", "-F", value], cwd=ROOT,
                               capture_output=True, text=True).stdout.split()
        if found:
            # The value itself is never printed: the files are enough.
            problems.append(f"une donnée du titulaire apparaît dans : {', '.join(found[:5])}")
    return problems


def main(argv: list[str]) -> int:
    problems = checks()
    if problems:
        print("Publication refusée :")
        for p in problems:
            print(f"  - {p}")
        return 1
    git("fetch", "--quiet", PUBLIC, BRANCH)
    parent = git("rev-parse", "FETCH_HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if tree == git("rev-parse", "FETCH_HEAD^{tree}"):
        print("Rien de nouveau : le dépôt public a déjà ces fichiers.")
        return 0
    if "--dry-run" in argv:
        print("Contrôles passés ; rien publié (--dry-run).")
        return 0
    name, email = AUTHOR
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    message = f"Version du {dt.date.today():%d.%m.%Y}"
    commit = git("commit-tree", tree, "-p", parent, "-m", message, env=env)
    git("push", "--quiet", PUBLIC, f"{commit}:refs/heads/{BRANCH}")
    print(f"Publié : {message} → {PUBLIC}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
