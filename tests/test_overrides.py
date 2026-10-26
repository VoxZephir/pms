"""Manual corrections: what they catch, what wins, and what survives re-import.

The property that matters is permanence. A correction is only useful if next
month's statement lands in the same place without being touched again.
"""

from __future__ import annotations

import copy
import json

import pytest

from pms import analysis, buckets
from pms.categories import classify_all
from pms.overrides import CONTAINS, Overrides, key_of


@pytest.fixture
def rows(statement):
    """A private copy: overrides mutate transactions in place."""
    rows = copy.deepcopy(statement.transactions[:400])
    classify_all(rows)
    return rows


@pytest.fixture
def store(tmp_path):
    return Overrides(tmp_path / "overrides.json")


def test_a_pin_touches_exactly_one_movement(store, rows):
    target = rows[10]
    store.pin(key_of(target), category="Loisirs & voyages")

    assert store.apply(rows) == 1
    assert target.category == "Loisirs & voyages"
    assert sum(1 for t in rows if t.overridden) == 1


def test_a_merchant_rule_catches_every_payment_to_that_counterparty(store, rows):
    label = rows[10].label
    expected = [t for t in rows if t.label == label]
    assert len(expected) > 1, "pick a counterparty that actually repeats"

    store.rule(label, category="Loisirs & voyages")
    store.apply(rows)

    assert all(t.category == "Loisirs & voyages" for t in expected)


def test_a_merchant_rule_also_catches_movements_added_later(store, rows,
                                                            statement):
    """The whole point: next month's payment needs no second correction."""
    label = rows[10].label
    store.rule(label, category="Loisirs & voyages")
    store.apply(rows)

    # A statement imported afterwards, containing a new payment to that same
    # counterparty, gets classified without touching the store again.
    later = copy.deepcopy([t for t in statement.transactions
                           if t.label == label][:1])
    classify_all(later)
    store.apply(later)
    assert later[0].category == "Loisirs & voyages"


def test_a_pin_beats_the_rule_covering_its_merchant(store, rows):
    """Correcting one odd payment must not fight the merchant's own rule."""
    label = rows[10].label
    odd = next(t for t in rows if t.label == label)

    store.rule(label, category="Alimentation")
    store.pin(key_of(odd), category="Shopping")
    store.apply(rows)

    assert odd.category == "Shopping"
    siblings = [t for t in rows if t.label == label and t is not odd]
    assert all(t.category == "Alimentation" for t in siblings)


def test_restating_a_rule_replaces_it(store, rows):
    label = rows[10].label
    store.rule(label, category="Alimentation")
    store.rule(label, category="Transport")

    assert len(store.rules) == 1
    store.apply(rows)
    assert next(t for t in rows if t.label == label).category == "Transport"


def test_contains_mode_matches_a_family_of_merchants(store, rows):
    store.rule("Coop", mode=CONTAINS, category="Shopping")
    store.apply(rows)

    hits = [t for t in rows if "coop" in t.label.casefold()]
    assert hits
    assert all(t.category == "Shopping" for t in hits)


def test_bucket_override_does_not_change_the_category(store, rows):
    """A shared rent is still a transfer; only its Need/Want answer changes."""
    target = next(t for t in rows if t.category == "Twint non identifié")
    original = target.category

    store.pin(key_of(target), bucket=buckets.NEED)
    store.apply(rows)
    buckets.annotate(rows)

    assert target.category == original
    assert target.bucket == buckets.NEED


def test_bucket_still_follows_the_category_when_not_overridden(store, rows):
    target = rows[10]
    store.pin(key_of(target), category="Restaurants & bars")
    store.apply(rows)
    buckets.annotate(rows)
    assert target.bucket == buckets.WANT


def test_removing_a_correction_restores_the_rule_engine(store, rows):
    label = rows[10].label
    before = [t.category for t in rows]

    store.rule(label, category="Loisirs & voyages")
    store.apply(rows)
    assert store.unrule(label)

    fresh = copy.deepcopy(rows)
    classify_all(fresh)
    store.apply(fresh)
    assert [t.category for t in fresh] == before


def test_survives_a_round_trip_through_disk(store, rows, tmp_path):
    """Corrections live in their own file, so re-ingesting the PDFs keeps them."""
    target = rows[10]
    store.pin(key_of(target), category="Shopping", label=target.label)
    store.rule("Coop", mode=CONTAINS, bucket=buckets.NEED)
    store.save()

    reloaded = Overrides.load(store.path)
    assert len(reloaded) == 2
    reloaded.apply(rows)
    buckets.annotate(rows)
    assert target.category == "Shopping"
    assert all(t.bucket == buckets.NEED
               for t in rows if "coop" in t.label.casefold())


def test_a_corrupt_file_does_not_break_the_app(tmp_path, rows):
    path = tmp_path / "overrides.json"
    path.write_text("{ not json at all", encoding="utf-8")

    store = Overrides.load(path)
    assert store.empty
    assert store.apply(rows) == 0


def test_saving_is_atomic(store, rows, tmp_path):
    store.pin("1:CHF", category="Shopping")
    store.save()
    assert not (tmp_path / "overrides.tmp").exists()
    assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == 1


def test_describe_reports_the_current_reach(store, rows):
    label = rows[10].label
    store.rule(label, category="Shopping")
    store.pin(key_of(rows[0]), category="Transport", label=rows[0].label)

    analysis.annotate_chf_stub = None  # amounts are already annotated below
    for txn in rows:
        txn.amount_chf = txn.amount

    described = store.describe(rows)
    rule = next(d for d in described if d["kind"] == "rule")
    pin = next(d for d in described if d["kind"] == "pin")

    assert rule["count"] == len([t for t in rows if t.label == label])
    assert pin["count"] == 1
    assert rule["category"] == "Shopping"


def test_a_pin_on_a_movement_we_no_longer_hold_is_flagged(store, rows):
    """An orphan pin is shown rather than silently dropped."""
    store.pin("999999999:CHF", category="Shopping", label="Disparu")
    for txn in rows:
        txn.amount_chf = txn.amount

    orphan = next(d for d in store.describe(rows) if d["kind"] == "pin")
    assert orphan["orphan"] is True
    assert orphan["count"] == 0


# --- bulk -------------------------------------------------------------------

def test_bulk_pin_touches_every_selected_movement(store, rows):
    target = [t for t in rows if t.category == "Twint non identifié"]
    assert len(target) > 5

    keys = store.pin_many(target, bucket=buckets.NEED)
    store.apply(rows)
    buckets.annotate(rows)

    assert len(keys) == len(target)
    assert all(t.bucket == buckets.NEED for t in target)


def test_bulk_rules_cover_the_distinct_counterparties(store, rows):
    """One rule per counterparty, not one per movement -- otherwise the file
    grows with the statement instead of with the decisions."""
    target = [t for t in rows if t.category == "Twint non identifié"]
    labels = store.rule_many(target, bucket=buckets.NEED)

    assert len(labels) == len({t.label for t in target})
    assert len(store.rules) == len(labels)


def test_bulk_rules_also_catch_later_movements(store, rows, statement):
    target = [t for t in rows if t.category == "Twint non identifié"]
    label = target[0].label
    store.rule_many(target, bucket=buckets.NEED)

    later = copy.deepcopy([t for t in statement.transactions
                           if t.label == label][:1])
    classify_all(later)
    store.apply(later)
    buckets.annotate(later)
    assert later[0].bucket == buckets.NEED


def test_bulk_undo_removes_exactly_what_it_added(store, rows):
    before = len(store)
    target = [t for t in rows if t.category == "Twint non identifié"]

    keys = store.pin_many(target, bucket=buckets.NEED)
    assert len(store) == before + len(keys)
    assert store.unpin_many(keys) == len(keys)
    assert len(store) == before


# --- a row's own pin, and undoing ---------------------------------------------

def test_a_row_reclassified_by_its_merchant_drops_its_conflicting_pin(store, rows):
    """15.10: a payment pinned to "Non catégorisé", dragged onto Restaurants
    -- the rule was written and the row stayed put, its pin outranking it."""
    target = rows[10]
    key = key_of(target)
    store.pin(key, category="Non catégorisé", label=target.label)
    store.rule(target.label, category="Restaurants & bars")
    store.yield_to_rule(key, category="Restaurants & bars")
    store.apply(rows)
    assert target.category == "Restaurants & bars"
    assert key not in store.pins


def test_a_pinned_bucket_outlives_a_rule_that_names_a_category(store, rows):
    target = rows[10]
    key = key_of(target)
    store.pin(key, category="Non catégorisé", bucket=buckets.WANT, label=target.label)
    store.yield_to_rule(key, category="Restaurants & bars")
    assert store.pins[key]["bucket"] == buckets.WANT
    assert store.pins[key]["category"] == ""


def test_undo_puts_back_what_was_there_not_nothing(store, rows):
    """A rule restated over an older one, a pin written over a bucket-only
    pin: undoing used to leave no rule and no pin at all."""
    target = rows[10]
    key = key_of(target)
    store.rule(target.label, category="Courses")
    store.rule("Autre marchand", category="Transport")
    store.pin(key, bucket=buckets.NEED, label=target.label)
    before_rules = copy.deepcopy(store.rules)
    before_pin = dict(store.pins[key])

    snap = store.snapshot([key], [target.label])
    store.rule(target.label, category="Restaurants & bars")
    store.pin(key, category="Loisirs & voyages", label=target.label)
    store.restore(json.loads(json.dumps(snap)))      # it travels as JSON

    assert store.rules == before_rules                # same rule, same place
    assert store.pins[key] == before_pin


def test_undo_of_something_new_removes_it(store, rows):
    target = rows[10]
    key = key_of(target)
    snap = store.snapshot([key], [target.label])
    store.rule(target.label, category="Courses")
    store.pin(key, category="Courses", label=target.label)
    store.restore(snap)
    assert store.empty


# --- aliases ----------------------------------------------------------------

def test_merging_two_spellings_makes_one_counterparty(store, rows):
    """The bank prints the same letting agent two ways; every total would
    otherwise count it as two people."""
    labels = [t.label for t in rows]
    variant = next(l for l in labels if labels.count(l) >= 1)
    canonical = next(l for l in labels if l != variant)

    store.alias(variant, canonical)
    store.apply(rows)

    assert not any(t.label == variant for t in rows)
    assert any(t.label == canonical for t in rows)


def test_a_rule_on_the_canonical_name_catches_the_variant(store, rows):
    labels = [t.label for t in rows]
    variant, canonical = labels[0], labels[1]
    assert variant != canonical

    store.alias(variant, canonical)
    store.rule(canonical, category="Loisirs & voyages")
    store.apply(rows)

    merged = [t for t in rows if t.label == canonical]
    assert all(t.category == "Loisirs & voyages" for t in merged)


def test_aliases_never_chain(store):
    """A -> B then B -> C must leave A pointing at C, not at a stale B."""
    store.alias("A", "B")
    store.alias("B", "C")
    assert store.canonical("A") == "C"
    assert store.canonical("B") == "C"


def test_an_alias_survives_the_round_trip(store, rows):
    labels = [t.label for t in rows]
    store.alias(labels[0], labels[1])
    store.save()

    reloaded = Overrides.load(store.path)
    assert reloaded.canonical(labels[0]) == labels[1]
    assert not reloaded.empty


def test_removing_an_alias_restores_both_names(store, rows):
    labels = [t.label for t in rows]
    variant, canonical = labels[0], labels[1]
    store.alias(variant, canonical)
    assert store.unalias(variant)
    store.apply(rows)
    assert any(t.label == variant for t in rows)


# --- merging a whole brand --------------------------------------------------

def test_a_pattern_merges_every_branch_of_a_brand(store, rows):
    """A supermarket prints one counterparty per till. Merging exact names
    would be a list that grows every month."""
    before = {t.label for t in rows if t.label.lower().startswith("coop")}
    assert len(before) > 3, "the fixture must contain several Coop branches"

    assert store.alias_pattern("^Coop", "Coop")
    store.apply(rows)

    after = {t.label for t in rows if t.label.lower().startswith("coop")}
    assert after == {"Coop"}


def test_a_pattern_catches_a_branch_seen_for_the_first_time(store, rows):
    store.alias_pattern("^Coop", "Coop")
    store.apply(rows)

    newcomer = copy.deepcopy(rows[0])
    newcomer.merchant = "Coop-9999 Une Nouvelle Succursale"
    newcomer.kind = "Paiement par carte - se terminant par 4802"
    newcomer.label_override = ""
    store.apply([newcomer])
    assert newcomer.label == "Coop"


def test_an_exact_merge_beats_a_pattern(store, rows):
    """The exact name is the more specific statement, so it wins."""
    branch = next(t.label for t in rows if t.label.lower().startswith("coop"))
    store.alias_pattern("^Coop", "Coop")
    store.alias(branch, "Coop Exception")
    store.apply(rows)

    assert any(t.label == "Coop Exception" for t in rows)


def test_a_rule_on_the_brand_covers_every_branch(store, rows):
    store.alias_pattern("^Coop", "Coop")
    store.rule("Coop", category="Shopping")
    store.apply(rows)

    merged = [t for t in rows if t.label == "Coop"]
    assert merged
    assert all(t.category == "Shopping" for t in merged)


def test_an_invalid_pattern_is_refused(store):
    assert not store.alias_pattern("^(unclosed", "X")
    assert not store.alias_patterns


def test_pattern_merges_survive_a_round_trip(store, rows):
    store.alias_pattern("^Coop", "Coop")
    store.save()

    reloaded = Overrides.load(store.path)
    assert reloaded.canonical("Coop-2359 Schwamending") == "Coop"


def test_removing_a_pattern_restores_the_branches(store, rows):
    store.alias_pattern("^Coop", "Coop")
    assert store.unalias("^Coop")
    store.apply(rows)
    assert len({t.label for t in rows if t.label.lower().startswith("coop")}) > 1


def test_merging_does_not_move_a_branch_out_of_its_category(store, rows):
    """Categories are decided before the merge, so a Coop petrol station stays
    in transport even though it now displays as "Coop"."""
    petrol = [t.category for t in rows
              if t.label.lower().startswith("coop") and t.category == "Transport"]
    store.alias_pattern("^Coop", "Coop")
    store.apply(rows)
    still = [t.category for t in rows
             if t.label == "Coop" and t.category == "Transport"]
    assert len(still) == len(petrol)


def test_a_pin_under_a_renamed_category_lands_in_the_new_one(tmp_path):
    import datetime as dt

    from pms.models import Transaction
    from pms.overrides import Overrides, key_of
    t = Transaction(date=dt.date(2025, 1, 1), reference="R9", currency="CHF", amount=-50.0,
                    value_date=None, balance=None, kind="Ordre de paiement", merchant="Guichet")
    store = Overrides(tmp_path / "o.json")
    store.pins[key_of(t)] = {"category": "Impôts & administration", "subcategory": "Services publics"}
    store.apply([t])
    assert (t.category, t.subcategory) == ("Administration", "Documents & autorités")
