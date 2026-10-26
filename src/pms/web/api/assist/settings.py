"""The Assistant page: which model, whether each key is in its file (never
the key), a test, the journal, and what the assistant costs and is worth."""

from __future__ import annotations

import datetime as dt
from collections import Counter


from .... import ai
from .... import categories as categories_module
from .. import api, payload, store
from . import _body, _config, _failed, _folder


# --- the settings page -----------------------------------------------------------

def _settings() -> dict:
    folder = _folder()
    try:
        raw = ai._read_config(folder)
    except ai.AIError:
        raw = {}
    chosen = raw.get("provider") if raw.get("provider") in ai.PROVIDERS else None
    installed = ai.local_models()
    providers = []
    for pid, spec in ai.PROVIDERS.items():
        key = ai.key_file(folder, pid)
        models = list(ai.MODELS[pid])
        if pid == "ollama" and installed is not None:
            known = {m["id"] for m in models}
            models = [m for m in models if m["id"] in installed] + \
                     [{"id": n, "label": n, "note": "installé"} for n in installed if n not in known]
        providers.append({
            "id": pid, "label": spec["label"], "privacy": spec["privacy"],
            "where": spec["where"], "default": spec["model"], "models": models,
            "needs_key": spec["key"],
            # Whether a key is there, and where it goes -- never the key.
            "has_key": key.exists() and bool(key.read_text(encoding="utf-8").strip()),
            "key_file": f"data/{key.name}" if key.exists() else f"data/ai.{pid}.key",
            "running": installed is not None if pid == "ollama" else None,
        })
    return {"status": ai.status(folder), "provider": chosen,
            "model": raw.get("model") or "", "enabled": raw.get("enabled", True) and bool(chosen),
            "providers": providers, "journal": ai.journal(folder),
            "spending": ai.spending(folder), "prices_as_of": ai.PRICES_AS_OF,
            "merchants": _merchant_outcomes(store())}


def _merchant_outcomes(data) -> dict:
    """What became of the categories proposed for payees, read from the
    ledger rather than from clicks: a payee is "kept" when its lines now sit
    in the category proposed, "changed" when the owner chose another, still
    "open" while they wait. The Twint sorter shows its own measured rate;
    this is the same honesty for the merchants."""
    out = {"kept": 0, "changed": 0, "open": 0, "none": 0, "examples": []}
    if data.empty:
        return out
    by_label: dict[str, list] = {}
    for t in data.statement.transactions:
        if t.label:
            by_label.setdefault(t.label, []).append(t)
    for label, memo in ai.memos(_folder(), "merchant:").items():
        rows = by_label.get(label)
        if not rows or not isinstance(memo, dict):
            continue
        proposed = memo.get("category")
        if not proposed:
            out["none"] += 1
            continue
        now = Counter(t.category for t in rows).most_common(1)[0][0]
        if now == categories_module.UNCATEGORISED:
            out["open"] += 1
        elif now == proposed:
            out["kept"] += 1
        else:
            out["changed"] += 1
            if len(out["examples"]) < 3:
                out["examples"].append({"label": label, "proposed": proposed, "chosen": now})
    return out


@api.route("/api/ai/settings")
def ai_settings():
    return payload(_settings())


@api.route("/api/ai/settings", methods=["POST"])
def ai_settings_save():
    """`{"provider": id, "model": name}`, or `{"provider": null}` to switch
    the assistant off. Only the choice is written: keys stay files."""
    body = _body()
    provider = body.get("provider") or None
    try:
        ai.save_config(_folder(), provider, str(body.get("model") or ""))
    except ai.AIError as e:
        return payload({"errors": {"model" if provider in ai.PROVIDERS else "provider": str(e)}}), 400
    return payload(_settings())


TEST_SCHEMA = ai.strict({"type": "object", "properties": {"ok": {"type": "boolean"}}})


@api.route("/api/ai/test", methods=["POST"])
def ai_test():
    """One tiny request, never cached: does the chosen model answer, and in
    the expected shape?"""
    config, refused = _config()
    if refused:
        return refused
    started = dt.datetime.now()
    try:
        ai.ask_json(config, "test", "Réponds par un objet JSON.", 'Réponds {"ok": true}.',
                    TEST_SCHEMA, max_tokens=200, cache=False)
    except ai.AIError as e:
        return _failed(e)
    ms = int((dt.datetime.now() - started).total_seconds() * 1000)
    return payload({"ok": True, "ms": ms, "label": config.label, "model": config.model})
