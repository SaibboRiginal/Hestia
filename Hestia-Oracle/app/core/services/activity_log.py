"""Recent chat turns — what Oracle did for each request (WebUI page *Cervello*, ``GET /api/ui/activity``).

One short row per finished chat turn: route (quick / quick_chat / agent), domains chosen, tools called (ok or not),
model + provider, total ms and the LLM usage of the turn. In memory only (a bounded ring, lost on restart): it is a
live inside view, not an audit log (the logs keep ``event=chat_done_summary``).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Iterable

_MAX = 200
_PREVIEW = 80
_lock = threading.Lock()
_turns: deque = deque(maxlen=_MAX)


def _usage_delta(before: dict | None, after: dict | None) -> dict:
    before, after = before or {}, after or {}
    keys = ("calls", "input_tokens", "output_tokens", "cost_usd")
    out = {k: max(0, (after.get(k) or 0) - (before.get(k) or 0)) for k in keys}
    out["cost_usd"] = round(float(out["cost_usd"]), 6)
    return out


def record_turn(*, session_id: str, client: str = "", mode: str, route: str, model: str, provider: str,
                domains: Iterable[str] | None = None, tool_log: list[dict] | None = None, total_ms: int = 0,
                message: str = "", usage_before: dict | None = None, usage_after: dict | None = None,
                trace_id: str = "") -> dict:
    """Store one finished turn. Never raises (the chat must not fail because of the inside view)."""
    try:
        tools = [{"tool": str(e.get("tool") or ""), "ok": bool(e.get("ok")), "writes": bool(e.get("writes"))}
                 for e in (tool_log or [])]
        text = " ".join(str(message or "").split())
        row: dict[str, Any] = {
            "at": time.time(), "trace_id": trace_id, "session": str(session_id or "")[:12],
            "client": str(client or "")[:40], "mode": mode, "route": route,
            "model": str(model or ""), "provider": str(provider or ""),
            "domains": [str(d) for d in (domains or []) if d],
            "tools": tools, "tools_failed": sum(1 for t in tools if not t["ok"]),
            "ms": int(total_ms or 0),
            "preview": text[:_PREVIEW] + ("…" if len(text) > _PREVIEW else ""),
            "usage": _usage_delta(usage_before, usage_after),
        }
        with _lock:
            _turns.append(row)
        return row
    except Exception:  # noqa: BLE001 — inside view only
        return {}


def recent(limit: int = 30) -> list[dict]:
    """Newest first."""
    with _lock:
        rows = list(_turns)
    rows.reverse()
    return rows[: max(1, min(int(limit or 30), _MAX))]


def reset() -> None:
    with _lock:
        _turns.clear()
