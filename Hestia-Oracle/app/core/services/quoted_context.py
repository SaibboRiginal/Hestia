"""A reply to (or a quote of) an earlier message = context for this turn (docs/work/2026-10-23-telegram-da-zero §5.10).

The chat client sends ``quoted: {text, from, at, ref}`` with ``/api/chat``: ``from`` is assistant | user | notification,
``ref`` is the client's id of that message (optional). Oracle adds one short instruction line; the saved user message
stays the text the user wrote, so history and memory hold no copies.
"""
from __future__ import annotations

MAX_CHARS = 1200    # a quoted notification or a long answer: the start is enough to know what the user means
WHO = {"assistant": "your message", "user": "their own message", "notification": "your notification"}


def instruction(quoted: dict | None) -> str:
    """Caveman line for the model, or "" when there is nothing usable."""
    if not isinstance(quoted, dict):
        return ""
    text = " ".join(str(quoted.get("text") or "").split())
    if not text:
        return ""
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
    who = WHO.get(str(quoted.get("from") or "").lower(), "a message")
    at = str(quoted.get("at") or "")[:16].replace("T", " ")
    head = f"THEY ARE REPLYING TO {who}" + (f" ({at})" if at else "")
    return f"{head}: «{text}». Their message refers to this."


def with_instructions(client_instructions: str | None, quoted: dict | None) -> str | None:
    line = instruction(quoted)
    if not line:
        return client_instructions
    return "\n\n".join(p for p in (client_instructions or "", line) if p)
