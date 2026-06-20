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

import requests

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
    """Reads MODEL_USECASE_* environment variables and constructs an AgentBundle.

    Every model name comes from env vars — NO hardcoded models (Rulebook 1.4).
    """

    # Four architectural use cases.  The MODEL for each comes from env vars.
    _USECASES: tuple[str, ...] = ("generic", "reasoning", "code", "embedding")

    # Thinking-auto-detection family set — configurable, not hardcoded.
    _THINKING_FAMILIES: frozenset[str] = frozenset(
        f.strip().lower() for f in os.getenv(
            "ORACLE_THINKING_FAMILIES",
            "gemma4,gemma3,gemma,qwen3,deepseek-r1,llama4,phi4,llama,llama2,llama3",
        ).split(",") if f.strip()
    )

    # Per-model cache: model_name → bool
    _thinking_cache: dict[str, bool] = {}

    @staticmethod
    def create() -> AgentBundle:
        cfg = AgentFactory._read_config()
        AgentFactory._validate_config(cfg)
        AgentFactory._normalize_gemini_models(cfg)
        AgentFactory._remap_gemini_when_no_api_key(cfg)
        AgentFactory._resolve_thinking_flags(cfg)
        AgentFactory._log_config(cfg)
        return AgentFactory._build_bundle(cfg)

    # ── Config reading ──────────────────────────────────────────────────────

    @staticmethod
    def _read_config() -> dict[str, dict[str, str]]:
        """Read MODEL_USECASE_<USECASE>_{PROVIDER,MODEL,THINKING,FALLBACK_*}."""
        result: dict[str, dict[str, str]] = {}
        for usecase in AgentFactory._USECASES:
            prefix = f"MODEL_USECASE_{usecase.upper()}"
            # THINKING: "true" / "false" / "auto" (default: auto)
            thinking_default = "true" if usecase == "reasoning" else "auto"
            result[usecase] = {
                "prov": os.getenv(f"{prefix}_PROVIDER", "ollama"),
                "mod":  os.getenv(f"{prefix}_MODEL", "").strip(),
                "thinking_raw": os.getenv(
                    f"{prefix}_THINKING", thinking_default).strip().lower(),
            }
            result[f"{usecase}_fallback"] = {
                "prov": os.getenv(f"{prefix}_FALLBACK_PROVIDER", "gemini"),
                "mod":  os.getenv(f"{prefix}_FALLBACK_MODEL", "").strip(),
            }
        return result

    # ── Validation ──────────────────────────────────────────────────────────

    @staticmethod
    def _validate_config(cfg: dict[str, dict[str, str]]) -> None:
        """Refuse to start if any primary use case has no model configured."""
        missing: list[str] = []
        for usecase in AgentFactory._USECASES:
            if not cfg[usecase]["mod"]:
                missing.append(f"MODEL_USECASE_{usecase.upper()}_MODEL")
        if missing:
            msg = (
                "event=agent_factory_missing_models "
                "Missing required env vars: %s. "
                "Set them in .env or docker-compose.yml."
            ) % ", ".join(missing)
            logger.critical(msg)
            raise RuntimeError(msg)

    # ── Thinking auto-detection ───────────────────────────────────────────────

    @staticmethod
    def _detect_thinking_support(model_name: str) -> bool:
        """Check whether *model_name* supports the Ollama ``think`` parameter.

        Queries ``POST /api/show`` and inspects ``details.family`` against
        the known-thinking-families set.  Cached per model name.
        """
        if model_name in AgentFactory._thinking_cache:
            return AgentFactory._thinking_cache[model_name]

        ollama_url = str(
            os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        ).replace("/api/generate", "").replace("/api/chat", "").rstrip("/")
        try:
            resp = requests.post(
                f"{ollama_url}/api/show",
                json={"name": model_name},
                timeout=5,
            )
            resp.raise_for_status()
            info = resp.json() or {}
            details = info.get("details") if isinstance(
                info.get("details"), dict) else {}
            family = str(details.get("family", "") or "").strip().lower()
            supports = family in AgentFactory._THINKING_FAMILIES
            logger.info(
                "event=thinking_auto_detect model=%s family=%s supports=%s",
                model_name, family or "unknown", supports,
            )
        except Exception as exc:
            logger.debug(
                "event=thinking_auto_detect_failed model=%s error=%s — assuming False",
                model_name, exc,
            )
            supports = False

        AgentFactory._thinking_cache[model_name] = supports
        return supports

    @staticmethod
    def _resolve_thinking_flag(usecase: str, model_name: str, thinking_raw: str) -> bool:
        """Resolve the thinking flag for *usecase*.

        - ``"true"``  → always on
        - ``"false"`` → always off
        - ``"auto"``  → detect via Ollama /api/show (family-based heuristic)
        """
        if thinking_raw == "true":
            return True
        if thinking_raw == "false":
            return False
        # "auto" — detect from model architecture
        return AgentFactory._detect_thinking_support(model_name)

    @staticmethod
    def _resolve_thinking_flags(cfg: dict[str, dict[str, str]]) -> None:
        """Add resolved ``thinking`` bool to each use-case entry in *cfg*."""
        for key, entry in cfg.items():
            if key.endswith("_fallback"):
                entry["thinking"] = False  # fallbacks never think
            else:
                entry["thinking"] = AgentFactory._resolve_thinking_flag(
                    key, entry["mod"], entry.pop("thinking_raw", "auto"),
                )

    # ── Gemini model name validation ─────────────────────────────────────────

    _GEMINI_TEXT_DEFAULT = os.getenv("ORACLE_GEMINI_TEXT_DEFAULT_MODEL", "")
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
        """If GEMINI_API_KEY is missing and a use case uses Gemini, remap to Ollama.

        The remap target models come from env vars (Rulebook 1.4).
        """
        api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
        if api_key:
            return
        defaults = {
            "embed": os.getenv("ORACLE_GEMINI_FALLBACK_EMBED_MODEL", ""),
            "code":  os.getenv("ORACLE_GEMINI_FALLBACK_CODE_MODEL", ""),
            "":      os.getenv("ORACLE_GEMINI_FALLBACK_DEFAULT_MODEL", ""),
        }
        for key, entry in cfg.items():
            if str(entry.get("prov", "")).strip().lower() != "gemini":
                continue
            category = ""
            if "embed" in key:
                category = "embed"
            elif "code" in key:
                category = "code"
            fb = defaults.get(category, defaults[""])
            if not fb:
                logger.warning(
                    "event=gemini_key_missing_no_fallback key=%s gemini_model=%s "
                    "— GEMINI_API_KEY not set and no ORACLE_GEMINI_FALLBACK_*_MODEL configured",
                    key, entry.get("mod", ""),
                )
                continue
            logger.warning(
                "event=gemini_key_missing_remapping key=%s from=%s to=ollama/%s",
                key, entry.get("mod", ""), fb,
            )
            entry["prov"] = "ollama"
            entry["mod"] = fb

    # ── Build ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_bundle(cfg: dict[str, dict[str, str]]) -> AgentBundle:
        def _make(key: str, prompt: str) -> UniversalAgent:
            return UniversalAgent(
                role_prompt=prompt,
                provider=cfg[key]["prov"],
                model_name=cfg[key]["mod"],
                thinking=cfg[key].get("thinking", False),
            )

        return AgentBundle(
            generic=_make("generic", _GENERIC_SYSTEM_PROMPT),
            generic_fallback=_make("generic_fallback", _GENERIC_SYSTEM_PROMPT),
            reasoning=_make("reasoning", _GENERIC_SYSTEM_PROMPT),
            reasoning_fallback=_make(
                "reasoning_fallback", _GENERIC_SYSTEM_PROMPT),
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
            "generic=%s generic_thinking=%s "
            "reasoning=%s reasoning_thinking=%s "
            "code=%s code_thinking=%s "
            "embedding=%s",
            cfg["generic"]["mod"], cfg["generic"].get("thinking", False),
            cfg["reasoning"]["mod"], cfg["reasoning"].get("thinking", False),
            cfg["code"]["mod"], cfg["code"].get("thinking", False),
            cfg["embedding"]["mod"],
        )


def conversation_style_contract() -> str:
    """Return the mandatory conversation-style contract for prompt injection."""
    return prompt_config.conversation_style_contract()
