"""Provider ``anthropic`` — Claude through the Anthropic API (key ``ORACLE_ANTHROPIC_API_KEY``).

Thinking: the chat mode level maps to ``thinking_by_mode`` (off → thinking disabled + effort
low; otherwise adaptive thinking with that effort, summarized reasoning returned as
``reasoning_content``).  Prompt caching: system prompt, tool list and the static part of the
agent-loop prompt (before ``SYSTEM_PROMPT_DYNAMIC_BOUNDARY``) are cache breakpoints.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Iterator

from agents.providers.base import LLMProvider, split_static, think_level, tool_result

logger = logging.getLogger("hestia_oracle.providers.anthropic")

_EPHEMERAL = {"type": "ephemeral"}


class AnthropicProvider(LLMProvider):
    TYPE = "anthropic"
    LABEL = "Claude (chiave API)"
    CONFIG_FIELDS = (
        {"key": "api_key", "type": "secret_ref", "label": "Chiave API", "env": "ORACLE_ANTHROPIC_API_KEY"},
        {"key": "thinking_by_mode", "type": "object", "label": "Ragionamento per modalità",
         "default": {"fast": "off", "normal": "low", "deep": "high"}},
        {"key": "prompt_cache", "type": "bool", "label": "Cache del prompt", "default": True},
        {"key": "max_tokens", "type": "int", "label": "Token massimi per risposta", "default": 16000},
        {"key": "timeout_sec", "type": "int", "label": "Timeout (secondi)", "default": 180},
    )
    CAPABILITIES = frozenset({"chat", "tools", "stream", "vision", "thinking"})
    MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._client = None

    # ── Introspection ─────────────────────────────────────────────────────
    def available(self) -> tuple[bool, str]:
        if not self.config.get("api_key"):
            return False, "ORACLE_ANTHROPIC_API_KEY not set"
        return True, "ok"

    def list_models(self) -> list[str]:
        if self.available()[0]:
            try:
                ids = [m.id for m in self.client.models.list()]
                if ids:
                    return ids
            except Exception as exc:
                logger.warning("[🔄] event=anthropic_list_models_failed error=%s using=builtin", exc)
        return list(self.MODELS)

    @property
    def client(self):
        if self._client is None:
            import anthropic

            ok, detail = self.available()
            if not ok:
                raise RuntimeError(f"anthropic provider unavailable: {detail}")
            self._client = anthropic.Anthropic(api_key=self.config["api_key"],
                                               timeout=float(self.config["timeout_sec"]))
        return self._client

    # ── Request building ──────────────────────────────────────────────────
    def _cache(self) -> dict:
        return {"cache_control": _EPHEMERAL} if self.config.get("prompt_cache") else {}

    def _thinking(self, thinking: Any) -> tuple[dict, str]:
        effort = (self.config.get("thinking_by_mode") or {}).get(think_level(thinking), "low")
        if effort == "off":
            return {"type": "disabled"}, "low"
        return {"type": "adaptive", "display": "summarized"}, effort

    def _params(self, model: str, system: str, content: list[dict], thinking: Any,
                tools: list[dict] | None = None) -> dict:
        thinking_cfg, effort = self._thinking(thinking)
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": int(self.config["max_tokens"]),
            "messages": [{"role": "user", "content": content}],
            "thinking": thinking_cfg,
            "output_config": {"effort": effort},
        }
        if system:
            params["system"] = [{"type": "text", "text": system, **self._cache()}]
        if tools:
            params["tools"] = tools
        return params

    def _prompt_content(self, prompt: str) -> list[dict]:
        static, dynamic = split_static(prompt)
        content = []
        if static:
            content.append({"type": "text", "text": static, **self._cache()})
        content.append({"type": "text", "text": dynamic or "(vuoto)"})
        return content

    def _tools(self, tools: list[dict]) -> list[dict]:
        out = [{
            "name": str(t.get("name", "")).strip(),
            "description": str(t.get("description", "")).strip(),
            "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
        } for t in tools if str(t.get("name", "")).strip()]
        if out and self.config.get("prompt_cache"):
            out[-1]["cache_control"] = _EPHEMERAL
        return out

    def _create(self, params: dict):
        import anthropic

        try:
            response = self.client.messages.create(**params)
        except anthropic.BadRequestError as exc:
            # Some models refuse disabled thinking: retry adaptive at low effort.
            if params["thinking"].get("type") != "disabled" or "thinking" not in str(exc).lower():
                raise
            logger.warning("[🔄] event=anthropic_thinking_disabled_rejected model=%s retry=adaptive_low",
                           params["model"])
            params = {**params, "thinking": {"type": "adaptive", "display": "summarized"},
                      "output_config": {"effort": "low"}}
            response = self.client.messages.create(**params)
        self._log_usage(params["model"], response)
        return response

    @staticmethod
    def _log_usage(model: str, response) -> None:
        usage = getattr(response, "usage", None)
        logger.info(
            "event=anthropic_usage model=%s stop=%s input=%s output=%s cache_read=%s cache_write=%s",
            model, getattr(response, "stop_reason", None), getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None), getattr(usage, "cache_read_input_tokens", None),
            getattr(usage, "cache_creation_input_tokens", None))

    @staticmethod
    def _parse(response) -> tuple[str, str, list[dict]]:
        texts, reasoning, calls = [], [], []
        for block in response.content or []:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "thinking":
                if getattr(block, "thinking", ""):
                    reasoning.append(block.thinking)
            elif block.type == "tool_use":
                calls.append({"name": block.name, "params": dict(block.input or {})})
        if response.stop_reason == "refusal":
            logger.warning("event=anthropic_refusal category=%s",
                           getattr(getattr(response, "stop_details", None), "category", None))
            if not texts:
                texts.append("Non posso aiutarti con questa richiesta.")
        return "".join(texts).strip(), "\n".join(reasoning).strip(), calls

    # ── Calls ─────────────────────────────────────────────────────────────
    def ask(self, model: str, system: str, prompt: str, thinking: Any = None) -> str:
        response = self._create(self._params(model, system, self._prompt_content(prompt), thinking))
        return self._parse(response)[0]

    def ask_with_tools(self, model: str, system: str, prompt: str, tools: list[dict],
                       thinking: Any = None) -> dict:
        params = self._params(model, system, self._prompt_content(prompt), thinking, self._tools(tools))
        text, reasoning, calls = self._parse(self._create(params))
        logger.info("event=anthropic_tool_decision model=%s tool_calls=%s reasoning_len=%d text_len=%d",
                    model, [c["name"] for c in calls], len(reasoning), len(text))
        return tool_result(calls, "" if calls else text, reasoning)

    def ask_stream(self, model: str, system: str, prompt: str, thinking: Any = None) -> Iterator[str]:
        params = self._params(model, system, self._prompt_content(prompt), thinking)
        with self.client.messages.stream(**params) as stream:
            yield from stream.text_stream
            self._log_usage(model, stream.get_final_message())

    def ask_with_attachment(self, model: str, system: str, file_bytes: bytes, mime_type: str,
                            prompt: str, thinking: Any = None) -> str:
        data = base64.standard_b64encode(file_bytes).decode("utf-8")
        if mime_type.startswith("image/"):
            block = {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": data}}
        elif mime_type == "application/pdf":
            block = {"type": "document", "source": {"type": "base64", "media_type": mime_type, "data": data}}
        else:
            return self.ask(model, system, prompt, thinking)
        content = [block, {"type": "text", "text": prompt}]
        return self._parse(self._create(self._params(model, system, content, thinking)))[0]
