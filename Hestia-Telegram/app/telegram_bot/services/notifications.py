"""Telegram as a Hermes notification client (SPEC hermes-global-notifications).

Hermes delivers to every client that declares ``capabilities.notify_endpoint``;
this module renders those notifications as Telegram messages:

- ``notification``: message + inline buttons ``ntf:<id>:<action>``; ``silent``
  ones (pushed to another client) are skipped — Telegram has no inbox.
- ``update``: seen elsewhere / answered → the buttons are replaced by a
  status line ("✓ Vista su WebUI", "✅ Approva · da WebUI").
- ``retract``: delete the message (Hermes asks after the cleanup delay).

A button press goes to Hermes (first answer wins); any user message in the
chat marks the notifications shown here as seen.
"""
from __future__ import annotations

import logging
import threading
from html import escape
from typing import Any

import requests
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot import core

logger = logging.getLogger("hestia_telegram.notifications")

CLIENT_NAME = "telegram"
_CLIENT_LABELS = {"telegram": "Telegram", "webui": "WebUI"}

# Notifications shown in this chat and not yet seen (cleared when the user writes).
_unseen: set[str] = set()
_unseen_lock = threading.Lock()


def _client_label(name: str) -> str:
    return _CLIENT_LABELS.get(str(name or ""), str(name or "un altro client"))


def _hermes(path: str, body: dict | None = None, method: str = "POST", timeout: float = 20) -> tuple[int, Any]:
    try:
        resp = requests.post(
            f"{core.HUB_API_URL}/route/hermes/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": {}, "body": body, "timeout_seconds": timeout},
            timeout=timeout + 1,
        )
        if resp.status_code != 200:
            return resp.status_code, None
        routed = resp.json() or {}
        return int(routed.get("status_code", 500) or 500), routed.get("payload")
    except Exception as exc:
        logger.warning("[🔄] event=hermes_call_failed path=%s error=%s", path, exc)
        return 0, None


def _status_markup(text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(keyboard=[[InlineKeyboardButton(text=text[:60], callback_data="ntf:noop")]])


def _parse_ref(ref: Any) -> tuple[str, int] | None:
    try:
        chat_id, message_id = str(ref or "").split(":", 1)
        return chat_id, int(message_id)
    except (ValueError, TypeError):
        return None


# ── Hermes → Telegram ─────────────────────────────────────────────────────────

def handle_notify(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    kind = str(body.get("kind") or "notification")
    if kind == "update":
        return 200, _apply_update(body)
    if kind == "retract":
        return 200, _retract(body)
    return _deliver(body)


def _deliver(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if body.get("silent"):
        return 200, {"delivered": False, "skipped": True}
    chat_id = core.resolve_notify_target(body.get("target"))
    if not chat_id:
        return 400, {"delivered": False, "detail": "target required (or ALLOWED_USER_ID for target 'owner')"}
    notification_id = str(body.get("notification_id") or "")
    message = str(body.get("message") or "").strip()
    title = str(body.get("title") or "").strip()
    if title and title not in message:
        message = f"<b>{escape(title)}</b>\n{message}" if message else f"<b>{escape(title)}</b>"
    if not message:
        return 400, {"delivered": False, "detail": "message required"}

    markup = None
    buttons = [
        InlineKeyboardButton(text=str(a.get("label") or "")[:40],
                             callback_data=f"ntf:{notification_id}:{a.get('id')}"[:64])
        for a in body.get("actions") or [] if isinstance(a, dict) and a.get("label") and a.get("id")
    ]
    if buttons:
        markup = InlineKeyboardMarkup(keyboard=[buttons])
    try:
        sent = core.send_user_message(chat_id, message, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logger.warning("event=notification_send_failed notification_id=%s error=%s", notification_id, exc)
        return 502, {"delivered": False, "detail": str(exc)[:200]}
    last = sent[-1] if sent else None
    ref = f"{chat_id}:{last.message_id}" if last is not None and getattr(last, "message_id", None) else None
    with _unseen_lock:
        _unseen.add(notification_id)
    logger.info("event=notification_delivered notification_id=%s parts=%d", notification_id, len(sent or []))
    return 200, {"delivered": True, "ref": ref}


def _apply_update(body: dict[str, Any]) -> dict[str, Any]:
    notification_id = str(body.get("notification_id") or "")
    with _unseen_lock:
        _unseen.discard(notification_id)
    target = _parse_ref(body.get("ref"))
    if not target:
        return {"status": "ok", "edited": False}
    state = str(body.get("state") or "")
    text = ""
    if state in ("answered", "expired"):
        answer = body.get("answer") or {}
        if state == "expired" or answer.get("status") == "expired":
            text = "⌛ Scaduta"
        else:
            label = answer.get("label") or answer.get("outcome_text") or "Gestita"
            by = answer.get("by")
            text = f"✅ {label}" + (f" · da {_client_label(by)}" if by and by != CLIENT_NAME else "")
    elif state == "seen":
        seen_by = (body.get("seen") or {}).get("by")
        if not seen_by or seen_by == CLIENT_NAME or body.get("pending"):
            return {"status": "ok", "edited": False}
        text = f"✓ Vista su {_client_label(seen_by)}"
    if not text:
        return {"status": "ok", "edited": False}
    try:
        core.bot.edit_message_reply_markup(chat_id=target[0], message_id=target[1],
                                           reply_markup=_status_markup(text))
        return {"status": "ok", "edited": True}
    except Exception as exc:
        if "not modified" not in str(exc).lower():
            logger.info("event=notification_edit_skipped notification_id=%s error=%s", notification_id, exc)
        return {"status": "ok", "edited": False}


def _retract(body: dict[str, Any]) -> dict[str, Any]:
    target = _parse_ref(body.get("ref"))
    if not target:
        return {"status": "ok", "deleted": False}
    try:
        core.bot.delete_message(target[0], target[1])
        return {"status": "ok", "deleted": True}
    except Exception as exc:
        # Older than 48 h or already gone: nothing else to do.
        logger.info("event=notification_retract_skipped ref=%s error=%s", body.get("ref"), exc)
        return {"status": "ok", "deleted": False}


# ── Telegram → Hermes ─────────────────────────────────────────────────────────

def handle_callback(call) -> None:
    """``ntf:<notification_id>:<action_id>`` button pressed."""
    parts = str(call.data or "").split(":", 2)
    if len(parts) < 3:
        core.bot.answer_callback_query(call.id)  # ntf:noop (status line)
        return
    _, notification_id, action_id = parts
    chat_id = call.message.chat.id
    with _unseen_lock:
        _unseen.discard(notification_id)
    status, payload = _hermes(f"api/notifications/{notification_id}/answer",
                              {"action_id": action_id, "client": CLIENT_NAME})
    payload = payload if isinstance(payload, dict) else {}
    answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}

    if status == 409:
        by = answer.get("by")
        note = f"Già gestita da {_client_label(by)}" if by and by != CLIENT_NAME else "Già gestita"
        core.bot.answer_callback_query(call.id, note)
        try:
            core.bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id,
                                               reply_markup=_status_markup(f"✅ {answer.get('label') or note}"))
        except Exception:
            pass
        return
    if status == 200 and payload.get("execute") == "command":
        # Legacy Hub command action: run it here, then report the outcome.
        from telegram_bot.services.executor import execute_direct_command
        command, _, args = str(payload.get("command") or "").partition(" ")
        ok = True
        try:
            execute_direct_command(command, chat_id, args)
        except Exception as exc:
            ok = False
            logger.warning("event=notification_command_failed notification_id=%s error=%s", notification_id, exc)
        _hermes(f"api/notifications/{notification_id}/answer/outcome",
                {"client": CLIENT_NAME, "ok": ok, "text": "" if ok else "Errore"})
        core.bot.answer_callback_query(call.id, "Comando eseguito" if ok else "Errore")
        return
    if status == 200:
        core.bot.answer_callback_query(call.id, str(answer.get("outcome_text") or "Fatto")[:190])
        return
    detail = payload.get("detail") if isinstance(payload.get("detail"), str) else "riprova più tardi"
    core.bot.answer_callback_query(call.id, f"Non riuscito: {detail}"[:190], show_alert=True)


def mark_seen_on_activity(message) -> None:
    """The user wrote in the chat → the notifications shown here are seen (global state)."""
    if not core.is_allowed_user(getattr(getattr(message, "from_user", None), "id", "")):
        return
    with _unseen_lock:
        if not _unseen:
            return
        _unseen.clear()

    def _send():
        _hermes("api/notifications/seen-all", {"client": CLIENT_NAME, "delivered_to": CLIENT_NAME}, timeout=10)

    threading.Thread(target=_send, daemon=True, name="ntf-seen").start()
