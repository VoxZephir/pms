"""Manual corrections: the ones in place, the personal rules, the merges, and
the Twint triage -- the same functions as the `/reclasser` pages."""

from __future__ import annotations

import re

from flask import request
from werkzeug.datastructures import MultiDict

from ... import analysis, tidy, twint
from ... import categories as categories_module
from ... import overrides as overrides_module
from . import encode
from ..views.corrections import (
    TRIAGE_KEYS, _edit_local_rules, _target_choices, triage_apply, triage_state,
)
from . import api, payload, store


def _form() -> MultiDict:
    """The JSON body as the form the shared helpers read; lists stay lists."""
    body = request.get_json(silent=True) or {}
    form = MultiDict()
    for key, value in body.items():
        for item in (value if isinstance(value, list) else [value]):
            if item is not None:
                form.add(key, str(item))
    return form


@api.route("/api/corrections")
def corrections():
    data = store()
    statement = data.statement
    return payload({
        "entries": data.overrides.describe(statement.transactions),
        "total": len(data.overrides),
        "touched": getattr(data, "override_count", 0),
        "twint_left": sum(1 for t in statement.transactions
                          if t.category == categories_module.TWINT_UNKNOWN),
        "local_rules": [e for e in categories_module.load_local_rules_raw(data.local_rules_path)
                        if isinstance(e, dict) and e.get("pattern")],
        "choices": _target_choices(statement),
        "counterparties": sorted({t.label for t in statement.transactions if t.label},
                                 key=str.casefold),
        "coverage": tidy.coverage(statement),
        "merges": tidy.merge_suggestions(statement.transactions, data.overrides),
        "counts": {"rules": len(data.overrides.rules), "pins": len(data.overrides.pins),
                   "merges": len(data.overrides.aliases) + len(data.overrides.alias_patterns)},
    })


@api.route("/api/corrections", methods=["POST"])
def corrections_edit():
    """`delete` (a pin, a rule or a merge), `edit` (a rule or a pin given
    another category), `lr-add` / `lr-delete` (the personal rules), `merge`
    (two spellings, or a whole chain by prefix). A delete or an edit answers
    with its `undo`: the body that puts it back (`restore`, `realias`)."""
    data = store()
    form = _form()
    action = form.get("action") or ""
    if action in ("lr-add", "lr-delete"):
        errors, _values = _edit_local_rules(data, action, form)
        if errors:
            return payload({"errors": errors}), 400
        data.invalidate()
        return payload({"ok": True})
    undo: dict | None = None
    if action == "delete":
        kind = form.get("kind")
        match = form.get("match") or ""
        mode = form.get("mode") or overrides_module.EXACT
        if kind == "alias":
            # Put back as it was: an exact merge, or a whole chain's pattern.
            pattern = next((p for p in data.overrides.alias_patterns if p["pattern"] == match), None)
            undo = ({"action": "realias", "pattern": match, "canonical": pattern["canonical"]} if pattern
                    else {"action": "realias", "variant": match,
                          "canonical": data.overrides.aliases.get(match, "")})
            data.overrides.unalias(match)
        elif kind == "rule":
            undo = {"action": "restore", "restore": data.overrides.snapshot((), [match], mode)}
            data.overrides.unrule(match, mode)
        else:
            key = form.get("key") or ""
            undo = {"action": "restore", "restore": data.overrides.snapshot([key])}
            data.overrides.unpin(key)
    elif action == "edit":
        # A rule or a pin given another category or bucket, in place: what a
        # delete-and-redo did in two steps, losing the reach in between.
        kind = form.get("kind")
        fields = {"category": form.get("category") or "", "subcategory": form.get("subcategory") or "",
                  "bucket": form.get("bucket") or ""}
        if not fields["category"] and not fields["bucket"]:
            return payload({"errors": {"edit": "Une catégorie ou un bloc est requis."}}), 400
        if kind == "rule":
            match = form.get("match") or ""
            mode = form.get("mode") or overrides_module.EXACT
            if not any(r["match"] == match and r.get("mode", overrides_module.EXACT) == mode
                       for r in data.overrides.rules):
                return payload({"error": "règle introuvable"}), 404
            undo = {"action": "restore", "restore": data.overrides.snapshot((), [match], mode)}
            data.overrides.rule(match, mode=mode, **fields)
        elif kind == "pin":
            key = form.get("key") or ""
            if key not in data.overrides.pins:
                return payload({"error": "épingle introuvable"}), 404
            undo = {"action": "restore", "restore": data.overrides.snapshot([key])}
            data.overrides.pin(key, label=data.overrides.pins[key].get("label", ""), **fields)
        else:
            return payload({"error": "seules une règle ou une épingle se modifient"}), 400
    elif action == "restore":
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("restore"), dict):
            return payload({"error": "rien à rétablir"}), 400
        data.overrides.restore(body["restore"])
    elif action == "realias":
        canonical = (form.get("canonical") or "").strip()
        if form.get("pattern"):
            data.overrides.alias_pattern(form.get("pattern") or "", canonical)
        elif form.get("variant"):
            data.overrides.alias(form.get("variant") or "", canonical)
    elif action == "merge":
        canonical = (form.get("canonical") or "").strip()
        variant = (form.get("variant") or "").strip()
        prefix = (form.get("prefix") or "").strip()
        if canonical and prefix:
            # Anchored, so "Coop" does not swallow a merchant that merely
            # mentions it.
            pattern = "^" + re.escape(prefix)
            data.overrides.alias_pattern(pattern, canonical)
            undo = {"action": "delete", "kind": "alias", "match": pattern}
        elif canonical and variant:
            data.overrides.alias(variant, canonical)
            undo = {"action": "delete", "kind": "alias", "match": variant}
        else:
            return payload({"errors": {"merge": "Les deux noms sont requis."}}), 400
    else:
        return payload({"error": f"action inconnue : {action}"}), 400
    data.overrides.save()
    data.invalidate()
    return payload({"ok": True, "undo": undo})


@api.route("/api/advances")
def advances():
    """What others still owe, and the movements behind it, newest first."""
    data = store()
    rows = [t for t in data.statement.transactions
            if t.category == categories_module.ADVANCE]
    rows.sort(key=lambda t: (t.date, t.seq), reverse=True)
    return payload({
        **data.overrides.advance_balance(rows),
        "rows": rows[:60],
    })


@api.route("/api/advance", methods=["POST"])
def advance():
    """Mark the part of one movement paid for someone else -- or, on a
    credit, repaid by them. `amount` 0 removes the mark. The key may be the
    split-off row's: the mark lives on the row the bank printed."""
    data = store()
    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "").strip()
    try:
        amount = round(abs(float(body.get("amount") or 0)), 2)
    except (TypeError, ValueError):
        return payload({"error": "montant illisible"}), 400
    rows = data.statement.transactions
    txn = next((t for t in rows if overrides_module.key_of(t) == key), None)
    if txn is not None and txn.advance_of:
        key = txn.advance_of
        txn = next((t for t in rows if overrides_module.key_of(t) == key), None)
    if txn is None:
        return payload({"error": f"mouvement introuvable : {key}"}), 404
    if analysis.is_fx_leg(txn) or txn.category == categories_module.INTERNAL:
        return payload({"error": "un virement entre tes comptes n'est pas une avance"}), 409
    gross = abs(encode.printed(txn))
    if amount > gross + 0.005:
        return payload({"error": f"au plus {gross:.2f} {txn.currency} : le montant de la ligne"}), 400
    before = data.overrides.snapshot([key])
    data.overrides.advance(key, amount, label=txn.label)
    data.overrides.save()
    data.invalidate()
    return payload({"ok": True, "key": key, "amount": amount, "gross": gross,
                    "currency": txn.currency,
                    "undo": {"scope": "pin", "key": key, "restore": before}})


@api.route("/api/note", methods=["POST"])
def note():
    """Set the note of one movement (`text` empty removes it). The key may be
    the split-off half of an advance: the note lives on the printed row.
    Answers the previous note, which the toast's "Annuler" sends back."""
    data = store()
    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "").strip()
    rows = data.statement.transactions
    txn = next((t for t in rows if overrides_module.key_of(t) == key), None)
    if txn is not None and txn.advance_of:
        key = txn.advance_of
        txn = next((t for t in rows if overrides_module.key_of(t) == key), None)
    if txn is None:
        return payload({"error": f"mouvement introuvable : {key}"}), 404
    previous = (data.overrides.notes.get(key) or {}).get("text", "")
    text = data.overrides.annotate(key, str(body.get("text") or ""))
    data.overrides.save()
    data.invalidate()
    return payload({"ok": True, "key": key, "text": text,
                    "undo": {"key": key, "text": previous}})


@api.route("/api/triage")
def triage():
    data = store()
    try:
        at = max(int(request.args.get("at") or 0), 0)
    except ValueError:
        at = 0
    state = triage_state(data, at, request.args.get("last") or "")
    current = state.get("current")
    state["weekday"] = (["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
                         "dimanche"][current.date.weekday()] if current else None)
    state["keys"] = TRIAGE_KEYS
    suggester = _suggester(data)
    state["suggestions"], state["measured"] = (suggester.suggest(current) if current
                                               else ([], None))
    state["trip"] = twint.trip_hint(current, suggester.ctx) if current else None
    if state["trip"] and state["trip"]["category"] not in state["targets"]:
        state["trip"] = None
    state["bands"] = suggester.band_groups(
        [t for t in data.statement.transactions if t.category == categories_module.TWINT_UNKNOWN])
    return payload(state)


def _suggester(data) -> twint.Suggester:
    """Trained on the owner's sorted Twints, once per load of the ledger:
    a pin reloads it, so the next card already learns from the last one."""
    statement = data.statement
    cached = getattr(data, "_twint_suggester", None)
    if cached is None or cached[0] is not statement:
        cached = (statement, twint.Suggester(statement))
        data._twint_suggester = cached
    return cached[1]


@api.route("/api/triage", methods=["POST"])
def triage_edit():
    data = store()
    body = request.get_json(silent=True) or {}
    if body.get("action") == "restore" and isinstance(body.get("restore"), dict):
        # "Annuler" after a whole amount or band: the pins as they were.
        data.overrides.restore(body["restore"])
        data.overrides.save()
        data.invalidate()
        return payload({"ok": True})
    last, before = triage_apply(data, _form())
    return payload({"ok": True, "last": last, "restore": before})
