"""LLM agent factory — model normalisation and UniversalAgent wiring.

Single responsibility: read environment variables, validate model/provider
pairs, and construct the set of UniversalAgent instances used by Oracle.

Consumers receive an AgentBundle dataclass; they do not need to know anything
about env-var names, Gemini model normalisation, or prompt templates.
"""
import logging
import os
from dataclasses import dataclass

from agents.universal_agent import UniversalAgent

logger = logging.getLogger(__name__)

# ── Gemini model normalisation ────────────────────────────────────────────────
# These prefixes identify local / incompatible model names that are sometimes
# accidentally set for Gemini provider — they must be replaced with defaults.
_GEMINI_TEXT_DEFAULT = "gemini-2.5-flash"
_GEMINI_EMBED_DEFAULT = "models/embedding-001"


# ── System prompts ────────────────────────────────────────────────────────────

_ROUTER_PROMPT = """You are a Universal Data Router.
Analyze the user's message and conversation context.

Output ONLY valid JSON with:
1. "domains": array of best matching domains. For general chat use ["general"].
2. "filters": exact-match hints dictionary (or {}).
3. "filters_gt": numerical "greater than" constraints dictionary (or {}).
4. "filters_lt": numerical "less than" constraints dictionary (or {}).
5. "sort_by": sort field or null.
6. "sort_order": "asc" or "desc".
"""

_SCRIBE_PROMPT = """You are Hestia's Memory Manager.
Infer enduring user facts/preferences from natural language context.

Do NOT rely on explicit trigger words. Infer intent semantically.
If user asks to forget/reset memory (explicitly or implicitly), output DEPRECATE actions for all active preference IDs.
Output ONLY valid JSON array or NONE.
"""

_CONVERSATION_STYLE_CONTRACT = """
CONVERSATION STYLE CONTRACT (MANDATORY):
- The reply must feel like an ongoing chat, not a ticket closure.
- Never end with generic assistant closure lines in any language (examples: "Fammi sapere...", "Se in futuro...", "If you need anything else...", "Let me know if...").
- End directly on useful content (fact, answer, suggestion, or next concrete step), without ritual outro.
- Keep tone personal, natural, and context-aware.
""".strip()

_ANALYST_PROMPT = f"""Sei Hestia, assistente IA universale.

REGOLE CORE:
1. Rispondi nella lingua dell'utente.
2. Usa CONTEXT_DATA_RECORDS solo se pertinente.
3. Applica sempre USER_PREFERENCES.
4. Se i record sono molti, sintetizza e mostra solo i migliori risultati.
5. Puoi attivare notifiche proattive: quando l'utente chiede avvisi/notifiche automatiche, conferma che Hestia può salvarle come sottoscrizioni e inviare alert via Hermes (non dire che non puoi farlo).

FORMATTAZIONE:
- Solo Markdown.
- Usa elenchi puntati e grassetto per chiarezza.
- Se un record contiene URL/link, includilo quando utile.
- LINK POLICY: Per OGNI link/URL, usa SEMPRE il titolo o una descrizione significativa dell'elemento come testo del link.
  ESEMPI CORRETTI: [Appartamento 3 camere via Roma](URL), [Villa con giardino](URL), [Casa luminosa centro](URL)
  MAI USARE: "Apri annuncio", "Clicca qui", "Link", "URL", "Vedi qui" o altri testi generici.
- Non mostrare URL lunghi in chiaro.

STILE FINALE:
{_CONVERSATION_STYLE_CONTRACT}
"""


@dataclass
class AgentBundle:
    """All LLM agents used by Oracle, fully initialised and ready to use."""

    router: UniversalAgent
    fallback_router: UniversalAgent
    scribe: UniversalAgent
    fallback_scribe: UniversalAgent
    analyst: UniversalAgent
    fallback_analyst: UniversalAgent
    embedder: UniversalAgent
    fallback_embedder: UniversalAgent

    # Convenience: expose analyst model name for capability detection
    @property
    def analyst_model_name(self) -> str:
        return self.analyst.model_name or ""


class AgentFactory:
    """Reads configuration from environment and constructs an AgentBundle."""

    @staticmethod
    def create() -> AgentBundle:
        """Build and return the full set of Oracle agents from env vars."""
        models = AgentFactory._read_model_config()
        AgentFactory._normalize_gemini_models(models)
        AgentFactory._log_config(models)
        return AgentFactory._build_bundle(models)

    # ── Configuration reading ─────────────────────────────────────────────────

    @staticmethod
    def _read_model_config() -> dict[str, dict[str, str]]:
        e = os.getenv
        return {
            "router":            {"prov": e("ROUTER_PROVIDER", "gemini"),           "mod": e("ROUTER_MODEL", "gemma-3-12b-it")},
            "scribe":            {"prov": e("SCRIBE_PROVIDER",  e("FALLBACK_ANALYST_PROVIDER", e("ROUTER_PROVIDER", "ollama"))),
                                  "mod":  e("SCRIBE_MODEL",     e("FALLBACK_ANALYST_MODEL",    e("ROUTER_MODEL", "qwen2.5:7b")))},
            "analyst":           {"prov": e("ANALYST_PROVIDER", "gemini"),           "mod": e("ANALYST_MODEL", "gemma-3-27b-it")},
            "embedder":          {"prov": e("EMBEDDING_PROVIDER", "ollama"),         "mod": e("EMBEDDING_MODEL", "nomic-embed-text")},
            "fallback_router":   {"prov": e("FALLBACK_ROUTER_PROVIDER", "ollama"),   "mod": e("FALLBACK_ROUTER_MODEL", "mistral:7b")},
            "fallback_scribe":   {"prov": e("FALLBACK_SCRIBE_PROVIDER",  e("SCRIBE_PROVIDER", e("FALLBACK_ROUTER_PROVIDER", "ollama"))),
                                  "mod":  e("FALLBACK_SCRIBE_MODEL",     e("SCRIBE_MODEL",    e("FALLBACK_ROUTER_MODEL", "mistral:7b")))},
            "fallback_analyst":  {"prov": e("FALLBACK_ANALYST_PROVIDER", "ollama"),  "mod": e("FALLBACK_ANALYST_MODEL", "mistral:7b")},
            "fallback_embedder": {"prov": e("FALLBACK_EMBEDDING_PROVIDER", "gemini"), "mod": e("FALLBACK_EMBEDDING_MODEL", "models/embedding-001")},
        }

    @staticmethod
    def _normalize_gemini_models(models: dict[str, dict[str, str]]) -> None:
        """Replace invalid Gemini model names with safe defaults (in-place)."""
        for key, cfg in models.items():
            if str(cfg.get("prov", "")).strip().lower() != "gemini":
                continue
            name = str(cfg.get("mod", "")).strip()
            lower = name.lower()
            is_invalid = lower.startswith("gemma") or ":" in lower
            if not is_invalid:
                continue
            replacement = _GEMINI_EMBED_DEFAULT if "embed" in key else _GEMINI_TEXT_DEFAULT
            logger.warning(
                "Invalid Gemini model for %s: '%s'. Auto-switching to '%s'.",
                key, name, replacement,
            )
            cfg["mod"] = replacement

    @staticmethod
    def _log_config(models: dict[str, dict[str, str]]) -> None:
        logger.info(
            "Oracle agents | router=%s scribe=%s analyst=%s embedder=%s",
            models["router"]["mod"], models["scribe"]["mod"],
            models["analyst"]["mod"], models["embedder"]["mod"],
        )
        print(
            f"🧠 Oracle Init | Router: {models['router']['mod']} | "
            f"Scribe: {models['scribe']['mod']} | Analyst: {models['analyst']['mod']} | "
            f"Embedder: {models['embedder']['mod']}"
        )

    @staticmethod
    def _build_bundle(models: dict[str, dict[str, str]]) -> AgentBundle:
        def _agent(key: str, prompt: str) -> UniversalAgent:
            return UniversalAgent(
                role_prompt=prompt,
                provider=models[key]["prov"],
                model_name=models[key]["mod"],
            )

        return AgentBundle(
            router=_agent("router", _ROUTER_PROMPT),
            fallback_router=_agent("fallback_router", _ROUTER_PROMPT),
            scribe=_agent("scribe", _SCRIBE_PROMPT),
            fallback_scribe=_agent("fallback_scribe", _SCRIBE_PROMPT),
            analyst=_agent("analyst", _ANALYST_PROMPT),
            fallback_analyst=_agent("fallback_analyst", _ANALYST_PROMPT),
            embedder=_agent("embedder", ""),
            fallback_embedder=_agent("fallback_embedder", ""),
        )


def conversation_style_contract() -> str:
    """Return the mandatory conversation-style contract snippet for prompt injection."""
    return _CONVERSATION_STYLE_CONTRACT
