"""A language model, kept on a short leash.

The app's rule holds here too: Flask computes, the model only reads what was
computed and puts it in words, or turns a sentence into a request the app
then runs itself. It never adds up a number, never writes anything without
a click, and every number it prints is checked against the figures it was
given (`unsupported_numbers`) -- a sentence that cites a number the app did
not hand over is dropped, not shown.

What leaves the machine is the user's choice and is kept to what each task
needs:

- `data/ai.json` names the provider and the model, chosen in the app's
  Assistant page (`save_config`); `data/ai.<provider>.key` holds each key,
  set by the user in the file, never printed, never put in an error message,
  never sent to the browser;
- labels of anything but a card payment (a transfer names a person or a
  company) are replaced by `[P1]`, `[P2]`... before they are sent, and put
  back in the answer (`Redactor`);
- every request is written to `data/ai_log.jsonl`, exactly as sent, so the
  user can read what went out;
- an answer is cached (`data/ai_cache.json`) under the exact request: asking
  again costs nothing and returns the same words.

Three providers, one interface (`ask_json`): Claude through the Anthropic
SDK, and anything that speaks the OpenAI chat format over plain HTTP --
DeepSeek, or a local Ollama, for which nothing leaves the PC.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "ai.json"
KEY_NAME = "ai.key"
LOG_NAME = "ai_log.jsonl"
CACHE_NAME = "ai_cache.json"
# Old answers fall out first; a few hundred is months of use.
CACHE_LIMIT = 500
TIMEOUT = 90  # seconds: a local model on a laptop CPU is slow

PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic)", "model": "claude-opus-5-5",
                  "key": True, "where": "console.anthropic.com",
                  "privacy": "Serveurs d'Anthropic (États-Unis). L'API n'entraîne pas "
                             "ses modèles sur ce qui lui est envoyé."},
    "deepseek": {"label": "DeepSeek", "model": "deepseek-flash",
                 "base_url": "https://api.deepseek.com", "key": True,
                 "where": "platform.deepseek.com",
                 "privacy": "Selon sa politique de confidentialité, DeepSeek stocke les "
                            "données en Chine, sous le droit chinois."},
    "ollama": {"label": "Ollama (sur ce PC)", "model": "qwen2.5:7b",
               "base_url": "http://127.0.0.1:11434/v1", "key": False,
               "where": "ollama.com",
               "privacy": "Rien ne sort du PC. Plus lent, et moins fiable sur les "
                          "questions et les scénarios."},
}
# What the settings page offers. Any other model name can still be typed:
# providers publish new ones faster than this list changes.
MODELS = {
    "anthropic": [
        {"id": "claude-opus-5-5", "label": "Claude Opus 5.5",
         "note": "le plus capable · 4 $ / 20 $ par million de jetons (envoyés / reçus)"},
        {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5",
         "note": "rapide et solide · 2 $ / 10 $ par million de jetons"},
        {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5",
         "note": "le plus économique · 0.10 $ / 0.50 $ par million de jetons"},
    ],
    "deepseek": [
        {"id": "deepseek-flash", "label": "DeepSeek Flash",
         "note": "V4.1, recommandé pour ces tâches courtes · 0.30 $ / 1.20 $ par million de "
                 "jetons au plus (moitié en heures creuses) ; deepseek-chat y mène aussi"},
    ],
    "ollama": [
        {"id": "qwen2.5:7b", "label": "Qwen 2.5 7B", "note": "suit bien le format JSON"},
        {"id": "llama3.1:8b", "label": "Llama 3.1 8B", "note": ""},
        {"id": "mistral:7b", "label": "Mistral 7B", "note": ""},
    ],
}
MODEL_NAME = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")
# Claude models that accept the server-side refusal fallback.
_FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                    "claude-sonnet-5-5")

_lock = threading.Lock()

# What each request cost, from the tokens the provider reports. USD per
# million tokens: (sent, sent and read from the provider's cache, received),
# public prices of October 2026. DeepSeek bills twice as much at peak hours,
# which the app cannot tell from here: its peak price is used, so the figure
# is a ceiling ("au plus"). A model missing here is counted in tokens only.
PRICES_AS_OF = "10.2026"
PRICES = {
    "claude-fable-5-1": (10.0, 0.25, 50.0),
    "claude-opus-5-5": (4.0, 0.20, 20.0),
    "claude-sonnet-5-5": (2.0, 0.20, 10.0),
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    "deepseek-flash": (0.30, 0.006, 1.20),
    "deepseek-chat": (0.30, 0.006, 1.20),   # routed to Flash
}
CEILING = {"deepseek"}  # providers whose price above is the peak one

# The usage of the request this thread just made, read once by `ask_json`.
_usage = threading.local()


def _note_usage(sent: int, cached: int, received: int, searches: int = 0) -> None:
    previous = getattr(_usage, "value", None) or {"sent": 0, "cached": 0, "received": 0, "searches": 0}
    _usage.value = {"sent": previous["sent"] + sent, "cached": previous["cached"] + cached,
                    "received": previous["received"] + received,
                    "searches": previous["searches"] + searches}


def _take_usage() -> dict | None:
    value, _usage.value = getattr(_usage, "value", None), None
    return value


def cost(provider: str, model: str, usage: dict | None) -> float | None:
    """USD, or None when the model has no known price. A local model costs
    nothing."""
    if provider == "ollama":
        return 0.0
    price = PRICES.get(model)
    if price is None or not usage:
        return None
    fresh = max(usage.get("sent", 0) - usage.get("cached", 0), 0)
    return (fresh * price[0] + usage.get("cached", 0) * price[1]
            + usage.get("received", 0) * price[2]) / 1e6


class AIError(Exception):
    """A request that did not give a usable answer. The message is French,
    for the screen, and never carries the key."""


@dataclass
class Config:
    provider: str
    model: str
    base_url: str
    key: str
    effort: str
    folder: Path

    @property
    def label(self) -> str:
        return PROVIDERS[self.provider]["label"]

    @property
    def local(self) -> bool:
        return self.provider == "ollama"


def key_file(folder: Path, provider: str) -> Path:
    """Where a provider's key lives: `ai.<provider>.key`, so switching
    provider in the app needs no file edit; `ai.key` is read for any
    provider when the specific one is absent."""
    own = Path(folder) / f"ai.{provider}.key"
    return own if own.exists() or not (Path(folder) / KEY_NAME).exists() else Path(folder) / KEY_NAME


def _read_config(folder: Path) -> dict:
    path = Path(folder) / CONFIG_NAME
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise AIError(f"data/{CONFIG_NAME} n'est pas un JSON lisible.") from None
    return raw if isinstance(raw, dict) else {}


def save_config(folder: Path, provider: str | None, model: str = "") -> None:
    """The choice made in the app. `None` switches the assistant off without
    forgetting which model was chosen; other fields of the file are kept."""
    try:
        raw = _read_config(folder)
    except AIError:
        raw = {}
    if provider is None:
        raw["enabled"] = False
    else:
        if provider not in PROVIDERS:
            raise AIError(f"Fournisseur inconnu : {provider}.")
        model = (model or PROVIDERS[provider]["model"]).strip()
        if not MODEL_NAME.match(model):
            raise AIError("Nom de modèle invalide.")
        raw.update(provider=provider, model=model, enabled=True)
        raw.pop("_aide", None)
    with _lock:
        (Path(folder) / CONFIG_NAME).write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def local_models(base_url: str = PROVIDERS["ollama"]["base_url"]) -> list[str] | None:
    """The models installed in Ollama, or None when it is not running."""
    root = base_url.rsplit("/v1", 1)[0]
    try:
        with urllib.request.urlopen(f"{root}/api/tags", timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))


def journal(folder: Path, limit: int = 30) -> list[dict]:
    """The last requests sent, newest first, without their content."""
    path = Path(folder) / LOG_NAME
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        row = {k: e.get(k) for k in ("at", "task", "provider", "model", "chars", "outcome")}
        usage = e.get("usage")
        row["tokens"] = (usage.get("sent", 0) + usage.get("received", 0)) if usage else None
        price = cost(e.get("provider") or "", e.get("model") or "", usage)
        row["usd"] = round(price, 5) if price is not None else None
        out.append(row)
    return out


def spending(folder: Path, months: int = 2, today: dt.date | None = None) -> list[dict]:
    """The requests of the last `months` calendar months, added up: count,
    tokens, web searches, and the cost where every model has a price."""
    today = today or dt.date.today()
    keys = []
    year, month = today.year, today.month
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    totals = {k: {"month": k, "requests": 0, "sent": 0, "received": 0, "searches": 0,
                  "usd": 0.0, "unpriced": 0, "ceiling": False} for k in keys}
    path = Path(folder) / LOG_NAME
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        bucket = totals.get(str(e.get("at", ""))[:7])
        if bucket is None:
            continue
        if e.get("task") == "search":
            bucket["searches"] += 1
            continue
        bucket["requests"] += 1
        usage = e.get("usage")
        if not usage:
            bucket["unpriced"] += 1
            continue
        bucket["sent"] += usage.get("sent", 0)
        bucket["received"] += usage.get("received", 0)
        bucket["searches"] += usage.get("searches", 0)
        price = cost(e.get("provider") or "", e.get("model") or "", usage)
        if price is None:
            bucket["unpriced"] += 1
        else:
            bucket["usd"] += price
            bucket["ceiling"] |= e.get("provider") in CEILING
    for bucket in totals.values():
        bucket["usd"] = round(bucket["usd"], 4)
    return list(totals.values())


def status(folder: Path) -> dict:
    """What the app shows about the model: on or off, which one, and why
    not. The key itself never appears."""
    try:
        config = load(folder)
    except AIError as e:
        return {"enabled": False, "reason": str(e)}
    if config is None:
        return {"enabled": False,
                "reason": "Aucun modèle choisi : le choisir dans la page Assistant."}
    return {"enabled": True, "provider": config.provider, "label": config.label,
            "model": config.model, "local": config.local}


def load(folder: Path) -> Config | None:
    """The configuration next to the ledger, or None when there is none --
    the app then runs without any of the assisted features."""
    folder = Path(folder)
    raw = _read_config(folder)
    if not raw or raw.get("enabled") is False:
        return None
    provider = str(raw.get("provider") or "anthropic")
    if provider not in PROVIDERS:
        raise AIError(f"Fournisseur inconnu dans data/{CONFIG_NAME} : {provider} "
                      f"(connus : {', '.join(PROVIDERS)}).")
    spec = PROVIDERS[provider]
    key = ""
    path = key_file(folder, provider)
    if path.exists():
        key = path.read_text(encoding="utf-8").strip()
    if spec["key"] and not key:
        raise AIError(f"Clé absente : poser la clé {spec['label']} dans "
                      f"data/ai.{provider}.key.")
    return Config(provider=provider, model=str(raw.get("model") or spec["model"]),
                  base_url=str(raw.get("base_url") or spec.get("base_url", "")).rstrip("/"),
                  key=key, effort=str(raw.get("effort") or "low"), folder=folder)


# --- the request -------------------------------------------------------------

def ask_json(config: Config, task: str, system: str, user: str, schema: dict,
             *, max_tokens: int = 4000, cache: bool = True, web: bool = False) -> dict:
    """One question, one JSON answer that validates against `schema`.

    `web` lets the model search the web first where the provider can
    (`can_search`: Claude's server-side search); elsewhere it is ignored.
    Cached under the exact request; logged as sent. Raises AIError on
    anything that is not a valid answer -- a refusal, a network error, a
    JSON that does not match."""
    digest = hashlib.sha256(json.dumps(
        [config.provider, config.model, task, system, user, schema, web and can_search(config)],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cached = _cache_get(config.folder, digest) if cache else None
    if cached is not None:
        return cached
    _take_usage()
    try:
        if web and can_search(config):
            text = _call_anthropic(config, system, user, schema, max(max_tokens, 8000), web=True)
        else:
            text = _call(config, system, user, schema, max_tokens)
    except AIError:
        _log(config, task, system, user, outcome="échec", usage=_take_usage())
        raise
    _log(config, task, system, user, usage=_take_usage())
    try:
        answer = json.loads(_json_part(text))
    except json.JSONDecodeError:
        raise AIError("Le modèle n'a pas répondu en JSON.") from None
    problems = validate(answer, schema)
    if problems:
        raise AIError("Réponse du modèle hors format : " + problems[0])
    if cache:
        _cache_put(config.folder, digest, answer)
    return answer


SEARCH_RESULTS = 3


def search_snippets(config: Config, query: str, count: int = SEARCH_RESULTS) -> list[dict]:
    """DeepSeek's own search (`POST /v1/tools/search`, the same key), for a
    merchant name the model does not know. The answer is `{"results": [...]}`,
    each with a title, a URL, a snippet and a summary; it is still read
    leniently (other list keys, other text fields). Any failure is no result:
    the suggestion goes on without the web. Every search is written to the
    journal with what came of it -- how many pages, or which failure -- so a
    search that silently returns nothing can be seen."""
    if config.provider != "deepseek" or not query.strip():
        return []
    body = json.dumps({"query": query[:128], "count": count}).encode()
    request = urllib.request.Request(f"{config.base_url}/v1/tools/search", data=body,
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {config.key}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        _log(config, "search", "", query, outcome=f"échec HTTP {e.code}")
        return []
    except (urllib.error.URLError, TimeoutError, OSError):
        _log(config, "search", "", query, outcome="injoignable")
        return []
    except ValueError:
        _log(config, "search", "", query, outcome="réponse illisible")
        return []
    items = data
    if isinstance(data, dict):
        items = next((data[k] for k in ("results", "data", "items", "web") if k in data), [])
        if isinstance(items, dict):
            items = items.get("results", [])
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        text = next((str(item[k]) for k in ("snippet", "summary", "content", "description", "text")
                     if item.get(k)), "")
        title = str(item.get("title") or item.get("site_name") or item.get("name") or "")
        if title or text:
            out.append({"titre": title[:120], "url": str(item.get("url") or item.get("link") or "")[:200],
                        "extrait": text[:300]})
    out = out[:count]
    _log(config, "search", "", query,
         outcome=f"{len(out)} page{'s' if len(out) > 1 else ''}" if out
         else "aucun résultat lisible" + ("" if isinstance(data, dict) and "results" in data
                                          else f" (clés : {', '.join(list(data)[:5]) if isinstance(data, dict) else type(data).__name__})"))
    return out


def can_search(config: Config) -> bool:
    """Only Claude's API searches the web itself; DeepSeek's and Ollama's do
    not. The page offers a plain search link for everyone."""
    return config.provider == "anthropic"


WEB_SEARCHES = 5   # per request: a handful of merchant names


def _json_part(text: str) -> str:
    """The JSON object in a reply that may carry a sentence around it -- what
    a model writes after searching, when the format cannot be enforced."""
    text = _strip_fence(text)
    if text.startswith("{"):
        return text
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


def _call(config: Config, system: str, user: str, schema: dict, max_tokens: int) -> str:
    if config.provider == "anthropic":
        return _call_anthropic(config, system, user, schema, max_tokens)
    return _call_openai_format(config, system, user, schema, max_tokens)


def _call_anthropic(config: Config, system: str, user: str, schema: dict,
                    max_tokens: int, web: bool = False) -> str:
    try:
        import anthropic
    except ImportError:
        raise AIError("Le paquet anthropic n'est pas installé : "
                      "relancer run.bat (ou uv sync --extra web)") from None
    client = anthropic.Anthropic(api_key=config.key, timeout=TIMEOUT, max_retries=2)
    messages = [{"role": "user", "content": user}]
    request = dict(model=config.model, max_tokens=max_tokens, system=system, messages=messages,
                   output_config={"effort": config.effort,
                                  "format": {"type": "json_schema", "schema": schema}})
    if web:
        # The search runs on Anthropic's side; the answer's shape is then
        # asked in words and checked by `validate`, like the other providers.
        request["tools"] = [{"type": "web_search_20260209", "name": "web_search",
                             "max_uses": WEB_SEARCHES}]
        request["output_config"] = {"effort": config.effort}
        request["system"] = system + ("\n\nTu peux chercher sur le web. Termine par un objet "
                                      "JSON conforme à ce schéma, et rien après :\n"
                                      + json.dumps(schema, ensure_ascii=False))

    def create():
        if config.model in _FALLBACK_MODELS:
            # A request a safety classifier declines is re-run server-side
            # on the model Anthropic recommends for that case.
            return client.beta.messages.create(
                **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        return client.messages.create(**request)

    def note(response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        tool = getattr(usage, "server_tool_use", None)
        _note_usage((getattr(usage, "input_tokens", 0) or 0)
                    + (getattr(usage, "cache_creation_input_tokens", 0) or 0) + cached,
                    cached, getattr(usage, "output_tokens", 0) or 0,
                    getattr(tool, "web_search_requests", 0) or 0)

    try:
        response = create()
        note(response)
        # A long server-side search pauses the turn; sending it back resumes.
        for _ in range(3):
            if response.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": response.content})
            response = create()
            note(response)
    except anthropic.AuthenticationError:
        raise AIError("Clé refusée par Anthropic : vérifier data/ai.key.") from None
    except anthropic.RateLimitError:
        raise AIError("Limite de requêtes atteinte chez Anthropic : réessayer plus tard.") from None
    except anthropic.APIStatusError as e:
        raise AIError(f"Anthropic a répondu {e.status_code}.") from None
    except anthropic.APIConnectionError:
        raise AIError("Anthropic injoignable : pas de réseau ?") from None
    if response.stop_reason == "refusal":
        raise AIError("Le modèle a refusé de répondre.")
    if response.stop_reason == "max_tokens":
        raise AIError("Réponse tronquée par le modèle.")
    texts = [b.text for b in response.content if b.type == "text" and b.text.strip()]
    # After a search, the JSON is the last thing written.
    text = next((t for t in reversed(texts) if "{" in t), texts[-1] if texts else "")
    if not text:
        raise AIError("Réponse vide du modèle.")
    return text


def _call_openai_format(config: Config, system: str, user: str, schema: dict,
                        max_tokens: int) -> str:
    """DeepSeek and Ollama speak the OpenAI chat format. Their JSON mode
    guarantees JSON, not the shape: the schema goes into the instructions,
    and `validate` checks the answer."""
    body = {
        "model": config.model,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system + "\n\nRéponds uniquement par un "
             "objet JSON conforme à ce schéma JSON :\n" + json.dumps(schema, ensure_ascii=False)},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if config.key:
        headers["Authorization"] = f"Bearer {config.key}"
    request = urllib.request.Request(f"{config.base_url}/chat/completions",
                                     data=json.dumps(body).encode(), headers=headers)
    name = PROVIDERS[config.provider]["label"]
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AIError(f"Clé refusée par {name} : vérifier data/ai.key.") from None
        if e.code == 402:
            raise AIError(f"Solde épuisé chez {name}.") from None
        raise AIError(f"{name} a répondu {e.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AIError(f"{name} injoignable"
                      + (" : Ollama tourne-t-il ?" if config.local else " : pas de réseau ?")) from None
    except json.JSONDecodeError:
        raise AIError(f"{name} a répondu autre chose que du JSON.") from None
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict):
        _note_usage(int(usage.get("prompt_tokens") or 0),
                    int(usage.get("prompt_cache_hit_tokens") or 0),
                    int(usage.get("completion_tokens") or 0))
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise AIError(f"Réponse inattendue de {name}.") from None
    if choice.get("finish_reason") == "length":
        raise AIError("Réponse tronquée par le modèle.")
    return text


def _strip_fence(text: str) -> str:
    """Some models wrap JSON in a ```json fence despite being asked not to."""
    text = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    return match.group(1) if match else text


# --- the answer's shape --------------------------------------------------------

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def validate(value, schema: dict, path: str = "réponse") -> list[str]:
    """The subset of JSON Schema the app's schemas use: type (or a list of
    types), properties, required, items, enum, maxItems. Returns what is
    wrong, empty when the value fits."""
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind] if kind else []
    if kinds and not any(_is(value, k) for k in kinds):
        return [f"{path} : attendu {'/'.join(kinds)}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path} : valeur hors liste"]
    problems: list[str] = []
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                problems.append(f"{path}.{name} : manquant")
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                problems += validate(value[name], sub, f"{path}.{name}")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append(f"{path} : trop d'éléments")
        for i, item in enumerate(value):
            problems += validate(item, schema.get("items", {}), f"{path}[{i}]")
    return problems


def _is(value, kind: str) -> bool:
    if kind == "null":
        return value is None
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES.get(kind, object))


def strict(schema: dict) -> dict:
    """The schema as structured outputs want it: every object closed, every
    property required (an optional one is a nullable type instead)."""
    schema = dict(schema)
    if schema.get("type") == "object":
        schema["properties"] = {k: strict(v) for k, v in schema.get("properties", {}).items()}
        schema["required"] = list(schema["properties"])
        schema["additionalProperties"] = False
    if schema.get("type") == "array" and "items" in schema:
        schema["items"] = strict(schema["items"])
    return schema


# --- what the model may say ----------------------------------------------------

_NUMBER = re.compile(r"(?<![\w.'’])[-+−]?\d{1,3}(?:['’  ]\d{3})+(?:[.,]\d+)?"
                     r"|(?<![\w.'’])[-+−]?\d+(?:[.,]\d+)?")


def numbers_in(text: str) -> list[float]:
    """Every number written in `text`, Swiss style included (1'234.50)."""
    found = []
    for match in _NUMBER.finditer(text):
        raw = re.sub(r"['’  ]", "", match.group()).replace(",", ".").replace("−", "-")
        try:
            found.append(abs(float(raw)))
        except ValueError:
            continue
    return found


def allowed_numbers(facts) -> set[float]:
    """The numbers a text about `facts` may cite: each one as given, rounded
    to the franc and to the hundred, and the percentages it implies."""
    allowed: set[float] = set()

    def walk(value):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            v = abs(float(value))
            allowed.update({round(v, 2), round(v, 1), float(round(v)),
                            float(round(v, -1)), float(round(v, -2))})
            return
        if isinstance(value, str):
            for n in numbers_in(value):
                allowed.update({n, float(round(n))})
            return
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(facts)
    return allowed


def unsupported_numbers(text: str, facts) -> list[float]:
    """The numbers in `text` that `facts` does not contain. A day of the
    month, a year, a count of a handful are allowed: "le 4 juillet", "en
    2025", "deux lignes" written as 2."""
    allowed = allowed_numbers(facts)
    bad = []
    for n in numbers_in(text):
        if n in allowed or (n == int(n) and (n <= 31 or 1990 <= n <= 2100)):
            continue
        if any(abs(n - a) <= 0.011 for a in allowed):
            continue
        bad.append(n)
    return bad


def checked_text(text: str, facts) -> str:
    """`text` when every number in it comes from `facts`; AIError otherwise."""
    bad = unsupported_numbers(text, facts)
    if bad:
        raise AIError("Le modèle a cité un chiffre que l'app ne lui a pas donné "
                      f"({bad[0]:g}) : réponse écartée.")
    return text.strip()


# --- what leaves the machine ---------------------------------------------------

CARD_KIND = "Paiement par carte"


def is_card(txn) -> bool:
    """The bank prints "Paiement par carte - se terminant par 1234"."""
    return txn.kind.startswith(CARD_KIND)


class Redactor:
    """Names that are not public commerce go out as `[P1]`, `[P2]`...

    A card payment names a shop, which is public; a transfer names a
    person, a landlord, an employer -- the description of a life that
    `data/local_rules.json` keeps out of the repository for the same
    reason. The placeholders are put back in the model's answer, so the
    screen still reads the real names.
    """

    def __init__(self):
        self.names: dict[str, str] = {}

    def label(self, txn) -> str:
        if is_card(txn) or not txn.label:
            return txn.label
        return self.name(txn.label)

    def name(self, label: str) -> str:
        if label not in self.names:
            self.names[label] = f"[P{len(self.names) + 1}]"
        return self.names[label]

    def restore(self, text: str) -> str:
        for real, token in sorted(self.names.items(), key=lambda kv: -len(kv[1])):
            text = text.replace(token, real)
        return text


# --- journal and cache ----------------------------------------------------------

def _log(config: Config, task: str, system: str, user: str, outcome: str = "",
         usage: dict | None = None) -> None:
    entry = {"at": dt.datetime.now().isoformat(timespec="seconds"), "task": task,
             "provider": config.provider, "model": config.model,
             "chars": len(system) + len(user), "system": system, "sent": user,
             **({"outcome": outcome} if outcome else {}),
             **({"usage": usage} if usage else {})}
    with _lock, (config.folder / LOG_NAME).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _cache_read(folder: Path) -> dict:
    path = Path(folder) / CACHE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _cache_get(folder: Path, digest: str):
    with _lock:
        entry = _cache_read(folder).get(digest)
    return entry.get("answer") if isinstance(entry, dict) else None


def _cache_put(folder: Path, digest: str, answer) -> None:
    with _lock:
        cache = _cache_read(folder)
        cache[digest] = {"at": dt.datetime.now().isoformat(timespec="seconds"),
                         "answer": answer}
        if len(cache) > CACHE_LIMIT:
            keep = sorted(cache.items(), key=lambda kv: kv[1].get("at", ""))[-CACHE_LIMIT:]
            cache = dict(keep)
        (Path(folder) / CACHE_NAME).write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def memo_get(folder: Path, name: str):
    """A finished answer kept under a name the app chooses (the review of a
    month, the suggestions for a merchant), so a page can show it without
    asking the model again."""
    return _cache_get(folder, "memo:" + name)


def memos(folder: Path, prefix: str) -> dict:
    """Every memo whose name starts with `prefix`, by the rest of the name."""
    with _lock:
        cache = _cache_read(folder)
    head = "memo:" + prefix
    return {k[len(head):]: v.get("answer") for k, v in cache.items()
            if k.startswith(head) and isinstance(v, dict)}


def memo_put(folder: Path, name: str, value) -> None:
    _cache_put(folder, "memo:" + name, value)
