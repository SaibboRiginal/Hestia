"""Goal for a conversation (Cindy idea 23, dossier docs/work/2026-10-24-tutto-brainstorm-cindy).

The owner fixes a goal in a chat («obiettivo: sistema le categorie delle spese di ottobre», or the model calls
``goal_set`` when he asks for a long job). After answering each of his messages the assistant works on the goal for a
few more rounds of the agent loop, then reports; his messages always come first (a round runs only after his
message is answered) and he can stop it at any time («ferma l'obiettivo» → ``goal_stop``). The model ends it with
``goal_done``. Budget: ``oracle.obiettivo.giri`` rounds in all and ``oracle.obiettivo.giri_per_risposta`` per answer.
Kept in Archive (``oracle-store``, kind ``goal``, ref = session) so a restart does not lose it. Only the owner's turns
(origin ``utente``) run goal rounds.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("hestia_oracle.conversation_goal")

TOTAL_ROUNDS = "oracle.obiettivo.giri"
ROUNDS_PER_ANSWER = "oracle.obiettivo.giri_per_risposta"
_STORE = "api/oracle-store/records"
_PREFIX = re.compile(r"^\s*(obiettivo|goal)\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)
_STOP = re.compile(r"\b(ferma|stop|basta|annulla)\b.*\bobiettivo\b|\bobiettivo\b.*\b(fermati|stop|basta)\b",
                   re.IGNORECASE)

_cache: dict[str, dict | None] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_prefix(message: str) -> str:
    """«obiettivo: X» at the start of a message → X (the goal), else ""."""
    m = _PREFIX.match(message or "")
    return m.group(2).strip()[:500] if m else ""


def is_stop(message: str) -> bool:
    return bool(_STOP.search(message or ""))


# ── storage ──────────────────────────────────────────────────────────────────
def _save(hub, goal: dict, deleted: bool = False) -> None:
    row = {"kind": "goal", "id": goal["id"], "ref_id": goal["session_id"], "at": goal.get("created_at"),
           "data": goal, "updated_at": _now(), "deleted": deleted}
    try:
        ok, res = hub.route_to_service("archive", _STORE, "PUT", body={"rows": [row]}, timeout=6)
        if not ok:
            logger.warning("[🔄] event=goal_store_failed session_id=%s error=%s", goal["session_id"], str(res)[:160])
    except Exception as exc:
        logger.warning("[🔄] event=goal_store_failed session_id=%s error=%s", goal["session_id"], exc)


def active(hub, session_id: str) -> dict | None:
    if not session_id:
        return None
    if session_id in _cache:
        return _cache[session_id]
    goal = None
    try:
        ok, res = hub.route_to_service("archive", _STORE, "GET", query={"kind": "goal", "ref_id": session_id},
                                       timeout=6)
        rows = (res or {}).get("rows") if ok and isinstance(res, dict) else []
        live = [dict(r.get("data") or {}) for r in rows or [] if (r.get("data") or {}).get("state") == "attivo"]
        goal = live[-1] if live else None
    except Exception as exc:
        logger.warning("[🔄] event=goal_load_failed session_id=%s error=%s", session_id, exc)
    _cache[session_id] = goal
    return goal


def set_goal(hub, session_id: str, text: str) -> dict:
    old = active(hub, session_id)
    if old:
        old.update(state="sostituito", ended_at=_now())
        _save(hub, old)
    goal = {"id": f"goal_{uuid.uuid4().hex[:10]}", "session_id": session_id, "text": text.strip()[:500],
            "state": "attivo", "rounds": 0, "notes": [], "created_at": _now()}
    _save(hub, goal)
    _cache[session_id] = goal
    logger.info("event=goal_set session_id=%s goal_id=%s", session_id, goal["id"])
    return goal


def end(hub, session_id: str, state: str, summary: str = "") -> dict | None:
    goal = active(hub, session_id)
    if not goal:
        return None
    goal.update(state=state, ended_at=_now(), summary=str(summary or "")[:1000])
    _save(hub, goal)
    _cache[session_id] = None
    logger.info("event=goal_ended session_id=%s goal_id=%s state=%s rounds=%s", session_id, goal["id"], state,
                goal.get("rounds"))
    return goal


def note_round(hub, goal: dict, answer: str) -> None:
    goal["rounds"] = int(goal.get("rounds") or 0) + 1
    goal["notes"] = (list(goal.get("notes") or []) + [str(answer or "")[:400]])[-6:]
    _save(hub, goal)


def budget() -> tuple[int, int]:
    from core.services import oracle_settings as s
    return s.get_int(TOTAL_ROUNDS, 1), s.get_int(ROUNDS_PER_ANSWER, 1)


def continuation_message(goal: dict) -> str:
    notes = "\n".join(f"- {n}" for n in (goal.get("notes") or [])[-3:])
    total, _ = budget()
    return (f"[OBIETTIVO della conversazione, giro {int(goal.get('rounds') or 0) + 1}/{total}] {goal['text']}\n"
            + (f"Fatto finora:\n{notes}\n" if notes else "")
            + "Fai il prossimo passo con gli strumenti. Se l'obiettivo è raggiunto chiama goal_done con un riepilogo; "
              "se ti serve l'utente chiedi con ask_user. Rispondi breve: cosa hai fatto in questo giro.")


# ── tools for the agent loop ─────────────────────────────────────────────────
def tool_specs() -> list[dict[str, Any]]:
    return [
        {"name": "goal_set", "description": "Fissa un obiettivo per questa conversazione quando l'utente chiede un "
                                            "lavoro lungo su più passi: dopo ogni risposta ci lavori ancora qualche "
                                            "giro e lo aggiorni.",
         "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "L'obiettivo"}},
                        "required": ["text"]}, "title": "Obiettivo"},
        {"name": "goal_done", "description": "L'obiettivo della conversazione è raggiunto: chiudilo con un riepilogo.",
         "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": []},
         "title": "Obiettivo raggiunto"},
        {"name": "goal_stop", "description": "Ferma l'obiettivo della conversazione (l'utente lo chiede).",
         "parameters": {"type": "object", "properties": {}}, "title": "Ferma obiettivo"},
    ]
