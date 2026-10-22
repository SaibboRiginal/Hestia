"""Questions the assistant asks in this chat (docs/work/2026-10-19-oracle-offline v3 A).

Oracle streams a ``question`` frame (id ``ask_…``) when the model calls ``ask_user``. Here it becomes inline buttons:
confirm and single choice answer at once; multiple choice toggles options (✓) then «Invia»; free text — and the
«Altro…» of a choice that allows it — is the next message written in the chat. The answer goes to Oracle, which
returns ``resume.message``: sent as the next chat turn, so the reply arrives here like any other.
"""
from __future__ import annotations

import logging
import time
import uuid
from html import escape

import requests
from telebot import types

from telegram_bot import core

logger = logging.getLogger("hestia_telegram.assistant_questions")

TEXT_FLOW = "assistant_question_text"
_PREFIXES = ("ask:", "askt:", "asks:")


def is_callback(data: str) -> bool:
    return str(data or "").startswith(_PREFIXES)


def _keyboard(token: str, entry: dict) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    opts = entry["options"]
    if entry["kind"] == "multi_choice":
        for i, o in enumerate(opts):
            mark = "✓ " if o["value"] in entry["picked"] else ""
            markup.row(types.InlineKeyboardButton(f"{mark}{o['label']}"[:60], callback_data=f"askt:{token}:{i}"))
        markup.row(types.InlineKeyboardButton("Invia", callback_data=f"asks:{token}"))
        return markup
    row = [types.InlineKeyboardButton(str(o["label"])[:60], callback_data=f"ask:{token}:{i}") for i, o in enumerate(opts)]
    if len(row) <= 3 and sum(len(o["label"]) for o in opts) <= 30:
        markup.row(*row)
    else:
        for button in row:
            markup.row(button)
    return markup


def send(chat_id, session_id: str, question: dict) -> None:
    options = [o if isinstance(o, dict) else {"label": str(o), "value": str(o)} for o in (question.get("options") or [])]
    options = [{"label": str(o.get("label") or o.get("value")), "value": str(o.get("value") or o.get("label"))}
               for o in options if o.get("value") or o.get("label")]
    kind = str(question.get("kind") or ("single_choice" if options else "free_text"))
    token = uuid.uuid4().hex[:16]
    entry = {"action": "assistant_question", "chat_id": str(chat_id), "session_id": session_id,
             "question_id": str(question.get("question_id")), "kind": kind, "options": options, "picked": [],
             "created_at": int(time.time())}
    core.PENDING_CONFIRMATIONS[token] = entry
    free = kind == "free_text" or not options or bool(question.get("allow_other"))
    hint = {"multi_choice": "Scegli una o più risposte, poi «Invia».",
            "free_text": "Scrivi la risposta qui sotto."}.get(kind, "")
    if free and options:
        hint = (hint + " " if hint else "") + "Oppure scrivi un'altra risposta."
    text = f"❓ <b>{escape(str(question.get('header') or 'Domanda'))}</b>"
    if question.get("prompt"):
        text += f"\n{escape(str(question['prompt']))}"
    if hint:
        text += f"\n<i>{escape(hint)}</i>"
    core.bot.send_message(int(chat_id), text, parse_mode="HTML",
                          reply_markup=_keyboard(token, entry) if options else None)
    if free:
        core.PENDING_WORKFLOWS[str(chat_id)] = {"action": TEXT_FLOW, "token": token}
    logger.info("event=assistant_question_sent chat=%s question_id=%s kind=%s", chat_id, entry["question_id"], kind)


def handle_callback(call) -> None:
    action, _, rest = call.data.partition(":")
    token, _, idx = rest.partition(":")
    entry = core.PENDING_CONFIRMATIONS.get(token)
    if not entry:
        core.bot.answer_callback_query(call.id, "Domanda scaduta")
        return
    if action == "askt":
        value = entry["options"][int(idx)]["value"]
        entry["picked"] = [v for v in entry["picked"] if v != value] if value in entry["picked"] else [*entry["picked"], value]
        core.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                           reply_markup=_keyboard(token, entry))
        core.bot.answer_callback_query(call.id)
        return
    if action == "asks":
        if not entry["picked"]:
            core.bot.answer_callback_query(call.id, "Scegli almeno una risposta")
            return
        answer = "\n".join(entry["picked"])
        shown = ", ".join(o["label"] for o in entry["options"] if o["value"] in entry["picked"])
    else:
        option = entry["options"][int(idx)]
        answer, shown = option["value"], option["label"]
    # Answer the tap at once: the reply that follows is a whole chat turn.
    core.bot.answer_callback_query(call.id, shown[:60])
    original = call.message.html_text or call.message.text
    core.bot.edit_message_text(f"{original}\n\n<b>{escape(shown)}</b> ✓", chat_id=call.message.chat.id,
                               message_id=call.message.message_id, parse_mode="HTML")
    if not _submit(call.message, token, entry, answer):
        core.bot.edit_message_text(original, chat_id=call.message.chat.id, message_id=call.message.message_id,
                                   parse_mode="HTML", reply_markup=_keyboard(token, entry))
        core.bot.send_message(call.message.chat.id, "⚠️ Risposta non inviata: riprova tra poco.")


def answer_text(message, flow: dict, text: str) -> bool:
    """The next message as the answer; False when the question is gone (the message is a normal chat turn)."""
    token = str(flow.get("token") or "")
    entry = core.PENDING_CONFIRMATIONS.get(token)
    if not entry or not text or text.startswith("/"):
        return False
    if entry["kind"] == "multi_choice" and entry["picked"]:
        text = "\n".join([*entry["picked"], text])
    return _submit(message, token, entry, text)


def _submit(reply_to, token: str, entry: dict, answer: str) -> bool:
    """Answer → Oracle; its ``resume.message`` goes on as the next turn of this chat."""
    oracle_base_url = core.resolve_oracle_chat_url().rsplit("/api/chat", 1)[0]
    try:
        response = requests.post(f"{oracle_base_url}/api/chat/question-answer", json={
            "session_id": entry["session_id"], "question_id": entry["question_id"], "answer": answer,
            "client": "telegram"}, timeout=20)
        result = response.json() if response.content else {}
    except Exception as error:
        logger.warning("[🔄] event=assistant_question_answer_failed question_id=%s error=%s", entry["question_id"], error)
        return False
    core.PENDING_CONFIRMATIONS.pop(token, None)
    if core.PENDING_WORKFLOWS.get(entry["chat_id"], {}).get("token") == token:
        core.PENDING_WORKFLOWS.pop(entry["chat_id"], None)
    if response.status_code == 404:
        core.bot.send_message(int(entry["chat_id"]), "⌛ Questa domanda non è più aperta: scrivimi di nuovo.")
        return True
    if response.status_code >= 400:
        return False
    resume = str((result.get("resume") or {}).get("message") or "")
    if resume:
        from telegram_bot.services.chat_service import run_chat_turn
        run_chat_turn(reply_to, int(entry["chat_id"]), resume)
    logger.info("event=assistant_question_answered question_id=%s resumed=%s", entry["question_id"], bool(resume))
    return True
