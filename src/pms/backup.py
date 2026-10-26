"""A copy of what cannot be rebuilt: `data/` and `inbox/`, encrypted, elsewhere.

The ledger rebuilds from the statements; the decisions do not -- the
corrections (`overrides.json`), the personal rules, the budgets, the plans,
the crypto calibration. All of it lives in `data/`, git-ignored, on a Desktop
OneDrive does not sync (checked 23.09). One lost disk, and the hours of
reclassification go with it.

`python -m pms --backup [FOLDER]` zips both into FOLDER (default: a
`PMS-sauvegardes` folder in OneDrive) and keeps the newest copies. run.bat
calls it at every launch, so a copy is written only when something changed
since the last one: a folder of identical zips would push out the copy that
mattered.

**Every copy is encrypted** (Fernet: AES-128 and an HMAC-SHA256 over it, from
`cryptography`, which pdfplumber already pulls in). The default destination is
someone else's cloud: a plain zip there was every statement, IBAN and
correction, readable by whoever reads that account. The key is random, lives
in `data/backup.key`, is created on the first backup and never goes into an
archive -- a copy that carried its own key would be no lock at all. The user
keeps a second copy of it in a password manager: without it, after a lost
disk, the backups are noise. Restoring is `python -m pms --restore ARCHIVE`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import os
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEEP = 10
PREFIX = "pms-"
SUFFIX = ".zip.enc"
KEY_NAME = "backup.key"


def default_destination() -> Path | None:
    """OneDrive's `PMS-sauvegardes`, or None on a machine without OneDrive."""
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.environ.get(var)
        if root and Path(root).is_dir():
            return Path(root) / "PMS-sauvegardes"
    return None


# --- the key ----------------------------------------------------------------

def key_path(data_dir: Path) -> Path:
    return Path(data_dir) / KEY_NAME


def check_key(key: bytes) -> bytes:
    """The key itself, or ValueError when it is not one (a truncated copy
    from the password manager, a stray space)."""
    key = key.strip()
    try:
        Fernet(key)
    except (ValueError, TypeError):
        raise ValueError("ce n'est pas une clé de sauvegarde (44 caractères "
                         "attendus, tels que dans data/backup.key)") from None
    return key


def load_key(data_dir: Path) -> bytes | None:
    path = key_path(data_dir)
    return check_key(path.read_bytes()) if path.is_file() else None


def ensure_key(data_dir: Path) -> tuple[bytes, bool]:
    """The key, created on first use. Returns (key, created)."""
    existing = load_key(data_dir)
    if existing:
        return existing, False
    key = Fernet.generate_key()
    path = key_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key + b"\n")
    return key, True


# --- the copies -------------------------------------------------------------

def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _files(sources: dict[str, Path], exclude: set[Path] = frozenset()
           ) -> list[tuple[str, Path]]:
    """(name in the zip, file), sorted: the same tree always lists the same way."""
    skip = {Path(p).resolve() for p in exclude}
    out = []
    for name, folder in sources.items():
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.resolve() not in skip:
                out.append((f"{name}/{path.relative_to(folder).as_posix()}", path))
    return sorted(out)


def fingerprint(files: list[tuple[str, Path]]) -> str:
    """Names and contents, not modification times: an untouched file that an
    ingestion rewrote byte for byte is not a change."""
    digest = hashlib.sha256()
    for arcname, path in files:
        digest.update(arcname.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def copies(dest: Path) -> list[Path]:
    """The backups in `dest`, oldest first (the name carries the timestamp)."""
    return sorted(Path(dest).glob(f"{PREFIX}*{SUFFIX}")) if Path(dest).is_dir() else []


def plain_copies(dest: Path) -> list[Path]:
    """Zips written before the encryption, still readable by anyone. Never
    deleted here: they are the only copies the old way could restore, and
    removing them is the user's call once the key is safe."""
    return sorted(Path(dest).glob(f"{PREFIX}*.zip")) if Path(dest).is_dir() else []


def open_copy(path: Path, key: bytes) -> zipfile.ZipFile:
    """An encrypted copy, decrypted in memory -- the plain zip never touches
    the disk."""
    try:
        clear = Fernet(key).decrypt(Path(path).read_bytes())
    except InvalidToken:
        raise ValueError(f"{Path(path).name} : clé incorrecte ou copie abîmée") from None
    return zipfile.ZipFile(io.BytesIO(clear))


def _seal(files: list[tuple[str, Path]], digest: str, key: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname, path in files:
            archive.write(path, arcname)
        archive.comment = digest.encode("ascii")
    return Fernet(key).encrypt(buffer.getvalue())


def backup(sources: dict[str, Path], dest: Path, keep: int = KEEP, *, key: bytes,
           repo: Path | None = None, now: dt.datetime | None = None,
           exclude: set[Path] = frozenset()) -> dict:
    """Zip and encrypt `sources` into `dest` unless the newest copy already
    holds the same files; then keep the newest `keep` copies. `exclude`
    leaves files out -- the key, above all. Returns what happened."""
    dest = Path(dest)
    for folder in [*sources.values(), *([repo] if repo else [])]:
        if _inside(dest, Path(folder)):
            # Inside data/ the zip would contain itself; anywhere else in the
            # repository it is one `git add -A` away from being published.
            raise ValueError(f"le dossier de sauvegarde ne peut pas être dans {folder}")
    if keep < 1:
        raise ValueError("--keep doit valoir au moins 1")
    files = _files(sources, exclude)
    if not files:
        raise ValueError("rien à sauvegarder : data/ et inbox/ sont vides")
    digest = fingerprint(files)
    existing = copies(dest)
    if existing:
        try:
            with open_copy(existing[-1], key) as previous:
                if previous.comment.decode("ascii", "replace") == digest:
                    return {"path": existing[-1], "skipped": True, "files": len(files),
                            "bytes": existing[-1].stat().st_size, "removed": [],
                            "kept": len(existing), "plain": plain_copies(dest)}
        except (ValueError, zipfile.BadZipFile, OSError):
            pass  # a damaged copy, or one under another key: write a new one

    dest.mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = dest / f"{PREFIX}{stamp}{SUFFIX}"
    partial = dest / f".{PREFIX}{stamp}.partial"
    # Written aside then renamed: a copy cut short (a full disk, a sync
    # client grabbing the file) never passes for a complete one.
    partial.write_bytes(_seal(files, digest, key))
    os.replace(partial, target)

    removed = []
    current = copies(dest)
    for old in current[:-keep]:
        old.unlink()
        removed.append(old)
    return {"path": target, "skipped": False, "files": len(files),
            "bytes": target.stat().st_size, "removed": removed,
            "kept": len(current) - len(removed), "plain": plain_copies(dest)}


def restore(archive: Path, key: bytes, into: Path) -> list[Path]:
    """Decrypt `archive` and lay `data/` and `inbox/` out under `into`.

    Nothing is overwritten: restoring over a live `data/` would replace the
    corrections made since that copy with older ones. A file already there
    stops the whole restore before anything is written.
    """
    into = Path(into)
    with open_copy(archive, key) as copy:
        names = [n for n in copy.namelist() if not n.endswith("/")]
        targets = [into / n for n in names]
        if any(not _inside(t, into) for t in targets):
            raise ValueError(f"{Path(archive).name} : un chemin sort du dossier de restauration")
        present = [t for t in targets if t.exists()]
        if present:
            raise ValueError(f"{len(present)} fichier(s) existent déjà, dont {present[0]} : "
                             "rien n'a été écrasé (choisir un dossier vide avec --into)")
        copy.extractall(into)
    return targets


# --- reading a copy back ----------------------------------------------------
#
# A copy is only worth the restore it allows. Writing one proved nothing
# about reading it: a key changed by hand, a sync client that truncated the
# file, and the first sign would have been the day of the lost disk. The
# newest copy is therefore read back as a restore would -- decrypted, every
# member's checksum checked, the fingerprint recomputed from the contents --
# each time one is written, and once a week otherwise.

STATUS_NAME = "backup_status.json"
VERIFY_EVERY = dt.timedelta(days=7)
# run.bat backs up at every launch: a status this old means it stopped.
STALE_AFTER = dt.timedelta(days=14)


def verify(path: Path, key: bytes) -> int:
    """The number of files in `path` once read back in full; ValueError when
    any part of it does not read."""
    path = Path(path)
    try:
        with open_copy(path, key) as copy:
            broken = copy.testzip()
            if broken:
                raise ValueError(f"{path.name} : {broken} est abîmé dans la copie")
            names = [n for n in copy.namelist() if not n.endswith("/")]
            digest = hashlib.sha256()
            for name in names:
                digest.update(name.encode("utf-8") + b"\0")
                digest.update(copy.read(name))
                digest.update(b"\0")
            if digest.hexdigest() != copy.comment.decode("ascii", "replace"):
                raise ValueError(f"{path.name} : le contenu ne correspond plus à son empreinte")
            return len(names)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"{path.name} : illisible ({exc.__class__.__name__})") from None


def status_path(data_dir: Path) -> Path:
    return Path(data_dir) / STATUS_NAME


def read_status(data_dir: Path) -> dict:
    import json
    try:
        status = json.loads(status_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return status if isinstance(status, dict) else {}


def write_status(data_dir: Path, status: dict) -> None:
    import json
    path = status_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")


def due(status: dict, copy: Path, now: dt.datetime) -> bool:
    """A copy not yet read back, or a check older than a week."""
    if status.get("verified_copy") != Path(copy).name or not status.get("verified_at"):
        return True
    try:
        return now - dt.datetime.fromisoformat(status["verified_at"]) >= VERIFY_EVERY
    except ValueError:
        return True


def health(data_dir: Path, now: dt.datetime | None = None) -> dict | None:
    """What the app says about the backups, or None when there is nothing
    to say: the last run failed, a copy did not read back, or no backup
    has run for two weeks."""
    now = now or dt.datetime.now()
    status = read_status(data_dir)
    if not status:
        return {"title": "Aucune sauvegarde",
                "detail": "lance run.bat, ou python -m pms --backup DOSSIER"}
    if not status.get("ok", False):
        return {"title": "Sauvegarde en échec", "detail": status.get("error") or "voir la console"}
    try:
        age = now - dt.datetime.fromisoformat(status["ran_at"])
    except (KeyError, ValueError):
        return None
    if age >= STALE_AFTER:
        return {"title": "Sauvegarde ancienne", "detail": f"la dernière date de {age.days} jours"}
    return None
