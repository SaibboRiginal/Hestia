"""Questions the assistant asks the user (docs/work/2026-10-19-oracle-offline v3 A).

The model calls the tool ``ask_user`` when the answer changes what it does: the request is ambiguous, an action is
risky or hard to undo, or there are real alternatives. The turn stops there (agent loop) and the question goes out as
the existing ``question`` frame (kinds free_text | single_choice | multi_choice | confirm). The answer does not wake a
paused thread: the client sends it back and gets a ``resume`` message, a normal chat turn in the same session, whose
history already holds the question. So nothing is lost if Oracle restarts in between; pending questions are also
kept in Archive (``/api/oracle-store``, kind ``question``) so the answer is still accepted and clients can show them
again after a reload.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

KINDS = ("free_text", "single_choice", "multi_choice", "confirm")
_HEADERS = {"free_text": "Rispondi", "single_choice": "Scegli", "multi_choice": "Scegli (anche più di una)",
            "confirm": "Confermi?"}
_STORE = "api/oracle-store/records"

TOOL_DESCRIPTION = (
    "Ask the user and wait. Use ONLY when the answer changes what you do: request ambiguous, action risky or not "
    "easy to undo, real alternatives to pick from. Not for small talk or what you can decide. kind: confirm (yes/no), "
    "single_choice, multi_choice (options required), free_text. After calling it STOP: the answer arrives as the "
    "user's next message.")

TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string", "description": "The question, short, in the user's language"},
        "kind": {"type": "string", "enum": list(KINDS), "description": "confirm | single_choice | multi_choice | free_text"},
        "options": {"type": "array", "items": {"type": "string"},
                    "description": "Choices for single_choice / multi_choice (2-8 short labels)"},
        "allow_other": {"type": "boolean", "description": "Also accept a free answer («Altro…»)"},
    },
    "required": ["prompt"],
}


def build_question(prompt: str = "", kind: str = "confirm", options: list | None = None,
                   allow_other: bool = False) -> tuple[bool, Any]:
    """Validate the model's call; the result carries ``ask`` (agent loop stops the turn on it)."""
    prompt = str(prompt or "").strip()
    if not prompt:
        return False, "prompt is required"
    kind = kind if kind in KINDS else "confirm"
    labels = [str(o).strip() for o in (options or []) if str(o).strip()][:8]
    if kind in ("single_choice", "multi_choice") and len(labels) < 2:
        return False, "single_choice / multi_choice need at least 2 options"
    if kind == "confirm":
        opts = [{"value": "si", "label": "Sì"}, {"value": "no", "label": "No"}]
    else:
        opts = [{"value": label, "label": label} for label in labels]
    ask = {"question_id": f"ask_{uuid.uuid4().hex[:12]}", "header": _HEADERS[kind], "prompt": prompt,
           "kind": kind, "options": opts, "allow_other": bool(allow_other) or kind == "free_text"}
    return True, {"ask": ask, "status": "asked", "note": "Domanda inviata. Fermati: la risposta arriva come prossimo messaggio."}


def resume_message(entry: dict, answer: str) -> str:
    """The user's answer as the next chat message (the question is already in the history)."""
    prompt = str(entry.get("prompt") or "").strip()
    answer = str(answer or "").strip()
    if entry.get("kind") == "confirm":
        answer = {"si": "Sì", "no": "No"}.get(answer.lower(), answer)
    if entry.get("kind") == "multi_choice":
        parts = [p.strip() for p in answer.split("\n") if p.strip()]
        answer = ", ".join(parts) if parts else answer
    if not answer:
        return f"(Nessuna risposta alla domanda «{prompt}»: decidi tu la cosa più sicura.)"
    return f"Risposta alla tua domanda «{prompt}»: {answer}"


def expires_at(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=max(1, int(hours or 24)))).isoformat()


def expired(entry: dict) -> bool:
    try:
        return datetime.fromisoformat(str(entry.get("expires_at"))) < datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False


def save(hub, entry: dict, deleted: bool = False) -> None:
    """Best effort: a pending question is also kept in Archive (survives an Oracle restart)."""
    row = {"kind": "question", "id": entry["question_id"], "ref_id": entry.get("session_id") or None,
           "at": entry.get("asked_at"), "data": {k: v for k, v in entry.items() if k != "actions"},
           "updated_at": datetime.now(timezone.utc).isoformat(), "deleted": deleted}
    ok, res = hub.route_to_service("archive", _STORE, "PUT", body={"rows": [row]}, timeout=6)
    if not ok:
        logger.warning("[🔄] event=user_question_store_failed question_id=%s error=%s",
                       entry["question_id"], str(res)[:200])


def load(hub, question_id: str) -> dict | None:
    ok, res = hub.route_to_service("archive", _STORE, "GET", query={"kind": "question", "ids": question_id},
                                   timeout=6)
    rows = (res or {}).get("rows") if ok and isinstance(res, dict) else None
    return dict(rows[0].get("data") or {}) if rows else None


def open_for_session(hub, session_id: str) -> list[dict]:
    """Questions still waiting for an answer in this session (clients draw them again after a reload)."""
    ok, res = hub.route_to_service("archive", _STORE, "GET", query={"kind": "question", "ref_id": session_id},
                                   timeout=6)
    rows = (res or {}).get("rows") if ok and isinstance(res, dict) else []
    out = []
    for r in rows or []:
        data = dict(r.get("data") or {})
        if not data.get("resolved") and not expired(data):
            out.append(data)
    return out
