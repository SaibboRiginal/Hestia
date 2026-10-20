"""LLM use cases a module declares to Oracle (dossier ``docs/work/2026-10-19-oracle-a-blocchi``).

A module that asks Oracle for text (``POST /api/llm/generate`` with ``use_case``) declares each kind of task as a
use case, with a suggested chain (``veloce``, ``potente``, ``codice``…). The declaration rides in the module's Hub
registration (``capabilities.llm_usecases``, re-sent by the keepalive), so nothing else to call or retry. Marko
picks the chain and mode of every use case in one place (Oracle → Cervello → Modelli); the module never names a
provider or a model.

    from hestia_common.oracle_usecases import usecase, capabilities as llm_capabilities

    LLM_USECASES = [usecase("scout.annunci", "Scout · lettura annunci", chain="veloce",
                            help="Estrae i dati degli annunci dalle mail.")]
    payload["capabilities"].update(llm_capabilities(LLM_USECASES))
    ... json={"prompt": prompt, "use_case": "scout.annunci"}
"""
from __future__ import annotations

import re

CHAINS = ("veloce", "potente", "codice", "visione")
MODES = ("segui", "interna", "esterna")
_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_.-]+$")


def usecase(id: str, label: str, *, chain: str = "veloce", help: str = "", thinking: str = "auto",
            mode: str = "segui") -> dict:
    """One use case: id ``<module>.<task>``, Italian label, suggested chain/thinking/mode."""
    if not _ID.match(id):
        raise ValueError(f"use case id {id!r} must be '<module>.<task>' (lowercase)")
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} must be one of {MODES}")
    if thinking not in ("auto", "true", "false"):
        raise ValueError("thinking must be auto | true | false")
    return {"id": id, "label": label, "chain": chain, "help": help, "thinking": thinking, "mode": mode}


def capabilities(usecases: list[dict]) -> dict:
    """Keys to merge into ``capabilities`` of the Hub registration."""
    return {"llm_usecases": list(usecases)}
