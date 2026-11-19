"""Named LLM providers — *where* models live (dossier ``docs/work/2026-10-19-oracle-blocks``).

A provider is a named instance of a **standard** (type): ``ollama``, ``openai`` (any OpenAI-compatible server:
llama-server, LM Studio, DeepSeek, OpenRouter, Groq…), ``anthropic`` (Claude API, DeepSeek's Anthropic
endpoint…), ``gemini``, ``claude_cli`` (Claude subscription through the ``claude`` CLI).
Name, type, label and address are the Themis setting ``oracle.providers`` (edited from the WebUI); the key alone
is a secret in env: ``ORACLE_KEY_<NAME>`` (name upper-cased, ``-``/spaces → ``_``). Chains (``llm_chains``)
refer to providers by name.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger("hestia_oracle.llm_providers")

KEY_PREFIX = "ORACLE_KEY_"

# Standards Oracle speaks. Label = what the WebUI shows in the type picker.
TYPES: dict[str, str] = {
    "ollama": "Ollama",
    "openai": "OpenAI compatible",
    "llamacpp": "llama-server (slots and saved context)",
    "anthropic": "Anthropic compatible",
    "gemini": "Gemini",
    "claude_cli": "Claude (subscription, CLI)",
}

# Default addresses per type ("" = not needed / from infrastructure env).
_DEFAULT_URL = {
    "gemini": "https://generativelanguage.googleapis.com",
    "anthropic": "https://api.anthropic.com",
}

# Defaults of ``oracle.providers``: Marko only adds the keys he has. A provider without its key (cloud) or
# its CLI login is simply skipped by every chain.
DEFAULT_PROVIDERS: dict[str, dict[str, str]] = {
    "ollama": {"type": "ollama", "label": "Ollama (local)", "url": ""},
    "llamacpp": {"type": "llamacpp", "label": "llama-server (local)", "url": "http://hestia_llamacpp:8080/v1"},
    "gemini": {"type": "gemini", "label": "Gemini", "url": ""},
    "deepseek": {"type": "openai", "label": "DeepSeek", "url": "https://api.deepseek.com/v1"},
    "claude-api": {"type": "anthropic", "label": "Claude (API key)", "url": ""},
    "claude": {"type": "claude_cli", "label": "Claude (subscription)", "url": ""},
}

# Types that need a key to be usable (local servers and the CLI do not).
_NEEDS_KEY = {"gemini", "anthropic"}


def key_env(name: str) -> str:
    """Env var holding the key of provider *name* (``deepseek`` → ``ORACLE_KEY_DEEPSEEK``)."""
    return KEY_PREFIX + re.sub(r"[^A-Z0-9]+", "_", str(name or "").upper()).strip("_")


def env_path():
    """Oracle's own ``.env`` (``Hestia-Oracle/app/.env``, mounted at ``/code``), written by the guided setup."""
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / ".env"


def reload_keys() -> list[str]:
    """Re-read the ``ORACLE_KEY_*`` lines of Oracle's ``.env``: a key saved by the setup works at once."""
    from hestia_common import env_keys
    return env_keys.reload(env_path(), KEY_PREFIX)


def api_key(name: str) -> str:
    return (os.getenv(key_env(name)) or "").strip()


def ollama_host() -> str:
    """Ollama base address from infrastructure env (``OLLAMA_URL`` may carry an ``/api/...`` path)."""
    raw = os.getenv("OLLAMA_API_URL") or os.getenv("OLLAMA_URL") or "http://localhost:11434"
    return raw.split("/api/")[0].rstrip("/")


def _normalize(name: str, raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    ptype = str(raw.get("type") or "").strip().lower()
    if ptype not in TYPES:
        logger.warning("[🔄] event=llm_provider_unknown_type provider=%s type=%s skipped", name, ptype)
        return None
    return {"name": name, "type": ptype, "label": str(raw.get("label") or name).strip(),
            "url": str(raw.get("url") or "").strip()}


def providers() -> dict[str, dict[str, str]]:
    """Every configured provider: ``{name: {name, type, label, url}}`` (setting ``oracle.providers``)."""
    from core.services import oracle_settings
    value = oracle_settings.settings.get(oracle_settings.PROVIDERS_KEY)
    if not isinstance(value, dict) or not value:
        value = DEFAULT_PROVIDERS
    out: dict[str, dict[str, str]] = {}
    for name, raw in value.items():
        name = str(name or "").strip().lower()
        prov = _normalize(name, raw) if name else None
        if prov:
            out[name] = prov
    return out


def get(name: str) -> dict[str, str] | None:
    """One provider by name. Bare type names still resolve (``ollama``/``gemini`` with no setting)."""
    name = str(name or "").strip().lower()
    found = providers().get(name)
    if found is None and name in TYPES:
        found = {"name": name, "type": name, "label": TYPES[name], "url": ""}
    return found


def type_of(name: str) -> str:
    prov = get(name)
    return prov["type"] if prov else ""


def url(name: str) -> str:
    """Address of a provider (default per type when empty; Ollama from infrastructure env)."""
    prov = get(name) or {}
    value = prov.get("url") or ""
    if prov.get("type") == "ollama":
        return (value or ollama_host()).rstrip("/")
    return value or _DEFAULT_URL.get(prov.get("type", ""), "")


def class_config(name: str) -> dict[str, Any]:
    """Config dict for a provider class in ``agents.providers`` (address, key, type tunables, CLI infra)."""
    from agents.llm_config import load_llm_config
    from core.services import oracle_settings
    prov = get(name) or {}
    ptype = prov.get("type", "")
    config: dict[str, Any] = dict(load_llm_config().get(ptype, {}))
    config.update(oracle_settings.provider_settings(ptype))
    if ptype in ("openai", "anthropic", "llamacpp"):
        config["base_url"] = url(name) if prov.get("url") or ptype in ("openai", "llamacpp") else ""
        config["api_key"] = api_key(name)
    config["name"] = prov.get("name", name)
    return config


def available(name: str) -> tuple[bool, str]:
    """Whether a provider can be called now (key present, CLI logged in…) — no network probe."""
    prov = get(name)
    if prov is None:
        return False, f"provider '{name}' not configured"
    ptype = prov["type"]
    if ptype in _NEEDS_KEY and not api_key(name):
        return False, f"{key_env(name)} not set"
    if ptype in ("openai", "llamacpp") and not url(name):
        return False, "address missing"
    if ptype in ("claude_cli", "llamacpp"):   # CLI login / server health probe (cached)
        from agents.providers import get_provider
        return get_provider(name).available()
    return True, "ok"


def public_view(check: bool = False) -> list[dict[str, Any]]:
    """Providers for the WebUI / ``GET /api/llm/providers`` (never the key, only whether it is set)."""
    from core.services import llm_chains
    out = []
    for name, prov in providers().items():
        ok, detail = available(name)
        row = {**prov, "url": url(name), "key_env": key_env(name), "key_set": bool(api_key(name)),
               "needs_key": prov["type"] in _NEEDS_KEY, "available": ok, "detail": detail,
               "exhausted": llm_chains.exhausted_for(name)}
        if check and ok:
            row["models"] = list_models(name)
        out.append(row)
    return out


# Used only when Google's model list cannot be read (no key yet, network down); free text is accepted too.
GEMINI_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest", "gemini-2.5-flash",
                 "gemini-2.5-pro", "gemini-embedding-001"]

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "host.docker.internal", "host-gateway")


def is_local(name: str) -> bool:
    """True for a provider that runs on the user's machines (Ollama, llama-server, LM Studio, Jan… on this PC or the
    home network), False for a cloud service. Decided by type, then by address: an OpenAI-compatible block on
    ``localhost:1234`` is local, the same type on ``api.deepseek.com`` is cloud."""
    import ipaddress
    from urllib.parse import urlsplit
    prov = get(name)
    if not prov:
        return False
    if prov["type"] in ("ollama", "llamacpp"):
        return True
    if prov["type"] != "openai":
        return False
    host = (urlsplit(url(name)).hostname or "").lower()
    if not host:
        return False
    if host in _LOCAL_HOSTS or host.startswith("hestia_") or host.endswith(".local") or "." not in host:
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


# ── What a model is for (dossier 2026-11-18-real-test-problems E): pickers show only the models that fit ──────────
USES = ("chat", "embedding")
# Names that are not for chatting (speech, pictures, live audio…), when the provider does not say it itself.
_NOT_CHAT = ("tts", "image", "audio", "live", "native", "embed", "aqa", "imagen", "veo", "computer-use", "robotics",
             "whisper", "dall-e", "moderation", "transcribe", "rerank")


def is_embedding_name(name: str, family: str = "") -> bool:
    """An embedding model judged by its name (used when the provider does not declare what its models do)."""
    low = f"{name} {family}".lower()
    return "embed" in low or "bert" in low or "bge-" in low


def is_chat_name(name: str) -> bool:
    """A model to chat with judged by its name: not embedding, not speech, pictures or live audio."""
    return not is_embedding_name(name) and not any(w in name.lower() for w in _NOT_CHAT)


def _fits(use: str, name: str, caps: set[str] | None) -> bool:
    """*name* fits *use*: from the capabilities the provider declares when there are some, else from the name."""
    if not use:
        return True
    if caps:
        if use == "embedding":
            return "embedding" in caps
        return "completion" in caps and "embedding" not in caps
    return is_embedding_name(name) if use == "embedding" else is_chat_name(name)


def _gemini_models(name: str, use: str = "") -> list[str]:
    """Google's own list for this key (``models.list``) with what each model supports: chat = ``generateContent`` and
    not a speech/picture/live model, embedding = ``embedContent``. A retired alias never shows up. Curated list when
    it cannot be read."""
    import requests
    key = api_key(name)
    curated = [m for m in GEMINI_MODELS if _fits(use, m, None)]
    if not key:
        return curated
    try:
        resp = requests.get(f"{url(name).rstrip('/')}/v1beta/models", params={"key": key, "pageSize": 1000}, timeout=8)
        resp.raise_for_status()
        out = []
        for m in (resp.json() or {}).get("models") or []:
            methods = set(m.get("supportedGenerationMethods") or [])
            model = str(m.get("name") or "").removeprefix("models/")
            if not model or not methods & {"generateContent", "embedContent"}:
                continue
            if use == "embedding" and "embedContent" not in methods:
                continue
            if use == "chat" and ("generateContent" not in methods or not is_chat_name(model)):
                continue
            out.append(model)
        return out or curated
    except Exception as exc:
        logger.warning("[🔄] event=llm_list_models_failed provider=%s error=%s fallback=curated", name, str(exc)[:160])
        return curated


_ollama_caps_cache: dict[str, set[str]] = {}


def _ollama_caps(base: str, model: str, digest: str = "") -> set[str] | None:
    """What an installed Ollama model can do (``/api/show`` ``capabilities``: completion, tools, vision, embedding,
    thinking), cached per model and digest. None when this Ollama does not say (older versions): the name decides."""
    import requests
    key = f"{base}|{model}|{digest}"
    if key in _ollama_caps_cache:
        return _ollama_caps_cache[key] or None
    try:
        resp = requests.post(f"{base}/api/show", json={"model": model}, timeout=4)
        resp.raise_for_status()
        caps = {str(c) for c in (resp.json() or {}).get("capabilities") or []}
    except Exception as exc:
        logger.info("[🔄] event=ollama_caps_unknown model=%s error=%s", model, str(exc)[:120])
        return None
    _ollama_caps_cache[key] = caps
    return caps or None


def list_models(name: str, use: str = "") -> list[str]:
    """Model names of a provider, from the provider itself (Ollama: installed models; Gemini, OpenAI-compatible servers
    such as LM Studio, Jan, vLLM, DeepSeek: their ``models`` API; Claude: its CLI/API list).
    *use* (``chat`` | ``embedding``, empty = all): only the models that fit, from what the provider declares (Gemini
    methods, Ollama capabilities) or else from the name."""
    import requests
    use = use if use in USES else ""
    ptype = type_of(name)
    if ptype == "ollama":
        try:
            base = url(name)
            resp = requests.get(f"{base}/api/tags", timeout=5)
            resp.raise_for_status()
            rows = [m for m in (resp.json() or {}).get("models", []) if m.get("name")]
            if use:
                rows = [m for m in rows if _fits(use, m["name"], _ollama_caps(base, m["name"], str(m.get("digest") or "")))]
            return sorted(m["name"] for m in rows)
        except Exception as exc:
            logger.warning("[🔄] event=llm_list_models_failed provider=%s error=%s", name, exc)
            return []
    if ptype == "gemini":
        return _gemini_models(name, use)
    if ptype:
        from agents.providers import get_provider
        try:
            return [m for m in get_provider(name).list_models() if _fits(use, m, None)]
        except Exception as exc:
            logger.warning("[🔄] event=llm_list_models_failed provider=%s error=%s", name, exc)
    return []
