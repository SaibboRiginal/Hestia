"""Voice on Telegram (dossier docs/work/2026-10-20-voice-module §7): voice notes become chat messages, replies can
be listened to, and ``/live`` makes Hestia answer voice notes by voice.

Telegram never touches audio engines: the voice module (Echo) listens and speaks through the Hub
(``hestia_common.voice_client``). The chat stays text: a voice note is transcribed, shown, and handled exactly like
the same sentence typed; every reply gets «Listen»; in live mode a voice note also gets a voice answer (the
text always stays). User texts never name modules.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from html import escape

from telebot import types

from hestia_common.voice_client import VoiceClient
from hestia_common.voice_usecases import capabilities as voice_capabilities, usecase as voice_usecase
from telegram_bot import core
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_telegram.voice")

USE_LISTEN = "telegram.voice_note"
USE_SPEAK = "telegram.answer"
VOICE_USECASES = [
    voice_usecase(USE_LISTEN, "Telegram · voice messages", direction="listen", help="The voice messages you send to the bot."),
    voice_usecase(USE_SPEAK, "Telegram · spoken answers", direction="voice",
                  help="«Listen» under the answers and the answers in live mode."),
]
LIVE_KEY = "voice_live"
LISTEN_CALLBACK = "voice:play"
CANT_LISTEN = "I can't listen to the voice message right now, could you write it?"
CANT_SPEAK = "I can't read it aloud right now, try again shortly."

_client: VoiceClient | None = None
_answers: "OrderedDict[tuple[int, int], str]" = OrderedDict()     # (chat, message) → reply text, for «Listen»
_answers_lock = threading.Lock()


def client() -> VoiceClient:
    global _client
    if _client is None:
        _client = VoiceClient(core.HUB_API_URL)
    return _client


def capabilities() -> dict:
    """Keys for Telegram's Hub registration."""
    return voice_capabilities(VOICE_USECASES)


def ref(chat_id, message_id) -> str:
    """Id of a Telegram message in the kept-audio index."""
    return f"tg:{chat_id}:{message_id}"


# ── live mode ────────────────────────────────────────────────────────────────
def is_live(chat_id) -> bool:
    return str(core.get_session_settings(str(chat_id)).get(LIVE_KEY) or "") == "on"


def set_live(chat_id, on: bool) -> str:
    core.set_session_setting(str(chat_id), LIVE_KEY, "on" if on else "")
    return (tr("<b>Voice replies: on</b>\nI also answer your voice messages aloud.")
            if on else tr("<b>Voice replies: off</b>\nI answer in text; under each answer there is «Listen»."))


# ── listening ────────────────────────────────────────────────────────────────
def transcribe_note(message, audio: bytes, mime_type: str, session_id: str) -> str | None:
    """Text of a voice note (the recording is kept with its message), or None."""
    heard = client().transcribe(audio, mime_type, use_case=USE_LISTEN,
                                keep={"kind": "recording", "session_id": session_id, "client": "telegram",
                                      "message_id": ref(message.chat.id, message.message_id)})
    if not heard:
        return None
    return str(heard["text"]).strip() or None


def heard_html(text: str) -> str:
    return f"<i>«{escape(text)}»</i>"


# ── speaking ─────────────────────────────────────────────────────────────────
def remember_answer(chat_id, message_id, text: str) -> None:
    with _answers_lock:
        _answers[(int(chat_id), int(message_id))] = text
        while len(_answers) > 300:
            _answers.popitem(last=False)


def answer_text(chat_id, message_id) -> str:
    """The reply text of one of Hestia's messages, when this bot still remembers it ("" otherwise)."""
    with _answers_lock:
        return _answers.get((int(chat_id), int(message_id))) or ""


def listen_keyboard(feedback: bool = False, trace_id: str = "") -> types.InlineKeyboardMarkup:
    """One row under the answer: «Listen» and, when a vote is asked, 👍 👎 (the only emoji buttons). ``trace_id``
    (Oracle's id of the turn) rides in the callback so the vote lands on this answer (training dataset)."""
    row = [types.InlineKeyboardButton(tr("Listen"), callback_data=LISTEN_CALLBACK)]
    if feedback:
        tail = f":{trace_id}" if trace_id else ""
        row += [types.InlineKeyboardButton("👍", callback_data=f"fb:good{tail}"),
                types.InlineKeyboardButton("👎", callback_data=f"fb:bad{tail}")]
    return types.InlineKeyboardMarkup(keyboard=[row])


def after_reply(chat_id, renderer, *, spoken: bool, reply_to: int | None = None, feedback: bool = False) -> None:
    """Under a finished reply: «Listen» (+ vote); in live mode after a voice note, the voice answer too."""
    answer = str(getattr(renderer, "answer_text", "") or "").strip()
    ids = list(getattr(renderer, "answer_ids", []) or [])
    if not answer or not ids:
        return
    last = ids[-1]
    remember_answer(chat_id, last, answer)
    try:
        core.bot.edit_message_reply_markup(
            chat_id, last, reply_markup=listen_keyboard(feedback, str(getattr(renderer, "trace_id", "") or "")))
    except Exception as exc:                      # e.g. message already has buttons or was replaced
        logger.debug("event=voice_listen_button_failed chat_id=%s error=%s", chat_id, exc)
    if spoken and is_live(chat_id):
        send_spoken(chat_id, answer, last, reply_to=reply_to)


def send_spoken(chat_id, text: str, answer_message_id: int, *, reply_to: int | None = None) -> bool:
    try:
        core.bot.send_chat_action(chat_id, "record_voice")
    except Exception:
        pass
    spoken = client().speak(text, use_case=USE_SPEAK, fmt="ogg_opus",
                            keep={"kind": "generated", "client": "telegram",
                                  "message_id": ref(chat_id, answer_message_id),
                                  "session_id": core.get_session(chat_id)})
    if not spoken:
        return False
    core.bot.send_voice(chat_id, spoken["audio"], reply_to_message_id=reply_to or answer_message_id,
                        duration=int(float(spoken.get("duration_s") or 0)) or None)
    return True


def handle_listen_callback(call) -> None:
    """«Listen» under a reply."""
    chat_id, message_id = call.message.chat.id, call.message.message_id
    with _answers_lock:
        text = _answers.get((int(chat_id), int(message_id)))
    text = text or str(call.message.text or "")
    try:
        core.bot.answer_callback_query(call.id, tr("Preparing the audio…"))
    except Exception:
        pass
    if not text.strip() or not send_spoken(chat_id, text, message_id):
        core.bot.send_message(chat_id, tr(CANT_SPEAK), reply_to_message_id=message_id)
