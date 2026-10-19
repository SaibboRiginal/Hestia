"""Provider types dispatched by ``UniversalAgent`` (see ``base.py``).

``ollama`` and ``gemini`` are still implemented inline in ``UniversalAgent``; the other standards
live here and register in ``PROVIDER_TYPES``.  Oracle calls *named* providers
(``core.services.llm_providers``: name → type, address, key ``ORACLE_KEY_<NAME>``); a provider's
config = its address/key + CLI infrastructure (``load_llm_config``) + its type's Themis tunables.
"""
from __future__ import annotations

from agents.providers.anthropic_api import AnthropicProvider
from agents.providers.base import LLMProvider
from agents.providers.claude_cli import ClaudeCliProvider
from agents.providers.openai_compat import OpenAICompatProvider

PROVIDER_TYPES: dict[str, type[LLMProvider]] = {
    AnthropicProvider.TYPE: AnthropicProvider,
    ClaudeCliProvider.TYPE: ClaudeCliProvider,
    OpenAICompatProvider.TYPE: OpenAICompatProvider,
}


def provider_type(name: str) -> str:
    """Type of a named provider (or of a bare type name)."""
    from core.services import llm_providers  # lazy: settings → providers → settings
    return llm_providers.type_of(name)


def is_provider_type(name: str) -> bool:
    """True when *name* (a named provider or a type) is served by a class here, not inline."""
    return provider_type(name) in PROVIDER_TYPES


def get_provider(name: str) -> LLMProvider:
    """A provider instance for a named provider (``deepseek``) or a bare type (``anthropic``)."""
    from core.services import llm_providers
    config = llm_providers.class_config(name)
    return PROVIDER_TYPES[llm_providers.type_of(name)](config)


# Inline types (UniversalAgent): label, context window (0 = local num_ctx setting), billing.
_INLINE = {
    "ollama": ("Ollama (locale)", 0, "Locale · gratis"),
    "gemini": ("Gemini (cloud)", 1_048_576, "API Gemini · a consumo"),
}


def runtime_info(name: str, local_window: int) -> dict:
    """Label, context window and billing kind of a named provider (chat context gauge)."""
    from core.services import llm_providers
    name = str(name or "").strip().lower()
    ptype = llm_providers.type_of(name) or name
    if ptype in PROVIDER_TYPES:
        cls = PROVIDER_TYPES[ptype]
        label, window, billing = cls.LABEL, cls.CONTEXT_WINDOW, cls.BILLING
    else:
        label, window, billing = _INLINE.get(ptype, (name, 0, ""))
    prov = llm_providers.get(name)
    if prov:
        label = prov["label"]
    if ptype == "openai" and not llm_providers.api_key(name):
        billing = "Server locale · gratis"
    elif ptype == "openai":
        billing = "API · a consumo"
    return {"provider": name, "provider_label": label, "context_window": int(window or local_window),
            "billing": billing}
