"""Watch on the cached prompt prefix (dossier docs/work/2026-11-17-compact-outputs v1.2, idea from Headroom).

A model server reuses the work already done on a prompt only for the part that is byte-identical to the previous
one (KV cache: Ollama, llama-server, vLLM; prompt cache: cloud services). Oracle builds its prompts so that the start
stays fixed (system part first, tools sorted, history window moving in jumps), but nothing checked that it really
does: one volatile line near the top (a time, a hint, a changed tool list) makes the model read the whole prompt
again at every message, slower, without any error.

``check`` is called with the first prompt of every turn of a conversation loop. When the part that should stay
fixed changed since the previous turn, it logs ``event=prompt_prefix_changed`` with where it changed (the section
title and a few characters), so the cause can be found and moved below the fixed part. Log only: it never changes a
prompt. In memory, a few hundred conversations at most.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict

logger = logging.getLogger("hestia_oracle.prefix_watch")

_MAX_KEYS = 200
_SNIPPET = 60

_lock = threading.Lock()
_last: "OrderedDict[str, tuple[str, tuple[str, ...]]]" = OrderedDict()   # key → (fixed part, tool names)


def reset() -> None:
    with _lock:
        _last.clear()


def _common(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _section_at(text: str, index: int) -> str:
    """Title of the prompt section that holds *index*: the closest line above it written like ``TITLE:``."""
    for line in reversed(text[:index].splitlines()):
        head = line.strip()
        if head.endswith(":") and head[:-1].replace(" ", "").replace("_", "").isupper():
            return head[:-1]
        if head.startswith("[") and "]" in head:
            return head[1:head.index("]")]
    return "start"


def check(key: str, fixed: str, tools: tuple[str, ...] = ()) -> dict | None:
    """Compare the fixed part of this turn's prompt (and its tool names, which servers put at the top too) with the
    previous turn of the same *key* (conversation + loop). Returns what changed (also logged) or None."""
    if not key:
        return None
    with _lock:
        prev = _last.pop(key, None)
        _last[key] = (fixed, tuple(tools))
        while len(_last) > _MAX_KEYS:
            _last.popitem(last=False)
    if prev is None:
        return None
    old_fixed, old_tools = prev
    change: dict | None = None
    if old_tools != tuple(tools):
        added = sorted(set(tools) - set(old_tools))
        removed = sorted(set(old_tools) - set(tools))
        change = {"where": "tools", "kept_chars": 0, "of_chars": len(fixed),
                  "detail": f"+{','.join(added)[:120]} -{','.join(removed)[:120]}"}
    elif old_fixed != fixed:
        kept = _common(old_fixed, fixed)
        change = {"where": _section_at(fixed, kept), "kept_chars": kept, "of_chars": len(fixed),
                  "detail": fixed[kept:kept + _SNIPPET].replace("\n", " ")}
    if change:
        logger.info("event=prompt_prefix_changed key=%s where=%s kept_chars=%d of_chars=%d detail=%r",
                    key, change["where"], change["kept_chars"], change["of_chars"], change["detail"])
    return change
