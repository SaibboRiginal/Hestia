"""Turn traces for the training dataset (docs/work/2026-10-30-dataset-allenamento, phase D1).

After every finished chat turn typed by the owner, Oracle pushes **what the model saw and did** to Metis
(``POST /route/metis/api/metis/traces``), in the background: system prompt, the history text it got, the user
message, each tool call with its arguments and result, the final answer, model and route. Metis owns the dataset
(storage, signals, exclusions, retention); Oracle only emits. A failed push is logged and dropped: the chat never
waits for it or fails because of it.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Iterable

logger = logging.getLogger("hestia_oracle.turn_trace")

_PATH = "api/metis/traces"
_MAX_TEXT = 60_000          # one field (system prompt, history) never above this
_MAX_RESULT = 4_000         # one tool result


def _cut(text: Any, limit: int) -> str:
    s = str(text or "")
    return s if len(s) <= limit else s[:limit] + "…"


def build(*, trace_id: str, session_id: str, client: str, route: str, mode: str, use_case: str, model: str,
          provider: str, origin: dict | None, user_message: str, answer: str, history_text: str = "",
          system: str = "", tools: Iterable[dict] | None = None, tool_log: Iterable[dict] | None = None,
          domains: Iterable[str] | None = None, total_ms: int = 0, usage: dict | None = None) -> dict:
    """The trace body Metis stores (pure: no I/O)."""
    steps = []
    for e in tool_log or []:
        steps.append({
            "turn": e.get("turn"), "tool": str(e.get("tool") or ""), "params": e.get("params") or {},
            "ok": bool(e.get("ok")), "writes": bool(e.get("writes")),
            "result": _cut(e.get("result_text") or e.get("result_preview") or "", _MAX_RESULT),
        })
    return {
        "trace_id": trace_id, "session_id": session_id, "client": str(client or "")[:40],
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "route": route, "mode": mode, "use_case": use_case, "model": str(model or ""), "provider": str(provider or ""),
        "origin": {k: (origin or {}).get(k, "") for k in ("kind", "level")},
        "domains": [str(d) for d in (domains or []) if d],
        "system": _cut(system, _MAX_TEXT), "history": _cut(history_text, _MAX_TEXT),
        "user": _cut(user_message, _MAX_TEXT), "answer": _cut(answer, _MAX_TEXT),
        "tools": [{"name": t.get("name"), "description": t.get("description"), "parameters": t.get("parameters")}
                  for t in (tools or []) if isinstance(t, dict) and t.get("name")],
        "steps": steps, "total_ms": int(total_ms or 0), "usage": usage or {},
    }


def wanted(*, origin: dict | None, save_history: bool, session_id: str) -> bool:
    """Only turns the owner typed in a real conversation (routines, modules and external AIs are another set)."""
    return bool(session_id) and bool(save_history) and str((origin or {}).get("level") or "utente") == "utente" \
        and str((origin or {}).get("kind") or "") != "esterno"


def send(hub, trace: dict) -> None:
    """Push in a daemon thread; never raises."""
    def _run() -> None:
        try:
            ok, out = hub.route_to_service("metis", _PATH, "POST", body=trace, timeout=10)
            if ok:
                logger.debug("event=turn_trace_sent trace_id=%s", trace.get("trace_id"))
            else:
                logger.info("[🔄] event=turn_trace_dropped trace_id=%s reason=%s", trace.get("trace_id"),
                            str(out)[:160])
        except Exception as exc:  # noqa: BLE001 — the dataset never breaks the chat
            logger.info("[🔄] event=turn_trace_dropped trace_id=%s reason=%s", trace.get("trace_id"), exc)

    threading.Thread(target=_run, daemon=True, name="turn-trace").start()


def forget_session(hub, session_id: str) -> None:
    """The owner deleted a conversation or excluded it from training: Metis drops its traces (background)."""
    sid = str(session_id or "").strip()
    if not sid:
        return

    def _run() -> None:
        try:
            ok, out = hub.route_to_service("metis", _PATH, "DELETE", query={"session_id": sid}, timeout=15)
        except Exception as exc:  # noqa: BLE001
            ok, out = False, exc
        if not ok:
            logger.warning("[🔄] event=turn_trace_forget_failed session_id=%s reason=%s", sid, str(out)[:160])

    threading.Thread(target=_run, daemon=True, name="turn-trace-forget").start()
