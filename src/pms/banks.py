"""Which parser reads which export in inbox/.

One line per bank: where its exports are dropped, and the function that turns
one into a `Statement`. Ingestion (`ledger.ingest`) asks `parser_for` per file,
so the CLI and the app's ⟳ button read the same banks the same way.

Adding a bank is adding a line here, plus its parser (README, "Brancher une
autre banque").
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import camt, parser, revolut, ubs
from .models import Statement

# (glob under inbox/, parser). The first matching glob wins.
def _pdf(path: Path) -> Statement:
    """A PDF at the top of inbox/: Swissquote's, unless its content says UBS
    -- a friend's export dropped there by hand is still read right."""
    return ubs.parse_statement(path) if ubs.looks_like(path) else parser.parse_statement(path)


SOURCES: list[tuple[str, Callable[[Path], Statement]]] = [
    ("*.pdf", _pdf),                               # Swissquote, the primary account
    ("revolut/*.csv", revolut.parse_statement),
    ("camt/*.xml", camt.parse_statement),          # ISO 20022, most Swiss banks
    ("ubs/*.pdf", ubs.parse_statement),            # UBS "Account transactions"
]


@dataclass(frozen=True)
class Bank:
    """What the app says about a source, beyond parsing it."""
    name: str
    account: str                        # the `Transaction.account` it feeds
    export: str                         # how the import page names the file
    recognise: Callable[[Path], bool]   # cheap: is this file one of its exports?
    url: str                            # where the export is fetched
    # Whether the export prints the period it covers. Swissquote's does;
    # Revolut's CSV only has its movements, so a quiet month looks like a
    # statement that stops early -- its import date says more.
    prints_period: bool = True


# One per source -- a new bank adds its line here too. The Swissquote link is
# the public homepage, not a login URL: the bank warns of phishing pages, and
# its login button sits at the top of that page.
BANKS: dict[str, Bank] = {
    "*.pdf": Bank("Swissquote", "", "le relevé PDF de Swissquote",
                  parser.looks_like, "https://www.swissquote.com/"),
    # The e-banking's "Account transactions" export, in English; at most 500
    # movements per file (docs/releves.md).
    "ubs/*.pdf": Bank("UBS", "", "l'export PDF « Account transactions » d'UBS",
                      ubs.looks_like, "https://www.ubs.com/"),
    "revolut/*.csv": Bank("Revolut", revolut.ACCOUNT, "l'export CSV de Revolut",
                          revolut.looks_like, "https://app.revolut.com/",
                          prints_period=False),
    # Any bank's: no link to give, the name of the bank is not in the glob.
    "camt/*.xml": Bank("Relevé ISO 20022", "", "le relevé camt.053 (XML) de votre banque",
                       camt.looks_like, ""),
}


def discover(inbox: Path) -> list[Path]:
    """Every export in inbox/ that some parser reads, in a stable order."""
    inbox = Path(inbox)
    if not inbox.exists():
        return []
    found = []
    for pattern, _ in SOURCES:
        found += sorted(inbox.glob(pattern))
    return found


def parser_for(path: Path) -> Callable[[Path], Statement]:
    """The parser of the bank this export belongs to.

    Matched on where the file sits (`revolut/x.csv`), so a file dropped at
    the wrong place fails loudly instead of being read by the wrong parser.
    """
    path = Path(path)
    # A bank's own folder first: a glob matches from the right, so "*.pdf"
    # would take ubs/x.pdf too.
    for pattern, parse in sorted(SOURCES, key=lambda s: Path(s[0]).parent == Path(".")):
        folder = Path(pattern).parent
        if path.match(pattern) and (folder == Path(".") or path.parent.name == folder.name):
            return parse
    if path.suffix.lower() == ".pdf":
        return parser.parse_statement
    raise ValueError(f"{path.name}: no parser for this file (see banks.SOURCES)")


def accepted_suffixes() -> list[str]:
    return sorted({Path(pattern).suffix.lower() for pattern, _ in SOURCES})


def recognise(path: Path) -> str | None:
    """The source (its glob) whose bank recognises this file by its content,
    or None. Never by its name: a renamed export is still one, and a PDF
    called `transactionStatement.pdf` from elsewhere is not."""
    path = Path(path)
    for pattern, bank in BANKS.items():
        if Path(pattern).suffix.lower() == path.suffix.lower() and bank.recognise(path):
            return pattern
    return None


def placement(filename: str, data: bytes, inbox: Path,
              pattern: str | None = None) -> tuple[Path, bool]:
    """Where an export belongs in inbox/, and whether that exact file is
    already there.

    The folder is the one its bank's glob reads -- `pattern` when the caller
    recognised the file (`recognise`), else the first source taking that
    extension -- so the file lands where `parser_for` will look for it.
    The name is the sender's, reduced to characters no filesystem argues
    with; it never carries a path, and never replaces another file. Raises
    ValueError, in words for the page, when no bank reads this file.
    """
    suffix = Path(filename).suffix.lower()
    pattern = pattern or next((p for p, _ in SOURCES if Path(p).suffix.lower() == suffix),
                              None)
    if pattern is None:
        raise ValueError(f"format non reconnu ({suffix or 'sans extension'}) — "
                         f"l'app lit les fichiers {', '.join(accepted_suffixes())}")
    if suffix == ".pdf" and b"%PDF-" not in data[:1024]:
        raise ValueError("ce fichier porte l'extension .pdf mais n'est pas un PDF")
    if suffix != ".pdf" and b"\0" in data[:4096]:
        raise ValueError(f"ce fichier porte l'extension {suffix} mais n'est pas du texte")
    folder = Path(inbox) / Path(pattern).parent
    if folder.is_dir():
        for existing in sorted(folder.glob(f"*{suffix}")):
            if existing.is_file() and existing.read_bytes() == data:
                return existing, True
    # "Relevé" keeps its letters as "Releve": accents dropped, not the letter.
    plain = unicodedata.normalize("NFKD", Path(filename).stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", plain).strip("-")[:80] or "releve"
    target, n = folder / f"{stem}{suffix}", 2
    while target.exists():
        target, n = folder / f"{stem}-{n}{suffix}", n + 1
    return target, False
