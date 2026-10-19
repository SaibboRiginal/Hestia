"""Chat queue — messages written while the brain (Oracle) is offline.

SPEC docs/work/2026-10-19-cervello-offline §3. A message Oracle did not accept is stored in Archive
(``/api/chat-queue``, client ``telegram``) and the user gets a fixed reply. When the brain is back, Chronos calls
``POST /api/chat-queue/drain`` (capability ``chat_queue_drain``); the same drain runs at startup. Oldest first,
one at a time, each answered as a reply to the original message.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from html import escape
from typing import Any

import requests

from telegram_bot import core

logger = logging.getLogger("hestia_telegram.chat_queue")

CLIENT = "telegram"
DRAIN_PATH = "/api/chat-queue/drain"
FILE_OFFLINE_TEXT = ("🧠 <b>Il cervello è offline</b>: non posso leggere il file adesso. "
                     "Rimandamelo appena torno.")
_drain_lock = threading.Lock()


def _archive(method: str, path: str, body: Any = None, query: dict | None = None,
             timeout: float = 8) -> tuple[int, Any]:
    try:
        resp = requests.post(f"{core.HUB_API_URL}/route/archive/{path.lstrip('/')}",
                             json={"method": method, "headers": {}, "query": query or {}, "body": body,
                                   "timeout_seconds": timeout}, timeout=timeout + 4)
        if resp.status_code != 200:
            return resp.status_code, None
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")
    except Exception as exc:
        logger.warning("[🔄] event=chat_queue_archive_failed path=%s error=%s", path, exc)
        return 0, None


def enqueue(chat_id, session_id: str, text: str, message_id: int | None, error: Exception | str = "") -> dict | None:
    """Store a message Oracle did not accept. ``None`` when Archive is unreachable too (caller shows the error)."""
    if not str(text or "").strip():
        return None
    status, item = _archive("POST", "api/chat-queue", {
        "client": CLIENT, "session_id": session_id, "target": str(chat_id), "text": text,
        "client_ref": str(message_id) if message_id is not None else None,
        "meta": {"error": str(error)[:300]}})
    if status >= 400 or not isinstance(item, dict):
        logger.warning("[🔄] event=chat_queue_enqueue_failed chat=%s status=%s", chat_id, status)
        return None
    logger.info("[🔄] event=chat_queued id=%s position=%s error=%s", item.get("id"), item.get("position"),
                str(error)[:120])
    return item


def queued_text(item: dict) -> str:
    position = int(item.get("position") or 1)
    where = f" (n° {position})" if position > 1 else ""
    return (f"🧠 <b>Il cervello è offline</b>: messaggio in coda{where}, "
            "ti rispondo appena torna.")


def _note(item: dict) -> str:
    created = str(item.get("created_at") or "")
    try:
        when = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone().strftime("%d/%m %H:%M")
    except ValueError:
        when = created[:16]
    return (f"Nota: questo messaggio è stato scritto alle {when} mentre eri offline; rispondi ora tenendo conto "
            "del tempo passato.")


def drain_async(reason: str = "") -> bool:
    """Start a drain in the background; False when one is already running."""
    if _drain_lock.locked():
        return False
    threading.Thread(target=drain, args=(reason,), daemon=True, name="telegram-chat-drain").start()
    return True


def drain(reason: str = "") -> dict:
    """Answer the queued messages, oldest first. Stops at the first Oracle failure (still offline)."""
    if not _drain_lock.acquire(blocking=False):
        return {"status": "busy"}
    answered = failed = 0
    try:
        status, payload = _archive("GET", "api/chat-queue", query={"client": CLIENT, "state": "queued"})
        items = (payload or {}).get("items") if isinstance(payload, dict) else None
        if status >= 400 or not items:
            return {"status": "ok", "answered": 0}
        logger.info("event=chat_queue_drain_start items=%d reason=%s", len(items), reason or "-")
        per_chat: dict[str, int] = {}
        for item in items:
            per_chat[str(item.get("target"))] = per_chat.get(str(item.get("target")), 0) + 1
        headed: set[str] = set()
        for item in items:
            target = str(item.get("target") or "")
            if not target:
                continue
            code, claimed = _archive("POST", f"api/chat-queue/{item['id']}/claim")
            if code >= 400 or not isinstance(claimed, dict):
                continue      # another drain holds it
            if per_chat.get(target, 0) > 1 and target not in headed:
                headed.add(target)
                try:
                    core.bot.send_message(int(target), f"🧠 Rispondo ai {per_chat[target]} messaggi arrivati "
                                                       "mentre ero offline.", parse_mode="HTML")
                except Exception:
                    pass
            ok, detail = _answer(item)
            _archive("POST", f"api/chat-queue/{item['id']}/done", {"ok": ok, "detail": detail})
            if ok:
                answered += 1
                continue
            failed += 1
            break
        logger.info("event=chat_queue_drain_done answered=%d failed=%d", answered, failed)
        return {"status": "ok", "answered": answered, "failed": failed}
    finally:
        _drain_lock.release()


def _answer(item: dict) -> tuple[bool, str]:
    from telegram_bot.services.chat_service import OracleUnavailable, ask_oracle, send_oracle_questions

    chat_id = int(item["target"])
    ref = item.get("client_ref")
    try:
        status_msg = core.bot.send_message(
            chat_id, "⏳ <b>Rispondo al messaggio in coda...</b>", parse_mode="HTML",
            reply_to_message_id=int(ref) if ref and str(ref).isdigit() else None,
            allow_sending_without_reply=True)
    except Exception as exc:
        return False, f"telegram: {exc}"[:300]
    try:
        result = ask_oracle(chat_id, str(item["session_id"]), str(item["text"]), status_msg.message_id,
                            extra_instructions=_note(item))
        send_oracle_questions(chat_id, str(item["session_id"]), result.signals, result.questions)
        return True, ""
    except OracleUnavailable as exc:
        core.bot.edit_message_text(f"🧠 Il cervello non risponde ancora: resto in coda.\n<code>{escape(str(exc))}</code>",
                                   chat_id=chat_id, message_id=status_msg.message_id, parse_mode="HTML")
        return False, str(exc)[:300]
    except Exception as exc:
        core.bot.edit_message_text(f"⚠️ <b>Risposta non riuscita</b>\n<code>{escape(str(exc))}</code>",
                                   chat_id=chat_id, message_id=status_msg.message_id, parse_mode="HTML")
        return False, str(exc)[:300]
