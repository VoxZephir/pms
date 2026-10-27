"""What the statement brings to the tax return, rubric by rubric, for
`/impots` (`docs/impots.md`): the 3a paid in, the care left to pay, the
donations, the commute, the training, the premiums, the interest -- each
with the federal rule that turns it into a deduction, and the lines behind it.

The rules are the federal direct tax's (IFD) for an employed single person;
the cantons have their own, often close, sometimes not -- the page says so.
The certificates (salary, 3a, insurer, donations) remain what the return is
filled from: this is where to look, and roughly how much.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

from . import analysis, fiscal, health, holdings

# IFD amounts by tax year (ESTV circular 215: unchanged for 2026). A year
# past the table carries the last known one and says so.
RULES = {
    2024: {"commute_cap": 3200, "training_cap": 12_900, "premiums_flat": 1700, "premiums_flat_no_pension": 2550},
    2025: {"commute_cap": 3300, "training_cap": 13_000, "premiums_flat": 1800, "premiums_flat_no_pension": 2700},
    2026: {"commute_cap": 3300, "training_cap": 13_000, "premiums_flat": 1800, "premiums_flat_no_pension": 2700},
}
MEDICAL_THRESHOLD = 0.05      # of net income (LIFD art. 33 al. 1 let. h)
DONATION_MIN = 100.0          # a year (LIFD art. 33a)
DONATION_CAP = 0.20           # of net income

# Charities whose name says what they are; a personal rule filing a payee
# under a "Dons" subcategory is counted too.
DONATIONS = re.compile(
    r"Croix[- ]Rouge|Rotes Kreuz|Caritas|M[ée]decins Sans Fronti[èe]res|\bMSF\b|UNICEF|\bWWF\b|"
    r"Pro Natura|Greenpeace|Amnesty|Terre des hommes|Swissaid|HEKS|EPER|Helvetas|Pro Juventute|"
    r"Pro Senectute|Winterhilfe|Glückskette|Cha[iî]ne du Bonheur|Ligue suisse contre le cancer|"
    r"Krebsliga|Rega\b|Pro Infirmis|SOS Villages|Emmaüs|Armée du Salut|Heilsarmee|Fondation\b|Stiftung\b",
    re.IGNORECASE)
TRAINING = re.compile(
    r"Udemy|Coursera|Preply|LANGUATALK|edX|Migros Klubschule|[ÉE]cole[- ]club|Universit[éä]|"
    r"\bHES\b|\bEPF\b|\bETH\b|Formation|Weiterbildung|Fernuni|IFAGE|Bildungszentrum",
    re.IGNORECASE)

PAY_MIN = 1000.0

# The canton's own rules (ICC), from the year the return is filed there.
# Geneva (LIPP): care above 0.5 % of net income (art. 32), commuting capped
# at 529 CHF whatever the means (art. 29), health premiums actually paid up
# to a cap (art. 32) -- read on ge.ch on 19.10.2026 from the ICC table, its
# year not printed: check it against the guide of the year. Where the
# canton's figure was not found, the federal one stands, marked to check.
CANTONS = {
    "GE": {"name": "Genève", "medical_threshold": 0.005, "commute_cap": 529, "premiums_cap": 6864,
           "donation_cap": 0.20, "training_cap": None,
           "guide": "https://www.ge.ch/c/guidepp2026"},
}
SETTINGS = {"canton": "", "since": None, "paid_next_year": False}


def load_settings(path) -> dict:
    """Where the return is filed, from which year, and whether a year's tax
    is paid the year after (`data/tax.json`)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    out = {**SETTINGS, **{k: raw[k] for k in SETTINGS if k in raw}}
    if out["canton"] not in CANTONS:
        out["canton"] = ""
    try:
        out["since"] = int(out["since"]) if out["since"] else None
    except (TypeError, ValueError):
        out["since"] = None
    out["paid_next_year"] = bool(out["paid_next_year"])
    return out


def save_settings(path, canton: str, since: int | None, paid_next_year: bool) -> dict:
    if canton and canton not in CANTONS:
        raise ValueError("Canton non pris en charge.")
    settings = {"canton": canton, "since": since if canton else None,
                "paid_next_year": paid_next_year}
    Path(path).write_text(json.dumps(settings, indent=1), encoding="utf-8")
    return settings


def canton_for(settings: dict, year: int) -> dict | None:
    if settings["canton"] and (settings["since"] is None or year >= settings["since"]):
        return {"code": settings["canton"], **CANTONS[settings["canton"]]}
    return None

PUBLIC_TRANSPORT = ("Transport", "Train & transports publics")
TAXES = "Impôts"
INSURANCE = {("Santé & assurance", "Assurance maladie"), ("Santé & assurance", "Autres assurances")}


def rules(year: int) -> tuple[dict, bool]:
    if year in RULES:
        return RULES[year], True
    known = [y for y in RULES if y <= year] or [min(RULES)]
    return RULES[max(known)], False


def years(statement) -> list[int]:
    return sorted({t.date.year for t in statement.transactions}, reverse=True)


def _line(t) -> dict:
    return {"date": t.date, "label": t.label, "amount": round(-t.amount_chf, 2),
            "key": f"{t.reference}:{t.currency}"}


def _rows(transactions) -> list[dict]:
    return [_line(t) for t in sorted(transactions, key=lambda t: t.date)]


def _in_year(statement, year: int):
    return [t for t in statement.transactions if t.date.year == year and not analysis.is_internal(t)]


def _whole(statement, year: int) -> bool:
    return statement.period_start <= dt.date(year, 1, 1) and statement.period_end >= dt.date(year, 12, 31)


def salaries(rows) -> list[dict]:
    """What came in as pay, payer by payer -- the salary certificate is the
    figure the return wants, this is the net it paid out."""
    by_payer: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for t in rows:
        if t.amount_chf > 0 and t.category == "Revenus" and not t.subcategory.startswith("Remboursement"):
            by_payer[t.label] += t.amount_chf
            count[t.label] += 1
    # Pay is large and regular: a friend paying back twice is not a payer.
    return [{"label": k, "amount": round(v, 2), "count": count[k]}
            for k, v in sorted(by_payer.items(), key=lambda kv: -kv[1])
            if v >= PAY_MIN and v / count[k] >= PAY_MIN / 2]


def return_items(statement, year: int, *, net_income: float | None, finpension: dict | None,
                 ibkr: dict | None, crypto: dict | None, franchise: int, insurer: str | None,
                 today: dt.date, settings: dict | None = None, owned: list[dict] | None = None) -> dict:
    """Every rubric of the return the statement says something about, under
    the federal rule and, from the year the canton is set, under its own."""
    settings = settings or dict(SETTINGS)
    canton = canton_for(settings, year)
    rule, published = rules(year)
    rows = _in_year(statement, year)
    pay = salaries(rows)
    paid_out = sum(p["amount"] for p in pay)
    pillar = fiscal.pillar3a(finpension, statement.transactions, year, today)
    # The thresholds are shares of the net income: declared on the page, or
    # the pay received less the 3a -- the closest the statement comes.
    estimated = net_income is None
    net = net_income if net_income is not None else max(paid_out - pillar["paid"], 0.0)

    items = []

    deductible_3a = min(pillar["paid"], pillar["ceiling"])
    items.append({
        "key": "3a", "group": "deductions", "title": "Pilier 3a",
        "form": "Déductions · cotisations au pilier 3a",
        "amount": pillar["paid"], "deductible": round(deductible_3a, 2), "certainty": "exact",
        "rule": f"Versé dans l'année, jusqu'à {analysis.chf(pillar['ceiling'], 0)} CHF avec une caisse de pension. "
                "L'attestation de la fondation fait foi.",
        "rows": [{"date": d, "label": label, "amount": round(a, 2), "key": None} for d, a, label in pillar["deposits"]],
        "note": (f"{analysis.chf(pillar['left'], 0)} CHF encore versables avant le 31.12." if pillar["left"] and year == today.year else ""),
    })

    premiums = [t for t in rows if (t.category, t.subcategory) in INSURANCE and t.amount_chf < 0]
    paid_premiums = sum(-t.amount_chf for t in premiums)
    flat = rule["premiums_flat"]
    items.append({
        "key": "premiums", "group": "deductions", "title": "Primes d'assurance",
        "form": "Déductions · primes d'assurance et intérêts de capitaux d'épargne",
        "amount": round(paid_premiums, 2), "deductible": float(min(paid_premiums, flat)), "certainty": "rule",
        "rule": f"Un forfait : {analysis.chf(flat, 0)} CHF au plus avec un 2e pilier ou un 3a "
                f"({analysis.chf(rule['premiums_flat_no_pension'], 0)} sans), quel que soit le montant payé au-delà.",
        "rows": _rows(premiums), "note": "",
    })

    care = next((y for y in health.care_by_year(statement, insurer, franchise) if y["year"] == year), None)
    share = care["share"] if care else 0.0
    threshold = MEDICAL_THRESHOLD * net
    care_rows = [t for t in rows if (t.category, t.subcategory) == health.CARE
                 or (t.category == health.CARE[0] and t.subcategory == "Remboursement")]
    items.append({
        "key": "medical", "group": "deductions", "title": "Frais de maladie",
        "form": "Déductions · frais de maladie et d'accident",
        "amount": round(share, 2), "deductible": round(max(share - threshold, 0.0), 2), "certainty": "estimate",
        "rule": f"La part restée à ta charge (franchise, quote-part, soins non couverts), au-delà de 5 % du revenu net : "
                f"{analysis.chf(threshold, 0)} CHF ici.",
        "rows": _rows(care_rows),
        "note": "Les primes n'en font pas partie. Le décompte annuel de la caisse donne le chiffre exact.",
    })

    gifts = [t for t in rows if t.amount_chf < 0 and (DONATIONS.search(t.label or "") or "Don" in t.subcategory)]
    given = sum(-t.amount_chf for t in gifts)
    items.append({
        "key": "donations", "group": "deductions", "title": "Dons",
        "form": "Déductions · dons à des institutions d'utilité publique",
        "amount": round(given, 2),
        "deductible": round(min(given, DONATION_CAP * net), 2) if given >= DONATION_MIN else 0.0,
        "certainty": "estimate",
        "rule": f"À des institutions suisses exonérées, {analysis.chf(DONATION_MIN, 0)} CHF au moins dans l'année, "
                f"jusqu'à 20 % du revenu net. Repérés à leur nom : vérifier chaque ligne, garder les reçus.",
        "rows": _rows(gifts), "note": "",
    })

    transport = [t for t in rows if (t.category, t.subcategory) == PUBLIC_TRANSPORT and t.amount_chf < 0]
    commute = sum(-t.amount_chf for t in transport)
    items.append({
        "key": "commute", "group": "deductions", "title": "Trajets domicile – travail",
        "form": "Déductions · frais de déplacement",
        "amount": round(commute, 2), "deductible": None, "certainty": "indicative",
        "rule": f"Seul le trajet entre le domicile et le travail compte, au prix de l'abonnement, "
                f"jusqu'à {analysis.chf(rule['commute_cap'], 0)} CHF (IFD). Le total ci-contre compte tous les billets.",
        "rows": _rows(transport), "note": "",
    })

    courses = [t for t in rows if t.amount_chf < 0 and TRAINING.search(t.label or "")]
    trained = sum(-t.amount_chf for t in courses)
    items.append({
        "key": "training", "group": "deductions", "title": "Formation continue",
        "form": "Déductions · frais de formation et de perfectionnement",
        "amount": round(trained, 2), "deductible": round(min(trained, rule["training_cap"]), 2) if trained else 0.0,
        "certainty": "estimate",
        "rule": f"Une formation en lien avec le métier, jusqu'à {analysis.chf(rule['training_cap'], 0)} CHF. "
                "Repérée au nom de l'école : vérifier chaque ligne.",
        "rows": _rows(courses), "note": "",
    })

    if canton:
        name = canton["name"]
        same = f"Comme l'impôt fédéral : {name} suit la même règle."
        by_key = {
            "3a": (deductible_3a, same, True),
            "premiums": (min(paid_premiums, canton["premiums_cap"]),
                         f"Les primes payées, jusqu'à {analysis.chf(canton['premiums_cap'], 0)} CHF pour une "
                         f"personne seule (barème ICC lu sur ge.ch, à vérifier pour l'année).", False),
            "medical": (max(share - canton["medical_threshold"] * net, 0.0),
                        f"Au-delà de {canton['medical_threshold'] * 100:.1f} % du revenu net : "
                        f"{analysis.chf(canton['medical_threshold'] * net, 0)} CHF ici, bien plus bas qu'au fédéral.", True),
            "donations": (min(given, canton["donation_cap"] * net) if given else 0.0,
                          f"Jusqu'à {canton['donation_cap'] * 100:.0f} % du revenu net, à des institutions exonérées ; "
                          "le montant minimal du canton est à vérifier.", False),
            "commute": (min(commute, canton["commute_cap"]) if commute else 0.0,
                        f"Plafonnés à {analysis.chf(canton['commute_cap'], 0)} CHF par an, quel que soit le moyen de "
                        "transport : dès que le trajet domicile – travail coûte autant, le plafond est atteint.", True),
            "training": (min(trained, rule["training_cap"]) if trained else 0.0,
                         "Plafond cantonal non trouvé : celui de l'impôt fédéral, à vérifier.", False),
        }
        for item in items:
            amount, text, certain = by_key[item["key"]]
            item["canton"] = {"deductible": round(amount, 2), "rule": text, "certain": certain}

    # Income the return asks for beside the salary.
    interest = [t for t in rows if t.amount_chf > 0 and t.kind.startswith("Intérêts")]
    wealth = fiscal.year_end(statement, ibkr, finpension, crypto, year,
                             None if _whole(statement, year) or year < statement.period_end.year
                             else statement.period_end)
    # Securities outside the statement (an unlisted share): their declared
    # value joins the wealth, their dividends the income (`holdings.py`).
    securities = []
    for h in owned or []:
        unit = holdings.value_at(h, year)
        if unit is None:
            continue
        paid = holdings.dividends(statement, h, year)
        securities.append({"id": h["id"], "name": h["name"], "kind": holdings.kind_of(h),
                           "quantity": h["quantity"], "unit": unit,
                           "value": round(unit * h["quantity"], 2), "payer": h["payer"],
                           "withholding": h["withholding"], "dividends": paid})
        share = holdings.kind_of(h) == holdings.SHARE
        quantity = (f"{h['quantity']:g} titre{'s' if h['quantity'] > 1 else ''}" if share
                    else f"{h['quantity']:g}")
        wealth["rows"].append({"name": h["name"], "kind": "security" if share else "asset",
                               "detail": f"{quantity} × {analysis.chf(unit, 2)}, valeur déclarée",
                               "value": round(unit * h["quantity"], 2)})
        wealth["taxable"] = round(wealth["taxable"] + unit * h["quantity"], 2)
    # Which payments settle this year's tax: those of the year itself, or --
    # where the settings say a year's tax is paid the year after (as in
    # Geneva) -- those of the next.
    paid_later = bool(canton) and settings["paid_next_year"]
    paid_year = year + 1 if paid_later else year
    paid_rows = _in_year(statement, paid_year)
    taxes_out = [t for t in paid_rows if t.category == TAXES and t.amount_chf < 0]
    taxes_back = [t for t in paid_rows if t.category == TAXES and t.subcategory == "Remboursement"]

    deductions = [i for i in items if i["group"] == "deductions"]
    return {
        "year": year, "whole": _whole(statement, year), "published": published,
        "net": {"value": round(net, 2), "estimated": estimated, "pay": round(paid_out, 2)},
        "salaries": pay,
        "items": deductions,
        "deducted": round(sum(i["deductible"] or 0.0 for i in deductions), 2),
        "pillar3a": pillar,
        "interest": {"bank": round(sum(t.amount_chf for t in interest), 2),
                     "dividends": wealth["dividends"], "broker": wealth["interest"],
                     "withheld": wealth["withheld"], "rows": [{**_line(t), "amount": round(t.amount_chf, 2)} for t in interest]},
        "wealth": wealth,
        "securities": securities,
        "canton": canton, "settings": settings,
        "deducted_canton": (round(sum(i["canton"]["deductible"] for i in deductions), 2) if canton else None),
        "paid": {"year": paid_year, "later": paid_later,
                 "seen": statement.period_end >= dt.date(paid_year, 1, 1),
                 "out": round(sum(-t.amount_chf for t in taxes_out), 2),
                 "back": round(sum(t.amount_chf for t in taxes_back), 2),
                 "rows": _rows(taxes_out) + [{**_line(t), "amount": round(-t.amount_chf, 2)} for t in taxes_back]},
    }
