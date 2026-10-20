"""Provider type ``openai`` — any OpenAI-compatible server: llama.cpp ``llama-server``, vLLM, LM Studio,
DeepSeek, OpenRouter, Groq…  Address and key come from the named provider (setting ``oracle.providers``,
key ``ORACLE_KEY_<NAME>``, optional for local servers).
Prompt cache: the static part of the prompt (before ``SYSTEM_PROMPT_DYNAMIC_BOUNDARY``) goes in the
system message so every request starts with the same prefix; llama-server reuses it with
``cache_prompt`` (setting), vLLM with automatic prefix caching (server flag).
Thinking: ``fast`` sends ``chat_template_kwargs.enable_thinking=false`` (Qwen3-style templates).
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Iterator

import requests

from agents.providers.base import LLMProvider, split_static, think_level, tool_result

logger = logging.getLogger("hestia_oracle.providers.openai")


class OpenAICompatProvider(LLMProvider):
    TYPE = "openai"
    LABEL = "Compatibile OpenAI"
    BILLING = "Server locale · gratis"
    CONFIG_FIELDS = (
        {"key": "base_url", "type": "string", "label": "Indirizzo (…/v1)"},
        {"key": "api_key", "type": "secret_ref", "label": "Chiave API (ORACLE_KEY_<NOME>)"},
        {"key": "cache_prompt", "type": "bool", "label": "Riusa la cache del prompt", "default": True},
        {"key": "timeout_sec", "type": "int", "label": "Timeout (secondi)", "default": 180},
    )
    CAPABILITIES = frozenset({"chat", "tools", "stream", "vision", "embed", "thinking"})

    # ── Introspection ─────────────────────────────────────────────────────
    def available(self) -> tuple[bool, str]:
        if not self.config.get("base_url"):
            return False, "address not set"
        return True, "ok"

    def _url(self, path: str) -> str:
        return f"{str(self.config['base_url']).rstrip('/')}/{path.lstrip('/')}"

    def _headers(self) -> dict:
        key = self.config.get("api_key")
        return {"Authorization": f"Bearer {key}"} if key else {}

    def list_models(self) -> list[str]:
        if not self.available()[0]:
            return []
        try:
            resp = requests.get(self._url("models"), headers=self._headers(), timeout=5)
            resp.raise_for_status()
            return [str(m.get("id")) for m in (resp.json() or {}).get("data") or [] if m.get("id")]
        except Exception as exc:
            logger.warning("[🔄] event=openai_list_models_failed error=%s", exc)
            return []

    # ── Request building ──────────────────────────────────────────────────
    @staticmethod
    def _messages(system: str, prompt: str, user_content: Any = None) -> list[dict]:
        static, dynamic = split_static(prompt)
        system_text = "\n\n".join(p for p in (system, static) if p)
        messages = [{"role": "system", "content": system_text}] if system_text else []
        messages.append({"role": "user", "content": user_content if user_content is not None
                         else (dynamic or prompt or "(vuoto)")})
        return messages

    def _body(self, model: str, messages: list[dict], thinking: Any, **extra) -> dict:
        body: dict[str, Any] = {"model": model, "messages": messages, **extra}
        if self.config.get("cache_prompt"):
            body["cache_prompt"] = True  # llama-server extension; ignored by most other servers
        if think_level(thinking) == "fast":
            body["chat_template_kwargs"] = {"enable_thinking": False}
        return body

    def _post(self, body: dict, stream: bool = False):
        ok, detail = self.available()
        if not ok:
            raise RuntimeError(f"openai provider unavailable: {detail}")
        resp = requests.post(self._url("chat/completions"), json=body, headers=self._headers(),
                             timeout=int(self.config["timeout_sec"]), stream=stream)
        resp.raise_for_status()
        return resp

    def _stats(self, model: str, data: dict) -> None:
        try:
            from core.services import llm_stats
            llm_stats.record_openai(self.label, model, data)
        except Exception as exc:
            logger.debug("event=openai_stats_failed error=%s", exc)

    @staticmethod
    def _message(data: dict) -> dict:
        choices = data.get("choices") or [{}]
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        return msg if isinstance(msg, dict) else {}

    @staticmethod
    def _reasoning(msg: dict) -> str:
        return str(msg.get("reasoning_content") or msg.get("reasoning") or "").strip()

    # ── Calls ─────────────────────────────────────────────────────────────
    def ask(self, model: str, system: str, prompt: str, thinking: Any = None) -> str:
        data = self._post(self._body(model, self._messages(system, prompt), thinking)).json() or {}
        self._stats(model, data)
        return str(self._message(data).get("content") or "").strip()

    def ask_with_tools(self, model: str, system: str, prompt: str, tools: list[dict],
                       thinking: Any = None) -> dict:
        specs = [{
            "type": "function",
            "function": {
                "name": str(t.get("name", "")).strip(),
                "description": str(t.get("description", "")).strip(),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
            },
        } for t in tools if str(t.get("name", "")).strip()]
        body = self._body(model, self._messages(system, prompt), thinking, **({"tools": specs} if specs else {}))
        data = self._post(body).json() or {}
        self._stats(model, data)
        msg = self._message(data)
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except ValueError:
                    args = {}
            calls.append({"name": str(fn.get("name") or ""), "params": dict(args or {})})
        return tool_result(calls, text=str(msg.get("content") or "").strip(), reasoning=self._reasoning(msg))

    def ask_stream(self, model: str, system: str, prompt: str, thinking: Any = None) -> Iterator[str]:
        body = self._body(model, self._messages(system, prompt), thinking, stream=True,
                          stream_options={"include_usage": True})
        with self._post(body, stream=True) as resp:
            for raw in resp.iter_lines():
                line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                except ValueError:
                    continue
                if data.get("usage") or data.get("timings"):
                    self._stats(model, data)
                for choice in data.get("choices") or []:
                    token = ((choice or {}).get("delta") or {}).get("content")
                    if token:
                        yield token

    def ask_with_attachment(self, model: str, system: str, file_bytes: bytes, mime_type: str,
                            prompt: str, thinking: Any = None) -> str:
        if not mime_type.startswith("image/"):
            return super().ask_with_attachment(model, system, file_bytes, mime_type, prompt, thinking)
        url = f"data:{mime_type};base64,{base64.b64encode(file_bytes).decode('ascii')}"
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]
        data = self._post(self._body(model, self._messages(system, "", content), thinking)).json() or {}
        self._stats(model, data)
        return str(self._message(data).get("content") or "").strip()

    def embed(self, model: str, text: str) -> list[float]:
        resp = requests.post(self._url("embeddings"), json={"model": model, "input": text},
                             headers=self._headers(), timeout=int(self.config["timeout_sec"]))
        resp.raise_for_status()
        rows = (resp.json() or {}).get("data") or [{}]
        return list(rows[0].get("embedding") or [])
