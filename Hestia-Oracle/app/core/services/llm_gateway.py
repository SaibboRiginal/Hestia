"""LLM gateway — Oracle is the single owner of LLM provider access.

Other services (Hephaestus Forge, ...) never hold provider URLs or API keys:
they ask Oracle via Hub for a *profile* and send an OpenAI-compatible chat body
(messages + tools).  Oracle forwards it to the profile's endpoint.

Profiles (env, all optional except the built-in ``local`` default):
    ORACLE_LLM_PROFILE_<NAME>_BASE_URL   OpenAI-compatible base (…/v1)
    ORACLE_LLM_PROFILE_<NAME>_MODEL
    ORACLE_LLM_PROFILE_<NAME>_API_KEY
``local`` defaults to Ollama's OpenAI endpoint (OLLAMA_API_URL or OLLAMA_URL host + /v1).
Built-in: ``local`` = Ollama with the code model setting (``oracle.models.code.*``); ``cloud`` =
Gemini (OpenAI-compat) with the code fallback model setting + GEMINI_API_KEY. The
ORACLE_LLM_PROFILE_* vars only override/add providers (e.g. OpenRouter).
"""
from __future__ import annotations

import json
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
    if "base_url" not in local:
        # Built-in Ollama profile: served through the native /api/chat (see _chat_ollama).
        local["base_url"] = f"{ollama}/v1"
        local["ollama_host"] = ollama
    from core.services import oracle_settings
    code = oracle_settings.usecase("code")
    local.setdefault("model", code["mod"] if code["prov"] == "ollama" else oracle_settings.USECASES["code"][2])
    local.setdefault("api_key", "ollama")
    # "cloud" needs no extra config: the first Gemini model among the code / reasoning /
    # generic settings (primary or fallback) + GEMINI_API_KEY. Explicit
    # ORACLE_LLM_PROFILE_CLOUD_* only to point Forge at another provider.
    cloud = found.setdefault("cloud", {})
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    for usecase in ("code", "reasoning", "generic"):
        uc = oracle_settings.usecase(usecase)
        model = uc["mod"] if uc["prov"] == "gemini" else uc["fb_mod"] if uc["fb_prov"] == "gemini" else ""
        if model and gemini_key:
            cloud.setdefault("base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
            cloud.setdefault("model", model)
            cloud.setdefault("api_key", gemini_key)
            break
    return {n: p for n, p in found.items() if p.get("base_url") and p.get("model")}


def list_profiles(check: bool = True) -> dict[str, Any]:
    """Public view (no keys).  ``check`` probes ``/models`` reachability."""
    out = {}
    for name, prof in _profiles().items():
        row = {"model": prof["model"], "base_url": prof["base_url"]}
        if prof.get("ollama_host"):
            from core.services import oracle_settings
            row["context_window"] = oracle_settings.context_window()
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


# Curated Gemini choices (free text is accepted too).
_GEMINI_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash",
                  "gemini-2.0-flash-lite", "gemini-embedding-001"]


def list_models(provider: str) -> list[dict[str, str]]:
    """Model options for a provider type (settings panel). Ollama: installed models."""
    provider = str(provider or "").strip().lower()
    if provider == "ollama":
        base = (os.getenv("OLLAMA_API_URL") or os.getenv("OLLAMA_URL", "http://localhost:11434")
                ).split("/api/")[0].rstrip("/")
        try:
            resp = requests.get(f"{base}/api/tags", timeout=5)
            resp.raise_for_status()
            names = sorted(m.get("name", "") for m in (resp.json() or {}).get("models", []) if m.get("name"))
            return [{"value": n, "label": n} for n in names]
        except Exception as exc:
            logger.warning("[🔄] event=llm_list_models_failed provider=ollama error=%s", exc)
            return []
    if provider == "gemini":
        return [{"value": m, "label": m} for m in _GEMINI_MODELS]
    from agents.providers import get_provider, is_provider_type
    if is_provider_type(provider):
        return [{"value": m, "label": m} for m in get_provider(provider).list_models()]
    return []


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
    if prof.get("ollama_host"):
        return _chat_ollama(prof, body)
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


# ── Ollama native ───────────────────────────────────────────────────────────
# Ollama's OpenAI endpoint (/v1) ignores num_ctx: the model is reloaded with Ollama's
# default window (a few k tokens), long agent prompts get cut silently and the answer
# stops mid-sentence. /api/chat takes the same num_ctx + keep_alive as every other
# Oracle call (no reload). Request and response are translated to the OpenAI shape.


def _ollama_messages(messages: list[dict]) -> list[dict]:
    out = []
    for msg in messages:
        row = {"role": msg.get("role") or "user", "content": msg.get("content") or ""}
        calls = []
        for call in msg.get("tool_calls") or []:
            fn = dict(call.get("function") or {})
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except ValueError:
                    args = {"raw": args}
            calls.append({"function": {"name": fn.get("name", ""), "arguments": args or {}}})
        if calls:
            row["tool_calls"] = calls
        if msg.get("name"):
            row["tool_name"] = msg["name"]
        out.append(row)
    return out


def _openai_response(data: dict, model: str) -> dict[str, Any]:
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    calls = []
    for i, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        calls.append({"id": f"call_{i}_{fn.get('name', '')}", "type": "function",
                      "function": {"name": fn.get("name", ""),
                                   "arguments": args if isinstance(args, str)
                                   else json.dumps(args or {}, ensure_ascii=False)}})
    out_msg: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("thinking"):
        out_msg["reasoning_content"] = message["thinking"]
    if calls:
        out_msg["tool_calls"] = calls
    finish = "tool_calls" if calls else ("length" if data.get("done_reason") == "length" else "stop")
    return {"object": "chat.completion", "model": data.get("model") or model,
            "choices": [{"index": 0, "message": out_msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": data.get("prompt_eval_count"),
                      "completion_tokens": data.get("eval_count")}}


def _chat_ollama(prof: dict, body: dict[str, Any]) -> dict[str, Any]:
    from core.services import oracle_settings
    model = body.get("model") or prof["model"]
    request = {"model": model, "messages": _ollama_messages(body["messages"]), "stream": False,
               **oracle_settings.ollama_request_options()}
    request["options"] = dict(request.get("options") or {})
    if body.get("tools"):
        request["tools"] = body["tools"]
    if body.get("temperature") is not None:
        request["options"]["temperature"] = body["temperature"]
    if body.get("max_tokens"):
        request["options"]["num_predict"] = body["max_tokens"]
    try:
        resp = requests.post(f"{prof['ollama_host']}/api/chat", json=request,
                             timeout=float(os.getenv("ORACLE_LLM_CHAT_TIMEOUT_SEC", "600")))
    except requests.RequestException as exc:
        raise LLMGatewayError(f"profile 'local' unreachable: {exc}", 502)
    if resp.status_code >= 400:
        raise LLMGatewayError(f"profile 'local' error {resp.status_code}: {resp.text[:300]}", 502)
    data = resp.json() or {}
    num_ctx = request["options"].get("num_ctx")
    prompt_tokens = int(data.get("prompt_eval_count") or 0)
    logger.info("event=llm_gateway_chat profile=local model=%s backend=ollama_native num_ctx=%s "
                "prompt_tokens=%s completion_tokens=%s done_reason=%s",
                model, num_ctx, prompt_tokens, data.get("eval_count"), data.get("done_reason"))
    if num_ctx and prompt_tokens >= int(num_ctx) * 0.95:
        logger.warning("[🔄] event=llm_gateway_context_full profile=local num_ctx=%s prompt_tokens=%s "
                       "hint=raise oracle.provider.ollama.num_ctx or send a shorter prompt", num_ctx, prompt_tokens)
    return _openai_response(data, model)
