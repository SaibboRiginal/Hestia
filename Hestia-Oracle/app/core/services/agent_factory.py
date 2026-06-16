"""LLM agent factory — use-case model config and UniversalAgent wiring.

Single responsibility: read USE-CASE environment variables, validate
model/provider pairs, and construct UniversalAgent instances used by Oracle.

Four use cases — each with primary + fallback:
  generic   → chat, classify, tool selection, memory extraction, formatting
  reasoning → deep thinking, complex multi-step analysis (loaded on demand)
  code      → code generation, debugging, technical tasks
  embedding → vector embeddings (must output 768-dim vectors)

Consumers receive an AgentBundle dataclass keyed by use case.
Mode (quick/auto/thinking) controls orchestration; use case controls which brain.
"""
import logging
import os
from dataclasses import dataclass

from agents.universal_agent import UniversalAgent
from core.services import prompt_config

logger = logging.getLogger(f"hestia_oracle.{__name__}")

# ── System prompts ────────────────────────────────────────────────────────────

_GENERIC_SYSTEM_PROMPT = os.getenv(
    "HESTIA_PERSONA", prompt_config.analyst_persona_default())
_CODE_SYSTEM_PROMPT = (
    "You are an expert software engineer. Output clean, correct, well-structured code. "
    "Think before writing. Explain your approach briefly, then provide the implementation."
)


@dataclass
class AgentBundle:
    """LLM agents keyed by USE CASE, not internal role name.

    generic   → daily driver: chat, classify, tool selection, memory, formatting
    reasoning → heavy lifter: deep thinking, complex analysis (loaded on demand)
    code      → specialist: code generation, debugging, technical tasks
    embedding → vector embeddings (tiny model, always loaded, 768-dim output)
    """

    generic: UniversalAgent
    generic_fallback: UniversalAgent
    reasoning: UniversalAgent
    reasoning_fallback: UniversalAgent
    code: UniversalAgent
    code_fallback: UniversalAgent
    embedding: UniversalAgent
    embedding_fallback: UniversalAgent

    @property
    def generic_model_name(self) -> str:
        return self.generic.model_name or ""


class AgentFactory:
    """Reads MODEL_USECASE_* environment variables and constructs an AgentBundle."""

    # ── Use-case defaults (provider, model) ──────────────────────────────────
    _DEFAULTS: dict[str, tuple[str, str]] = {
        "generic":   ("ollama", "gemma4:e4b"),
        "reasoning": ("ollama", "gemma-4-26B-A4B-it-UD-IQ4_NL:latest"),
        "code":      ("ollama", "gemma4:e4b"),
        "embedding": ("ollama", "nomic-embed-text"),
    }

    @staticmethod
    def create() -> AgentBundle:
        cfg = AgentFactory._read_config()
        AgentFactory._normalize_gemini_models(cfg)
        AgentFactory._remap_gemini_when_no_api_key(cfg)
        AgentFactory._log_config(cfg)
        return AgentFactory._build_bundle(cfg)

    # ── Config reading ──────────────────────────────────────────────────────

    @staticmethod
    def _read_config() -> dict[str, dict[str, str]]:
        """Read MODEL_USECASE_<USECASE>_{PROVIDER,MODEL,FALLBACK_PROVIDER,FALLBACK_MODEL}."""
        result: dict[str, dict[str, str]] = {}
        for usecase, (def_prov, def_mod) in AgentFactory._DEFAULTS.items():
            prefix = f"MODEL_USECASE_{usecase.upper()}"
            result[usecase] = {
                "prov": os.getenv(f"{prefix}_PROVIDER", def_prov),
                "mod":  os.getenv(f"{prefix}_MODEL", def_mod),
            }
            result[f"{usecase}_fallback"] = {
                "prov": os.getenv(f"{prefix}_FALLBACK_PROVIDER", "gemini"),
                "mod":  os.getenv(f"{prefix}_FALLBACK_MODEL", _fallback_model_for(usecase)),
            }
        return result

    # ── Gemini model name validation ─────────────────────────────────────────

    _GEMINI_TEXT_DEFAULT = "gemini-2.5-flash"
    _GEMINI_EMBED_DEFAULT = "models/embedding-001"

    @staticmethod
    def _normalize_gemini_models(cfg: dict[str, dict[str, str]]) -> None:
        """Replace invalid Gemini model names with safe defaults."""
        for key, entry in cfg.items():
            if str(entry.get("prov", "")).strip().lower() != "gemini":
                continue
            name = str(entry.get("mod", "")).strip()
            lower = name.lower()
            if not (lower.startswith("gemma") or ":" in lower):
                continue
            replacement = (
                AgentFactory._GEMINI_EMBED_DEFAULT if "embed" in key
                else AgentFactory._GEMINI_TEXT_DEFAULT
            )
            logger.warning(
                "event=invalid_gemini_model_switching key=%s from=%s to=%s",
                key, name, replacement,
            )
            entry["mod"] = replacement

    # ── Gemini → Ollama fallback when no API key ─────────────────────────────

    @staticmethod
    def _remap_gemini_when_no_api_key(cfg: dict[str, dict[str, str]]) -> None:
        api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
        if api_key:
            return
        for key, entry in cfg.items():
            if str(entry.get("prov", "")).strip().lower() != "gemini":
                continue
            if "embed" in key:
                fb = "nomic-embed-text"
            elif "code" in key:
                fb = "qwen2.5-coder:7b"
            else:
                fb = "qwen2.5:7b"
            logger.warning(
                "event=gemini_key_missing_remapping key=%s from=%s to=ollama/%s",
                key, entry.get("mod", ""), fb,
            )
            entry["prov"] = "ollama"
            entry["mod"] = fb

    # ── Build ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_bundle(cfg: dict[str, dict[str, str]]) -> AgentBundle:
        def _make(key: str, prompt: str, thinking: bool = True) -> UniversalAgent:
            return UniversalAgent(
                role_prompt=prompt,
                provider=cfg[key]["prov"],
                model_name=cfg[key]["mod"],
                thinking=thinking,
            )

        return AgentBundle(
            generic=_make("generic", _GENERIC_SYSTEM_PROMPT),
            generic_fallback=_make("generic_fallback", _GENERIC_SYSTEM_PROMPT),
            reasoning=_make("reasoning", _GENERIC_SYSTEM_PROMPT),
            reasoning_fallback=_make("reasoning_fallback", _GENERIC_SYSTEM_PROMPT),
            code=_make("code", _CODE_SYSTEM_PROMPT),
            code_fallback=_make("code_fallback", _CODE_SYSTEM_PROMPT),
            embedding=_make("embedding", ""),
            embedding_fallback=_make("embedding_fallback", ""),
        )

    # ── Logging ──────────────────────────────────────────────────────────────

    @staticmethod
    def _log_config(cfg: dict[str, dict[str, str]]) -> None:
        logger.info(
            "event=oracle_agents_configured "
            "generic=%s reasoning=%s code=%s embedding=%s",
            cfg["generic"]["mod"],
            cfg["reasoning"]["mod"],
            cfg["code"]["mod"],
            cfg["embedding"]["mod"],
        )


def _fallback_model_for(usecase: str) -> str:
    """Return sensible Gemini fallback model per use case."""
    if usecase == "embedding":
        return "gemini-embedding-001"
    if usecase == "reasoning":
        return "gemini-2.5-flash"
    return "gemini-2.0-flash-lite"


def conversation_style_contract() -> str:
    """Return the mandatory conversation-style contract for prompt injection."""
    return prompt_config.conversation_style_contract()
