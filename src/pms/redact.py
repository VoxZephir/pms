"""Redact a PDF before it leaves the machine: IBANs and proper names out of
the file itself, not hidden under a box (`docs/caviardage.md`).

The page content is rewritten (PyMuPDF's redactions): a redacted word is
gone from the text layer, the document's metadata is scrubbed, and the
output is read back to prove that nothing found is still in it. What is
found:

- IBANs, checked by their mod-97 digit, and whatever follows the word "IBAN";
  the client number of a statement;
- the names a statement PMS can read carries: the holder, and the
  counterparty of every move that is not a card payment (an employer, a
  landlord, a person) -- the shops paid by card stay, they say nothing about
  who holds the account;
- in any PDF, a person's name: a common given name next to a capitalised
  word ("Jean Dupont", "DUPONT Jean"), or a capitalised name after a title
  (M., Mme, Monsieur, Herr, Dr) -- and a postal address (a street and its
  number, a postcode and its town alone on a line);
- the patterns of `data/local_rules.json` (the rules that name an employer,
  a landlord, a practitioner, a person) and the terms passed with `--also`.

`--keep` spares a term (the bank's own name, say). The report masks what it
names: "D***** G*******", never the name in clear.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Where redacted copies go: gitignored, and never inbox/ -- a copy there
# would be ingested.
OUTPUT = Path(__file__).resolve().parents[2] / "output" / "caviarde"


def available() -> bool:
    """Whether PyMuPDF is installed (the dev group: `caviarder.bat` syncs it)."""
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False
    return True


# Given names common in Switzerland and around it: enough to recognise a
# person next to a capitalised word, not an exhaustive register.
FIRST_NAMES = frozenset("""
aaron adam adrian adrien agathe agnes aisha alain alba albert alessandro alessia alex alexandra alexandre alexis
ali alice alicia aline alma amandine amelie amir ana anais andre andrea andreas angela angelo anita anja anna
annabelle anne annette antoine anton antonio arnaud arthur aurelie aurore axel barbara bastien beat beatrice
benjamin benoit bernard bertrand blerim brigitte bruno camille carla carlos carmen caroline catherine cecile
celine charles charlotte chiara chloe christian christine christophe claire clara claude claudia clement colette
corinne cyril damien daniel daniela danielle david debora delphine denis diana didier diego dimitri
dominique dorian dylan edouard elena eliane elias elisa elisabeth elise ella emil emilie emma emmanuel enzo eric
erika ethan etienne eva evan fabian fabien fabienne fabio fanny felix fernando florence florian francesca
francesco francois francoise frank franziska frederic gabriel gabriela gael gaelle georges gerald gerard
giovanni gilles giulia guillaume hannah hans helene henri hugo ines irene isabel isabelle ivan jacqueline
jacques jan jana jasmine jean jeanne jennifer jeremy jerome joao joel johan johanna john jonas jonathan jordan
jose joseph josiane judith jules julia julie julien juliette justine karin katarina katharina kevin lara laura
laurence laurent lea leila lena leo leon leonie liam lina lisa loic lorenzo louis louise luc luca lucas lucie
ludovic luis lukas luna madeleine mael magali manon manuel manuela marc marcel marco margaux maria marianne
marie marine mario marion mark marta martin martina mathias mathieu mathilde matteo matthias maxime melanie
michael michel michele mikael milan mira mohamed monique muriel nadia nadine natalia natacha nathalie nathan
nicolas nicole nina noah noemie nora oliver olivia olivier oscar pascal pascale patricia patrick paul paula
pauline pedro peter philippe pierre quentin rachel rafael raphael rebecca regula remi renato rene ricardo
robert roberto romain romane rosa ruth sabine sabrina samuel sandra sara sarah sebastien serge silvia simon
simone sofia sophie stefan stefanie stephane stephanie sven sylvain sylvie tamara theo thierry thomas tiago
tim timothee tobias tom ursula valentin valerie vanessa vera veronique victor vincent virginie walter xavier
yann yannick yasmine yves yvonne zoe
""".split())

# Capitalised words that are not names: the words of the statement around
# one ("Debit UBS TWINT", "Payment UBS"), and a company's form.
NOT_NAMES = frozenset("""
payment debit credit ubs twint bank banque sa ag sarl gmbh ltd inc order transfer virement paiement
""".split())
TITLES = r"(?:M\.|Mme|Mlle|MM\.|Monsieur|Madame|Mademoiselle|Herr|Frau|Hr\.|Fr\.|Dr\.?|Prof\.?|Me|Maître)"
CAP = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
# A word in capitals or with a capital first letter, the shape of a name.
NAME_WORD = re.compile(rf"^{CAP}$")
TITLED = re.compile(rf"\b{TITLES}\s+(?:{CAP}\s+){{0,2}}{CAP}")
STREET = re.compile(
    r"\b(?:rue|chemin|ch\.|avenue|av\.|route|rte|place|pl\.|boulevard|bd|quai|allée|impasse|sentier|promenade|"
    r"[A-Za-zäöüÄÖÜ]+(?:strasse|straße|weg|gasse|platz|rain|halde)|via|viale|piazza)\b[^\n]{0,40}?\b\d{1,4}[a-zA-Z]?\b",
    re.IGNORECASE)
POSTCODE_TOWN = re.compile(rf"^(?:CH-|F-|D-)?\d{{4,5}}\s+{CAP}(?:[\s\-]{CAP})*$")
# One line only: a space may split an IBAN in groups, a line break may not
# (the next line's first word is not part of it).
IBAN_CANDIDATE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){10,32}")
AFTER_IBAN = re.compile(r"\bIBAN[ \t]*:?[ \t]*([A-Z0-9][A-Z0-9 ]{9,40})")
CLIENT = re.compile(r"\b(?:Client|Kunde|Cliente|N° client|No client)\s*:?\s*(\d{4,})")
# Card payments name a shop, not a person; currency legs and Twint name nobody.
# A Twint to or from a person names them (UBS); Swissquote's names nobody.
NAMELESS_KINDS = ("Paiement par carte", "Transfert automatisé", "Transfert Forex manuel")


def fold(text: str) -> str:
    """Lower case without accents: "Jérôme" and "JEROME" are one name."""
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c))


def fold_same(text: str) -> str:
    """`fold`, character by character, keeping the length: an index in the
    folded text is the same character in the original ("ß" stays itself
    rather than become "ss"). Matching runs on this, so "Genève" and
    "GENEVE" are one name, and a match maps back to the words on the page."""
    out = []
    for c in text:
        f = fold(c)
        out.append(f if len(f) == 1 else (c.lower() if len(c.lower()) == 1 else c))
    return "".join(out)


def iban_ok(compact: str) -> bool:
    """The ISO 13616 check: the country and check digits moved to the end,
    letters as numbers, the whole thing 1 modulo 97."""
    if not (15 <= len(compact) <= 34 and compact.isascii() and compact.isalnum()
            and compact[:2].isalpha() and compact[2:4].isdigit()):
        return False
    moved = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


def terms(text: str) -> list[str]:
    """A list of words as people type it: one per line, or separated by
    commas or semicolons."""
    return [t.strip() for t in re.split(r"[,;\n]+", text or "") if t.strip()]


def mask(term: str) -> str:
    """"Dupont SA" -> "D***** S*": what the report shows of a name."""
    return " ".join(w[:1] + "*" * (len(w) - 1) for w in term.split())


@dataclass
class Found:
    kind: str
    text: str


@dataclass
class Report:
    pages: int = 0
    found: list[Found] = field(default_factory=list)
    leftover: list[str] = field(default_factory=list)

    def by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.found:
            out[f.kind] = out.get(f.kind, 0) + 1
        return out


def statement_terms(path: Path) -> list[tuple[str, str]]:
    """The holder and the counterparties a statement PMS reads carries, as
    (kind, name). Nothing when PMS does not read this PDF."""
    from . import banks
    pattern = banks.recognise(path)
    if pattern is None:
        return []  # not a statement PMS reads: the generic rules alone
    try:
        statement = banks.parser_for(Path("inbox") / pattern.replace("*", "x"))(path)
    except Exception:  # a statement it cannot read after all
        return []
    out = []
    if statement.holder:
        out.append(("titulaire", statement.holder))
    if statement.client_number:
        # Read from "Client 1234567" on the cover; the label and the number
        # can sit in two blocks, where the CLIENT rule never sees them side
        # by side.
        out.append((CLIENT_KIND, statement.client_number))
    for t in statement.transactions:
        if t.kind.startswith(NAMELESS_KINDS) or not t.merchant.strip():
            continue
        out.append(("contrepartie", t.merchant.strip()))
    return out


RULE = "règle personnelle"


def rule_patterns() -> list[re.Pattern]:
    """The personal rules' patterns, read as they are matched."""
    from . import categories
    out = []
    for rule in categories.load_local_rules_raw():
        pattern = (rule.get("pattern") or "").strip()
        if pattern:
            try:
                out.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                continue
    return out


CLIENT_KIND = "numéro de client"


def _number_pattern(number: str) -> re.Pattern | None:
    """A number wherever its digits run, spaced or not, even inside a longer
    word: the whole word goes."""
    digits = re.sub(r"\D", "", number)
    if len(digits) < 4:
        return None
    return re.compile(r"[ .'’]?".join(digits))


def _term_pattern(term: str) -> re.Pattern | None:
    """A name to find in folded text, its words across spaces, commas and
    line ends."""
    words = [re.escape(w) for w in fold_same(term).split() if w]
    if not words or len("".join(words)) < 3:
        return None
    return re.compile(r"(?<![\w])" + r"[\s,]+".join(words) + r"(?![\w])", re.IGNORECASE)


def _loose_pattern(term: str) -> re.Pattern | None:
    """A name as it may still be read: its words in order, whatever stands
    between them (a hyphen, a slash, nothing at all), whole words."""
    words = [re.escape(w) for w in re.findall(r"\w+", fold_same(term))]
    if not words or len("".join(words)) < 3:
        return None
    return re.compile(r"(?<![\w])" + r"[\W_]*".join(words) + r"(?![\w])", re.IGNORECASE)


class Block:
    """A block of the page as one string, each character mapped to the word
    it came from -- so a match found in the text becomes boxes on the page,
    across the lines a name wraps over."""

    def __init__(self, words: list[tuple]):
        self.words = words
        parts, self.owner = [], []
        for i, w in enumerate(words):
            if parts:
                same_line = (w[5], w[6]) == (words[i - 1][5], words[i - 1][6])
                parts.append(" " if same_line else "\n")
                self.owner.append(None)
            parts.append(w[4])
            self.owner.extend([i] * len(w[4]))
        self.text = "".join(parts)
        self.folded = fold_same(self.text)
        self.hit: set[int] = set()

    def mark(self, start: int, end: int) -> None:
        self.hit.update(o for o in self.owner[start:end] if o is not None)

    def lines(self):
        """(start, end, text) of each line."""
        start = 0
        for line in self.text.split("\n"):
            yield start, start + len(line), line
            start += len(line) + 1


def find(block: Block, terms: list[tuple[str, re.Pattern]], keep: list[re.Pattern], report: Report) -> None:
    text = block.text

    def take(kind: str, start: int, end: int) -> None:
        piece = text[start:end]
        if any(k.search(block.folded[start:end]) for k in keep):
            return
        owners = {o for o in block.owner[start:end] if o is not None}
        if owners <= block.hit:
            return  # already taken by another rule: counted once
        block.mark(start, end)
        report.found.append(Found(kind, " ".join(piece.split())))

    for m in IBAN_CANDIDATE.finditer(text):
        raw = m.group(0)
        compact = raw.replace(" ", "")
        # The longest prefix that checks out: an IBAN followed by more digits.
        for n in range(min(len(compact), 34), 14, -1):
            if iban_ok(compact[:n]):
                kept, end = 0, m.start()
                while kept < n:
                    if text[end] != " ":
                        kept += 1
                    end += 1
                take("IBAN", m.start(), end)
                break
    for m in AFTER_IBAN.finditer(text):
        take("IBAN", m.start(1), m.end(1))
    for m in CLIENT.finditer(text):
        take("numéro de client", m.start(1), m.end(1))
    for kind, pattern in terms:
        # The names are folded; a personal rule is a regex as written,
        # matched as the categories match it.
        for m in pattern.finditer(text if kind == RULE else block.folded):
            take(kind, m.start(), m.end())
    for m in TITLED.finditer(text):
        take("nom (civilité)", m.start(), m.end())
    for m in STREET.finditer(text):
        take("adresse", m.start(), m.end())
    for start, end, line in block.lines():
        if POSTCODE_TOWN.match(line.strip()):
            take("adresse", start, end)
    # A given name next to a capitalised word, either side, on one line.
    spans = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\S+", text)]

    def namelike(k: int) -> bool:
        bare = spans[k][2].strip(",.;:()")
        return bool(NAME_WORD.match(bare)) and fold(bare) not in NOT_NAMES
    for i, (start, end, word) in enumerate(spans):
        bare = word.strip(",.;:()")
        if fold(bare) not in FIRST_NAMES or not NAME_WORD.match(bare):
            continue
        run_start, run_end = start, end
        for j in (i + 1, i + 2):
            if j < len(spans) and namelike(j) and "\n" not in text[run_end:spans[j][0]] \
                    and not spans[j - 1][2].endswith((",", ";")):
                run_end = spans[j][1]
            else:
                break
        # A surname in capitals before the given name ("DUPONT Jean", "DUPONT,
        # Jean"), whether or not one follows it too.
        if i > 0 and namelike(i - 1) and spans[i - 1][2].strip(",").isupper() \
                and "\n" not in text[spans[i - 1][1]:start]:
            run_start = spans[i - 1][0]
        if (run_start, run_end) != (start, end):
            take("nom", run_start, run_end)


def redact(source: Path, target: Path, also: list[str] = (), keep: list[str] = ()) -> Report:
    """Write `target`, a copy of `source` with what is found removed, and
    say what was. Raises when the read-back still finds a removed term."""
    terms: list[tuple[str, re.Pattern]] = []
    seen: set[str] = set()
    named = statement_terms(source) + [("ajouté", t) for t in also if t.strip()]
    for kind, name in named:
        key = fold(" ".join(name.split()))
        pattern = _number_pattern(name) if kind == CLIENT_KIND else _term_pattern(name)
        if pattern and key not in seen:
            seen.add(key)
            terms.append((kind, pattern))
            # A person's or a company's name also turns up word by word (a
            # surname alone, a name cut by the end of a line): its distinctive
            # words go too, the short and the common ones stay.
            if kind == "titulaire":
                for word in name.split():
                    p = _term_pattern(word)
                    if p and len(word) >= 3:
                        terms.append((kind, p))
    terms += [(RULE, p) for p in rule_patterns()]
    keep_patterns = [p for p in (_term_pattern(k) for k in keep) if p]

    # A name found in one place may stand elsewhere in a form no rule
    # catches there (cut by a block, glued to a word): the read-back sees it.
    # Each round removes again, from the original, every name still read --
    # whole and word by word -- until none is; past three, refuse.
    report = Report()
    for _ in range(3):
        report = _apply(source, target, terms, keep_patterns)
        if not report.leftover:
            return report
        for f in report.leftover:
            loose = _loose_pattern(f)
            if loose:
                terms.append(("même nom ailleurs", loose))
            for word in re.findall(r"\w+", f):
                p = _term_pattern(word)
                if p and len(word) >= 4:
                    terms.append(("même nom ailleurs", p))
    raise RuntimeError(f"{len(report.leftover)} élément(s) encore lisible(s) après caviardage : "
                       + ", ".join(mask(t) for t in report.leftover[:5]))


def _apply(source: Path, target: Path, terms: list[tuple[str, re.Pattern]],
           keep_patterns: list[re.Pattern]) -> Report:
    """One redaction of `source` into `target`, then the read-back: every
    name found must be gone, accents and case aside, whole words only."""
    import pymupdf

    report = Report()
    doc = pymupdf.open(source)
    report.pages = doc.page_count
    for page in doc:
        words = page.get_text("words", sort=True)
        blocks: dict[int, list] = {}
        for w in words:
            blocks.setdefault(w[5], []).append(w)
        for block_words in blocks.values():
            block = Block(block_words)
            find(block, terms, keep_patterns, report)
            for i in block.hit:
                x0, y0, x1, y1 = block.words[i][:4]
                page.add_redact_annot(pymupdf.Rect(x0, y0, x1, y1), fill=(0, 0, 0))
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    doc.scrub()
    target.parent.mkdir(parents=True, exist_ok=True)
    doc.save(target, garbage=4, deflate=True, clean=True)
    doc.close()

    check = pymupdf.open(target)
    left = fold_same("\n".join(page.get_text() for page in check))
    check.close()
    for kind, f in sorted({(f.kind, f.text) for f in report.found}):
        # A number is read even inside a longer word; a name as whole words.
        loose = _number_pattern(f) if kind == CLIENT_KIND else _loose_pattern(f)
        if loose and loose.search(left) and f not in report.leftover:
            report.leftover.append(f)
    return report
