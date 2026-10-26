"""The leash on the model (`pms.ai`): configuration, the answer's shape, the
numbers it may cite, what is masked before anything leaves, the journal and
the cache. No network: the provider call is replaced."""

from __future__ import annotations

import json

import pytest

from pms import ai
from pms.models import Transaction


def _config(folder, provider="deepseek", key="sk-test-123"):
    (folder / ai.CONFIG_NAME).write_text(json.dumps({"provider": provider}), encoding="utf-8")
    if key:
        (folder / ai.KEY_NAME).write_text(key + "\n", encoding="utf-8")
    return ai.load(folder)


def test_no_file_means_no_model(tmp_path):
    assert ai.load(tmp_path) is None
    status = ai.status(tmp_path)
    assert status["enabled"] is False and "Assistant" in status["reason"]


def test_a_missing_key_is_named_without_any_key(tmp_path):
    (tmp_path / ai.CONFIG_NAME).write_text('{"provider": "anthropic"}', encoding="utf-8")
    with pytest.raises(ai.AIError, match="ai.anthropic.key"):
        ai.load(tmp_path)


def test_the_key_never_reaches_the_status(tmp_path):
    _config(tmp_path, key="sk-very-secret")
    status = ai.status(tmp_path)
    assert status["enabled"] and status["provider"] == "deepseek"
    assert "sk-very-secret" not in json.dumps(status)


def test_a_local_model_needs_no_key(tmp_path):
    config = _config(tmp_path, provider="ollama", key="")
    assert config.local and config.base_url.startswith("http://127.0.0.1")


def test_an_unknown_provider_is_refused(tmp_path):
    (tmp_path / ai.CONFIG_NAME).write_text('{"provider": "oracle"}', encoding="utf-8")
    with pytest.raises(ai.AIError, match="inconnu"):
        ai.load(tmp_path)


def test_disabled_reads_as_off(tmp_path):
    (tmp_path / ai.CONFIG_NAME).write_text('{"provider": "deepseek", "enabled": false}',
                                           encoding="utf-8")
    assert ai.load(tmp_path) is None


SCHEMA = ai.strict({"type": "object", "properties": {
    "text": {"type": "string"},
    "lines": {"type": "array", "items": {"type": "integer"}, "maxItems": 2},
    "kind": {"type": "string", "enum": ["a", "b"]},
    "maybe": {"type": ["string", "null"]},
}})


def test_strict_closes_every_object():
    assert SCHEMA["additionalProperties"] is False
    assert set(SCHEMA["required"]) == {"text", "lines", "kind", "maybe"}


@pytest.mark.parametrize("value, ok", [
    ({"text": "x", "lines": [1], "kind": "a", "maybe": None}, True),
    ({"text": "x", "lines": [1], "kind": "c", "maybe": None}, False),
    ({"text": "x", "lines": [1, 2, 3], "kind": "a", "maybe": None}, False),
    ({"text": "x", "lines": ["1"], "kind": "a", "maybe": None}, False),
    ({"text": "x", "lines": [], "kind": "a"}, False),
    ({"text": 3, "lines": [], "kind": "a", "maybe": "y"}, False),
    ({"text": "x", "lines": [True], "kind": "a", "maybe": None}, False),
])
def test_validate(value, ok):
    assert (ai.validate(value, SCHEMA) == []) is ok


def test_swiss_numbers_are_read():
    assert ai.numbers_in("2'418.60 CHF en 57 passages, +690, 12,5 %") == [2418.6, 57, 690, 12.5]


def test_a_number_from_the_facts_passes_rounded():
    facts = {"total": 2418.6, "ecart": -690.4, "pct": 12.46}
    assert ai.checked_text("2'419 CHF, 690 de moins, 12 %, le 4 juillet 2025", facts)


def test_an_invented_number_is_refused():
    with pytest.raises(ai.AIError, match="chiffre"):
        ai.checked_text("Tu as dépensé 3'200 CHF.", {"total": 2418.6})


def _txn(kind, label):
    import datetime as dt
    return Transaction(date=dt.date(2026, 1, 1), reference="1", currency="CHF", amount=-1.0,
                       value_date=None, balance=None, kind=kind, merchant=label)


def test_a_transfer_is_masked_a_shop_is_not():
    r = ai.Redactor()
    shop = _txn("Paiement par carte - se terminant par 1234", "Coop")
    shop.label_override = "Coop"
    person = _txn("Ordre de paiement", "Jeanne Exemple")
    person.label_override = "Jeanne Exemple"
    assert r.label(shop) == "Coop"
    token = r.label(person)
    assert token == "[P1]" and r.label(person) == token
    assert r.restore(f"Payé à {token}.") == "Payé à Jeanne Exemple."


def test_ask_json_logs_caches_and_validates(tmp_path, monkeypatch):
    config = _config(tmp_path)
    calls = []

    def fake(config, system, user, schema, max_tokens):
        calls.append(user)
        return '```json\n{"text": "ok", "lines": [], "kind": "a", "maybe": null}\n```'

    monkeypatch.setattr(ai, "_call", fake)
    first = ai.ask_json(config, "t", "sys", "question", SCHEMA)
    second = ai.ask_json(config, "t", "sys", "question", SCHEMA)
    assert first == second and len(calls) == 1
    log = [json.loads(line) for line in (tmp_path / ai.LOG_NAME).read_text(encoding="utf-8").splitlines()]
    assert log[0]["sent"] == "question" and "sk-test" not in json.dumps(log)

    monkeypatch.setattr(ai, "_call", lambda *a: '{"text": 1}')
    with pytest.raises(ai.AIError, match="hors format"):
        ai.ask_json(config, "t", "sys", "autre", SCHEMA)


def test_memo_round_trip(tmp_path):
    assert ai.memo_get(tmp_path, "x") is None
    ai.memo_put(tmp_path, "x", {"a": 1})
    assert ai.memo_get(tmp_path, "x") == {"a": 1}


def test_each_provider_has_its_own_key_file(tmp_path):
    (tmp_path / ai.CONFIG_NAME).write_text('{"provider": "anthropic"}', encoding="utf-8")
    (tmp_path / "ai.anthropic.key").write_text("sk-ant", encoding="utf-8")
    (tmp_path / "ai.deepseek.key").write_text("sk-ds", encoding="utf-8")
    assert ai.load(tmp_path).key == "sk-ant"
    ai.save_config(tmp_path, "deepseek", "")
    config = ai.load(tmp_path)
    assert (config.key, config.model) == ("sk-ds", "deepseek-flash")


def test_the_old_single_key_file_still_serves(tmp_path):
    config = _config(tmp_path, provider="anthropic", key="sk-old")
    assert config.key == "sk-old"


def test_claude_searches_the_web_then_ends_on_the_json(tmp_path, monkeypatch):
    """With Claude, a merchant name can be looked up; the answer's shape is
    then asked in words, a paused search is resumed, and the JSON is the
    last thing written."""
    import sys
    from types import SimpleNamespace

    calls = []

    def block(text):
        return SimpleNamespace(type="text", text=text)

    replies = iter([
        SimpleNamespace(stop_reason="pause_turn", content=[block("Je cherche…")]),
        SimpleNamespace(stop_reason="end_turn",
                        content=[block("C'est un camping."), block('Voici : {"ok": true}')]),
    ])

    class Messages:
        def create(self, **request):
            calls.append(request)
            return next(replies)

    fake = SimpleNamespace(Anthropic=lambda **_: SimpleNamespace(messages=Messages(), beta=None),
                           AuthenticationError=type("A", (Exception,), {}),
                           RateLimitError=type("R", (Exception,), {}),
                           APIStatusError=type("S", (Exception,), {}),
                           APIConnectionError=type("C", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    (tmp_path / ai.CONFIG_NAME).write_text('{"provider": "anthropic", "model": "claude-haiku-5-5"}',
                                           encoding="utf-8")
    (tmp_path / "ai.anthropic.key").write_text("sk", encoding="utf-8")
    config = ai.load(tmp_path)
    schema = ai.strict({"type": "object", "properties": {"ok": {"type": "boolean"}}})
    assert ai.ask_json(config, "merchants", "sys", "Guillermo Camp", schema, web=True) == {"ok": True}
    assert calls[0]["tools"][0]["type"] == "web_search_20260209"
    assert "format" not in calls[0]["output_config"]
    assert len(calls) == 2 and calls[1]["messages"][-1]["role"] == "assistant"


def test_only_claude_searches(tmp_path):
    assert ai.can_search(_config(tmp_path, provider="anthropic"))
    assert not ai.can_search(_config(tmp_path, provider="deepseek"))


@pytest.mark.parametrize("body", [
    {"results": [{"title": "Guillermo Camp", "url": "https://x.example", "snippet": "Camping à Gruyères"}]},
    {"data": [{"name": "Guillermo Camp", "link": "https://x.example", "content": "Camping à Gruyères"}]},
    [{"title": "Guillermo Camp", "url": "https://x.example", "summary": "Camping à Gruyères"}],
])
def test_deepseek_search_is_read_leniently(tmp_path, monkeypatch, body):
    import io
    config = _config(tmp_path, provider="deepseek")
    sent = []

    def fake_urlopen(request, timeout):
        sent.append((request.full_url, json.loads(request.data), request.headers))
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(ai.urllib.request, "urlopen", fake_urlopen)
    found = ai.search_snippets(config, "Guillermo Camp Bulle")
    assert found == [{"titre": "Guillermo Camp", "url": "https://x.example", "extrait": "Camping à Gruyères"}]
    url, payload, headers = sent[0]
    assert url.endswith("/v1/tools/search") and payload["query"] == "Guillermo Camp Bulle"
    assert headers["Authorization"] == "Bearer sk-test-123"


def test_a_failed_or_unknown_search_is_no_result(tmp_path, monkeypatch):
    import io
    config = _config(tmp_path, provider="deepseek")
    monkeypatch.setattr(ai.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b'{"unexpected": 1}'))
    assert ai.search_snippets(config, "x") == []

    def boom(*a, **k):
        raise ai.urllib.error.URLError("down")

    monkeypatch.setattr(ai.urllib.request, "urlopen", boom)
    assert ai.search_snippets(config, "x") == []
    assert ai.search_snippets(_config(tmp_path, provider="anthropic"), "x") == []
    # The journal says what came of each search, never with the key.
    outcomes = [e["outcome"] for e in ai.journal(tmp_path) if e["task"] == "search"]
    assert outcomes == ["injoignable", "aucun résultat lisible (clés : unexpected)"]
    assert "sk-test" not in (tmp_path / ai.LOG_NAME).read_text(encoding="utf-8")


def test_each_request_is_logged_with_its_tokens_and_priced(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake(config, system, user, schema, max_tokens):
        ai._note_usage(1_000_000, 0, 500_000)
        return '{"ok": true}'

    monkeypatch.setattr(ai, "_call", fake)
    schema = ai.strict({"type": "object", "properties": {"ok": {"type": "boolean"}}})
    ai.ask_json(config, "test", "sys", "u", schema, cache=False)
    (row,) = ai.journal(tmp_path)
    assert row["tokens"] == 1_500_000
    # deepseek-flash at its peak price: 0.30 $ sent, 1.20 $ received per million.
    assert row["usd"] == pytest.approx(0.30 + 0.60)
    (month, before) = ai.spending(tmp_path)
    assert month["requests"] == 1 and month["usd"] == pytest.approx(0.90)
    assert month["ceiling"] is True and before["requests"] == 0


def test_a_failed_request_is_logged_too_and_an_unknown_model_is_not_priced(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def boom(*a):
        raise ai.AIError("down")

    monkeypatch.setattr(ai, "_call", boom)
    with pytest.raises(ai.AIError):
        ai.ask_json(config, "test", "s", "u", {"type": "object"}, cache=False)
    assert ai.journal(tmp_path)[0]["outcome"] == "échec"
    assert ai.cost("deepseek", "some-new-model", {"sent": 10, "received": 10}) is None
    assert ai.cost("ollama", "qwen2.5:7b", {"sent": 10, "received": 10}) == 0.0
    # Tokens read from the provider's cache are billed at the cache price.
    assert ai.cost("anthropic", "claude-opus-5-5", {"sent": 1_000_000, "cached": 1_000_000,
                                                    "received": 0}) == pytest.approx(0.20)
