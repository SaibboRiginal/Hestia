"""«Add now»: what the user writes while the assistant is still working on the same chat (dossier 2026-11-18-real-test-problems B).

The chat client sends the text to ``POST /api/chat/steer`` while a turn of that session runs. The agent loop of the
chat takes it at the start of its next step (``take``) and tells the client which texts it took (signal
``chat.steer_taken``). A text that arrives when no chat loop runs, or after the last step, is refused or dropped at
the end of the loop (``end``): the client then sends it as the next message, so nothing is lost and nothing leaks into
a later turn. In memory only: a steer lives a few seconds.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("hestia_oracle.steering")

MAX_TEXT = 2000
_lock = threading.Lock()
_running: dict[str, int] = {}            # session → chat loops running now
_pending: dict[str, list[dict]] = {}     # session → [{"id", "text"}] not taken yet


def begin(session: str) -> None:
    if not session:
        return
    with _lock:
        _running[session] = _running.get(session, 0) + 1


def end(session: str) -> list[dict]:
    """The chat loop ended: drop what it did not take (the client sends those as the next message)."""
    if not session:
        return []
    with _lock:
        left = _running.get(session, 0) - 1
        if left > 0:
            _running[session] = left
            return []
        _running.pop(session, None)
        dropped = _pending.pop(session, [])
    if dropped:
        logger.info("[🔄] event=chat_steer_not_taken session_id=%s count=%d", session, len(dropped))
    return dropped


def add(session: str, text: str, steer_id: str = "") -> bool:
    """Keep *text* for the running loop of *session*; False when none runs (the client queues it instead)."""
    text = str(text or "").strip()[:MAX_TEXT]
    if not session or not text:
        return False
    with _lock:
        if not _running.get(session):
            return False
        _pending.setdefault(session, []).append({"id": str(steer_id or "")[:64], "text": text})
    logger.info("event=chat_steer_added session_id=%s chars=%d", session, len(text))
    return True


def take(session: str) -> list[dict]:
    if not session:
        return []
    with _lock:
        return _pending.pop(session, [])


def note(items: list[dict]) -> str:
    """The scratchpad line the model reads (caveman: paid at every step)."""
    texts = " | ".join(i["text"] for i in items)
    return f"USER ADDED WHILE YOU WORKED (newer than USER above, follow it; answer covers both): {texts}"
