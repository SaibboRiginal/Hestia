"""Named LLM providers — *where* models live (dossier ``docs/work/2026-10-19-oracle-a-blocchi``).

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
    "openai": "Compatibile OpenAI",
    "llamacpp": "llama-server (slot e contesto salvato)",
    "anthropic": "Compatibile Anthropic",
    "gemini": "Gemini",
    "claude_cli": "Claude (abbonamento, CLI)",
}

# Default addresses per type ("" = not needed / from infrastructure env).
_DEFAULT_URL = {
    "gemini": "https://generativelanguage.googleapis.com",
    "anthropic": "https://api.anthropic.com",
}

# Defaults of ``oracle.providers``: Marko only adds the keys he has. A provider without its key (cloud) or
# its CLI login is simply skipped by every chain.
DEFAULT_PROVIDERS: dict[str, dict[str, str]] = {
    "ollama": {"type": "ollama", "label": "Ollama (locale)", "url": ""},
    "llamacpp": {"type": "llamacpp", "label": "llama-server (locale)", "url": "http://hestia_llamacpp:8080/v1"},
    "gemini": {"type": "gemini", "label": "Gemini", "url": ""},
    "deepseek": {"type": "openai", "label": "DeepSeek", "url": "https://api.deepseek.com/v1"},
    "claude-api": {"type": "anthropic", "label": "Claude (chiave API)", "url": ""},
    "claude": {"type": "claude_cli", "label": "Claude (abbonamento)", "url": ""},
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


def _gemini_models(name: str) -> list[str]:
    """Google's own list for this key (``models.list``): only models that can chat (``generateContent``) or embed,
    so a retired alias never shows up. Curated list when it cannot be read."""
    import requests
    key = api_key(name)
    if not key:
        return list(GEMINI_MODELS)
    try:
        resp = requests.get(f"{url(name).rstrip('/')}/v1beta/models", params={"key": key, "pageSize": 1000}, timeout=8)
        resp.raise_for_status()
        out = []
        for m in (resp.json() or {}).get("models") or []:
            methods = m.get("supportedGenerationMethods") or []
            model = str(m.get("name") or "").removeprefix("models/")
            if model and ("generateContent" in methods or "embedContent" in methods):
                out.append(model)
        return out or list(GEMINI_MODELS)
    except Exception as exc:
        logger.warning("[🔄] event=llm_list_models_failed provider=%s error=%s fallback=curated", name, str(exc)[:160])
        return list(GEMINI_MODELS)


def list_models(name: str) -> list[str]:
    """Model names of a provider, from the provider itself (Ollama: installed models; Gemini, OpenAI-compatible servers
    such as LM Studio, Jan, vLLM, DeepSeek: their ``models`` API; Claude: its CLI/API list)."""
    import requests
    ptype = type_of(name)
    if ptype == "ollama":
        try:
            resp = requests.get(f"{url(name)}/api/tags", timeout=5)
            resp.raise_for_status()
            return sorted(m.get("name", "") for m in (resp.json() or {}).get("models", []) if m.get("name"))
        except Exception as exc:
            logger.warning("[🔄] event=llm_list_models_failed provider=%s error=%s", name, exc)
            return []
    if ptype == "gemini":
        return _gemini_models(name)
    if ptype:
        from agents.providers import get_provider
        try:
            return list(get_provider(name).list_models())
        except Exception as exc:
            logger.warning("[🔄] event=llm_list_models_failed provider=%s error=%s", name, exc)
    return []
