"""Provider types dispatched by ``UniversalAgent`` (see ``base.py``).

``ollama`` and ``gemini`` are still implemented inline in ``UniversalAgent``; new types
live here and register in ``PROVIDER_TYPES``.
"""
from __future__ import annotations

from agents.llm_config import load_llm_config
from agents.providers.anthropic_api import AnthropicProvider
from agents.providers.base import LLMProvider
from agents.providers.claude_cli import ClaudeCliProvider

PROVIDER_TYPES: dict[str, type[LLMProvider]] = {
    AnthropicProvider.TYPE: AnthropicProvider,
    ClaudeCliProvider.TYPE: ClaudeCliProvider,
}


def is_provider_type(name: str) -> bool:
    return str(name or "").strip().lower() in PROVIDER_TYPES


def get_provider(name: str) -> LLMProvider:
    """A provider instance built from the current infrastructure config."""
    name = str(name or "").strip().lower()
    return PROVIDER_TYPES[name](load_llm_config().get(name, {}))


def available_types() -> list[tuple[str, str]]:
    """(type, label) of the provider types usable now (key/binary configured)."""
    out = []
    for name, cls in PROVIDER_TYPES.items():
        if get_provider(name).available()[0]:
            out.append((name, cls.LABEL))
    return out
