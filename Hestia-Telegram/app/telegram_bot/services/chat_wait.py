"""Messages written while the assistant is still answering in the same chat (dossier 2026-11-18-real-test-problems B).

One answer at a time per chat: a text that arrives meanwhile waits (a short note with «Add now» under it) and goes as
the next message when the answer ends; several waiting texts go together, in order. «Add now» hands the text to the
answer being written (Oracle ``/api/chat/steer``, read at its next step); a text the answer did not take (signal
``chat.steer_taken``) still goes next, so nothing is lost.
"""
from __future__ import annotations

import logging
import threading
import uuid

from telegram_bot import core, ui
from hestia_common.i18n import t as tr

logger = logging.getLogger("hestia_telegram.chat_wait")

CALLBACK = "cw:"
_lock = threading.Lock()
_busy: dict[str, dict] = {}       # chat → {"session": id, "held": [{"id", "text", "note_id", "sent"}]}


def start(chat_id, session_id: str) -> bool:
    """True = the chat was free and its answer starts now; False = an answer is running (hold the text)."""
    with _lock:
        if str(chat_id) in _busy:
            return False
        _busy[str(chat_id)] = {"session": session_id, "held": []}
        return True


def hold(message, chat_id, text: str, status_msg=None) -> bool:
    """Keep *text* for the next turn; the note under it offers «Add now». False = no answer runs now."""
    text = str(text or "").strip()
    if not text:
        return True                # nothing to keep
    item = {"id": uuid.uuid4().hex[:12], "text": text, "note_id": None, "sent": False}
    with _lock:
        state = _busy.get(str(chat_id))
        if state is None:          # the answer just ended: the caller starts a turn instead
            return False
        state["held"].append(item)
    note = tr("<i>Waiting: it goes as soon as the answer ends.</i>")
    markup = ui.keyboard([[ui.button(tr("Add now"), f"{CALLBACK}{item['id']}")]])
    try:
        if status_msg is not None:
            core.bot.edit_message_text(note, chat_id=chat_id, message_id=status_msg.message_id, parse_mode="HTML",
                                       reply_markup=markup)
            item["note_id"] = status_msg.message_id
        else:
            sent = (core.bot.reply_to(message, note, parse_mode="HTML", reply_markup=markup) if message is not None
                    else core.bot.send_message(chat_id, note, parse_mode="HTML", reply_markup=markup))
            item["note_id"] = getattr(sent, "message_id", None)
    except Exception as exc:  # noqa: BLE001 — the text is held anyway
        logger.warning("[🔄] event=chat_wait_note_failed chat_id=%s error=%s", chat_id, exc)
    logger.info("event=chat_message_held chat_id=%s held=%d", chat_id, len(state["held"]))
    return True


def finish(chat_id, signals: list[dict] | None) -> list[dict]:
    """The answer ended: drop what it took with «Add now»; return what goes next (the chat stays busy for it),
    or [] and the chat is free."""
    taken: set[str] = set()
    for s in signals or []:
        if s.get("event") == "chat.steer_taken":
            taken.update(str(i) for i in ((s.get("data") or {}).get("ids") or []))
    with _lock:
        state = _busy.get(str(chat_id))
        if state is None:
            return []
        left = [h for h in state["held"] if h["id"] not in taken]
        if not left:
            _busy.pop(str(chat_id), None)
            return []
        state["held"] = []
    for h in left:                 # the note goes: its text is about to be answered
        _clear_button(chat_id, h)
    return left


def release(chat_id) -> None:
    with _lock:
        _busy.pop(str(chat_id), None)


def _clear_button(chat_id, item: dict) -> None:
    if not item.get("note_id"):
        return
    try:
        core.bot.edit_message_reply_markup(chat_id, item["note_id"], reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


def is_callback(data: str) -> bool:
    return str(data or "").startswith(CALLBACK)


def handle_callback(call) -> None:
    """«Add now» under a waiting text."""
    item_id = str(call.data or "")[len(CALLBACK):]
    chat_id = call.message.chat.id
    with _lock:
        state = _busy.get(str(chat_id)) or {}
        item = next((h for h in state.get("held", []) if h["id"] == item_id), None)
        session = state.get("session", "")
    if item is None:
        core.bot.answer_callback_query(call.id, tr("Already sent"))
        return
    if item["sent"]:
        core.bot.answer_callback_query(call.id)
        return
    status, result = core.oracle_post("api/chat/steer", {"session_id": session, "text": item["text"],
                                                         "id": item_id}, timeout=10)
    if 0 < status < 400 and (result or {}).get("accepted"):
        item["sent"] = True
        try:
            core.bot.edit_message_text(tr("<i>Added to the answer being written.</i>"), chat_id=chat_id,
                                       message_id=call.message.message_id, parse_mode="HTML", reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        core.bot.answer_callback_query(call.id, tr("Added"))
        return
    core.bot.answer_callback_query(call.id, tr("This answer cannot take it: it goes as soon as the answer ends."))


def joined(items: list[dict]) -> str:
    return "\n\n".join(h["text"] for h in items)
