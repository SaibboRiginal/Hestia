"""LLM provider base — one class per provider TYPE (central-settings SPEC §3.9 / v2.0).

A provider gets its infrastructure config as a dict (``agents.llm_config.load_llm_config``)
and never reads env itself.  ``UniversalAgent`` dispatches to it by provider type.

Thinking level (from the chat mode): ``False`` (quick) | ``True`` (auto) | ``"deep"``
(thinking).  Each type maps it to its own knob.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Iterator

logger = logging.getLogger("hestia_oracle.providers")

# Field definitions follow central-settings SPEC §3.1 (key, type, label, default, ...).
ConfigField = dict[str, Any]


def think_level(thinking: Any) -> str:
    """Normalize the thinking flag/level to ``fast`` | ``normal`` | ``deep``."""
    if thinking is None or thinking is False:
        return "fast"
    if thinking is True:
        return "normal"
    value = str(thinking).strip().lower()
    if value in ("deep", "thinking", "high"):
        return "deep"
    if value in ("", "false", "off", "quick", "fast", "0"):
        return "fast"
    return "normal"


def split_static(prompt: str) -> tuple[str, str]:
    """Split a composed prompt at the static/dynamic boundary (cache-friendly prefix, rest)."""
    from core.services import prompt_config

    marker = prompt_config._DYNAMIC_BOUNDARY
    if marker and marker in (prompt or ""):
        static, dynamic = prompt.split(marker, 1)
        return static.strip(), dynamic.strip()
    return "", prompt or ""


def tool_result(calls: list[dict] | None = None, text: str = "", reasoning: str = "") -> dict:
    """Standard ``ask_with_tools`` result consumed by ``core.agent_loop``."""
    calls = [c for c in (calls or []) if c.get("name")]
    return {
        "tool_calls": calls,
        "tool_call": calls[0] if calls else None,
        "text": text,
        "reasoning_content": reasoning,
    }


class LLMProvider:
    TYPE: str = ""
    LABEL: str = ""
    CONFIG_FIELDS: tuple[ConfigField, ...] = ()
    CAPABILITIES: frozenset[str] = frozenset()

    def __init__(self, config: dict[str, Any] | None = None):
        self.config: dict[str, Any] = dict(config or {})
        for field in self.CONFIG_FIELDS:
            self.config.setdefault(field["key"], field.get("default"))

    # ── Introspection ─────────────────────────────────────────────────────
    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def list_models(self) -> list[str]:
        return []

    # ── Calls (override what CAPABILITIES declares) ───────────────────────
    def ask(self, model: str, system: str, prompt: str, thinking: Any = None) -> str:
        raise NotImplementedError(f"{self.TYPE}: chat not supported")

    def ask_with_tools(self, model: str, system: str, prompt: str, tools: list[dict],
                       thinking: Any = None) -> dict:
        return tool_result(text=self.ask(model, system, prompt, thinking))

    def ask_stream(self, model: str, system: str, prompt: str, thinking: Any = None) -> Iterator[str]:
        yield self.ask(model, system, prompt, thinking)

    def ask_with_attachment(self, model: str, system: str, file_bytes: bytes, mime_type: str,
                            prompt: str, thinking: Any = None) -> str:
        if mime_type == "application/pdf":
            text = extract_pdf_text(file_bytes)
            prompt = f"[Attached document content]\n{text}\n\n[User instruction]\n{prompt}"
        return self.ask(model, system, prompt, thinking)

    def embed(self, model: str, text: str) -> list[float]:
        raise RuntimeError(f"{self.TYPE}: embeddings not supported")


def extract_pdf_text(file_bytes: bytes) -> str:
    """Plain text of a PDF (pypdf); empty string when scanned/unreadable."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception:
        return ""
