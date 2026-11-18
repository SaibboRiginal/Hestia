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
from agents.providers.llamacpp import LlamaCppProvider
from agents.providers.openai_compat import OpenAICompatProvider
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

PROVIDER_TYPES: dict[str, type[LLMProvider]] = {
    AnthropicProvider.TYPE: AnthropicProvider,
    ClaudeCliProvider.TYPE: ClaudeCliProvider,
    OpenAICompatProvider.TYPE: OpenAICompatProvider,
    LlamaCppProvider.TYPE: LlamaCppProvider,
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
    "ollama": ("Ollama (local)", 0, "Local · free"),
    "gemini": ("Gemini (cloud)", 1_048_576, "Gemini API · pay per use"),
}


def runtime_info(name: str, local_window: int = 0, model: str = "") -> dict:
    """Label, context window (with where it comes from) and billing kind of a named provider (chat context
    gauge, budget and compaction). The window is read from the provider itself, never set in Hestia:
    ``window_source`` = ``runtime`` (read from the local program) · ``service`` (declared by the cloud service) ·
    ``floor`` (the local program's own is too small) · ``provider`` (the service does not declare it: the usual
    value of its type) · ``default`` (not read yet: *local_window*, else the floor)."""
    from core.services import llm_providers
    from core.services import local_window as _lw
    name = str(name or "").strip().lower()
    ptype = llm_providers.type_of(name) or name
    if ptype in PROVIDER_TYPES:
        cls = PROVIDER_TYPES[ptype]
        label, usual, billing = cls.LABEL, cls.CONTEXT_WINDOW, cls.BILLING
    else:
        label, usual, billing = _INLINE.get(ptype, (name, 0, ""))
    prov = llm_providers.get(name)
    if prov:
        label = prov["label"]
    if ptype in ("openai", "llamacpp") and not llm_providers.api_key(name):
        billing = tr("Local server · free")
    elif ptype == "openai":
        billing = tr("API · pay per use")
    window, source = _lw.window_of(name, model)
    if not window and usual:
        window, source = usual, "provider"
    if not window:
        window, source = (local_window or _lw.FLOOR), "default"
    return {"provider": name, "provider_label": label, "context_window": int(window), "window_source": source,
            "billing": billing}


def model_window(provider: str, model: str = "") -> int:
    """Context window (tokens) of one model, read from its provider: the same answer for the chat, the module
    agents and every loop (``run_agent_loop(context_window=…)``)."""
    try:
        return int(runtime_info(provider, 0, model)["context_window"])
    except Exception:
        from core.services import local_window as _lw
        return _lw.FLOOR
