"""A made-up statement shaped like a Swissquote export.

Every test that is about the app -- not about reading a PDF -- runs on this, so
the suite runs on a clone that has no bank statement in inbox/. Everything in
it is invented: the holder, the IBAN (the SIX documentation example), every
counterparty, every amount.

What it must reproduce is the *shape* of a real export, because that is what
the app's logic keys on:

- three currency sections, rows in printed order; EUR and USD open and close at
  0.00, every foreign purchase funded by a CHF conversion whose two legs share a
  reference and print the rate and the counter-amount, with a ~1 % markup
  between the printed rate and the CHF debited (the custodian's margin);
- the Information cell split the way the parser splits it: kind, merchant,
  location -- a card payment's location ending in ", <Pays>", a transfer
  naming its payee inline ("Versement pour X") above an IBAN line;
- a running balance on every row that chains without a break, and `seq` as the
  position within the date -- with a few days whose references are not in
  printed order, as the bank does;
- enough history for every panel to have something to say: two years, a payer
  change and a month without pay, a summer abroad, an insurance bill every
  December and a tax bill every May (seasonal suggestions), a subscription that
  stops (a late commitment), a canteen at a fixed price (the mode), a payee
  printed two ways (an alias), P2P transfers, a refund, an unknown merchant,
  a parking meter paid by Twint at the same 2.50 over and over.

`build()` is deterministic and returns a fresh statement on every call.
"""

from __future__ import annotations

import datetime as dt
import math
import random

from pms.models import AccountSummary, Statement, Transaction
from pms.parser import _enrich_forex

START = dt.date(2024, 7, 30)
END = dt.date(2026, 7, 30)
OPENING_CHF = 2480.35
IBAN = "CH93 0076 2011 6238 5295 7"  # the SIX documentation example
HOLDER = "Alex Exemple"

CARD = "Paiement par carte - se terminant par 1234"
TWINT = "Paiement Twint"
INCOMING = "Paiement entrant"
INTEREST = "Intérêts"
MARKUP = 0.0097

# A supermarket prints one counterparty per till: several Coop spellings, so
# that merging a brand by pattern has something to merge.
GROCERIES = [
    ("Coop-2181 Neuchâtel", "Rue du Seyon 10, Suisse"),
    ("Coop-1045 Peseux", "Grand-Rue 12, Suisse"),
    ("Coop Pronto Marin", "Route de Neuchâtel 3, Suisse"),
    ("Coop City Neuchâtel", "Rue du Temple-Neuf 11, Suisse"),
    ("Migros MM Marin", "Rue Fleury 20, Suisse"),
    ("Denner Satellit Peseux", "Grand-Rue 5, Suisse"),
    ("Aldi Suisse 147", "Route de Neuchâtel 1, Suisse"),
    ("Boulangerie du Centre", "Rue du Château 2, Suisse"),
]
EATING_OUT = [
    ("Pizzeria Da Mario", "Rue des Moulins 7, Suisse", 24, 68),
    ("Sushi Zen", "Place Pury 3, Suisse", 30, 85),
    ("Bar du Port", "Quai Osterwald 1, Suisse", 9, 42),
    ("Café de la Gare", "Place de la Gare 1, Suisse", 4.2, 9.8),
    ("Burger Factory", "Rue de l'Hôpital 9, Suisse", 18, 32),
]
SHOPS = [
    ("Zara Neuchâtel", "Rue de l'Hôpital 1, Suisse", 29, 120),
    ("Digitec Galaxus AG", "Pfingstweidstrasse 60, Suisse", 19, 310),
    ("AMAZON MKTPL", "Rue Plaetis 38, Luxembourg", 12, 80),
    ("Pharmacie du Lac", "Rue du Lac 4, Suisse", 8, 60),
]


def _chf5(value: float) -> float:
    """Swiss cash rounding: card amounts in CHF end in 0 or 5 centimes."""
    return round(round(value * 20) / 20, 2)


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", "’")


def _eur_rate(day: dt.date) -> float:
    return round(1.045 + 0.03 * (day - START).days / 730, 6)


def _usd_rate(day: dt.date) -> float:
    return round(1.12 + 0.06 * (day - START).days / 730
                 + 0.01 * math.sin((day - START).days / 40), 6)


def _payer(day: dt.date):
    """Who pays the salary: one employer, a month without pay, benefits,
    then another employer -- the transition the income band exists to show."""
    if day < dt.date(2026, 1, 1):
        return "Alpha Conseil SA", "Rue du Musée,4", 6450.00
    if day < dt.date(2026, 2, 1):
        return None
    if day < dt.date(2026, 5, 1):
        return "Caisse cantonale de chômage", "Rue des Moulins,12", 4180.00
    return "Beta Finance SA", "Quai du Port,8", 7120.00


class _Builder:
    def __init__(self, seed: int = 20240730):
        self.rng = random.Random(seed)
        self.rows: dict[str, list[dict]] = {"CHF": [], "EUR": [], "USD": []}
        self.ref = 612_000_000

    # --- one row ----------------------------------------------------------

    def _next_ref(self) -> str:
        self.ref += self.rng.randint(3, 400)
        return str(self.ref)

    def add(self, day, currency, kind, amount, merchant="", location="",
            detail=None, ref=None):
        self.rows[currency].append({
            "date": day, "currency": currency, "kind": kind,
            "amount": round(amount, 2), "merchant": merchant,
            "location": location,
            "detail": detail if detail is not None else [kind],
            "ref": ref or self._next_ref(),
        })

    def card(self, day, merchant, location, amount, currency="CHF"):
        self.add(day, currency, CARD, -amount, merchant, location,
                 [CARD, merchant, location])

    def transfer(self, day, payee, amount):
        kind = f"Versement pour {payee}"
        digits = "".join(str(self.rng.randint(0, 9)) for _ in range(27))
        self.add(day, "CHF", kind, -amount, detail=[
            kind, "IBAN : CH5604835012345678009", "BIC/SWIFT : POFICHBEXXX",
            f"Référence : {digits}"])

    def incoming(self, day, payer, address, amount):
        self.add(day, "CHF", INCOMING, amount, payer, address, [
            INCOMING, payer, address, "2000,Neuchâtel", "CH",
            "IBAN : CH4431999123000889012", "BIC/SWIFT : UBSWCHZH80A"])

    def twint(self, day, amount):
        self.add(day, "CHF", TWINT, amount)

    def fx(self, day, currency, foreign, manual=False):
        """Both legs of a CHF -> foreign conversion, one reference."""
        kind = (f"Transfert {'Forex manuel' if manual else 'automatisé'} "
                f"CHF vers {currency}")
        rate = _eur_rate(day) if currency == "EUR" else _usd_rate(day)
        charged = round(foreign / rate * (1 + MARKUP), 2)
        printed = f"Taux de change : 1 CHF = {rate:.6f} {currency}"
        ref = self._next_ref()
        self.add(day, "CHF", kind, -charged,
                 detail=[kind, printed, f"Montant: {_money(foreign)} {currency}"],
                 ref=ref)
        self.add(day, currency, kind, foreign,
                 detail=[kind, printed, f"Montant: {_money(charged)} CHF"],
                 ref=ref)

    # --- one day ------------------------------------------------------------

    def day(self, d: dt.date):
        rng = self.rng
        first_chf = len(self.rows["CHF"])
        weekday = d.weekday() < 5
        payer = _payer(d)

        # Fixed commitments.
        if d.day == 1 and d > START:
            # The bank prints the same property manager two ways.
            name = ("Régie du Centre SA" if d < dt.date(2025, 9, 1)
                    else "Régie du Centre S.A.")
            self.transfer(d, name, 1650.00)
        if d.day == 3 and d <= dt.date(2026, 5, 3):
            self.card(d, "Fitness Club Exemple", "Rue de la Gare 3, Suisse", 69.00)
        if d.day == 5:
            premium = {2024: 389.50, 2025: 412.30, 2026: 431.00}[d.year]
            self.transfer(d, "Assura-Basis SA", premium)
        if d.day == 10:
            self.transfer(d, "Swisscom (Schweiz) AG", 64.90)
            if d.month == 12:
                self.transfer(d, "La Mobilière Assurances", 1180.00)
        if d.day == 12:
            self.card(d, "NETFLIX.COM", "Stationsplein 1, Pays-Bas", 20.90)
        if d.day == 15 and d.month in (1, 4, 7, 10):
            self.transfer(d, "SERAFE AG", 83.50)
        if d.day == 20 and d.month % 2 == 0:
            self.transfer(d, "Viteos SA", round(rng.uniform(80, 120), 2))
        if d.day == 20 and d.month == 5:
            self.transfer(d, "Administration fiscale cantonale",
                          6240.00 if d.year == 2025 else 6810.00)
        # Money in from more payers than the income band has hues, so its
        # tail has to fold -- refunds, a friend paying back, a club.
        occasional = {
            dt.date(2024, 11, 3): ("Paul Exemple", "Chemin des Pins,2", 60.00),
            dt.date(2025, 1, 8): ("Marie Exemple", "Rue du Lac,14", 150.00),
            dt.date(2025, 2, 17): ("Swisscom (Schweiz) AG", "Alte Tiefenaustrasse,6", 25.90),
            dt.date(2025, 4, 14): ("Assura-Basis SA", "Avenue C.-F. Ramuz,70", 86.40),
            dt.date(2025, 8, 20): ("Marie Exemple", "Rue du Lac,14", 95.00),
            dt.date(2025, 9, 15): ("Administration fiscale cantonale",
                                   "Rue du Docteur-Coullery,5", 402.00),
            dt.date(2026, 6, 6): ("Club Nautique Exemple", "Port du Nid-du-Crô,1", 40.00),
        }
        if d in occasional:
            self.incoming(d, *occasional[d])
        if d.day == 25 and payer:
            name, address, pay = payer
            self.incoming(d, name, address, pay)
            if d.month == 11 and name == "Alpha Conseil SA":  # 13th salary
                self.incoming(d, name, address, pay)
        if d.month == 12 and d.day == 31:
            self.add(d, "CHF", INTEREST, 0.12 if d.year == 2024 else 0.07)

        # Everyday spending.
        if rng.random() < 0.4:
            merchant, location = rng.choice(GROCERIES)
            self.card(d, merchant, location, _chf5(rng.uniform(6, 95)))
        if weekday and payer and payer[0] == "Alpha Conseil SA" and rng.random() < 0.45:
            # The canteen: one price, most weekdays -- the payment mode.
            self.card(d, "Restaurant Cantine Alpha", "Rue du Musée 4, Suisse",
                      8.00 if rng.random() < 0.9 else 11.50)
        if weekday and payer and payer[0] == "Beta Finance SA" and rng.random() < 0.3:
            self.card(d, "Restaurant Le Comptoir", "Quai du Port 8, Suisse",
                      _chf5(rng.uniform(14, 22)))
        if rng.random() < 0.18:
            merchant, location, low, high = rng.choice(EATING_OUT)
            self.card(d, merchant, location, _chf5(rng.uniform(low, high)))
        if d in (dt.date(2024, 10, 5), dt.date(2025, 8, 2)):
            # Same brand, other category, and small next to the groceries: the
            # merged "Coop" keeps it in transport, reports the category that
            # carries the money, and does not call a 99 % split a mix.
            self.card(d, "Coop Tankstelle Thielle", "Route de Berne 2, Suisse",
                      19.00 if d.year == 2024 else 22.40)
        if rng.random() < 0.08:
            self.card(d, "SBB CFF FFS", "Place de la Gare 1, Suisse",
                      _chf5(rng.uniform(4.4, 92)))
        if rng.random() < 0.02:
            self.card(d, "UBER *TRIP", "Rue de la Gare 1, Suisse",
                      _chf5(rng.uniform(14, 38)))
        if rng.random() < 0.04:
            merchant, location, low, high = rng.choice(SHOPS)
            self.card(d, merchant, location, _chf5(rng.uniform(low, high)))
        if rng.random() < 0.12:
            self.twint(d, -_chf5(rng.uniform(5, 60)))
        if rng.random() < 0.03:
            self.twint(d, _chf5(rng.uniform(10, 80)))
        if (d - START).days % 75 == 40:
            self.transfer(d, "Marie Exemple", _chf5(rng.uniform(80, 300)))
        # A parking meter paid by Twint: the same small amount, over and
        # over, and nothing on the line but "Paiement Twint". Off the random
        # stream, so every other row stays where it was.
        if (d - START).days % 23 == 5:
            self.twint(d, -2.50)

        # One-offs.
        one_offs = {
            dt.date(2024, 9, 7): ("IKEA Aubonne", "Route de l'Etraz 2, Suisse", 389.00),
            dt.date(2025, 3, 14): ("Handelshaus Nord GmbH", "Industriestrasse 4, Suisse", 75.00),
            dt.date(2025, 6, 1): ("easyJet", "Hangar 89, Royaume-Uni", 186.00),
            dt.date(2025, 10, 2): ("Handelshaus Nord GmbH", "Industriestrasse 4, Suisse", 112.40),
            dt.date(2025, 11, 22): ("IKEA Aubonne", "Route de l'Etraz 2, Suisse", 145.50),
        }
        if d in one_offs:
            self.card(d, *one_offs[d])
        # October 2025, for the monthly review: a debit the card charged twice,
        # and a counterparty never paid before, by transfer.
        if d in (dt.date(2025, 10, 14), dt.date(2025, 10, 15)):
            self.card(d, "Ticketcorner AG", "Riedmattstrasse 12, Suisse", 89.90)
        if d == dt.date(2025, 10, 20):
            self.transfer(d, "Garage du Lac SA", 380.00)

        # Abroad: purchases in EUR / USD, each day funded by one conversion.
        eur = self._abroad(d)
        if eur:
            self.fx(d, "EUR", round(eur, 2))
        if d.day == 18 and d >= dt.date(2025, 1, 1):
            self.card(d, "OPENAI *CHATGPT SUBSCR", "San Francisco, Etats-Unis",
                      20.00, currency="USD")
            self.fx(d, "USD", 20.00)

        # The bank does not print a day's rows in reference order.
        day_rows = [r for r in self.rows["CHF"][first_chf:]
                    if not r["kind"].startswith("Transfert")]
        if len(day_rows) >= 2 and rng.random() < 0.15:
            a, b = rng.sample(day_rows, 2)
            a["ref"], b["ref"] = b["ref"], a["ref"]

        # For the tax return, after the shuffle so the random stream of every
        # other day stays where it was: a gift to a charity, an evening course.
        if d == dt.date(2025, 12, 3):
            self.transfer(d, "Croix-Rouge suisse", 150.00)
        if d == dt.date(2025, 2, 11):
            self.transfer(d, "Ecole-club Migros", 340.00)
        # Money moved between the holder's own accounts, the name printed
        # the bank's way round: neither income nor spending.
        if d == dt.date(2025, 3, 3):
            self.incoming(d, "EXEMPLE ALEX", "Chemin des Vignes,7", 2500.00)
        if d == dt.date(2025, 9, 2):
            self.transfer(d, "Alex Exemple", 1200.00)

    def _abroad(self, d: dt.date) -> float:
        """Card spending in EUR that day, still to be funded."""
        rng = self.rng
        trips = [
            (dt.date(2024, 8, 10), dt.date(2024, 8, 17), "Espagne",
             ("Hotel Sol Madrid", "Calle Mayor 5"), 540.00,
             [("Restaurante Casa Pepe", "Calle de Toledo 12", 20, 60),
              ("Carrefour Express", "Gran Via 30", 8, 40)]),
            (dt.date(2025, 7, 12), dt.date(2025, 7, 19), "Italie",
             ("Hotel Roma Centro", "Via del Corso 12"), 610.00,
             [("Trattoria da Luigi", "Via Cavour 4", 25, 70),
              ("Gelateria Fiore", "Piazza Navona 2", 4, 12)]),
            (dt.date(2026, 3, 7), dt.date(2026, 3, 8), "France",
             ("Hôtel du Parc", "Rue de Rivoli 10"), 230.00,
             [("Brasserie du Louvre", "Rue de Rivoli 2", 30, 75)]),
        ]
        for first, last, country, (hotel, street), night, places in trips:
            if not first <= d <= last:
                continue
            spent = 0.0
            if d == first:
                if country == "Italie":
                    # Paid ahead with a manual conversion: the EUR leg lands
                    # first, the hotel draws it back to zero.
                    self.fx(d, "EUR", night, manual=True)
                    self.card(d, hotel, f"{street}, {country}", night, "EUR")
                else:
                    self.card(d, hotel, f"{street}, {country}", night, "EUR")
                    spent += night
            for merchant, place, low, high in places:
                if rng.random() < 0.8:
                    amount = round(rng.uniform(low, high), 2)
                    self.card(d, merchant, f"{place}, {country}", amount, "EUR")
                    spent += amount
            return spent
        return 0.0

    # --- the statement -------------------------------------------------------

    def statement(self) -> Statement:
        d = START
        while d <= END:
            self.day(d)
            d += dt.timedelta(days=1)

        transactions: list[Transaction] = []
        accounts: list[AccountSummary] = []
        page = 2
        for currency in ("CHF", "EUR", "USD"):
            balance = OPENING_CHF if currency == "CHF" else 0.0
            opening = balance
            per_day: dict[dt.date, int] = {}
            credit = debit = 0.0
            for i, row in enumerate(self.rows[currency]):
                balance = round(balance + row["amount"], 2)
                seq = per_day.get(row["date"], 0)
                per_day[row["date"]] = seq + 1
                if row["amount"] > 0:
                    credit += row["amount"]
                else:
                    debit -= row["amount"]
                txn = Transaction(
                    date=row["date"], reference=row["ref"], currency=currency,
                    amount=row["amount"], value_date=row["date"],
                    balance=balance, kind=row["kind"],
                    merchant=row["merchant"], location=row["location"],
                    detail=list(row["detail"]), page=page + i // 22, seq=seq)
                if txn.kind.startswith("Transfert"):
                    _enrich_forex(txn)
                transactions.append(txn)
            page += len(self.rows[currency]) // 22 + 1
            accounts.append(AccountSummary(
                currency=currency, opening_balance=opening,
                closing_balance=balance, credit_total=round(credit, 2),
                debit_total=round(debit, 2)))

        return Statement(
            holder=HOLDER, iban=IBAN, client_number="1234567",
            period_start=START, period_end=END,
            generated_on=END + dt.timedelta(days=1),
            reference_currency="CHF", reference_currency_label="Franc suisse",
            accounts=accounts, transactions=transactions)


def build() -> Statement:
    return _Builder().statement()


def cover_pdf(path, lines: list[str]) -> None:
    """A one-page PDF whose only text is `lines`, one per line.

    Enough for what reads a cover page and nothing more -- the Downloads
    watcher's recognition. Written by hand (Helvetica, WinAnsi, so "é"
    survives) rather than with a PDF library the suite does not otherwise
    need. The text is invented like everything here.
    """
    from pathlib import Path

    def escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 11 Tf 14 TL 50 780 Td "
              + " ".join(f"({escape(line)}) Tj T*" for line in lines)
              + " ET").encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    Path(path).write_bytes(bytes(out))
