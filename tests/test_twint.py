"""Suggestions for the blank Twints (`pms.twint`), learned from the owner's
own decisions and measured on them. Run on the synthetic statement with a
pattern pinned by hand: the model must find it, say how often it is right,
and stay silent when it would not beat always naming the usual category."""

from __future__ import annotations

import pytest

from pms import twint
from pms.categories import TWINT_UNKNOWN


@pytest.fixture
def store(tmp_path, ledger_file):
    from pms.web.store import Store
    copy = tmp_path / "ledger.json"
    copy.write_bytes(ledger_file.read_bytes())
    return Store(copy)


def _blank(store):
    return [t for t in store.statement.transactions if t.category == TWINT_UNKNOWN]


def _sort_by_pattern(store, share=1.0):
    """The owner's habit, invented: the 2.50 Twints are parking, small ones
    on a weekend pay a friend back for a drink, the rest are gifts."""
    from pms.overrides import key_of
    rows = _blank(store)
    chosen = rows[: int(len(rows) * share)]
    for t in chosen:
        amount = -t.amount
        category = ("Transports" if amount == 2.5 else
                    "Restaurants" if t.date.weekday() >= 5 and amount < 60 else "Cadeaux")
        store.overrides.pin(key_of(t), category=category, label=t.label)
    store.overrides.save()
    store.invalidate()
    return len(chosen)


def test_no_suggestion_before_enough_decisions(store):
    assert not twint.Suggester(store.statement).useful


def test_the_pattern_is_found_and_measured(store):
    sorted_ = _sort_by_pattern(store, 0.8)
    s = twint.Suggester(store.statement)
    assert s.measured["examples"] == sorted_
    assert s.useful and s.measured["top1"] > s.measured["baseline"]
    assert s.measured["top3"] >= s.measured["top1"]
    parking = next(t for t in _blank(store) if t.amount == -2.5)
    ranked, band = s.suggest(parking)
    assert ranked[0]["category"] == "Transports" and ranked[0]["why"]
    assert 0 < ranked[0]["p"] <= 1
    assert band["band"] == "moins de 5" and band["examples"] >= twint.MIN_BAND
    assert band["top1"] >= twint.BAND_ACCURACY


def test_a_feature_reads_as_a_reason():
    assert twint.reason("trip:après") == "dans les semaines après un séjour à l'étranger"
    assert twint.reason("card:Restaurants") == "un achat « Restaurants » par carte le même jour"
    assert twint.band(7.5) == "5 à 15" and twint.band(450) == "plus de 300"


def test_the_report_is_aggregates_only(store):
    _sort_by_pattern(store, 0.8)
    r = twint.report(store.statement)
    assert r["sorted"] > 0 and r["accuracy"]["examples"] == r["sorted"]
    flat = repr(r)
    assert "Paiement Twint" not in flat and "date" not in flat
    assert {c["category"] for c in r["categories"]} <= {"Transports", "Restaurants", "Cadeaux"}


def test_the_triage_shows_suggestions_never_applies_them(tmp_path, ledger_file):
    from pms.web import create_app
    copy = tmp_path / "ledger.json"
    copy.write_bytes(ledger_file.read_bytes())
    app = create_app(copy)
    _sort_by_pattern(app.extensions["pms_store"], 0.8)
    with app.test_client() as c:
        state = c.get("/api/triage").get_json()
    assert state["suggestions"] and state["current"]["category"] == TWINT_UNKNOWN
    assert state["measured"]["top1"] >= twint.BAND_ACCURACY


def test_a_band_is_only_trusted_where_it_was_measured_right(store):
    """The real ledger's lesson: one rate over every band hid that small
    amounts were all one category and large ones all different."""
    _sort_by_pattern(store, 0.8)
    s = twint.Suggester(store.statement)
    for label, stats in s.bands.items():
        assert (s.trusted(label) is not None) == (
            stats["examples"] >= twint.MIN_BAND and stats["top1"] >= twint.BAND_ACCURACY)


def test_a_one_sided_band_is_offered_whole_and_undone(tmp_path, ledger_file):
    from pms.web import create_app
    copy = tmp_path / "ledger.json"
    copy.write_bytes(ledger_file.read_bytes())
    app = create_app(copy)
    store = app.extensions["pms_store"]
    _sort_by_pattern(store, 0.8)
    with app.test_client() as c:
        bands = c.get("/api/triage").get_json()["bands"]
        parking = next(b for b in bands if b["band"] == "moins de 5")
        assert parking["category"] == "Transports" and parking["purity"] >= twint.BAND_PURITY
        left = len(_blank(store))
        r = c.post("/api/triage", json={"action": "band", "keys": parking["keys"],
                                        "category": "Transport"},
                   headers={"Origin": "http://localhost"})
        assert r.status_code == 200
        assert len(_blank(store)) == left - parking["count"]
        c.post("/api/triage", json={"action": "restore", "restore": r.get_json()["restore"]},
               headers={"Origin": "http://localhost"})
        assert len(_blank(store)) == left


def _card(day, label, country, amount=-30.0):
    import datetime as dt
    from pms.models import Transaction
    t = Transaction(date=dt.date.fromisoformat(day), reference=day + label, currency="CHF",
                    amount=amount, value_date=None, balance=None,
                    kind="Paiement par carte - se terminant par 1234", merchant=label,
                    location=f"Rue 1, {country}")
    t.category = "Restaurants & bars"
    return t


def test_a_stay_abroad_is_shops_not_websites():
    import datetime as dt
    from types import SimpleNamespace
    rows = [_card("2026-07-04", "Café du Port", "Portugal"),
            _card("2026-07-05", "Mercado Central", "Portugal")]
    # A website billed from abroad every month is not a trip.
    rows += [_card(f"2026-0{m}-15", "Streaming Ltd", "Irlande") for m in range(1, 7)]
    rows += [_card("2026-03-15", "Une seule boutique", "France")]
    ctx = twint.Context(SimpleNamespace(transactions=rows))
    assert ctx.abroad == [dt.date(2026, 7, 4), dt.date(2026, 7, 5)]
    assert ctx.stays[0]["countries"] == ["Portugal"]
    assert ctx.near_abroad(dt.date(2026, 7, 5)) == "pendant"
    assert ctx.near_abroad(dt.date(2026, 7, 15)) == "après"
    assert ctx.near_abroad(dt.date(2026, 8, 1)) == ""
    assert ctx.near_abroad(dt.date(2026, 3, 16)) == ""


def test_a_day_across_the_border_is_not_a_trip():
    from types import SimpleNamespace
    rows = [_card("2026-05-09", "Hypermarché", "France"),
            _card("2026-05-09", "Station-service", "France")]
    assert twint.Context(SimpleNamespace(transactions=rows)).stays == []


def test_a_share_of_a_trip_is_named_a_trip():
    """The owner's convention: a Twint paying back a share of something is
    classified by what it paid for."""
    import datetime as dt
    from types import SimpleNamespace

    from pms.models import Transaction
    rows = [_card("2026-07-04", "Café du Port", "Portugal"),
            _card("2026-07-06", "Mercado Central", "Portugal")]
    ctx = twint.Context(SimpleNamespace(transactions=rows))

    def twint_of(day, amount):
        return Transaction(date=dt.date.fromisoformat(day), reference="t" + day, currency="CHF",
                           amount=-amount, value_date=None, balance=None, kind="Paiement Twint")

    hint = twint.trip_hint(twint_of("2026-07-12", 420.0), ctx)
    assert hint["when"] == "après" and hint["category"] == twint.TRAVEL
    assert twint.trip_hint(twint_of("2026-07-12", 18.6), ctx) is None
    assert twint.trip_hint(twint_of("2026-09-12", 420.0), ctx) is None


def test_a_mixed_band_still_shows_its_sure_guesses():
    """30 to 60 CHF on the real ledger: 75 % one category, under the bar for
    the band -- but the guesses the model is sure of are measured apart."""
    band = "band:30 à 60"
    examples = [([band, "day:weekend", "card:Restaurants & bars"], "Restaurants & bars")] * 15
    examples += [([band, "day:semaine"], "Cadeaux" if i % 2 else "Shopping") for i in range(16)]
    model = twint.Model(examples)
    stats = twint.band_stats(model)["30 à 60"]
    assert stats["top1"] < twint.BAND_ACCURACY
    assert stats["sure_examples"] >= twint.MIN_BAND and stats["sure_top1"] >= twint.BAND_ACCURACY

    s = twint.Suggester.__new__(twint.Suggester)
    s.bands = {"30 à 60": stats}
    assert s.trusted("30 à 60", 0.95)["basis"] == "sure"
    assert s.trusted("30 à 60", 0.6) is None
