"""Suggestions for the blank Twints, learned from the owner's own decisions.

A Twint sent prints "Paiement Twint" and nothing else: no payee, no message,
no place. No rule can read a category off that line, and neither can a
language model -- the information is not on it. What exists is the owner's
own history: hundreds of Twints already sorted by hand, and around each one
the rest of the statement on that day. Small amounts on an evening out are
paying a friend back for a drink; a few hundred francs after a trip abroad
is a share of the trip. That is a pattern in the owner's decisions, and it
can be measured.

So this is a small naive Bayes over features the statement does carry --
the amount's size and roundness, the day of the week, what else was paid by
card that day, whether a stay abroad is near, whether the same amount
recurs -- trained on the Twints the owner classified, and **measured on
them** by leaving each one out in turn. The triage shows the suggestion and
that measured rate, never applies it: the owner still decides every line.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter, defaultdict

from . import analysis
from . import categories as categories_module
from .models import Statement, Transaction

CARD_KIND = "Paiement par carte"   # followed by "- se terminant par 1234"
HOME = "Suisse"                     # the country as the card line prints it
# Fewer decisions than this and the rates mean nothing: no suggestion.
MIN_TRAINING = 20
# A category needs this many examples before it is ever suggested.
MIN_PER_CATEGORY = 3
# A suggestion is shown only where it was measured right: among the Twints
# already sorted in the same amount band, at least this many, this often.
# Measured on the real ledger: nearly all sorted Twints under 60 CHF were one
# category, while the few above 120 CHF were half a dozen different ones. One
# flattering rate over all of them said nothing about either.
MIN_BAND = 10
BAND_ACCURACY = 0.8
# "Classify the whole band" is offered only for a band this one-sided.
BAND_PURITY = 0.9
# A mixed band (one on the real ledger was three-quarters restaurants) can still
# hold Twints the model is sure of. Its own sure guesses are measured apart:
# shown when, at this confidence, it was right often enough on enough cases.
SURE_P = 0.9
# A stay abroad is shops in a foreign country over at least two days. A
# foreign merchant billed in many months is a website (a streaming service,
# an airline's booking site), not a trip: on the real ledger, counting those
# put nearly all Twints "near a stay abroad". A single day of shopping
# across the border is not a trip either, and a 45-day "after" window around
# each such day still covered most of the calendar (over half the restaurants).
TRIP_GAP_DAYS = 2           # foreign shop days this close are one stay
TRIP_MIN_DAYS = 2           # an overnight stay, not a day across the border
TRIP_MIN_MERCHANTS = 2
ONLINE_MONTHS = 3
TRIP_SHARE_DAYS = 14        # a share of a trip is paid back within two weeks...
TRIP_EARLY_DAYS = 3         # ...or just before leaving
# The owner's convention (17.10): a Twint paying back a share of something is
# classified by what the money paid for -- a share of a trip is a trip, not a
# transfer to a person. From this amount, a Twint near a stay says so.
TRAVEL = "Loisirs & voyages"
TRIP_SHARE_MIN = 100.0
RECUR_DAYS = (20, 40)       # the same amount about a month apart
SMOOTHING = 1.0

BANDS = [(5, "moins de 5"), (15, "5 à 15"), (30, "15 à 30"), (60, "30 à 60"),
         (120, "60 à 120"), (300, "120 à 300"), (math.inf, "plus de 300")]
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def is_twint_out(t: Transaction) -> bool:
    return t.kind in categories_module.PEER_KINDS and t.amount < 0


def labelled(t: Transaction) -> bool:
    """A Twint the owner sorted by hand: the training set."""
    return is_twint_out(t) and t.overridden \
        and t.category not in ("", categories_module.TWINT_UNKNOWN)


def band(amount: float) -> str:
    return next(label for limit, label in BANDS if amount < limit)


class Context:
    """What the statement says around each day, computed once."""

    def __init__(self, statement: Statement):
        self.card_by_day: dict[dt.date, set[str]] = defaultdict(set)
        foreign: list[tuple[dt.date, str, str]] = []
        months: dict[str, set[str]] = defaultdict(set)
        self.twint_amounts: dict[float, list[dt.date]] = defaultdict(list)
        for t in statement.transactions:
            if t.kind.startswith(CARD_KIND) and t.amount < 0:
                if t.category:
                    self.card_by_day[t.date].add(t.category)
                country = analysis.country_of(t)
                if country and country != HOME and not country.isdigit():
                    foreign.append((t.date, t.label, country))
                    months[t.label].add(t.date.strftime("%Y-%m"))
            if is_twint_out(t):
                self.twint_amounts[round(-t.amount, 2)].append(t.date)
        # Shops abroad, websites left out, grouped into stays: foreign shop
        # days a couple of days apart at most, over two days or more, at two
        # merchants or more.
        shops = sorted((d, label, country) for d, label, country in foreign
                       if len(months[label]) < ONLINE_MONTHS)
        self.stays: list[dict] = []
        run: list[tuple] = []
        for shop in shops + [None]:
            if shop is not None and run and (shop[0] - run[-1][0]).days <= TRIP_GAP_DAYS:
                run.append(shop)
                continue
            if run and len({d for d, _, _ in run}) >= TRIP_MIN_DAYS \
                    and len({label for _, label, _ in run}) >= TRIP_MIN_MERCHANTS:
                self.stays.append({"start": run[0][0], "end": run[-1][0],
                                   "countries": sorted({c for _, _, c in run})})
            run = [shop] if shop is not None else []
        self.abroad = sorted({d for s in self.stays
                              for d in (s["start"] + dt.timedelta(days=i)
                                        for i in range((s["end"] - s["start"]).days + 1))})

    def stay_near(self, day: dt.date) -> tuple[str, dict | None]:
        """('pendant', stay) from a few days before leaving to the day after
        coming back, ('après', stay) in the two weeks after, or ('', None)."""
        for stay in self.stays:
            if stay["start"] - dt.timedelta(days=TRIP_EARLY_DAYS) <= day <= stay["end"] + dt.timedelta(days=1):
                return "pendant", stay
        for stay in reversed(self.stays):
            if stay["end"] < day <= stay["end"] + dt.timedelta(days=TRIP_SHARE_DAYS):
                return "après", stay
        return "", None

    def near_abroad(self, day: dt.date) -> str:
        return self.stay_near(day)[0]

    def recurs(self, t: Transaction) -> bool:
        low, high = RECUR_DAYS
        return any(low <= abs((d - t.date).days) <= high
                   for d in self.twint_amounts[round(-t.amount, 2)])


def features(t: Transaction, ctx: Context) -> list[str]:
    """The tokens one Twint carries. Each says something the statement
    actually printed, and each reads as a reason (`REASONS`)."""
    amount = round(-t.amount, 2)
    tokens = [f"band:{band(amount)}", f"exact:{amount:.2f}",
              "day:weekend" if t.date.weekday() >= 5 else "day:semaine",
              f"dow:{t.date.weekday()}"]
    if amount == int(amount) and amount % 10 == 0:
        tokens.append("round:10")
    elif amount == int(amount) and amount % 5 == 0:
        tokens.append("round:5")
    elif amount != int(amount):
        tokens.append("round:centimes")
    tokens += [f"card:{c}" for c in sorted(ctx.card_by_day.get(t.date, ()))]
    if not ctx.card_by_day.get(t.date):
        tokens.append("card:aucun")
    trip = ctx.near_abroad(t.date)
    if trip:
        tokens.append(f"trip:{trip}")
    if ctx.recurs(t):
        tokens.append("recur:mensuel")
    return tokens


def reason(token: str) -> str:
    kind, _, value = token.partition(":")
    if kind == "band":
        return f"montant de {value} CHF"
    if kind == "exact":
        return f"montant exact de {value} CHF"
    if kind == "day":
        return "un week-end" if value == "weekend" else "un jour de semaine"
    if kind == "dow":
        return f"un {WEEKDAYS[int(value)]}"
    if kind == "round":
        return "montant à centimes" if value == "centimes" else f"montant rond ({value})"
    if kind == "card":
        return "aucun achat par carte ce jour-là" if value == "aucun" \
            else f"un achat « {value} » par carte le même jour"
    if kind == "trip":
        return "pendant un séjour à l'étranger" if value == "pendant" \
            else "dans les semaines après un séjour à l'étranger"
    if kind == "recur":
        return "le même montant revient chaque mois"
    return token


class Model:
    """Counts per category and per (category, token), so leaving one
    example out is a subtraction, not a refit."""

    def __init__(self, examples: list[tuple[list[str], str]]):
        self.examples = examples
        self.prior: Counter = Counter()
        self.tokens: dict[str, Counter] = defaultdict(Counter)
        self.total: Counter = Counter()
        self.vocab: set[str] = set()
        for toks, cat in examples:
            self._add(toks, cat, 1)

    def _add(self, toks: list[str], cat: str, sign: int) -> None:
        self.prior[cat] += sign
        for tok in toks:
            self.tokens[cat][tok] += sign
            self.total[cat] += sign
            self.vocab.add(tok)

    def scores(self, toks: list[str]) -> list[tuple[str, float]]:
        """Posterior probability of each category, best first."""
        n = sum(self.prior.values())
        cats = [c for c, k in self.prior.items() if k >= MIN_PER_CATEGORY]
        if not n or not cats:
            return []
        v = len(self.vocab) or 1
        logs = {}
        for c in cats:
            s = math.log(self.prior[c] / n)
            for tok in toks:
                s += math.log((self.tokens[c][tok] + SMOOTHING)
                              / (self.total[c] + SMOOTHING * v))
            logs[c] = s
        top = max(logs.values())
        z = sum(math.exp(s - top) for s in logs.values())
        return sorted(((c, math.exp(s - top) / z) for c, s in logs.items()),
                      key=lambda kv: -kv[1])

    def leave_one_out(self) -> list[tuple[str, list[str], float]]:
        """For each example, (truth, ranked categories, confidence of the
        first) predicted without it."""
        out = []
        for toks, cat in self.examples:
            self._add(toks, cat, -1)
            scores = self.scores(toks)
            out.append((cat, [c for c, _ in scores], scores[0][1] if scores else 0.0))
            self._add(toks, cat, 1)
        return out

    def why(self, toks: list[str], cat: str, limit: int = 3) -> list[str]:
        """The tokens that most favour `cat` over the other categories."""
        others = [c for c in self.prior if c != cat]
        if not others:
            return []
        v = len(self.vocab) or 1
        rest_total = sum(self.total[c] for c in others)

        def ratio(tok):
            p = (self.tokens[cat][tok] + SMOOTHING) / (self.total[cat] + SMOOTHING * v)
            q = (sum(self.tokens[c][tok] for c in others) + SMOOTHING) / (rest_total + SMOOTHING * v)
            return math.log(p / q)

        ranked = sorted((tok for tok in toks if self.tokens[cat][tok] > 0),
                        key=ratio, reverse=True)
        # "montant de 5 à 15" and "montant exact de 8.00" say the same thing
        # twice; keep the sharper one.
        chosen, kinds = [], set()
        for tok in ranked:
            kind = tok.split(":")[0]
            kind = "amount" if kind in ("band", "exact") else "day" if kind in ("day", "dow") else kind
            if ratio(tok) <= 0 or kind in kinds:
                continue
            chosen.append(tok)
            kinds.add(kind)
            if len(chosen) == limit:
                break
        return [reason(t) for t in chosen]


def train(statement: Statement) -> tuple[Model, Context] | None:
    ctx = Context(statement)
    examples = [(features(t, ctx), t.category) for t in statement.transactions if labelled(t)]
    if len(examples) < MIN_TRAINING:
        return None
    return Model(examples), ctx


def accuracy(model: Model) -> dict:
    """Leave-one-out: how often the first suggestion, or one of the first
    three, was the owner's own choice -- next to always guessing the most
    common category, the rate any suggestion must beat to be worth showing."""
    runs = model.leave_one_out()
    n = len(runs) or 1
    common = model.prior.most_common(1)[0][1] if model.prior else 0
    return {
        "examples": len(runs),
        "top1": sum(1 for truth, ranked, _ in runs if ranked[:1] == [truth]) / n,
        "top3": sum(1 for truth, ranked, _ in runs if truth in ranked[:3]) / n,
        "baseline": common / n,
    }


def band_stats(model: Model) -> dict[str, dict]:
    """Per amount band: how many Twints were sorted there, how often the
    first suggestion was right without them, and how one-sided the band is."""
    runs: dict[str, list[tuple[str, list[str], float]]] = defaultdict(list)
    for (toks, _), run in zip(model.examples, model.leave_one_out()):
        label = next(t for t in toks if t.startswith("band:")).split(":", 1)[1]
        runs[label].append(run)
    out = {}
    for label, items in runs.items():
        cats = Counter(truth for truth, _, _ in items)
        majority, count = cats.most_common(1)[0]
        n = len(items)
        sure = [(truth, ranked) for truth, ranked, p in items if p >= SURE_P]
        out[label] = {"band": label, "examples": n,
                      "top1": sum(1 for truth, ranked, _ in items if ranked[:1] == [truth]) / n,
                      "top3": sum(1 for truth, ranked, _ in items if truth in ranked[:3]) / n,
                      "majority": majority, "purity": count / n,
                      "sure_examples": len(sure),
                      "sure_top1": (sum(1 for truth, ranked in sure if ranked[:1] == [truth])
                                    / len(sure)) if sure else 0.0}
    return out


class Suggester:
    """Trained once per ledger load; answers for any Twint whose amount band
    it was measured right on."""

    def __init__(self, statement: Statement):
        trained = train(statement)
        self.model, self.ctx = trained if trained else (None, Context(statement))
        self.measured = accuracy(self.model) if self.model else None
        self.bands = band_stats(self.model) if self.model else {}

    def trusted(self, label: str, p: float = 0.0) -> dict | None:
        """The measurement that earns a suggestion its place: the whole band,
        or -- for a guess this sure -- the band's own sure guesses."""
        stats = self.bands.get(label)
        if not stats:
            return None
        if stats["examples"] >= MIN_BAND and stats["top1"] >= BAND_ACCURACY:
            return {**stats, "basis": "band"}
        if p >= SURE_P and stats["sure_examples"] >= MIN_BAND \
                and stats["sure_top1"] >= BAND_ACCURACY:
            return {**stats, "basis": "sure"}
        return None

    @property
    def useful(self) -> bool:
        return any(self.trusted(label) for label in self.bands)

    def suggest(self, t: Transaction, limit: int = 3) -> tuple[list[dict], dict | None]:
        """The ranked categories, and the band measurement that earns them a
        place on screen -- ([], None) where nothing was measured right."""
        if self.model is None:
            return [], None
        toks = features(t, self.ctx)
        ranked = self.model.scores(toks)[:limit]
        stats = self.trusted(band(-t.amount), ranked[0][1] if ranked else 0.0)
        if stats is None:
            return [], None
        return [{"category": c, "p": round(p, 3),
                 "why": self.model.why(toks, c) if i == 0 else []}
                for i, (c, p) in enumerate(ranked)], stats

    def band_groups(self, queue: list[Transaction]) -> list[dict]:
        """The blank Twints of each band where the sorted ones were nearly all
        one category: one decision for the band, offered, never taken."""
        rows: dict[str, list[Transaction]] = defaultdict(list)
        for t in queue:
            rows[band(-t.amount)].append(t)
        out = []
        for _, label in BANDS:
            stats = self.bands.get(label)
            if not rows.get(label) or not stats or stats["examples"] < MIN_BAND \
                    or stats["purity"] < BAND_PURITY:
                continue
            out.append({"band": label, "count": len(rows[label]),
                        "category": stats["majority"], "examples": stats["examples"],
                        "purity": stats["purity"],
                        "keys": [f"{t.reference}:{t.currency}" for t in rows[label]],
                        "total": round(sum(-t.amount for t in rows[label]), 2)})
        return out


def trip_hint(t: Transaction, ctx: Context) -> dict | None:
    """A Twint of a few hundred francs around a stay abroad: the stay, to jog
    the memory, and the owner's convention for a share of a trip."""
    if -t.amount < TRIP_SHARE_MIN:
        return None
    when, stay = ctx.stay_near(t.date)
    if stay is None:
        return None
    return {"when": when, "start": stay["start"], "end": stay["end"],
            "countries": stay["countries"], "category": TRAVEL}


def report(statement: Statement) -> dict:
    """The analysis behind the suggestions, for `--twint-report`: what was
    sorted, how each category spreads over amounts and days, and how often
    the model would have been right. Aggregates only -- no line, no date."""
    ctx = Context(statement)
    sorted_ = [t for t in statement.transactions if labelled(t)]
    left = sum(1 for t in statement.transactions
               if t.category == categories_module.TWINT_UNKNOWN)
    cats = Counter(t.category for t in sorted_)
    by_band: dict[str, Counter] = defaultdict(Counter)
    weekend: Counter = Counter()
    trip: Counter = Counter()
    amounts: dict[str, list[float]] = defaultdict(list)
    for t in sorted_:
        by_band[band(-t.amount)][t.category] += 1
        amounts[t.category].append(-t.amount)
        if t.date.weekday() >= 5:
            weekend[t.category] += 1
        if ctx.near_abroad(t.date):
            trip[t.category] += 1
    trained = train(statement)
    stats = band_stats(trained[0]) if trained else {}
    left_by_band = Counter(band(-t.amount) for t in statement.transactions
                           if t.category == categories_module.TWINT_UNKNOWN)
    return {
        "sorted": len(sorted_), "left": left,
        "left_bands": [{"band": label, "count": left_by_band[label]}
                       for _, label in BANDS if left_by_band[label]],
        "band_accuracy": [stats[label] for _, label in BANDS if label in stats],
        "trips": len(ctx.stays), "trip_days": len(ctx.abroad),
        "categories": [{"category": c, "count": n,
                        "median": sorted(amounts[c])[len(amounts[c]) // 2],
                        "total": round(sum(amounts[c]), 2),
                        "weekend": weekend[c] / n, "near_trip": trip[c] / n}
                       for c, n in cats.most_common()],
        "bands": [{"band": label, "categories": by_band[label].most_common(4),
                   "count": sum(by_band[label].values())}
                  for _, label in BANDS if by_band[label]],
        "accuracy": accuracy(trained[0]) if trained else None,
        "min_training": MIN_TRAINING,
    }


def print_report(statement: Statement) -> None:
    r = report(statement)
    print(f"Twint classés à la main : {r['sorted']}   encore à identifier : {r['left']}")
    if not r["sorted"]:
        return
    print("\nPar catégorie (montant médian, total, part le week-end, part près d'un séjour à l'étranger)")
    for c in r["categories"]:
        print(f"  {c['category']:<28} {c['count']:>4}  médiane {analysis.chf(c['median']):>9}"
              f"  total {analysis.chf(c['total']):>10}  week-end {c['weekend']:>4.0%}"
              f"  voyage {c['near_trip']:>4.0%}")
    print("\nPar tranche de montant (CHF)")
    for b in r["bands"]:
        top = ", ".join(f"{c} {n}" for c, n in b["categories"])
        print(f"  {b['band']:<12} {b['count']:>4}  {top}")
    if r["left_bands"]:
        print("\nEncore à identifier, par tranche")
        for b in r["left_bands"]:
            print(f"  {b['band']:<12} {b['count']:>4}")
    print(f"\nSéjours à l'étranger reconnus (deux jours ou plus en magasin, sites web exclus) :"
          f" {r['trips']}, {r['trip_days']} jours")
    a = r["accuracy"]
    if a is None:
        print(f"\nPas encore de suggestions : il faut {r['min_training']} Twint classés.")
        return
    print(f"\nSuggestions, mesurées en écartant chaque Twint de l'apprentissage ({a['examples']} cas) :")
    print(f"  première suggestion juste : {a['top1']:.0%}")
    print(f"  bonne catégorie parmi les trois premières : {a['top3']:.0%}")
    print(f"  toujours répondre la catégorie la plus fréquente : {a['baseline']:.0%}")
    print(f"\nPar tranche (suggestion montrée dès {MIN_BAND} cas et {BAND_ACCURACY:.0%} de juste ;"
          f" « tout classer » dès {BAND_PURITY:.0%} d'une seule catégorie)")
    for b in r["band_accuracy"]:
        shown = b["examples"] >= MIN_BAND and b["top1"] >= BAND_ACCURACY
        sure = not shown and b["sure_examples"] >= MIN_BAND and b["sure_top1"] >= BAND_ACCURACY
        bulk = b["examples"] >= MIN_BAND and b["purity"] >= BAND_PURITY
        print(f"  {b['band']:<12} {b['examples']:>4} cas  juste {b['top1']:>4.0%}"
              f"  majorité {b['majority']} {b['purity']:.0%}"
              f"  sûr à {SURE_P:.0%} : {b['sure_examples']} cas, juste {b['sure_top1']:.0%}"
              f"{'  suggestion' if shown else ''}{'  suggestion si sûr' if sure else ''}"
              f"{'  tout classer' if bulk else ''}")
