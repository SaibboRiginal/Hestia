"""Provider types dispatched by ``UniversalAgent`` (see ``base.py``).

``ollama`` and ``gemini`` are still implemented inline in ``UniversalAgent``; new types
live here and register in ``PROVIDER_TYPES``.  A type's config = infrastructure from
``load_llm_config()`` (env) + its tunables from Themis (``oracle_settings.provider_settings``).
"""
from __future__ import annotations

from agents.llm_config import load_llm_config
from agents.providers.anthropic_api import AnthropicProvider
from agents.providers.base import LLMProvider
from agents.providers.claude_cli import ClaudeCliProvider
from agents.providers.openai_compat import OpenAICompatProvider

PROVIDER_TYPES: dict[str, type[LLMProvider]] = {
    AnthropicProvider.TYPE: AnthropicProvider,
    ClaudeCliProvider.TYPE: ClaudeCliProvider,
    OpenAICompatProvider.TYPE: OpenAICompatProvider,
}


def is_provider_type(name: str) -> bool:
    return str(name or "").strip().lower() in PROVIDER_TYPES


def get_provider(name: str) -> LLMProvider:
    """A provider instance built from the current infrastructure config."""
    name = str(name or "").strip().lower()
    config = dict(load_llm_config().get(name, {}))
    try:
        from core.services import oracle_settings  # lazy: oracle_settings imports this module
        config.update(oracle_settings.provider_settings(name))
    except Exception:  # settings not importable yet (module import time): type defaults apply
        pass
    return PROVIDER_TYPES[name](config)


def available_types() -> list[tuple[str, str]]:
    """(type, label) of the provider types usable now (key/binary configured)."""
    out = []
    for name, cls in PROVIDER_TYPES.items():
        if get_provider(name).available()[0]:
            out.append((name, cls.LABEL))
    return out


# Inline types (UniversalAgent): label, context window (0 = local num_ctx setting), billing.
_INLINE = {
    "ollama": ("Ollama (locale)", 0, "Locale · gratis"),
    "gemini": ("Gemini (cloud)", 1_048_576, "API Gemini · a consumo"),
}


def runtime_info(name: str, local_window: int) -> dict:
    """Label, context window and billing kind of a provider type (chat context gauge)."""
    name = str(name or "").strip().lower()
    if name in PROVIDER_TYPES:
        cls = PROVIDER_TYPES[name]
        label, window, billing = cls.LABEL, cls.CONTEXT_WINDOW, cls.BILLING
    else:
        label, window, billing = _INLINE.get(name, (name, 0, ""))
    return {"provider": name, "provider_label": label, "context_window": int(window or local_window),
            "billing": billing}
