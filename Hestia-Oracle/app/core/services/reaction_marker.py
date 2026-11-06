"""Emoji reactions of Hestia to the owner's message (docs/work/2026-11-06-hestia-viva F4).

The model may open its answer with ``[[r:<emoji>]]``. Oracle strips the marker from the chat stream and sends one
frame ``{"type":"reaction","emoji":"👍"}`` before the text: clients show it on the owner's message (WebUI next to
the bubble, Telegram as a native reaction). An answer made only of the marker is a reaction alone: the ``final``
frame then carries ``reply: ""`` and ``reaction_only: true``.

The prompt line (``INSTRUCTION``) is added only for clients that can show reactions (``CLIENTS``).
"""
from __future__ import annotations

import json
import re
from typing import Iterator

CLIENTS = {"telegram", "webui"}
INSTRUCTION = ("REAZIONE (facoltativa): puoi reagire al suo messaggio iniziando con [[r:EMOJI]] (una sola emoji, "
               "es. [[r:👍]] [[r:😂]] [[r:❤]]), come in una chat tra amici. Se basta la reazione (ok, grazie, "
               "saluto di congedo) rispondi SOLO col marcatore.")

_MARKER = re.compile(r"^\s*\[\[\s*r\s*:\s*([^\]\s]{1,8})\s*\]\]\s*", re.UNICODE)
_MAX_PREFIX = 24          # longer than any marker: past this the answer has no marker


def strip(text: str) -> tuple[str, str]:
    """``(emoji, text without the marker)``; ``("", text)`` when there is none."""
    raw = str(text or "")
    m = _MARKER.match(raw)
    if not m:
        return "", raw
    return m.group(1), raw[m.end():]


def _frame(line: str) -> dict | None:
    try:
        data = json.loads(line)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def filter_stream(stream: Iterator[str]) -> Iterator[str]:
    """Pass a chat NDJSON stream through, turning a leading marker into a ``reaction`` frame.

    Tokens are held only until the start of the answer is decided (at most ``_MAX_PREFIX`` characters or the first
    non-token frame), so the stream keeps flowing."""
    held: list[str] = []          # token texts not yet sent
    decided = False
    reacted = ""

    def flush_tokens() -> Iterator[str]:
        nonlocal decided, reacted
        decided = True
        text = "".join(held)
        held.clear()
        emoji, rest = strip(text)
        if emoji:
            reacted = emoji
            yield _dump({"type": "reaction", "emoji": emoji})
        if rest:
            yield _dump({"type": "token", "text": rest})

    for chunk in stream:
        for line in str(chunk).splitlines(keepends=False):
            if not line.strip():
                continue
            frame = _frame(line)
            if frame is None:
                yield line + "\n"
                continue
            kind = frame.get("type")
            if kind == "token" and not decided:
                held.append(str(frame.get("text") or ""))
                joined = "".join(held).lstrip()
                if (len(joined) >= _MAX_PREFIX or (joined and not joined.startswith("[")) or "]]" in joined):
                    yield from flush_tokens()
                continue
            if kind == "final":
                if not decided:
                    yield from flush_tokens()
                emoji, rest = strip(frame.get("reply") or "")
                if emoji and not reacted:
                    reacted = emoji
                    yield _dump({"type": "reaction", "emoji": emoji})
                if emoji:
                    frame["reply"] = rest
                    frame["reaction"] = emoji
                    if not rest.strip():
                        frame["reaction_only"] = True
                    yield _dump(frame)
                    continue
                yield line + "\n"
                continue
            if not decided and kind not in ("status", "thinking", "signal", "notice"):
                yield from flush_tokens()
            yield line + "\n"
    if held:
        yield from flush_tokens()
