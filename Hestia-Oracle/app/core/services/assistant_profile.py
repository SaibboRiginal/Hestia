"""Hestia's profile for another AI (tool ``assistant_profile``, docs/work/2026-10-30-hestia-in-claude).

When the user switches Hestia on inside Claude (mod «hestia»), Claude becomes Hestia with the same pieces
Oracle puts in its own prompt: persona, style contract, the user's tone and instructions (``oracle.chat.*``),
what Hestia remembers about the user. One source of truth: change them in Hestia, the next Claude turn follows.
No LLM call; the whole block stays under ``oracle.chat.profile_max_tokens``.
"""
from __future__ import annotations

import hashlib
import logging

from core.services import oracle_settings, prompt_config

logger = logging.getLogger(f"hestia_oracle.{__name__}")

CLIENTS = ("claude",)
# Oracle's persona ends with Telegram formatting rules; another AI keeps its own formatting.
_PERSONA_CUT = "FORMATO HTML TELEGRAM"
_CHARS_PER_TOKEN = 4  # rough, Italian text; only used for the cap
DIGEST_MAX = 20


def persona_core() -> str:
    """Identity and rules of Oracle's persona, without the client-specific formatting part."""
    text = prompt_config.analyst_persona_default()
    return text.split(_PERSONA_CUT, 1)[0].strip()


def _memory_lines(memory_service, budget_chars: int) -> list[str]:
    if memory_service is None or budget_chars <= 0:
        return []
    try:
        ok, rows = memory_service.recall("")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=assistant_profile_memory_failed error=%s", exc)
        return []
    if not ok or not isinstance(rows, list):
        return []
    lines, used = [], 0
    for row in rows[:DIGEST_MAX]:
        fact = " ".join(str((row or {}).get("fact") or "").split())
        if not fact:
            continue
        line = f"- {fact}"
        if used + len(line) + 1 > budget_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return lines


def build(memory_service=None, *, client: str = "claude", session: str = "") -> dict:
    """The block another AI adds to its system prompt, plus a revision to cache it by.

    Order: persona → style → the user's instructions → the client contract → memory digest (what is left of
    the budget). Persona and contract are never cut; instructions and memory are."""
    client = client if client in CLIENTS else "claude"
    max_chars = oracle_settings.get_int(oracle_settings.PROFILE_MAX_TOKENS, 300) * _CHARS_PER_TOKEN
    persona = persona_core()
    style = prompt_config.conversation_style_contract()
    contract = prompt_config.prompt(f"client_contract_{client}")
    instructions = "\n".join(oracle_settings.chat_instructions(client=client, session=session))
    fixed = len(persona) + len(style) + len(contract) + 8
    if instructions and fixed + len(instructions) > max_chars:
        instructions = instructions[:max(0, max_chars - fixed)].rstrip()
    budget = max_chars - fixed - len(instructions) - len("RICORDI SULL'UTENTE:\n")
    memory = _memory_lines(memory_service, budget)

    parts = [persona, style]
    if instructions:
        parts.append(instructions)
    parts.append(contract)
    if memory:
        parts.append("RICORDI SULL'UTENTE (da Hestia; per altro usa memory_recall):\n" + "\n".join(memory))
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    revision = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    logger.info("event=assistant_profile_built client=%s chars=%d memories=%d revision=%s",
                client, len(text), len(memory), revision)
    return {"client": client, "revision": revision, "text": text,
            "tokens_estimate": len(text) // _CHARS_PER_TOKEN, "memories": len(memory),
            "max_tokens": max_chars // _CHARS_PER_TOKEN}
