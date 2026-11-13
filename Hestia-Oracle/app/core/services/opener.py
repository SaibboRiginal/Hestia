"""The assistant writes first (docs/work/2026-11-12-identita-e-proattivita, «parla con te»).

Athena decides *when* and brings the reasons (mood, what the areas noticed, what she already wrote); Oracle, the
only brain, writes the one or two sentences in the persona, with what it remembers of the owner. Hermes delivers.
Nothing to say that is true → ``NIENTE`` → no message (never small talk for its own sake).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from core.services import prompt_config

logger = logging.getLogger(f"hestia_oracle.{__name__}")

NOTHING = "NIENTE"
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
MAX_CHARS = 400
MEMORY_MAX = 20
# What a person who lives with someone knows about them: a gap here is a good reason for a question.
TOPICS = ("work or study", "loved ones", "passions and free time", "food", "music, films, books", "sport",
          "goals of this year", "a typical day", "what relaxes them", "what stresses them")


def _lines(values: Any, cap: int, width: int = 240) -> list[str]:
    out = []
    for value in values or []:
        text = " ".join(str(value or "").split())[:width]
        if text:
            out.append(f"- {text}")
        if len(out) >= cap:
            break
    return out


def memory_lines(memory_service) -> list[str]:
    if memory_service is None:
        return []
    try:
        ok, rows = memory_service.recall("")
    except Exception as exc:  # noqa: BLE001 - she can still write without memories
        logger.warning("[🔄] event=opener_memory_failed error=%s fallback=no_memories", exc)
        return []
    if not ok or not isinstance(rows, list):
        return []
    return _lines([(r or {}).get("fact") for r in rows], MEMORY_MAX)


def build_prompt(reasons: list[str], avoid: list[str], memories: list[str], awareness: list[str],
                 now_context: str = "", past: list[str] | None = None) -> str:
    parts = [prompt_config.prompt("opener_instruction", topics=", ".join(TOPICS))]
    if now_context:
        parts.append(f"NOW:\n{now_context.strip()}")
    if awareness:
        parts.append("CONTEXT:\n" + "\n".join(awareness))
    parts.append("REASONS OF TODAY:\n" + ("\n".join(_lines(reasons, 6)) or "- none in particular"))
    if past:
        parts.append("THE LAST DAYS (pick up a thread if there is one; never repeat a question left unanswered):\n"
                     + "\n".join(_lines(past, 8)))
    parts.append("WHAT YOU KNOW ABOUT THEM:\n" + ("\n".join(memories) or "- almost nothing yet"))
    if avoid:
        parts.append("YOU ALREADY WROTE THEM (do not repeat, do not insist):\n" + "\n".join(_lines(avoid, 6)))
    parts.append("Your message, in the language of what you know about them (Italian if unsure), or NIENTE:")
    return "\n\n".join(parts)


def clean(answer: str) -> str:
    """The message to send, or "" when she has nothing to say."""
    from core.services import reaction_marker
    _, text = reaction_marker.strip(str(answer or ""))
    text = _TAG.sub("", text).strip().strip('"«»').strip()      # plain text: every client shows it its own way
    if not text or text.upper().rstrip(".!") == NOTHING or text.upper().startswith(NOTHING):
        return ""
    return text[:MAX_CHARS].strip()


def write(ask: Callable[[str], str], *, reasons: list[str], avoid: list[str], memory_service=None,
          awareness: list[str] | None = None, now_context: str = "", past: list[str] | None = None) -> dict[str, Any]:
    """``{"text": "..."}`` or ``{"text": "", "skip": "nothing_to_say"}``. ``ask`` = the persona's chain."""
    memories = memory_lines(memory_service)
    answer = ask(build_prompt(reasons, avoid, memories, list(awareness or []), now_context, past))
    text = clean(answer)
    logger.info("event=opener_written chars=%d reasons=%d memories=%d", len(text), len(reasons or []), len(memories))
    return {"text": text} if text else {"text": "", "skip": "nothing_to_say"}
