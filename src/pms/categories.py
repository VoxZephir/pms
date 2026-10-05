"""Rule-based classification of transactions into spending categories.

The rules are ordered and the first match wins, so narrow rules must sit above
broad ones: "Coop Tankstelle" (a petrol station) is tested before the generic
"Coop" grocery rule, and supermarkets are tested before the food keywords so
that "Coop City Food" lands in Alimentation rather than Restaurants.

Adding a merchant is a one-line change to `RULES`. Whatever still falls through
is reported as `UNCATEGORISED` and shown as its own bucket in the dashboard --
the rule set is meant to be tuned against real data, not guessed at.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from .models import Transaction

UNCATEGORISED = "Non catégorisé"

# Rules that would name an employer, a landlord, a doctor or a person do not
# belong in a repository -- a categorisation file is otherwise a very precise
# description of someone's life. They live in `data/local_rules.json`, which is
# gitignored alongside the statements themselves, and are loaded on top of the
# rules below. What stays here is public retail: Coop, SBB, Uber, Swisscom.
LOCAL_RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "local_rules.json"


def _any(*words: str) -> str:
    """Join alternatives into one regex group."""
    return "(?:" + "|".join(words) + ")"


# (category, subcategory, regex) matched case-insensitively against
# "<kind> | <merchant> | <location>".
RULES: list[tuple[str, str, str]] = [
    # --- Custodian / banking --------------------------------------------
    ("Frais bancaires", "Change de devises", r"Transfert (?:automatisé|Forex manuel)"),
    ("Frais bancaires", "Intérêts", r"^Intérêts\b"),

    # --- Savings & investment ---------------------------------------------
    # Nothing matched these on the 2024-2026 statement; they are here so that a
    # future export routes 3a and brokerage contributions straight to "Save".
    ("Épargne & investissement", "Prévoyance 3a",
     _any("finpension", "VIAC", "frankly", "Selma", "Descartes Vorsorge",
          r"3\.?\s?a\b.*(pilier|S[äa]ule)", "Pilier 3a", "Liberty Vorsorge")),
    ("Épargne & investissement", "Courtage & titres",
     _any("Interactive Brokers", "IBKR", "IB LLC", "Saxo", "DEGIRO",
          "TrueWealth", "Swissquote Trading", "Yuh", "Neon Invest")),

    # --- Income ----------------------------------------------------------
    # Employers and clients are personal: see `data/local_rules.json`.
    ("Revenus", "Salaire / clients", r"(?!x)x"),

    # --- Housing & utilities ---------------------------------------------
    # A landlord's name is personal: see `data/local_rules.json`.
    # Banks often print names upper-case and unaccented: REGIE, GERANCE.
    ("Logement", "Loyer / régie", r"FLATFOX|R[ée]gie\b|Immobilier|G[ée]rance"),
    ("Logement", "Énergie",
     r"Elektrizitätswerk|SERVICES INDUSTRIELS|Services Industriels|Viteos|Romande Energie"),
    ("Logement", "Redevance TV", r"SERAFE|Billag"),
    ("Logement", "Ameublement & bricolage",
     _any("IKEA", r"OBI\b", "Jumbo", "Hornbach", "Micasa", "Pfister", "Casi Casa",
          "Depot", "BELWAG", "Cemplus", "De Tuinen", r"MUJI\b")),

    # --- Health & insurance ----------------------------------------------
    ("Santé & assurance", "Assurance maladie",
     _any("Assura", "Sanitas", "Groupe Mutuel", "Easy Sana", "Helsana", r"CSS\b",
          "Concordia", "Visana", "SWICA", "Atupri")),
    ("Santé & assurance", "Autres assurances",
     _any("AXA", "Zurich Assurance", "Mobilière", "Allianz", "Generali", "Baloise")),
    ("Santé & assurance", "Pharmacie & soins",
     _any("O F A C", "Medbase", "Pharmaci", "Apothe", "Amavita", "Drogerie", "Dentiste",
          "Clinic", "Permanence", "Hôpital", "Hopital", "Fielmann", "Optic",
          "Cabinet Vétéri", "Vétérinaire", "Laboratoire")),

    # --- Taxes & administration -------------------------------------------
    ("Impôts & administration", "Impôts",
     _any("Steueramt", "Etat de Neuchatel", "Kanton Zürich", "Wehrpflichtersatz",
          "Administration fiscale", "Office poursuites", "Impôt")),
    ("Impôts & administration", "Services publics",
     _any("Post CH AG", "Poste CH SA", "OMIT AG", "Gravoplaques", "Confédération",
          "Personenmeldeamt", r"MBA Zürich", "Kreisbüro", "Pompes Funèbres")),

    # --- Telecom & subscriptions -------------------------------------------
    ("Télécom & abonnements", "Téléphonie & internet",
     _any("Salt Mobile", "Sunrise", "yallo", "Swisscom", "Wingo", "Digital Republic")),
    ("Télécom & abonnements", "Streaming, jeux & logiciels",
     _any(r"Battle\.net", "Blizzard", "Netflix", "Spotify", "Steam", "PlayStation",
          "Nintendo", "Disney", r"Google \*", "Google Sleep", r"Apple\.com",
          "APPLE STORE", "OpenAI", "Anthropic", "Ankama", "REAL-DEBRID",
          r"PADDLE\.NET", "Microsoft", "Adobe")),
    # Wozber is an online resume builder billed as a one-off pass (wozber.com).
    ("Télécom & abonnements", "Formation & autres abonnements",
     _any("Preply", r"UDEMY", "LANGUATALK", r"UBER \*ONE", "MF Health", "Fitness",
          "Basic-Fit", "Golf Trust", r"Coursera", "WOZBER", "LinkedIn")),

    # --- Transport ---------------------------------------------------------
    ("Transport", "Carburant",
     _any("Migrol", "Coop Tankstelle", "Tamoil", "Shell", "Socar", r"Avia\b", r"BP\b",
          "Agrola", "Paupe Station", r"Eni\b", "Esso", "Ruedi Rüssel")),
    # Inovil SA runs the Riponne car park in Lausanne (inovil.ch).
    ("Transport", "Stationnement",
     _any("EasyPark", "Parking", "ParkingNW", "Parkhaus", "Parkplatz", "Inovil")),
    ("Transport", "Train & transports publics",
     _any(r"SBB", r"CFF", r"FFS", "SNCF", "RATP", r"TPG\b", r"VBZ", "Swiss Pass",
          r"BLS\b", "Chemins de fer", "NS Reizigers", "SERVICE NAVIGO", "NLOV[A-Z0-9]{6,}",
          "Trenitalia", "Deutsche Bahn", "Navigation")),
    ("Transport", "Taxi & VTC", _any(r"UBER \*TRIP", r"UBR\*", r"Bolt\b", "Taxi")),
    ("Transport", "Avion & car longue distance",
     _any("FLIXBUS", "Swiss Air", "easyJet", "Ryanair", "Lufthansa", "Air France",
          "Edelweiss", "Aéroport", "Airport")),

    # --- Groceries ----------------------------------------------------------
    ("Alimentation", "Supermarché",
     _any("Coop", "Migros", "Aldi", "Lidl", "Denner", "Carrefour", "FRANPRIX", "Manor Food",
          "Volg", r"Spar\b", "Landi", "Alnatura", "MINIMARKET", "Marché-", "Epicerie",
          r"L'EPICERIE", "Slagerij", r"AUX FRUITS", "MONOPRIX", "Pam Partner",
          "CASA SHOP", "GIMA SRL", "Markthal", "TooGoodToG", "Albert Heijn")),
    ("Alimentation", "Boulangerie, chocolat & traiteur",
     _any("Confiseur", "Confiserie", "Sprüngli", "Bachmann", "Jordann", "JOHN BAECKER",
          "JOHN BAKER", "Boulangerie", "Bäckerei", "Guillaume Bichet", "BachBuck",
          "Laederach", "Maison Cailler", "Brezelkönig", "BRIOCHE DOREE", "Bread Store",
          r"L Epi Dore", "Bagel Shop", "Koekmakeri", "Chocolade", "Merveilleux",
          "Pâtisserie", "Patisserie", "Crêperie", "MARTINUCCI", "DOLCE SIENA",
          "Aimé Pouly", "Fleur de Pains", "FOURNIL", "LA PARISIENNE", "PASTICCERIA",
          "Gelat", "GELATI", "Zuckerbaecker", "Baci di Berna", "Jamin",
          "F.LLI PERINI", "MAISON KERCK", "BOULANG")),

    # --- Eating out ---------------------------------------------------------
    ("Restaurants & bars", "Livraison",
     _any(r"UBER \*EATS", "Just Eat", "Smood", r"Eat\.ch", "Deliveroo", "Takeaway",
          "Take Awa")),
    ("Restaurants & bars", "Café & snack",
     _any("Caffe", "Café", "Cafe", "VICAFE", "Milchbar", "Starbucks", "Dunkin", "Vending",
          r"NYX\*", "Aperto", "KKiosk", r"Kiosk", "RELAY DAILY", "Kafi ", "Spettacolo",
          "CERAMICAFE", "Tartines")),
    ("Restaurants & bars", "Bar & sortie",
     _any(r"\bBar\b", "Barflyz", "Bowling", "Billiardino", r"\bClub\b", "Brasserie",
          "Brasseurs", "La Loge", "Guinguette", "Biergarten", "TAP HOUSE", "Paddy Reilly",
          "El Lokal", r"Le Mad\b", "Lucha Libre", "Wirtschaft", "Dr. Zhivago",
          "Auberge", r"LULU\b", "Craft Burger")),
    # Alfaset is a Neuchâtel social enterprise whose Terreaux 48 site runs a
    # canteen / catering service (alfaset.ch).
    ("Restaurants & bars", "Restaurant",
     _any("Culinarium", "Rasthof", "MadrePuglia", r"HC\d - ", "Holy Cow", "Atop AG",
          "ACUNA CHACON", "Claudia Ortis", r"RP RETAIL", "CREED", "Alfaset",
          "MITOHNE", "PRET A MANGER", "Restoshop", "MonteGalaico", "Mersi Dali",
          "PILO Sarl", r"N1 Express", "Inside Africa", "KING CR", "LS Sauvage",
          "VILLAGE AUTEUIL", "S.AGOSTINO", "LAURENT DHEILL", "JULIEN DUHAMEL",
          "ATELIER GENEVI", "LPC - ENOOBA", "IRIDE SERVIZI", "STE JEANNE",
          "Luigi", "Buvette",
          "Restaurant", "Rest\\.", "Ristor", "Pizz", "Bistro", "Kitchen", "Ramen", "POKÉ",
          "POKE", "Tacos", "Popeyes", "Yardbird", "Yooji", "SANDO", "Umamido",
          "Istanbul", "Kheops", "SAN XIN", "Food", "Scolarest", r"SV \(Suisse\)",
          "Bowls", "Friends Corner", "Bei Fouad", "Comme a la Maison", "Pancakes",
          "Croust", "Zem Geneve", "Baccini", "Bauschänzli", "Chuchi", "Giga", "Yakamoz",
          "Henan", "Redon Blanc", "Burger", "Chicken", "McDonald", "Kebab", "Thai",
          "Sushi", "Empanadas", "Piadina", "Omusubi", "Napule", "Trattoria", "Osteria",
          "Grill", "Tapas", "SPACCANAPOLI", "VINAIO", "ARTISAN", "BAXTER", "Smaggy",
          "Akiko", "Azuma", "Nonna", "KATREPICES", "KARTHY", "DIMDIMSUM", "Bao Canteen",
          "OH MY GREEK", "Rice Up", "Goodys", "Le Royaume", "Le Flibustier", "TARATATA",
          "SKEAT", "Saveurs", "Le Bassin Bleu", "Jetee de la", "Sauces Martin",
          "La Recette", "La Riotte", "La Fresque", "Le Saint Georges", "Le Sevres",
          "Ariana", "Almeko", "Momo", "Sadara", "Holy0", "Bombance", "Talacker",
          r"LS Enge", "Tropical Corner", "Shap Shap", "Panares", "Chic-?\\s?Chicken",
          "Five Guys", "Globus", "Foodtruck", "Streed", "Mr. Bird", "Butchers",
          "Cheese Inn", "Le Smash", "Foodhallen", "Creme d", "Van Stapele",
          "Albert Pougnier", "Pougnier", "MB2 ", "JUDE Sarl", "KINNIK", "NICO & CO",
          "RBC MOUSAVI", "A Table et", "O First", "Green Gorilla", "Simon Says",
          "BIGBANG", "SEGEP", "ORTE ", "SOMEG", "Con Gusto", "ANGOLO", "Visitaly",
          "Le Putain", r"DS 4 B\.V\.", "Stichting Spor", "Next Level")),

    # --- Shopping & leisure --------------------------------------------------
    ("Shopping", "Habillement & sport",
     _any("ITX Retail", "Zara", "Uniqlo", r"H&M", r"C&A", "Decathlon", "Chicorée",
          "Hilfiger", "Ochsner Sport", r"Manor\b", "Athleticum", "Snipes")),
    ("Shopping", "Électronique & culture",
     _any("Interdiscount", "FNAC", "Fust", "Orell Füssli", "Media Markt", "Digitec",
          "Galaxus", "EURONICS", "Music Avenue", "CULTURA", "Payot", "Librairie",
          "BOOK SHOP")),
    # Balexert shopping centre: the terminal sends its street address as the
    # merchant name, so the address is the only thing to match on.
    ("Shopping", "Centre commercial", r"Avenue Louis-Casai 27|Louis-Casa[iï] 27"),
    ("Shopping", "En ligne & marketplaces",
     _any("AMAZON", "AMZN", "Aliexpress", "Temu", "Zalando", "Revolut", "LYDIA",
          "PayPal", "Wish", r"eBay")),
    ("Shopping", "Beauté & bien-être",
     _any("Beauty Style", "Coiffure", "Coiffeu", "Barbier", "Barbie", r"Spa\b",
          "Schneiderei", "MONCEAU FLEURS", "Fleurs")),
    ("Loisirs & voyages", "Hébergement",
     _any("AIRBNB", "Hotel", "Hôtel", "Booking", "Uto Kulm", "ROOM007", "Hoxton",
          "Hostel", "Auberge de Jeunesse")),
    ("Loisirs & voyages", "Sorties & culture",
     _any("EUROPA PARK", "Cinéma", "Cinema", "Pathé", "Musée", "Museum", "Theater",
          "Théâtre", "Ticketcorner", r"ZOO\b", "Planet Bowl", "Piscine", "Patinoire",
          "Oper", "Landesmuseum", "LookOut", "Victoria hall", "Escape",
          "Artistes Assoc", "Associations d")),
]

def load_local_rules(path: Path | None = None) -> list[tuple[str, str, str]]:
    """Personal rules, kept out of the repository.

    Format: a JSON list of {"category", "subcategory", "pattern"}. Missing file
    or malformed content is not an error -- the app still runs on the public
    rules alone, it simply leaves those merchants uncategorised and says so.
    """
    path = Path(path or LOCAL_RULES_PATH)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rules = []
    for entry in raw if isinstance(raw, list) else raw.get("rules", []):
        pattern = entry.get("pattern")
        if not pattern:
            continue
        try:
            re.compile(pattern)
        except re.error:
            continue
        rules.append((entry.get("category", ""), entry.get("subcategory", ""), pattern))
    return rules


def load_local_rules_raw(path: Path | None = None) -> list[dict]:
    """The personal rules as stored, entries not tuples -- for editing.

    Same tolerance as `load_local_rules`: a missing file, malformed JSON or
    a dict wrapper read as an empty list. Entries that carry no pattern (the
    example file's `_comment`) are kept, so a save never drops them.
    """
    path = Path(path or LOCAL_RULES_PATH)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return raw if isinstance(raw, list) else raw.get("rules", [])


def save_local_rules(rules: list[dict], path: Path | None = None) -> Path:
    """Write the personal rules back to disk.

    The file is gitignored and may not exist yet -- it is created on the
    first save. Write then move, like the overrides, so an interrupted save
    cannot leave a truncated file behind.
    """
    path = Path(path or LOCAL_RULES_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(rules, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    temporary.replace(path)
    return path


def compile_rules(local: list[tuple[str, str, str]] | None = None):
    """Local rules first: they are the specific ones and must beat the generic."""
    local = load_local_rules() if local is None else local
    return [(cat, sub, re.compile(pattern, re.IGNORECASE))
            for cat, sub, pattern in [*local, *RULES]]


COMPILED = compile_rules()
LOCAL_RULE_COUNT = len(load_local_rules())

# Payment rails that carry no merchant name of their own. A Twint sent with
# no counterparty was long filed as a person-to-person transfer; it is not
# known to be one. The statement prints "Paiement Twint" and nothing else, and
# Twint pays parking meters, coffee machines and stalls as well as friends --
# 82 of the 313 on the real statement are ~2 CHF. So it is named for what is
# known: a Twint nobody has identified yet. /reclasser/tri sorts them.
PEER_KINDS = ("Paiement Twint",)
# The SWIFT code of Interactive Brokers' US entity, printed on its transfers.
BROKER_BIC = re.compile(r"\bIBKRUS33", re.IGNORECASE)
TWINT_UNKNOWN = "Twint non identifié"
INCOMING_KINDS = ("Paiement entrant",)


def _searchable(txn: Transaction) -> str:
    return f"{txn.kind} | {txn.merchant} | {txn.location}"


# Categories that describe money going out. A credit that matches one of them
# is a refund of that thing, not an instance of it.
SPENDING_CATEGORIES = {
    "Logement", "Santé & assurance", "Impôts & administration", "Alimentation",
    "Transport", "Télécom & abonnements", "Restaurants & bars", "Shopping",
    "Loisirs & voyages", "Transferts P2P", TWINT_UNKNOWN,
}


def classify(txn: Transaction, rules: list | None = None) -> tuple[str, str]:
    """Return (category, subcategory) for one transaction.

    `rules` overrides the module-level compiled set: the web store compiles
    its own from the personal rules file on every load, so an edit made from
    the app reclassifies on the next request. `None` falls back to the set
    compiled at import.
    """
    haystack = _searchable(txn)
    for category, subcategory, pattern in (COMPILED if rules is None else rules):
        if pattern.search(haystack):
            # A 402 CHF credit from the tax office is a refund; labelling it
            # "Impôts" reads as if it had been paid rather than received.
            if txn.amount > 0 and category in SPENDING_CATEGORIES:
                return category, "Remboursement"
            return category, subcategory

    if txn.amount > 0:
        # Money coming back from the brokerage is savings moved, not income.
        # The line names the owner as sender; only the sending bank's BIC
        # says Interactive Brokers -- a withdrawal on 20.12.2024 read as a
        # month's salary until this.
        if any(BROKER_BIC.search(line) for line in (txn.detail or [])):
            return "Épargne & investissement", "Retrait de courtage"
        if txn.kind in INCOMING_KINDS:
            return "Revenus", "Virement entrant"
        if txn.kind in PEER_KINDS:
            return "Revenus", "Remboursement Twint"
        return "Revenus", "Autre entrée"

    if txn.kind in PEER_KINDS:
        return TWINT_UNKNOWN, "Twint envoyé"
    if txn.kind.startswith("Versement pour "):
        return "Transferts P2P", "Virement sortant"

    return UNCATEGORISED, ""


def classify_all(transactions: Iterable[Transaction],
                 rules: list | None = None) -> None:
    """Annotate transactions in place, with `rules` when given."""
    for txn in transactions:
        txn.category, txn.subcategory = classify(txn, rules)
