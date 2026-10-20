"""One-time migration of the old per-use-case model settings (``oracle.models.*``, before 2026-10-19) into
chains + use case overrides (dossier ``2026-10-19-oracle-a-blocchi``).

Runs when settings load: only if Marko changed an old value and neither ``oracle.chains`` nor
``oracle.usecases`` was stored yet (so it runs once). Each changed use case becomes a chain
``<use case>-personale`` = [primary, fallback] and the use case points to it. The old rows stay in Archive
(Themis cannot delete undeclared keys) and are ignored from then on.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("hestia_oracle.llm_migration")

# Old defaults (2026-10-18): use case → (provider, model, fallback provider, fallback model, thinking)
_OLD = {
    "generic": ("ollama", "gemma4:e4b", "gemini", "gemini-2.0-flash-lite", "auto"),
    "reasoning": ("ollama", "gemma4:e4b", "gemini", "gemini-2.5-flash", "true"),
    "code": ("ollama", "gemma4:e4b", "gemini", "gemini-2.0-flash", "auto"),
    "embedding": ("ollama", "qwen3-embedding:0.6b", "gemini", "gemini-embedding-001", ""),
    "scout_extraction": ("gemini", "gemini-2.5-flash", "gemini", "gemini-2.5-flash-lite", ""),
    "athena_strategist": ("", "", "", "", ""),
    "athena_auditor": ("", "", "", "", ""),
}
_NEW_ID = {"generic": "oracle.generale", "reasoning": "oracle.ragionamento", "code": "oracle.codice",
           "embedding": "oracle.embedding", "scout_extraction": "scout.annunci",
           "athena_strategist": "athena.strategia", "athena_auditor": "athena.revisione"}
# Old provider TYPES → default named providers.
_PROVIDER_NAME = {"ollama": "ollama", "gemini": "gemini", "anthropic": "claude-api", "claude_cli": "claude",
                  "openai": "llamacpp"}


def plan(orphans: dict) -> tuple[dict, dict]:
    """(new chains, use case overrides) from the old stored values; empty when nothing was changed."""
    chains: dict[str, dict] = {}
    usecases: dict[str, dict] = {}
    for uc, (prov, model, fb_prov, fb_model, thinking) in _OLD.items():
        def old(field: str, default: str) -> str:
            return str(orphans.get(f"oracle.models.{uc}.{field}", default) or "").strip()
        cur = (old("provider", prov), old("model", model), old("fallback_provider", fb_prov),
               old("fallback_model", fb_model))
        new_id = _NEW_ID[uc]
        if cur != (prov, model, fb_prov, fb_model) and cur[0] and cur[1]:
            steps = [{"provider": _PROVIDER_NAME.get(cur[0], cur[0]), "model": cur[1]}]
            if cur[2] and cur[3] and uc != "embedding" and (cur[2], cur[3]) != cur[:2]:
                steps.append({"provider": _PROVIDER_NAME.get(cur[2], cur[2]), "model": cur[3]})
            name = f"{new_id.split('.', 1)[1]}-personale"
            if uc == "embedding":
                name = "embedding"
            chains[name] = {"label": f"{name.replace('-', ' ').capitalize()}", "steps": steps}
            usecases.setdefault(new_id, {})["chain"] = name
        old_thinking = old("thinking", thinking)
        if thinking and old_thinking and old_thinking != thinking:
            usecases.setdefault(new_id, {})["thinking"] = old_thinking
    return chains, usecases


def run(settings) -> bool:
    """Apply the migration once (see module doc). True when something was written."""
    from core.services import llm_chains, oracle_settings
    orphans = {k: v for k, v in settings.orphans().items() if k.startswith("oracle.models.")}
    stored = settings.stored()
    if not orphans or oracle_settings.CHAINS_KEY in stored or oracle_settings.USECASES_KEY in stored:
        return False
    chains, usecases = plan(orphans)
    if not chains and not usecases:
        return False
    merged = {**llm_chains.DEFAULT_CHAINS, **chains}
    ok = settings.put(oracle_settings.CHAINS_KEY, merged, actor="oracle", reason="migrazione oracle.models.*")
    ok = settings.put(oracle_settings.USECASES_KEY, usecases, actor="oracle",
                      reason="migrazione oracle.models.*") and ok
    logger.info("event=oracle_models_migrated chains=%s usecases=%s ok=%s", ",".join(chains) or "-",
                ",".join(usecases) or "-", ok)
    return ok
