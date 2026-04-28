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
- NEVER end with generic assistant closure lines in any language (examples: "Fammi sapere...", "Se in futuro...", "If you need anything else...", "Let me know if...", "Posso aiutarti con altro?", "Hai altri dubbi?").
- NEVER offer help with topics or tasks not mentioned in the current user message.
- NEVER ask follow-up questions or propose alternatives unless the user's request is genuinely ambiguous.
- End directly on useful content (fact, answer, confirmation, or concrete next step), without ritual outro.
- Keep tone personal, natural, and context-aware.
- Reply ONLY to what was asked. Do not introduce related subjects unprompted.
""".strip()

_ANALYST_PROMPT_DEFAULT = f"""Sei Hestia, assistente IA universale.

REGOLE CORE:
1. Rispondi nella lingua dell'utente.
2. Usa CONTEXT_DATA_RECORDS solo se pertinente.
3. Applica sempre USER_PREFERENCES.
4. Se i record sono molti, sintetizza e mostra solo i migliori risultati.
5. Puoi attivare notifiche proattive: quando l'utente chiede avvisi/notifiche automatiche, conferma che Hestia può salvarle come sottoscrizioni e inviare alert via Hermes (non dire che non puoi farlo).

FORMATTAZIONE HTML TELEGRAM (OBBLIGATORIA):
- Usa <b>testo</b> per grassetto, <i>testo</i> per corsivo.
- Usa <a href="url">testo</a> per link — usa SEMPRE il titolo o una descrizione significativa come testo del link, MAI "Apri annuncio", "Clicca qui", "Link" o testi generici.
- Per liste usa il simbolo \u2022 direttamente (MAI trattini - o asterischi * come marcatori di lista).
- MAI usare sintassi Markdown (**testo**, _testo_, ##, [testo](url), * testo, - testo come lista).
- Non mostrare URL lunghi in chiaro.

STILE FINALE:
{_CONVERSATION_STYLE_CONTRACT}
"""

_ANALYST_PROMPT = os.getenv("HESTIA_PERSONA", _ANALYST_PROMPT_DEFAULT)


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
    coder: UniversalAgent
    fallback_coder: UniversalAgent

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
        AgentFactory._fallback_if_gemini_unconfigured(models)
        AgentFactory._log_config(models)
        return AgentFactory._build_bundle(models)

    # ── Configuration reading ─────────────────────────────────────────────────

    @staticmethod
    def _read_model_config() -> dict[str, dict[str, str]]:
        e = os.getenv

        # ── New MODEL_CLASS_* vars (take precedence when set) ─────────────────
        # Class → role mapping:
        #   fast_chat  → used for quick responses, action selection, memory scribe
        #   planner    → route classification / intent planning
        #   analyst    → deep reasoning, domain synthesis (primary LLM)
        #   formatter  → payload-to-text formatting
        #   coder      → Hephaestus executor (code gen / bugfix)
        # Fallback chain: MODEL_CLASS_<CLASS>_PRIMARY → legacy per-role env var → hard default

        def _class_prov(cls: str, legacy_env: str, default: str) -> str:
            return e(f"MODEL_CLASS_{cls.upper()}_PROVIDER") or e(f"MODEL_CLASS_{cls.upper()}_PRIMARY_PROVIDER") or e(legacy_env, default)

        def _class_mod(cls: str, legacy_env: str, default: str) -> str:
            return e(f"MODEL_CLASS_{cls.upper()}_MODEL") or e(f"MODEL_CLASS_{cls.upper()}_PRIMARY_MODEL") or e(legacy_env, default)

        def _class_fb_prov(cls: str, legacy_env: str, default: str) -> str:
            return e(f"MODEL_CLASS_{cls.upper()}_FALLBACK_PROVIDER") or e(legacy_env, default)

        def _class_fb_mod(cls: str, legacy_env: str, default: str) -> str:
            return e(f"MODEL_CLASS_{cls.upper()}_FALLBACK_MODEL") or e(legacy_env, default)

        return {
            # planner ≈ old router: intent/domain classification
            "router": {
                "prov": _class_prov("planner", "ROUTER_PROVIDER", "gemini"),
                "mod":  _class_mod("planner", "ROUTER_MODEL", "gemma-3-12b-it"),
            },
            "fallback_router": {
                "prov": _class_fb_prov("planner", "FALLBACK_ROUTER_PROVIDER", "ollama"),
                "mod":  _class_fb_mod("planner", "FALLBACK_ROUTER_MODEL", "mistral:7b"),
            },
            # fast_chat ≈ old scribe: quick tasks, memory parsing, action selection
            "scribe": {
                "prov": _class_prov("fast_chat", "SCRIBE_PROVIDER",
                                    e("FALLBACK_ANALYST_PROVIDER", e("ROUTER_PROVIDER", "ollama"))),
                "mod":  _class_mod("fast_chat", "SCRIBE_MODEL",
                                   e("FALLBACK_ANALYST_MODEL", e("ROUTER_MODEL", "qwen2.5:7b"))),
            },
            "fallback_scribe": {
                "prov": _class_fb_prov("fast_chat", "FALLBACK_SCRIBE_PROVIDER",
                                       e("SCRIBE_PROVIDER", e("FALLBACK_ROUTER_PROVIDER", "ollama"))),
                "mod":  _class_fb_mod("fast_chat", "FALLBACK_SCRIBE_MODEL",
                                      e("SCRIBE_MODEL", e("FALLBACK_ROUTER_MODEL", "mistral:7b"))),
            },
            # analyst: deep reasoning / domain synthesis (primary LLM)
            "analyst": {
                "prov": _class_prov("analyst", "ANALYST_PROVIDER", "gemini"),
                "mod":  _class_mod("analyst", "ANALYST_MODEL", "gemma-3-27b-it"),
            },
            "fallback_analyst": {
                "prov": _class_fb_prov("analyst", "FALLBACK_ANALYST_PROVIDER", "ollama"),
                "mod":  _class_fb_mod("analyst", "FALLBACK_ANALYST_MODEL", "mistral:7b"),
            },
            # embedder: vector embedding
            "embedder": {
                "prov": _class_prov("embedder", "EMBEDDING_PROVIDER", "ollama"),
                "mod":  _class_mod("embedder", "EMBEDDING_MODEL", "nomic-embed-text"),
            },
            "fallback_embedder": {
                "prov": _class_fb_prov("embedder", "FALLBACK_EMBEDDING_PROVIDER", "gemini"),
                "mod":  _class_fb_mod("embedder", "FALLBACK_EMBEDDING_MODEL", "models/embedding-001"),
            },
            # coder: used by Hephaestus executor (code gen / bugfix)
            "coder": {
                "prov": _class_prov("coder", "CODER_PROVIDER",
                                    e("FALLBACK_ANALYST_PROVIDER", "ollama")),
                "mod":  _class_mod("coder", "CODER_MODEL",
                                   e("FALLBACK_ANALYST_MODEL", "qwen2.5-coder:7b")),
            },
            "fallback_coder": {
                "prov": _class_fb_prov("coder", "FALLBACK_CODER_PROVIDER",
                                       e("FALLBACK_ANALYST_PROVIDER", "ollama")),
                "mod":  _class_fb_mod("coder", "FALLBACK_CODER_MODEL",
                                      e("FALLBACK_ANALYST_MODEL", "mistral:7b")),
            },
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
    def _fallback_if_gemini_unconfigured(models: dict[str, dict[str, str]]) -> None:
        """When no Gemini API key is present, remap Gemini providers to Ollama.

        This keeps local/dev startup resilient instead of failing fast during
        OracleEngine initialisation.
        """
        api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
        if api_key:
            return

        for key, cfg in models.items():
            provider = str(cfg.get("prov", "")).strip().lower()
            if provider != "gemini":
                continue

            if "embed" in key:
                fallback_model = "nomic-embed-text"
            elif "coder" in key:
                fallback_model = "qwen2.5-coder:7b"
            else:
                fallback_model = "qwen2.5:7b"

            logger.warning(
                "Gemini API key missing; remapping %s from gemini/%s to ollama/%s.",
                key,
                cfg.get("mod", ""),
                fallback_model,
            )
            cfg["prov"] = "ollama"
            cfg["mod"] = fallback_model

    @staticmethod
    def _log_config(models: dict[str, dict[str, str]]) -> None:
        logger.info(
            "Oracle agents | planner=%s fast_chat=%s analyst=%s embedder=%s coder=%s",
            models["router"]["mod"], models["scribe"]["mod"],
            models["analyst"]["mod"], models["embedder"]["mod"],
            models["coder"]["mod"],
        )
        print(
            f"🧠 Oracle Init | Planner: {models['router']['mod']} | "
            f"FastChat: {models['scribe']['mod']} | Analyst: {models['analyst']['mod']} | "
            f"Embedder: {models['embedder']['mod']} | Coder: {models['coder']['mod']}"
        )

    @staticmethod
    def _build_bundle(models: dict[str, dict[str, str]]) -> AgentBundle:
        def _agent(key: str, prompt: str, thinking: bool = True) -> UniversalAgent:
            return UniversalAgent(
                role_prompt=prompt,
                provider=models[key]["prov"],
                model_name=models[key]["mod"],
                thinking=thinking,
            )

        return AgentBundle(
            router=_agent("router", _ROUTER_PROMPT, thinking=False),
            fallback_router=_agent(
                "fallback_router", _ROUTER_PROMPT, thinking=False),
            scribe=_agent("scribe", _SCRIBE_PROMPT, thinking=False),
            fallback_scribe=_agent(
                "fallback_scribe", _SCRIBE_PROMPT, thinking=False),
            analyst=_agent("analyst", _ANALYST_PROMPT),
            fallback_analyst=_agent("fallback_analyst", _ANALYST_PROMPT),
            embedder=_agent("embedder", ""),
            fallback_embedder=_agent("fallback_embedder", ""),
            coder=_agent(
                "coder", "You are an expert software engineer. Output clean, correct code.", thinking=True),
            fallback_coder=_agent(
                "fallback_coder", "You are an expert software engineer. Output clean, correct code.", thinking=True),
        )


def conversation_style_contract() -> str:
    """Return the mandatory conversation-style contract snippet for prompt injection."""
    return _CONVERSATION_STYLE_CONTRACT
