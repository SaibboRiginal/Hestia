"""LLM gateway — Oracle is the single owner of LLM provider access.

Other services (Hephaestus Forge, ...) never hold provider URLs or API keys: they send an
OpenAI-compatible chat body (messages + tools) with their ``use_case`` (default ``forge.codice``) and
Oracle walks that use case's chain (``llm_chains``): each step is forwarded to its provider in the
OpenAI chat-completions shape (Ollama through its native ``/api/chat`` so ``num_ctx`` is honoured;
Gemini and Anthropic through their OpenAI-compatible endpoints). A step out of quota is skipped until its
reset, any other failure moves to the next step. Subscription CLIs are not chat endpoints and are skipped.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests

from core.services import llm_chains, llm_providers, llm_stats, llm_usage

logger = logging.getLogger("hestia_oracle.llm_gateway")

DEFAULT_USECASE = "forge.codice"
_CLOUD_TYPES = {"gemini", "anthropic", "claude_cli"}


def _chat_timeout() -> float:
    from core.services import oracle_settings
    return float(oracle_settings.get_int(oracle_settings.GATEWAY_CHAT_TIMEOUT, 1))


def _openai_base(provider: str) -> str:
    """OpenAI-compatible base (…/v1) of a named provider, or "" when its standard has none."""
    ptype = llm_providers.type_of(provider)
    if ptype == "openai":
        return llm_providers.url(provider).rstrip("/")
    if ptype == "gemini":
        return f"{llm_providers.url(provider).rstrip('/')}/v1beta/openai"
    if ptype == "anthropic":
        return f"{llm_providers.url(provider).rstrip('/')}/v1"
    return ""


def billed(provider: str) -> bool:
    """Whether calls to *provider* cost money / subscription quota (Forge permission group «cloud»)."""
    ptype = llm_providers.type_of(provider)
    return ptype in _CLOUD_TYPES or (ptype == "openai" and bool(llm_providers.api_key(provider)))


def _chat_steps(use_case: str) -> list[tuple[int, dict]]:
    out = []
    for i, step in enumerate(llm_chains.chain_steps(use_case)):
        ptype = llm_providers.type_of(step["provider"])
        if ptype != "ollama" and not _openai_base(step["provider"]):
            continue
        if llm_chains.exhausted_until(step["provider"], step["model"]):
            continue
        if not llm_providers.available(step["provider"])[0]:
            continue
        out.append((i, step))
    return out


def usecase_status(use_case: str) -> dict[str, Any]:
    """What a chat on *use_case* would use now (Forge ``available()``): model, window, billing."""
    use_case = str(use_case or DEFAULT_USECASE).strip().lower()
    cfg = llm_chains.usecase_config(use_case)
    steps = _chat_steps(use_case)
    if not steps:
        return {"use_case": use_case, "chain": cfg["chain"], "available": False,
                "detail": f"no usable step in chain '{cfg['chain']}' (keys, addresses or quota)"}
    _, first = steps[0]
    window = 0
    if llm_providers.type_of(first["provider"]) == "ollama":
        from core.services import oracle_settings
        window = oracle_settings.context_window()
    return {"use_case": use_case, "chain": cfg["chain"], "available": True, "detail": "ok",
            "provider": first["provider"], "model": first["model"], "context_window": window,
            "billed": any(billed(step["provider"]) for _, step in steps),
            "steps": [{"provider": s["provider"], "model": s["model"]} for _, s in steps]}


class LLMGatewayError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class _StepError(Exception):
    def __init__(self, message: str, status_code: int = 502, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


def chat(body: dict[str, Any]) -> dict[str, Any]:
    """Forward an OpenAI-compatible chat completion along a use case's chain.

    body: {use_case?, messages, tools?, temperature?, max_tokens?, tool_choice?}
    Returns the provider's JSON (``choices[0].message`` ...) + ``hestia_step`` (which step answered).
    """
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise LLMGatewayError("messages required")
    use_case = str(body.get("use_case") or DEFAULT_USECASE).strip().lower()
    chain_name = llm_chains.usecase_config(use_case)["chain"]
    errors: list[str] = []
    for index, step in _chat_steps(use_case):
        provider, model = step["provider"], step["model"]
        with llm_usage.step(use_case, chain_name, index, provider, model) as usage:
            try:
                if llm_providers.type_of(provider) == "ollama":
                    data = _chat_ollama(provider, model, body)
                else:
                    data = _chat_openai(provider, model, body)
                llm_stats.record_openai(use_case, model, data)
            except _StepError as exc:
                quota = llm_chains.is_quota_error(exc)
                llm_usage.finish(usage, "quota" if quota else "error", str(exc)[:300])
                if quota:
                    llm_chains.mark_exhausted(provider, model, exc)
                else:
                    logger.warning("[🔄] event=llm_gateway_step_failed use_case=%s provider=%s model=%s error=%s",
                                   use_case, provider, model, str(exc)[:200])
                errors.append(f"{provider}/{model}: {str(exc)[:160]}")
                continue
        llm_usage.finish(usage)
        llm_chains.note_outcome(use_case, index)
        data["hestia_step"] = {"use_case": use_case, "chain": llm_chains.usecase_config(use_case)["chain"],
                               "step": index, "provider": provider, "model": model}
        return data
    chain = llm_chains.usecase_config(use_case)["chain"]
    llm_chains.note_outcome(use_case, None)
    logger.error("event=llm_chain_exhausted use_case=%s chain=%s errors=%s", use_case, chain,
                 " | ".join(errors) or "no usable step")
    raise LLMGatewayError(f"chain '{chain}' ({use_case}): " + (" | ".join(errors) or "no usable step"), 502)


def _chat_openai(provider: str, model: str, body: dict[str, Any]) -> dict[str, Any]:
    payload = {k: body[k] for k in ("messages", "tools", "temperature", "max_tokens", "tool_choice") if k in body}
    payload["model"] = model
    headers = {"Content-Type": "application/json"}
    key = llm_providers.api_key(provider)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        resp = requests.post(f"{_openai_base(provider)}/chat/completions", headers=headers, json=payload,
                             timeout=_chat_timeout())
    except requests.RequestException as exc:
        raise _StepError(f"unreachable: {exc}")
    if resp.status_code >= 400:
        raise _StepError(f"error {resp.status_code}: {resp.text[:300]}", resp.status_code, resp)
    data = resp.json()
    usage = data.get("usage") or {}
    logger.info("event=llm_gateway_chat provider=%s model=%s prompt_tokens=%s completion_tokens=%s",
                provider, model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
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


def _chat_ollama(provider: str, model: str, body: dict[str, Any]) -> dict[str, Any]:
    from core.services import oracle_settings
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
        resp = requests.post(f"{llm_providers.url(provider)}/api/chat", json=request,
                             timeout=_chat_timeout())
    except requests.RequestException as exc:
        raise _StepError(f"unreachable: {exc}")
    if resp.status_code >= 400:
        raise _StepError(f"error {resp.status_code}: {resp.text[:300]}", resp.status_code, resp)
    data = resp.json() or {}
    num_ctx = request["options"].get("num_ctx")
    prompt_tokens = int(data.get("prompt_eval_count") or 0)
    logger.info("event=llm_gateway_chat provider=%s model=%s backend=ollama_native num_ctx=%s "
                "prompt_tokens=%s completion_tokens=%s done_reason=%s",
                provider, model, num_ctx, prompt_tokens, data.get("eval_count"), data.get("done_reason"))
    if num_ctx and prompt_tokens >= int(num_ctx) * 0.95:
        logger.warning("[🔄] event=llm_gateway_context_full provider=%s num_ctx=%s prompt_tokens=%s "
                       "hint=raise oracle.provider.ollama.num_ctx or send a shorter prompt", provider, num_ctx, prompt_tokens)
    return _openai_response(data, model)
