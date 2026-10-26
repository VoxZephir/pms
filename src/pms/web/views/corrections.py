"""Manual corrections: pins, merchant rules, bulk moves, label merges and
the personal rules file -- the `/reclasser` page and its endpoints.
"""

from __future__ import annotations

import re
from collections import Counter

from flask import abort, jsonify, request

from ... import buckets
from ... import categories as categories_module
from ... import overrides as overrides_module
from .. import periods
from .common import _filtered, bp, store

# --- manual reclassification ------------------------------------------------

def _target_choices(statement) -> dict:
    """What a transaction can be moved to.

    Categories come from the rule engine's own vocabulary plus whatever the
    ledger already contains, so the list never offers a category the rest of the
    app would not recognise.
    """
    known = {cat for cat, _, _ in categories_module.RULES}
    known.update(t.category for t in statement.transactions if t.category)
    subs: dict[str, list[str]] = {}
    for cat, sub, _ in categories_module.RULES:
        subs.setdefault(cat, [])
        if sub and sub not in subs[cat]:
            subs[cat].append(sub)
    return {
        "categories": sorted(known),
        "subcategories": subs,
        "buckets": buckets.ORDER,
    }


@bp.route("/api/reclassify", methods=["POST"])
def reclassify():
    """Apply one correction and report what it changed.

    `scope` is the whole point: "pin" fixes this movement only, "merchant"
    writes a rule that also catches the same counterparty next month.
    """
    data = store()
    payload = request.get_json(silent=True) or request.form
    key = (payload.get("key") or "").strip()
    scope = payload.get("scope") or "pin"
    category = (payload.get("category") or "").strip()
    subcategory = (payload.get("subcategory") or "").strip()
    bucket = (payload.get("bucket") or "").strip()

    if not category and not bucket:
        return jsonify({"error": "rien à appliquer"}), 400
    if bucket and bucket not in buckets.ORDER:
        return jsonify({"error": f"bucket inconnu: {bucket}"}), 400

    statement = data.statement
    txn = next((t for t in statement.transactions
                if overrides_module.key_of(t) == key), None)
    if txn is None:
        return jsonify({"error": f"mouvement introuvable: {key}"}), 404

    store_ = data.overrides
    mode = payload.get("mode") or overrides_module.EXACT
    # Taken before anything moves: "Annuler" puts this back, whatever it was.
    before = store_.snapshot([key], [txn.label] if scope == "merchant" else [], mode)
    if scope == "merchant":
        hits = store_.affected(statement.transactions, txn.label, mode)
        store_.rule(txn.label, mode=mode, category=category,
                    subcategory=subcategory, bucket=bucket)
        # The row being reclassified must move, its own pin notwithstanding.
        store_.yield_to_rule(key, category=category, bucket=bucket)
        summary = {"scope": "merchant", "match": txn.label, "mode": mode,
                   "count": len(hits)}
    else:
        store_.pin(key, category=category, subcategory=subcategory,
                   bucket=bucket, label=txn.label)
        summary = {"scope": "pin", "match": txn.label, "count": 1}

    store_.save()
    data.invalidate()

    return jsonify({
        **summary,
        "category": category or txn.category,
        "subcategory": subcategory,
        "bucket": bucket,
        "undo": {"scope": summary["scope"], "key": key,
                 "match": txn.label, "mode": summary.get("mode", ""),
                 "restore": before},
    })


@bp.route("/api/reclassify/bulk", methods=["POST"])
def reclassify_bulk():
    """Reclassify many movements at once.

    Two ways to say which ones, because they answer different needs:

    * `keys` -- an explicit selection, for a handful of rows you ticked;
    * `scope_all` -- everything matching the filter currently on screen, which
      is the one that matters. "All the unclassified P2P transfers" is 443 rows
      across eight pages; ticking them one page at a time is not a workflow.

    `apply_as` then decides whether the correction is pinned to those exact
    movements or turned into rules on their counterparties, which also catch
    next month's statement.
    """
    data = store()
    payload = request.get_json(silent=True) or request.form

    # The target is namespaced `to_*` because the filter uses `category` and
    # `bucket` too. Sharing the keys made "everything in bucket X" and "move it
    # to bucket Y" the same parameter, so the selection silently came back empty.
    category = (payload.get("to_category") or "").strip()
    subcategory = (payload.get("to_subcategory") or "").strip()
    bucket = (payload.get("to_bucket") or "").strip()
    apply_as = payload.get("apply_as") or "pin"

    if not category and not bucket:
        return jsonify({"error": "rien à appliquer"}), 400
    if bucket and bucket not in buckets.ORDER:
        return jsonify({"error": f"bucket inconnu: {bucket}"}), 400

    low, high = data.bounds
    period = periods.resolve(payload, low, high)
    window = data.window(period["start"], period["end"])

    if payload.get("scope_all"):
        # Reuse the table's own filtering so "everything matching" means exactly
        # what the screen was showing -- one implementation, no drift.
        selection = _filtered(window, payload)
    else:
        keys = payload.getlist("keys") if hasattr(payload, "getlist") \
            else (payload.get("keys") or [])
        wanted = set(keys)
        selection = [t for t in window.transactions
                     if overrides_module.key_of(t) in wanted]

    if not selection:
        return jsonify({"error": "aucun mouvement sélectionné"}), 400

    selected = [overrides_module.key_of(t) for t in selection]
    before = data.overrides.snapshot(
        selected, [t.label for t in selection if t.label] if apply_as == "merchant" else [])
    if apply_as == "merchant":
        labels = data.overrides.rule_many(selection, category=category,
                                          subcategory=subcategory, bucket=bucket)
        # The rows on screen are the ones asked to move: their own pins yield.
        for key in selected:
            data.overrides.yield_to_rule(key, category=category, bucket=bucket)
        undo = {"kind": "rules", "matches": labels, "restore": before}
        rules_made = len(labels)
    else:
        keys = data.overrides.pin_many(selection, category=category,
                                       subcategory=subcategory, bucket=bucket)
        undo = {"kind": "pins", "keys": keys, "restore": before}
        rules_made = 0

    data.overrides.save()
    data.invalidate()

    return jsonify({
        "count": len(selection),
        "rules": rules_made,
        "merchants": len({t.label for t in selection}),
        "category": category,
        "bucket": bucket,
        "apply_as": apply_as,
        "undo": undo,
    })


@bp.route("/api/reclassify/bulk/undo", methods=["POST"])
def reclassify_bulk_undo():
    data = store()
    payload = request.get_json(silent=True) or request.form
    if isinstance(payload.get("restore"), dict):
        removed = data.overrides.restore(payload["restore"])
    elif payload.get("kind") == "rules":
        removed = data.overrides.unrule_many(payload.get("matches") or [])
    else:
        removed = data.overrides.unpin_many(payload.get("keys") or [])
    data.overrides.save()
    data.invalidate()
    return jsonify({"removed": removed})


@bp.route("/api/reclassify/undo", methods=["POST"])
def reclassify_undo():
    data = store()
    payload = request.get_json(silent=True) or request.form
    scope = payload.get("scope") or "pin"

    if isinstance(payload.get("restore"), dict):
        removed = data.overrides.restore(payload["restore"])
    elif scope == "merchant":
        removed = data.overrides.unrule(payload.get("match") or "",
                                        payload.get("mode") or overrides_module.EXACT)
    else:
        removed = data.overrides.unpin(payload.get("key") or "")

    data.overrides.save()
    data.invalidate()
    return jsonify({"removed": bool(removed)})


def _edit_local_rules(data, action, form=None) -> tuple[dict, dict]:
    """One edit to the personal rules; `({}, {})` when it succeeded.

    A failed add returns (errors, values) so the page re-renders with the
    error stated and the typed text kept -- a silent no-op would have the
    user type the same pattern again. These are categorisations, not
    exceptions: a rule written here reclassifies everything it matches,
    past and future, and beats the public rules.
    """
    form = request.form if form is None else form
    rules = categories_module.load_local_rules_raw(data.local_rules_path)

    if action == "lr-delete":
        wanted = tuple((form.get(key) or "").strip()
                       for key in ("pattern", "category", "subcategory"))
        categories_module.save_local_rules(
            [entry for entry in rules
             if not isinstance(entry, dict)
             or tuple((entry.get(key) or "").strip()
                      for key in ("pattern", "category", "subcategory"))
             != wanted],
            data.local_rules_path)
        return {}, {}

    pattern = (form.get("pattern") or "").strip()
    category = (form.get("category") or "").strip()
    subcategory = (form.get("subcategory") or "").strip()

    errors: dict[str, str] = {}
    values = {"lr-pattern": pattern, "lr-category": category,
              "lr-subcategory": subcategory}
    if not pattern:
        errors["lr-pattern"] = "Le motif est requis."
    else:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            errors["lr-pattern"] = f"Motif invalide : {exc}"
        else:
            # A pattern that matches the empty string (`|`, `a*`, `.*`)
            # matches every transaction: one keystroke would silently
            # reclassify the whole ledger into a single category.
            if compiled.search("") is not None:
                errors["lr-pattern"] = ("Le motif ne doit pas matcher une "
                                        "chaîne vide.")
    if not category:
        errors["lr-category"] = "La catégorie est requise."
    elif category not in _target_choices(data.statement)["categories"]:
        errors["lr-category"] = "Catégorie inconnue."
    if errors:
        return errors, values

    rules.append({"category": category, "subcategory": subcategory,
                  "pattern": pattern})
    categories_module.save_local_rules(rules, data.local_rules_path)
    return {}, {}


# --- sorting the unidentified Twints -----------------------------------------

# An amount with at least this many unidentified Twints gets its own row and
# a "classify them all" form: below it, one at a time is as fast.
TRIAGE_GROUP_MIN = 3
# The keys 1-9 pick a category; the rest of the list stays clickable.
TRIAGE_KEYS = 9


def _twint_queue(statement) -> list:
    """The Twints still unidentified, most recent first -- the ones the owner
    is most likely to remember."""
    return sorted((t for t in statement.transactions
                   if t.category == categories_module.TWINT_UNKNOWN),
                  key=lambda t: (t.date, t.seq), reverse=True)


def _twint_history(statement) -> dict:
    """What the owner already decided for Twints, by exact amount.

    The only evidence the statement offers is the amount: "Paiement Twint"
    and nothing else. Past decisions at the same amount are therefore the
    one honest hint -- the owner's own, never a guess -- and the triage
    shows them rather than preselecting anything silently.
    """
    by_amount: dict[float, Counter] = {}
    overall: Counter = Counter()
    for t in statement.transactions:
        if t.kind in categories_module.PEER_KINDS and t.amount < 0 \
                and t.overridden and t.category != categories_module.TWINT_UNKNOWN:
            by_amount.setdefault(round(-t.amount, 2), Counter())[t.category] += 1
            overall[t.category] += 1
    return {"by_amount": by_amount, "overall": overall}


def _triage_targets(statement, overall: Counter) -> list[str]:
    """Where a Twint can go: the categories the owner used most for Twints
    first, so the keys 1-9 land on the usual ones; the rest alphabetically.
    Income and the unidentified bucket itself are not destinations."""
    spending = [c for c in _target_choices(statement)["categories"]
                if c not in (categories_module.TWINT_UNKNOWN, "Revenus",
                             categories_module.UNCATEGORISED)]
    used = [c for c, _ in overall.most_common() if c in spending]
    return used + sorted((c for c in spending if c not in used), key=str.casefold)


def _pin_category(overrides, txn, category: str) -> None:
    """Set the category of a Twint, keeping the bucket already decided.

    `pin()` replaces the whole entry, and 153 of the real Twints already carry
    a Need/Want pin with no category -- a decision made in the table before
    there was anything to name. Pinning a category over it would silently
    re-derive the bucket from the category and undo that decision. An empty
    category restores the bucket-only pin (the triage's undo).
    """
    key = overrides_module.key_of(txn)
    bucket = (overrides.pins.get(key) or {}).get("bucket", "")
    if category or bucket:
        overrides.pin(key, category=category, bucket=bucket, label=txn.label)
    else:
        overrides.unpin(key)


def triage_apply(data, form) -> tuple[str, dict]:
    """Pin one Twint (`pin`), every Twint of one amount (`group`) or of one
    amount band (`band`), or undo the last pin; returns the key to offer the
    undo for, and the pins as they were (what "Annuler" puts back after a
    group). Aborts 404 on an unknown key, 409 on a row that is not an
    unidentified Twint, 400 on a category that is not a destination."""
    statement = data.statement
    by_key = {overrides_module.key_of(t): t for t in statement.transactions}
    action = form.get("action") or "pin"
    keys = (form.getlist("keys") if action in ("group", "band")
            else [(form.get("key") or "").strip()])
    rows = [by_key.get(key) for key in keys]
    if not rows or None in rows:
        abort(404)
    # Only what the triage is for: a Twint with no category yet (undo
    # aside, which puts one back).
    if action != "undo" and any(
            t.category != categories_module.TWINT_UNKNOWN for t in rows):
        abort(409)
    category = "" if action == "undo" else \
        (form.get("category") or "").strip()
    if action != "undo" and category not in _triage_targets(statement, Counter()):
        abort(400)
    before = data.overrides.snapshot(keys)
    for txn in rows:
        _pin_category(data.overrides, txn, category)
    data.overrides.save()
    data.invalidate()
    return (keys[0] if action == "pin" else ""), before


def triage_state(data, at: int, last_key: str) -> dict:
    """The queue at position `at`: the Twint on screen, what can jog the
    memory, the recurring amounts, and the last pin to undo."""
    statement = data.statement
    queue = _twint_queue(statement)
    history = _twint_history(statement)
    at = min(at, max(len(queue) - 1, 0))
    current = queue[at] if queue else None

    same_day, hint = [], []
    if current is not None:
        same_day = [t for t in statement.transactions
                    if t.date == current.date and t is not current]
        hint = history["by_amount"].get(round(-current.amount, 2),
                                        Counter()).most_common(3)

    counts = Counter(round(-t.amount, 2) for t in queue)
    groups = []
    for amount, count in counts.most_common():
        if count < TRIAGE_GROUP_MIN:
            break
        rows = [t for t in queue if round(-t.amount, 2) == amount]
        past = history["by_amount"].get(amount, Counter())
        groups.append({
            "amount": amount, "count": count,
            "first": rows[-1].date, "last": rows[0].date,
            "keys": [overrides_module.key_of(t) for t in rows],
            "past": past.most_common(3),
            "suggested": past.most_common(1)[0][0] if past else "",
        })

    last = next((t for t in statement.transactions
                 if overrides_module.key_of(t) == last_key), None)
    return dict(
        queue_size=len(queue),
        done=sum(1 for t in statement.transactions
                 if t.kind in categories_module.PEER_KINDS and t.amount < 0
                 and t.category != categories_module.TWINT_UNKNOWN),
        at=at,
        current=current,
        current_key=overrides_module.key_of(current) if current else "",
        same_day=same_day,
        hint=hint,
        targets=_triage_targets(statement, history["overall"]),
        keys=TRIAGE_KEYS,
        groups=groups,
        last=last,
        last_key=last_key,
    )

