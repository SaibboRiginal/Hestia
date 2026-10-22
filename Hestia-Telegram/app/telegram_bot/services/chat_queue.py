"""Chat queue — messages written while Oracle is offline.

SPEC docs/work/2026-10-19-oracle-offline §3. A message Oracle did not accept is stored in Archive
(``/api/chat-queue``, client ``telegram``) and the user gets a fixed reply. When Oracle is back, Chronos calls
``POST /api/chat-queue/drain`` (capability ``chat_queue_drain``); the same drain runs at startup. Chat by chat,
all of a chat's messages in one turn where the assistant decides how to answer (v3 C), as a reply to the last one.
"""
from __future__ import annotations

import logging
import threading
from html import escape
from typing import Any

import requests

from telegram_bot import core

logger = logging.getLogger("hestia_telegram.chat_queue")

CLIENT = "telegram"
DRAIN_PATH = "/api/chat-queue/drain"
FILE_OFFLINE_TEXT = ("⏳ <b>Non posso rispondere adesso</b>: non riesco a leggere il file. "
                     "Rimandamelo più tardi.")
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
    return (f"⏳ <b>Non posso rispondere adesso</b>: messaggio in coda{where}, "
            "ti rispondo appena possibile.")


def drain_async(reason: str = "") -> bool:
    """Start a drain in the background; False when one is already running."""
    if _drain_lock.locked():
        return False
    threading.Thread(target=drain, args=(reason,), daemon=True, name="telegram-chat-drain").start()
    return True


def drain(reason: str = "") -> dict:
    """Answer the queued messages chat by chat (oldest chat first). Stops at the first Oracle failure (still offline).
    All messages of one chat go to the assistant in one turn (``queued``): it decides whether to answer each, merge
    them, or ask which old ones still matter (oracle-offline v3 C)."""
    if not _drain_lock.acquire(blocking=False):
        return {"status": "busy"}
    answered = failed = 0
    try:
        status, payload = _archive("GET", "api/chat-queue", query={"client": CLIENT, "state": "queued"})
        items = (payload or {}).get("items") if isinstance(payload, dict) else None
        if status >= 400 or not items:
            return {"status": "ok", "answered": 0}
        logger.info("event=chat_queue_drain_start items=%d reason=%s", len(items), reason or "-")
        chats: dict[tuple[str, str], list[dict]] = {}
        for item in items:                     # oldest first: dict order = first message of each chat
            if str(item.get("target") or ""):
                chats.setdefault((str(item["target"]), str(item.get("session_id") or "")), []).append(item)
        for chat_items in chats.values():
            claimed = []
            for item in chat_items:
                code, got = _archive("POST", f"api/chat-queue/{item['id']}/claim")
                if code < 400 and isinstance(got, dict):
                    claimed.append(item)      # else another drain holds it
            if not claimed:
                continue
            ok, detail = _answer(claimed)
            for item in claimed:
                _archive("POST", f"api/chat-queue/{item['id']}/done", {"ok": ok, "detail": detail})
            if ok:
                answered += len(claimed)
                continue
            failed += len(claimed)
            break
        logger.info("event=chat_queue_drain_done answered=%d failed=%d", answered, failed)
        return {"status": "ok", "answered": answered, "failed": failed}
    finally:
        _drain_lock.release()


def _answer(items: list[dict]) -> tuple[bool, str]:
    from telegram_bot.services.chat_service import OracleUnavailable, ask_oracle, send_oracle_questions

    last = items[-1]
    chat_id = int(last["target"])
    ref = last.get("client_ref")
    what = "al messaggio in coda" if len(items) == 1 else f"ai {len(items)} messaggi in coda"
    try:
        status_msg = core.bot.send_message(
            chat_id, f"⏳ <b>Rispondo {what}...</b>", parse_mode="HTML",
            reply_to_message_id=int(ref) if ref and str(ref).isdigit() else None,
            allow_sending_without_reply=True)
    except Exception as exc:
        return False, f"telegram: {exc}"[:300]
    queued = [{"text": str(i["text"]), "written_at": i.get("created_at")} for i in items]
    try:
        result = ask_oracle(chat_id, str(last["session_id"]), "", status_msg.message_id, queued=queued)
        send_oracle_questions(chat_id, str(last["session_id"]), result.signals, result.questions)
        return True, ""
    except OracleUnavailable as exc:
        core.bot.edit_message_text("⏳ Non posso ancora rispondere: resto in coda.",
                                   chat_id=chat_id, message_id=status_msg.message_id, parse_mode="HTML")
        return False, str(exc)[:300]
    except Exception as exc:
        core.bot.edit_message_text(f"⚠️ <b>Risposta non riuscita</b>\n<code>{escape(str(exc))}</code>",
                                   chat_id=chat_id, message_id=status_msg.message_id, parse_mode="HTML")
        return False, str(exc)[:300]
