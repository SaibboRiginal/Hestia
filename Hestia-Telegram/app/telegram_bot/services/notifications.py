"""Telegram as a Hermes notification client (SPEC hermes-global-notifications).

Hermes delivers to every client that declares ``capabilities.notify_endpoint``;
this module renders those notifications as Telegram messages:

- ``notification``: tone dot + bold title, message, buttons two per row ``na:<short id>``; ``silent``
  ones (pushed to another client) are skipped — Telegram has no inbox.
- ``update``: seen elsewhere / answered → the buttons are replaced by one status line that does nothing
  («Vista su WebUI», «Fatto · da WebUI»).
- ``retract``: delete the message (Hermes asks after the cleanup delay).
- ``update`` with ``voice``: the module wanted it also as audio → a voice message replying to the
  notification (deleted together with it).
- repeat chains: a reminder sent again carries ``repeat.text`` («Saltato 2 volte»),
  shown in italics; the previous one arrives as ``update`` ``superseded`` and is
  deleted (over 48 h Telegram refuses: its buttons become «Sostituito»).

A button press goes to Hermes (first answer wins); any user message in the
chat marks the notifications shown here as seen.
"""
from __future__ import annotations

import base64
import logging
import re
import threading
from typing import Any

import requests

from telegram_bot import core, store, ui
logger = logging.getLogger("hestia_telegram.notifications")

CLIENT_NAME = "telegram"
_CLIENT_LABELS = {"telegram": "Telegram", "webui": "WebUI"}

# Notifications shown in this chat and not yet seen (cleared when the user writes).
_unseen: set[str] = set()
_unseen_lock = threading.Lock()
# Voice message sent under a notification: notification id → (chat id, message id), to delete it with the text.
_voices: dict[str, tuple[str, int]] = {}


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


def _status_markup(text: str):
    """The buttons of an answered notification become one status line that does nothing."""
    return ui.keyboard([[ui.button(text, disabled=True, limit=40)]])


def action_buttons(notification_id: str, actions: list) -> list:
    """Hermes actions → rows of at most two buttons (one per row when a label is long). Callback ``na:<id>``:
    a short id of ``notification|action``, so a long notification id is never cut."""
    buttons = []
    for a in actions or []:
        if not isinstance(a, dict) or not a.get("label") or not a.get("id"):
            continue
        style = str(a.get("style") or "")
        if not style:
            style = "danger" if str(a.get("id")).lower() in ("delete", "elimina", "reject", "rifiuta") else ""
        buttons.append(ui.button(str(a["label"]), f"na:{store.sid(f'{notification_id}|{a['id']}')}",
                                 style=style, limit=32))
    return ui.grid(buttons)


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


def render_notification(body: dict[str, Any]) -> str:
    """🟠 <b>Title</b> / message / <i>Saltato 2 volte</i> — the tone dot from the level, no other emoji."""
    title = ui.strip_emoji(body.get("title") or "")
    message = str(body.get("message") or "").strip()
    if message[:1] and ui._is_emoji_char(message[0]):
        message = ui.strip_emoji(message.split(" ", 1)[0]) + (" " + message.split(" ", 1)[1] if " " in message else "")
        message = message.strip()
    if not title and not message:
        return ""
    if not title:
        first, _, rest = message.partition("\n")
        title, message = re.sub(r"<[^>]+>", "", first)[:80], rest.strip()
    tone = ui.LEVEL_TONE.get(str(body.get("level") or "info").lower(), "info")
    lines = [message] if message and message != title else []
    repeat_text = str((body.get("repeat") or {}).get("text") or "").strip()
    if repeat_text:
        lines.append(ui.note(repeat_text))
    return ui.card(title, lines, tone=tone)


def _deliver(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if body.get("silent"):
        return 200, {"delivered": False, "skipped": True}
    chat_id = core.resolve_notify_target(body.get("target"))
    if not chat_id:
        return 400, {"delivered": False, "detail": "target required (or ALLOWED_USER_ID for target 'owner')"}
    notification_id = str(body.get("notification_id") or "")
    html = render_notification(body)
    if not html:
        return 400, {"delivered": False, "detail": "message required"}
    rows = action_buttons(notification_id, body.get("actions") or [])
    link = body.get("link") if isinstance(body.get("link"), dict) else {}
    if link.get("module") and link.get("page"):
        from telegram_bot import webapp
        button = webapp.open_button("Apri", f"/p/{link['module']}/{link['page']}")
        if button:
            rows.append([button])
    markup = ui.keyboard(rows)
    try:
        sent = core.send_user_message(chat_id, html, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logger.warning("event=notification_send_failed notification_id=%s error=%s", notification_id, exc)
        return 502, {"delivered": False, "detail": str(exc)[:200]}
    last = sent[-1] if sent else None
    ref = f"{chat_id}:{last.message_id}" if last is not None and getattr(last, "message_id", None) else None
    if last is not None and getattr(last, "message_id", None):
        from telegram_bot.services.chat_service import remember_notification_message
        remember_notification_message(chat_id, last.message_id, notification_id)
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
    if isinstance(body.get("voice"), dict) and not body.get("state"):
        return _send_voice(notification_id, target, body["voice"])
    state = str(body.get("state") or "")
    text = ""
    if state == "superseded":
        # A newer occurrence of the same reminder was sent: never two in the chat.
        if _retract(body).get("deleted"):
            return {"status": "ok", "deleted": True}
        text = "Sostituito"
    elif state in ("answered", "expired"):
        answer = body.get("answer") or {}
        if state == "expired" or answer.get("status") == "expired":
            text = "Scaduta"
        else:
            label = answer.get("label") or answer.get("outcome_text") or "Gestita"
            by = answer.get("by")
            text = ui.strip_emoji(label) + (f" · da {_client_label(by)}" if by and by != CLIENT_NAME else "")
    elif state == "seen":
        seen_by = (body.get("seen") or {}).get("by")
        if not seen_by or seen_by == CLIENT_NAME or body.get("pending"):
            return {"status": "ok", "edited": False}
        text = f"Vista su {_client_label(seen_by)}"
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


def _send_voice(notification_id: str, target: tuple[str, int], voice: dict[str, Any]) -> dict[str, Any]:
    try:
        audio = base64.b64decode(str(voice.get("audio_b64") or ""))
    except (ValueError, TypeError):
        audio = b""
    if not audio:
        return {"status": "ok", "voice": False}
    try:
        sent = core.bot.send_voice(target[0], audio, reply_to_message_id=target[1],
                                   duration=int(float(voice.get("duration_s") or 0)) or None)
    except Exception as exc:
        logger.info("event=notification_voice_send_failed notification_id=%s error=%s", notification_id, exc)
        return {"status": "ok", "voice": False}
    if getattr(sent, "message_id", None):
        _voices[notification_id] = (target[0], int(sent.message_id))
        while len(_voices) > 500:
            _voices.pop(next(iter(_voices)))
    return {"status": "ok", "voice": True}


def _retract(body: dict[str, Any]) -> dict[str, Any]:
    voice = _voices.pop(str(body.get("notification_id") or ""), None)
    if voice:
        try:
            core.bot.delete_message(voice[0], voice[1])
        except Exception as exc:
            logger.info("event=notification_voice_retract_skipped error=%s", exc)
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
    """``na:<short id>`` (``ntf:<notification_id>:<action_id>`` on older messages) button pressed."""
    data = str(call.data or "")
    if data.startswith("na:"):
        notification_id, _, action_id = str(store.resolve(data[3:]) or "").partition("|")
    else:
        parts = data.split(":", 2)
        notification_id, action_id = (parts[1], parts[2]) if len(parts) == 3 else ("", "")
    if not notification_id or not action_id:
        core.bot.answer_callback_query(call.id, "Questa notifica è vecchia")
        return
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
        status_line = ui.strip_emoji(answer.get("label") or note)
        if payload.get("state") == "superseded":
            note, status_line = "Sostituita da un promemoria più recente", "Sostituito"
        core.bot.answer_callback_query(call.id, note)
        try:
            core.bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id,
                                               reply_markup=_status_markup(status_line))
        except Exception:
            pass
        return
    if status == 200 and payload.get("execute") == "command":
        # Legacy Hub command action: the same action flow as a typed command, then report the outcome.
        from telegram_bot import actions
        command, _, args = str(payload.get("command") or "").lstrip("/").partition(" ")
        try:
            ok = actions.from_command(chat_id, command, args)
        except Exception as exc:  # noqa: BLE001
            ok = False
            logger.warning("event=notification_command_failed notification_id=%s error=%s", notification_id, exc)
        _hermes(f"api/notifications/{notification_id}/answer/outcome",
                {"client": CLIENT_NAME, "ok": ok, "text": "" if ok else "Non riuscito"})
        core.bot.answer_callback_query(call.id, "Fatto" if ok else "Non riuscito")
        return
    if status == 200:
        core.bot.answer_callback_query(call.id, ui.strip_emoji(answer.get("outcome_text") or "Fatto")[:190])
        return
    logger.warning("event=notification_answer_failed notification_id=%s status=%s", notification_id, status)
    core.bot.answer_callback_query(call.id, "Non riuscito, riprova tra poco", show_alert=True)


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
