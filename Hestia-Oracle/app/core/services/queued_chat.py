"""Messages written while the assistant could not answer, answered together (oracle-offline v3 C).

The chat client sends the whole queue of one chat in a single ``/api/chat`` call (``queued``). Oracle turns it into
one turn and lets the model decide: one answer per message, one merged answer, or — when some are old or superseded
by later ones — ask the user with ``ask_user`` (multi_choice) which to keep. Nothing is dropped silently.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Caveman style: paid every queued turn.
INSTRUCTIONS = (
    "QUEUED MESSAGES: the user wrote them while you could not answer (time and text below). You decide: "
    "different topics → answer each (short heading each); related → one answer; "
    "some old or overtaken by later ones → ask with ask_user multi_choice which to keep (options = short "
    "messages), then answer only those. Drop nothing without asking. No long apologies for the delay. "
    "Answer in the language of the messages.")


def _when(value: str | None, now: datetime) -> str:
    try:
        at = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return ""
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    minutes = int((now - at).total_seconds() // 60)
    ago = f"{minutes} min ago" if minutes < 120 else (f"{minutes // 60} h ago" if minutes < 48 * 60
                                                      else f"{minutes // 1440} days ago")
    return f"{at.astimezone().strftime('%d/%m %H:%M')}, {ago}"


def compose(items: list[dict], now: datetime | None = None) -> str:
    """One user message holding every queued text, oldest first."""
    now = now or datetime.now(timezone.utc)
    lines = []
    for i, item in enumerate(items, 1):
        when = _when(item.get("written_at"), now)
        lines.append(f"{i}. ({when}) {str(item.get('text') or '').strip()}" if when
                     else f"{i}. {str(item.get('text') or '').strip()}")
    if len(lines) == 1:
        return lines[0].split(") ", 1)[-1] if lines[0].startswith("1. (") else lines[0][3:]
    return "[Messages written while you could not answer]\n" + "\n".join(lines)


def instructions(items: list[dict], client_instructions: str | None) -> str:
    extra = INSTRUCTIONS if len(items) > 1 else (
        "QUEUED MESSAGE: written " + (_when(items[0].get("written_at"), datetime.now(timezone.utc)) or "earlier")
        + " while you could not answer. Answer now, minding the time passed.")
    return "\n\n".join(p for p in (client_instructions or "", extra) if p)
