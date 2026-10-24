"""Provider type ``llamacpp`` — llama.cpp ``llama-server`` with slots and saved context (brainstorm D17).

Same OpenAI-compatible API as ``openai`` plus what makes local chats fast when you switch between them
(evaluation ``valutazioni/contesto-chat-e-alternative-ollama.md``):

- **slots**: every chat session gets its own server slot (``id_slot``), so up to ``oracle.provider.llamacpp.slots``
  conversations keep their KV cache warm at the same time; calls without a session (classifier, memory, module use
  cases) use slot 0 so they never evict a chat;
- **saved context**: when a slot passes to another session, the outgoing session's KV cache is saved to disk
  (``POST /slots/{id}?action=save``) and restored when that session comes back (``action=restore``) instead of being
  recomputed. Needs ``--slot-save-path`` on the server; without it the first refusal turns saving off until restart
  ([🔄] logged), slots keep working.
- **health**: ``available`` probes ``/health`` (cached ``_HEALTH_TTL`` s), so a chain skips a server that is off at
  once and Ollama (next step) answers.

Start (compose service ``llamacpp``, profile ``llamacpp``):
``llama-server -m <model>.gguf -c 16384 -fa on -ngl 99 --parallel 3 --slot-save-path /slots``.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from typing import Any

import requests

from agents.providers.openai_compat import OpenAICompatProvider

logger = logging.getLogger("hestia_oracle.providers.llamacpp")

SLOTS_KEY = "oracle.provider.llamacpp.slots"
_HEALTH_TTL = 30.0

_lock = threading.Lock()
_slots: "dict[str, OrderedDict[str, int]]" = {}     # server url → session → slot (LRU order)
_health: dict[str, tuple[float, bool, str]] = {}    # server url → (checked at, ok, detail)
_save_disabled: dict[str, str] = {}                 # server url → reason


def _file(session: str) -> str:
    return "hestia-" + re.sub(r"[^A-Za-z0-9_-]+", "_", session)[:80] + ".bin"


def slot_count() -> int:
    try:
        from core.services import oracle_settings
        return max(2, oracle_settings.get_int(SLOTS_KEY, 2))
    except Exception:
        return 2


class LlamaCppProvider(OpenAICompatProvider):
    TYPE = "llamacpp"
    LABEL = "llama-server (slot e contesto salvato)"
    BILLING = "Server locale · gratis"

    # ── health ───────────────────────────────────────────────────────────
    def _root(self) -> str:
        return re.sub(r"/v1/?$", "", str(self.config.get("base_url") or "").rstrip("/"))

    def available(self) -> tuple[bool, str]:
        ok, detail = super().available()
        if not ok:
            return ok, detail
        root = self._root()
        now = time.time()
        with _lock:
            hit = _health.get(root)
        if hit and now - hit[0] < _HEALTH_TTL:
            return hit[1], hit[2]
        try:
            resp = requests.get(f"{root}/health", timeout=2)
            ok = resp.status_code < 500
            detail = "ok" if ok else f"health {resp.status_code}"
        except Exception as exc:
            ok, detail = False, f"server not reachable: {str(exc)[:80]}"
        with _lock:
            _health[root] = (now, ok, detail)
        return ok, detail

    # ── slots ────────────────────────────────────────────────────────────
    def _slot_action(self, slot: int, action: str, session: str) -> bool:
        root = self._root()
        if _save_disabled.get(root):
            return False
        try:
            resp = requests.post(f"{root}/slots/{slot}", params={"action": action}, json={"filename": _file(session)},
                                 timeout=30)
        except Exception as exc:
            logger.debug("event=llamacpp_slot_%s_failed slot=%d error=%s", action, slot, exc)
            return False
        if resp.status_code in (400, 404, 501) and action == "save":
            _save_disabled[root] = f"{resp.status_code}: {resp.text[:120]}"
            logger.warning("[🔄] event=llamacpp_slot_save_unsupported status=%s fallback=slots_only "
                           "hint=start llama-server with --slot-save-path", resp.status_code)
            return False
        return resp.status_code < 400

    def slot_for(self, session: str) -> int:
        """Slot of *session* (1..N-1; 0 = calls without a session). A newcomer takes the least recently used slot,
        whose session is saved first; a session that comes back gets its cache restored."""
        if not session:
            return 0
        root, n = self._root(), slot_count()
        with _lock:
            table = _slots.setdefault(root, OrderedDict())
            if session in table:
                table.move_to_end(session)
                return table[session]
            used = set(table.values())
            free = [i for i in range(1, n) if i not in used]
            evicted = ""
            if free:
                slot = free[0]
            else:
                evicted, slot = table.popitem(last=False)
            table[session] = slot
        if evicted:
            self._slot_action(slot, "save", evicted)
        if self._slot_action(slot, "restore", session):
            logger.info("event=llamacpp_slot_restored slot=%d", slot)
        return slot

    def _body(self, model: str, messages: list[dict], thinking: Any, **extra) -> dict:
        body = super()._body(model, messages, thinking, **extra)
        body["cache_prompt"] = True
        try:
            from core.services import llm_stats
            session = llm_stats.current_session()
        except Exception:
            session = ""
        body["id_slot"] = self.slot_for(session)
        return body
