"""LLM gateway — Oracle is the single owner of LLM provider access.

Other services (Hephaestus Forge, ...) never hold provider URLs or API keys:
they ask Oracle via Hub for a *profile* and send an OpenAI-compatible chat body
(messages + tools).  Oracle forwards it to the profile's endpoint.

Profiles (env, all optional except the built-in ``local`` default):
    ORACLE_LLM_PROFILE_<NAME>_BASE_URL   OpenAI-compatible base (…/v1)
    ORACLE_LLM_PROFILE_<NAME>_MODEL
    ORACLE_LLM_PROFILE_<NAME>_API_KEY
``local`` defaults to Ollama's OpenAI endpoint (OLLAMA_API_URL or OLLAMA_URL host + /v1).
Typical: ``local`` (Ollama) and ``cloud`` (OpenRouter / Gemini OpenAI-compat).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger("hestia_oracle.llm_gateway")

_PREFIX = "ORACLE_LLM_PROFILE_"


def _profiles() -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        m = re.fullmatch(rf"{_PREFIX}([A-Z0-9_]+)_(BASE_URL|MODEL|API_KEY)", key)
        if m:
            found.setdefault(m.group(1).lower(), {})[m.group(2).lower()] = value.strip()
    local = found.setdefault("local", {})
    ollama = (os.getenv("OLLAMA_API_URL") or os.getenv("OLLAMA_URL", "http://localhost:11434")
              ).split("/api/")[0].rstrip("/")
    local.setdefault("base_url", f"{ollama}/v1")
    local.setdefault("model", os.getenv("MODEL_USECASE_CODE_MODEL", "qwen2.5-coder:14b"))
    local.setdefault("api_key", "ollama")
    return {n: p for n, p in found.items() if p.get("base_url") and p.get("model")}


def list_profiles(check: bool = True) -> dict[str, Any]:
    """Public view (no keys).  ``check`` probes ``/models`` reachability."""
    out = {}
    for name, prof in _profiles().items():
        row = {"model": prof["model"], "base_url": prof["base_url"]}
        if check:
            try:
                resp = requests.get(f"{prof['base_url'].rstrip('/')}/models",
                                    headers={"Authorization": f"Bearer {prof.get('api_key', '')}"}, timeout=5)
                row["available"] = resp.status_code < 400
                row["detail"] = "ok" if row["available"] else f"status {resp.status_code}"
            except Exception as exc:
                row["available"], row["detail"] = False, f"unreachable: {exc}"
        out[name] = row
    return out


class LLMGatewayError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def chat(body: dict[str, Any]) -> dict[str, Any]:
    """Forward an OpenAI-compatible chat completion to a profile.

    body: {profile, messages, tools?, temperature?, model?, max_tokens?}
    Returns the provider's JSON (``choices[0].message`` ...).
    """
    name = str(body.get("profile") or "local").strip().lower()
    prof = _profiles().get(name)
    if not prof:
        raise LLMGatewayError(f"LLM profile '{name}' not configured ({_PREFIX}{name.upper()}_BASE_URL/_MODEL)", 404)
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise LLMGatewayError("messages required")
    payload = {k: body[k] for k in ("messages", "tools", "temperature", "max_tokens", "tool_choice") if k in body}
    payload["model"] = body.get("model") or prof["model"]
    try:
        resp = requests.post(
            f"{prof['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {prof.get('api_key', '')}", "Content-Type": "application/json"},
            json=payload, timeout=float(os.getenv("ORACLE_LLM_CHAT_TIMEOUT_SEC", "600")))
    except requests.RequestException as exc:
        raise LLMGatewayError(f"profile '{name}' unreachable: {exc}", 502)
    if resp.status_code >= 400:
        raise LLMGatewayError(f"profile '{name}' error {resp.status_code}: {resp.text[:300]}", 502)
    data = resp.json()
    usage = data.get("usage") or {}
    logger.info("event=llm_gateway_chat profile=%s model=%s prompt_tokens=%s completion_tokens=%s",
                name, payload["model"], usage.get("prompt_tokens"), usage.get("completion_tokens"))
    return data
