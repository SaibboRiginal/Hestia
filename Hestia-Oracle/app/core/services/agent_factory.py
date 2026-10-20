"""LLM agent factory — one chain agent per Oracle use case.

Single responsibility: build the ``AgentBundle`` Oracle's services use. Each slot is an
``llm_chains.ChainAgent`` for one of Oracle's use cases; the chain (ordered provider/model steps,
quota skip, fallback) and the providers are read live from settings at every call, so a change
from any client needs no restart and no reconfiguration.

  generic   → oracle.generale     chat, classify, tool selection, memory extraction, formatting
  reasoning → oracle.ragionamento deep thinking, complex multi-step analysis
  code      → oracle.codice       code generation, debugging, technical tasks
  documents → oracle.documenti    documents, images, audio (vision-capable chain)
  embedding → oracle.embedding    vector embeddings (one model: vectors must stay comparable)

Mode (quick/auto/thinking) controls orchestration; use case controls which brain.
"""
import logging
from dataclasses import dataclass

from core.services import prompt_config
from core.services.llm_chains import SLOTS, ChainAgent

logger = logging.getLogger(f"hestia_oracle.{__name__}")

# ── System prompts ────────────────────────────────────────────────────────────

# Persona text = prompt map (overridable in the prompts file like every prompt).
_GENERIC_SYSTEM_PROMPT = prompt_config.analyst_persona_default()
_CODE_SYSTEM_PROMPT = (
    "You are an expert software engineer. Output clean, correct, well-structured code. "
    "Think before writing. Explain your approach briefly, then provide the implementation."
)


@dataclass
class AgentBundle:
    """LLM agents keyed by USE CASE slot (each a chain of models)."""

    generic: ChainAgent
    reasoning: ChainAgent
    code: ChainAgent
    documents: ChainAgent
    embedding: ChainAgent

    @property
    def generic_model_name(self) -> str:
        return self.generic.model_name or ""


class AgentFactory:
    """Builds the AgentBundle (chains are resolved live at call time)."""

    @staticmethod
    def create() -> AgentBundle:
        prompts = {"generic": _GENERIC_SYSTEM_PROMPT, "reasoning": _GENERIC_SYSTEM_PROMPT,
                   "code": _CODE_SYSTEM_PROMPT, "documents": _GENERIC_SYSTEM_PROMPT, "embedding": ""}
        bundle = AgentBundle(**{slot: ChainAgent(SLOTS[slot], role_prompt=prompts[slot], label=slot)
                                for slot in prompts})
        logger.info("event=oracle_agents_configured use_cases=%s", ",".join(SLOTS.values()))
        return bundle


def conversation_style_contract() -> str:
    """Return the mandatory conversation-style contract for prompt injection."""
    return prompt_config.conversation_style_contract()
