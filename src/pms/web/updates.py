"""Updating the app from its own page, for someone who will never type
`git pull` -- the friend run.bat is meant for, or its owner on the phone.

What the button does is exactly that pull, fast-forward only: a local change
or a diverged branch stops it with git's own words, nothing is merged or
overwritten. The code reloads by itself (Werkzeug's reloader restarts on a
`.py` change, the front-end build is read at each request). A change of
dependencies is the one thing the running app cannot finish: replacing a
package whose compiled module is loaded fails on Windows. That update is
pulled, and the page asks for a relaunch of run.bat, whose `uv sync` installs
them.

The check runs `git fetch` at most once an hour, and only in the process that
serves (`python -m pms.web` turns it on): the test suite never reaches the
network or the repository.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FETCH_EVERY = 3600.0
# A change to any of these needs `uv sync`, i.e. a relaunch of run.bat.
DEPENDENCIES = {"uv.lock", "pyproject.toml", ".python-version"}
SHOWN = 8

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "result": None}


def _git(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _said(done: subprocess.CompletedProcess) -> str:
    """git's last words, for the page: never a URL with a token in it."""
    lines = [line for line in (done.stderr or done.stdout).splitlines() if line.strip()]
    text = lines[-1].strip() if lines else f"git a échoué ({done.returncode})"
    return " ".join(w for w in text.split() if "://" not in w)


# The branch the app lives on once a work branch is merged back: the update
# that brings the merge moves the copy onto it, and from then on it follows
# nothing else (19.10).
HOME_BRANCH = "main"
HOME = f"origin/{HOME_BRANCH}"


def _branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def _target() -> str | None:
    """The remote branch this copy follows, e.g. `origin/main`.

    The upstream when it has something new. Otherwise the remote branch this
    copy sits on -- its HEAD an ancestor, so a fast-forward reaches it --
    that moved last. A copy cloned on `main` and then updated with `git pull
    origin <branch>` tracks `origin/main`, which never moves: compared to its
    upstream alone it read as up to date for good, and the button never
    showed."""
    home = _git("rev-parse", "--verify", "--quiet", HOME).returncode == 0
    if home and _branch() == HOME_BRANCH:
        return HOME
    up = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    upstream = up.stdout.strip() if up.returncode == 0 else None
    refs = [r for r in _git("for-each-ref", "--sort=-committerdate", "--format=%(refname:short)",
                            "refs/remotes").stdout.split()
            if "/" in r and not r.endswith("/HEAD")]
    on = [r for r in refs if _git("merge-base", "--is-ancestor", "HEAD", r).returncode == 0]

    def ahead(ref: str) -> int:
        return int(_git("rev-list", "--count", f"HEAD..{ref}").stdout.strip() or 0)

    if upstream in on and ahead(upstream):
        return upstream
    moved = next((r for r in on if ahead(r)), None)
    return moved or upstream or (on[0] if on else None)


def check(force: bool = False, now: float | None = None) -> dict:
    """Whether the remote branch this copy follows (`_target`) has commits it
    has not: how many, their subjects, and whether they change the
    dependencies. Says which branch, and when it looked."""
    now = time.time() if now is None else now
    with _lock:
        if not force and _cache["result"] is not None and now - _cache["at"] < FETCH_EVERY:
            return _cache["result"]
        result = {**_check(), "checked": now}
        _cache.update(at=now, result=result)
        return result


def _check() -> dict:
    if not (ROOT / ".git").exists() or shutil.which("git") is None:
        return {"available": False, "reason": "copie sans git : relancer run.bat, qui propose de l'installer"}
    try:
        fetched = _git("fetch", "--quiet")
        if fetched.returncode:
            return {"available": False, "reason": "dépôt injoignable : " + _said(fetched)}
        target = _target()
        if target is None:
            return {"available": False, "reason": "aucune branche distante à suivre"}
        behind = int(_git("rev-list", "--count", f"HEAD..{target}").stdout.strip() or 0)
        if not behind:
            return {"available": False, "behind": 0, "branch": target}
        subjects = _git("log", f"-n{SHOWN}", "--format=%s", f"HEAD..{target}").stdout.splitlines()
        changed = set(_git("diff", "--name-only", "HEAD", target).stdout.split())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"available": False, "reason": "git n'a pas répondu"}
    return {"available": True, "behind": behind, "changes": subjects, "branch": target,
            "dependencies": bool(changed & DEPENDENCIES)}


def apply() -> dict:
    """Fetch, then fast-forward to the branch followed (`_target`) -- the pull
    the owner would type, `--ff-only`: a local change or a diverged branch
    stops it with git's own words. The branch becomes the upstream, so a
    plain `git pull` at the console goes to the same place. Returns what
    changed, or raises RuntimeError with git's reason.

    Everything is asked of git *before* the merge: the merge rewrites `.py`
    files, Werkzeug's reloader sees them within a second and stops this
    process -- on 19.10 it did so while the questions after the merge were
    still running, the answer never left, and the page read a dropped
    connection as a failed update. The browser now expects that too
    (`shell/Update.tsx`); this keeps the window as short as it can be."""
    with _lock:
        fetched = _git("fetch", "--quiet", timeout=120)
        if fetched.returncode:
            raise RuntimeError(_said(fetched))
        target = _target()
        if target is None:
            raise RuntimeError("aucune branche distante à suivre")
        changed = set(_git("diff", "--name-only", "HEAD", target).stdout.split())
        count = _git("rev-list", "--count", f"HEAD..{target}").stdout.strip()
        if target == HOME and _branch() != HOME_BRANCH:
            # The work branch was merged back: move onto main itself. A local
            # main with commits of its own is never overwritten.
            local = _git("rev-parse", "--verify", "--quiet", f"refs/heads/{HOME_BRANCH}")
            if local.returncode == 0 and _git("merge-base", "--is-ancestor", HOME_BRANCH, target).returncode:
                raise RuntimeError(f"la branche {HOME_BRANCH} locale a des commits absents de {HOME}")
            moved = _git("checkout", "-q", "-B", HOME_BRANCH, target, timeout=120)
            if moved.returncode:
                raise RuntimeError(_said(moved))
            _git("branch", f"--set-upstream-to={target}")
        else:
            _git("branch", f"--set-upstream-to={target}")
            pulled = _git("merge", "--ff-only", "--quiet", target, timeout=120)
            if pulled.returncode:
                raise RuntimeError(_said(pulled))
        _cache.update(at=0.0, result=None)
    return {"pulled": int(count or 0), "dependencies": bool(changed & DEPENDENCIES)}
