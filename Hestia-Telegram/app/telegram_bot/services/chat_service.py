"""Chat with the assistant (docs/work/2026-10-23-telegram-da-zero §7, §5.10).

A message (typed, voice note, file) is one chat turn: Oracle streams the answer into one message (``ReplyRenderer``),
notices go under it in italics, «Ascolta» and the vote share one row. A reply to a message — or a quote of part of
it — goes to the assistant as context (``quoted``). Confirm cards Oracle asks for (approvals, module questions,
the assistant's own questions) are buttons whose state is persisted (``store``), so they survive a restart.
"""
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from html import escape
from typing import Any

import requests

from telegram_bot import core, store, ui
from telegram_bot.services import assistant_questions, chat_queue, voice_service
from telegram_bot.services.reply_renderer import ReplyRenderer

logger = logging.getLogger("hestia_telegram.chat_service")

WORKING = "<i>Sto pensando…</i>"


def consume_oracle_stream(res, renderer: "ReplyRenderer", signals: list, questions: list) -> None:
    """Read Oracle NDJSON frames into the renderer. Standard frames: status, thinking,
    token, final, notice (system packets), question; legacy `signal` kept for flows."""
    for line in res.iter_lines():
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            logger.warning("event=oracle_stream_bad_line len=%d", len(line))
            continue
        kind = data.get("type")
        if kind == "status":
            renderer.on_status(str(data.get("content") or ""))
        elif kind == "thinking":
            renderer.on_thinking(data)
        elif kind == "token":
            renderer.on_token(str(data.get("text") or ""))
        elif kind == "final":
            # Render the answer immediately; notices may still arrive (memory) and are added after.
            renderer.on_final(str(data.get("reply") or ""))
        elif kind == "notice":
            renderer.on_notice(data)
        elif kind == "signal":
            signals.append(data)
        elif kind == "question":
            questions.append(data)
        elif kind == "error":
            logger.warning("event=oracle_stream_error detail=%s", str(data.get("message") or data.get("content"))[:300])
            renderer.on_notice({"type": "notice", "kind": "error", "level": "error",
                                "title": "Non sono riuscita a finire la risposta", "detail": "riprova tra poco"})


class OracleUnavailable(Exception):
    """Oracle never accepted the request (down, unreachable, not registered): the message can be queued
    (SPEC docs/work/2026-10-19-oracle-offline §3). An error inside an answer is not this."""


@dataclass
class OracleResult:
    renderer: "ReplyRenderer"
    signals: list
    questions: list


_DOWN_STATUSES = {502, 503, 504}


# ── reply = context (§5.10) ──────────────────────────────────────────────────

def remember_notification_message(chat_id, message_id, notification_id: str) -> None:
    """A delivered notification: a reply to it carries its id."""
    store.put_pending(f"msg:{chat_id}:{message_id}", {"notification_id": str(notification_id)})


def quoted_of(message) -> dict | None:
    """``{text, from, at, ref}`` of the message this one replies to (only the quoted part when there is one)."""
    target = getattr(message, "reply_to_message", None)
    if target is None:
        return None
    quote = getattr(message, "quote", None)
    text = str(getattr(quote, "text", "") or "") or str(getattr(target, "text", "") or
                                                          getattr(target, "caption", "") or "")
    if not text.strip():
        return None
    sender = getattr(target, "from_user", None)
    kind = "assistant" if getattr(sender, "is_bot", False) else "user"
    chat_id = getattr(getattr(message, "chat", None), "id", "")
    ref = f"telegram:{chat_id}:{getattr(target, 'message_id', '')}"
    hit = store.get_pending(f"msg:{chat_id}:{getattr(target, 'message_id', '')}")
    if hit and hit.get("notification_id"):
        kind, ref = "notification", f"notification:{hit['notification_id']}"
    at = getattr(target, "date", None)
    return {"text": text.strip()[:2000], "from": kind, "ref": ref,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(at)) if at else None}


# ── one turn ─────────────────────────────────────────────────────────────────

def ask_oracle(chat_id, session_id: str, user_text: str, status_message_id: int,
               extra_instructions: str = "", queued: list[dict] | None = None,
               quoted: dict | None = None) -> OracleResult:
    """Stream one chat turn from Oracle into a renderer on ``status_message_id``.
    ``queued``: messages written while the assistant could not answer ([{text, written_at}]), answered in one turn
    where the assistant decides how (oracle-offline v3 C). ``quoted``: the message replied to (context).
    Raises ``OracleUnavailable`` when Oracle did not accept the request."""
    session_settings = core.get_session_settings(str(chat_id))
    renderer = ReplyRenderer(chat_id, status_message_id, session_settings)
    signals: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    instructions = core.build_client_instructions_for_chat(str(chat_id))
    if extra_instructions:
        instructions = f"{instructions}\n{extra_instructions}" if instructions else extra_instructions
    try:
        res_cm = requests.post(
            core.resolve_oracle_chat_url(),
            json={
                "message": user_text,
                "session_id": session_id,
                "notify_target": str(chat_id),
                "force_notification_compiler": False,
                "client_instructions": instructions,
                "client": "telegram",
                **({"queued": queued} if queued else {}),
                **({"quoted": quoted} if quoted else {}),
            },
            stream=True,
            # (connect, max silence between chunks)
            timeout=(10, float(core.settings.get(core.tg_settings.ORACLE_STREAM_TIMEOUT))),
        )
    except (requests.ConnectionError, requests.Timeout) as error:
        raise OracleUnavailable(str(error)) from error
    with res_cm as res:
        if res.status_code in _DOWN_STATUSES:
            raise OracleUnavailable(f"HTTP {res.status_code}")
        res.raise_for_status()
        consume_oracle_stream(res, renderer, signals, questions)
    renderer.finish()
    return OracleResult(renderer, signals, questions)


def is_authorized(message) -> bool:
    user_id = str(message.from_user.id)
    if not core.is_allowed_user(user_id):
        logger.warning("event=unauthorized_access_attempt user_id=%s allowed_configured=%s",
                       user_id, bool(core.ALLOWED_USER_ID))
        core.bot.reply_to(message, "Questo è un assistente privato.")
        return False
    return True


def _typing(chat_id) -> threading.Event:
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                core.bot.send_chat_action(chat_id, "typing")
            except Exception:  # noqa: BLE001
                pass
            stop.wait(4)

    threading.Thread(target=loop, daemon=True).start()
    return stop


def run_chat_turn(message, chat_id, user_text: str, *, status_msg=None, spoken: bool = False,
                  quoted: dict | None = None) -> None:
    """One chat turn: Oracle streams the reply into ``status_msg`` (queued while unavailable). ``spoken``: the
    text came from a voice note (live mode answers it by voice too)."""
    session_id = core.get_session(chat_id)
    if status_msg is None:
        if message is not None:
            status_msg = core.bot.reply_to(message, WORKING, parse_mode="HTML")
        else:
            status_msg = core.bot.send_message(chat_id, WORKING, parse_mode="HTML")
    stop_typing = _typing(chat_id)
    try:
        result = ask_oracle(chat_id, session_id, user_text, status_msg.message_id, quoted=quoted)
        feedback = core.should_show_feedback_prompt(str(chat_id), str(user_text or "").strip())
        try:
            voice_service.after_reply(chat_id, result.renderer, spoken=spoken, feedback=feedback,
                                      reply_to=getattr(message, "message_id", None))
        except Exception as exc:              # the text reply is already there: voice is an addition
            logger.warning("[🔄] event=voice_after_reply_failed chat_id=%s error=%s", chat_id, exc)
        send_oracle_questions(chat_id, session_id, result.signals, result.questions)
    except Exception as error:
        if isinstance(error, OracleUnavailable):
            queued = chat_queue.enqueue(chat_id, session_id, str(user_text or ""),
                                        getattr(message, "message_id", None), error)
            if queued is not None:
                core.bot.edit_message_text(chat_queue.queued_text(queued), chat_id=chat_id,
                                           message_id=status_msg.message_id, parse_mode="HTML")
                return
        logger.warning("event=chat_turn_failed chat_id=%s error=%s", chat_id, error)
        core.bot.edit_message_text(ui.error("Non sono riuscita a rispondere", "Riscrivimi tra poco."),
                                   chat_id=chat_id, message_id=status_msg.message_id, parse_mode="HTML")
    finally:
        stop_typing.set()


def chat_from_text(chat_id, text: str) -> None:
    """A text that was held (e.g. written in the middle of an action) goes to the chat now."""
    run_chat_turn(None, chat_id, text)


def handle_chat_message(message) -> None:
    """Plain text that no door, command or open flow took: a chat turn."""
    from telegram_bot.services.oauth_paste import complete_oauth_from_paste, match_oauth_callback
    text = str(message.text or "").strip()
    oauth_paste = match_oauth_callback(text)
    if oauth_paste:
        core.bot.reply_to(message, complete_oauth_from_paste(*oauth_paste), parse_mode="HTML")
        return
    run_chat_turn(message, message.chat.id, text, quoted=quoted_of(message))


# ── confirm cards Oracle asks for ────────────────────────────────────────────

def _confirm_keyboard(token: str, confirm_label: str = "Conferma", cancel_label: str = "Annulla",
                      danger: bool = False):
    return ui.keyboard([[ui.button(ui.strip_emoji(confirm_label) or "Conferma", f"confirm:{token}",
                                   style="danger" if danger else "success"),
                         ui.button(ui.strip_emoji(cancel_label) or "Annulla", f"cancel:{token}")]])


def send_oracle_questions(chat_id, session_id: str, streamed_signals: list, streamed_questions: list) -> None:
    """Confirm cards Oracle asked for during the turn."""
    for question in streamed_questions:
        if str(question.get("question_id") or "").startswith("ask_"):
            assistant_questions.send(chat_id, session_id, question)   # the assistant itself asks (v3 A)
            continue
        if not question.get("id") and question.get("question_id"):
            _send_module_question(chat_id, session_id, question)
            continue
        token = str(question.get("id") or "").strip()
        if not token:
            continue
        options = question.get("options") if isinstance(question.get("options"), list) else []
        confirm_label = str(options[0]).strip() if len(options) >= 1 and str(options[0]).strip() else "Conferma"
        cancel_label = str(options[1]).strip() if len(options) >= 2 and str(options[1]).strip() else "Annulla"
        signal_match = next((sig for sig in streamed_signals
                             if str(sig.get("event") or "") == "action.approval.required"
                             and str((sig.get("data") or {}).get("approval_token") or "") == token), {})
        trace_id = str(signal_match.get("trace_id") or question.get("trace_id") or "").strip()
        store.put_pending(token, {"action": "oracle_high_impact_approval", "chat_id": str(chat_id),
                                  "trace_id": trace_id or None})
        header = ui.strip_emoji(question.get("header") or "Confermi?")
        prompt = str(question.get("prompt") or "").strip()
        core.bot.send_message(chat_id, ui.card(header, [escape(prompt)] if prompt else [], tone="warning"),
                              parse_mode="HTML", reply_markup=_confirm_keyboard(token, confirm_label, cancel_label))


def _send_module_question(chat_id, session_id: str, question: dict) -> None:
    """A confirm card a module asked for in this chat (e.g. a settings proposal): two buttons; the answer goes back
    to Oracle, which routes the module's action."""
    options = [o for o in (question.get("options") or []) if isinstance(o, dict) and o.get("value")]
    if len(options) < 2:
        options = [{"label": "Sì", "value": "yes"}, {"label": "No", "value": "no"}]
    token = uuid.uuid4().hex[:16]
    labels = [ui.strip_emoji(options[0].get("label") or "Sì"), ui.strip_emoji(options[1].get("label") or "No")]
    store.put_pending(token, {"action": "oracle_question", "chat_id": str(chat_id), "session_id": session_id,
                              "question_id": str(question.get("question_id")), "confirm": str(options[0]["value"]),
                              "cancel": str(options[1]["value"]), "labels": labels})
    header = ui.strip_emoji(question.get("header") or "Confermi?")
    lines = [escape(str(question["prompt"]))] if question.get("prompt") else []
    core.bot.send_message(chat_id, ui.card(header, lines), parse_mode="HTML",
                          reply_markup=_confirm_keyboard(token, labels[0], labels[1]))


def _done(call, line: str, note: str) -> None:
    original = call.message.html_text or escape(call.message.text or "")
    try:
        core.bot.edit_message_text(f"{original}\n{line}", chat_id=call.message.chat.id,
                                   message_id=call.message.message_id, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        pass
    try:
        core.bot.answer_callback_query(call.id, note)
    except Exception:  # noqa: BLE001
        pass


def handle_confirmation(call) -> None:
    """``confirm:<token>`` / ``cancel:<token>`` (also ``confirm_cmd``/``cancel_cmd`` on older messages)."""
    action, _, token = str(call.data or "").partition(":")
    cancel = action in ("cancel", "cancel_cmd")
    payload = store.pop_pending(token)
    if not payload:
        try:
            core.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        core.bot.answer_callback_query(call.id, "Questa richiesta è già chiusa")
        return
    if payload.get("action") == "oracle_question":
        answer = payload["cancel"] if cancel else payload["confirm"]
        label = payload["labels"][1] if cancel else payload["labels"][0]
        status, result = core.oracle_post("api/chat/question-answer", {
            "session_id": payload["session_id"], "question_id": payload["question_id"], "answer": answer,
            "client": "telegram"}, timeout=20)
        ok = 0 < status < 400 and (result.get("action") or {}).get("ok", True)
        if not ok:
            logger.warning("[🔄] event=oracle_question_answer_failed question_id=%s status=%s",
                           payload["question_id"], status)
            store.put_pending(token, payload)
            core.bot.answer_callback_query(call.id, "Non riuscito, riprova")
            return
        _done(call, f"<i>{escape(label)}</i>", label)
        return
    if payload.get("action") == "oracle_high_impact_approval":
        status, result = core.oracle_post("api/actions/approval/respond", {
            "approval_token": token, "approve": not cancel, "actor": str(call.from_user.id),
            "client_instructions": core.build_client_instructions_for_chat(str(call.message.chat.id))},
            timeout=35, trace_id=payload.get("trace_id"))
        if status == 404:
            _done(call, "<i>Scaduta</i>", "Scaduta")
            return
        if not 0 < status < 400:
            logger.warning("event=oracle_action_approval_failed status=%s", status)
            store.put_pending(token, payload)
            core.bot.answer_callback_query(call.id, "Non riuscito, riprova")
            return
        if cancel or str(result.get("status") or "") == "canceled":
            _done(call, "<i>Annullato</i>", "Annullato")
            return
        text = str((result.get("result") or {}).get("text") or "").strip() if isinstance(result.get("result"),
                                                                                       dict) else ""
        _done(call, "🟢 <i>Fatto</i>", "Fatto")
        if text:
            core.send_user_message(call.message.chat.id, core.format_for_telegram(text))
        return
    core.bot.answer_callback_query(call.id, "Fatto")


# ── files, voice notes ───────────────────────────────────────────────────────

_PHOTO_MIME = "image/jpeg"
ACCEPTED_MIMES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif", "image/bmp",
    "image/tiff", "application/pdf",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "audio/vorbis", "audio/flac", "audio/aac",
    "audio/x-aac", "audio/m4a", "audio/mp4",
    "video/mp4", "video/mpeg", "video/webm", "video/ogg", "video/quicktime", "video/x-msvideo",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword",
    "application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/csv", "text/markdown", "text/html", "application/json", "application/xml", "text/xml",
    "application/x-yaml", "application/yaml",
}
_DEFAULT_MSG = {"audio": "Trascrivi e riassumi questo audio.", "voice": "Trascrivi questo messaggio vocale.",
                "video": "Trascrivi e riassumi questo video.", "video_note": "Trascrivi questo video messaggio."}


def _download_telegram_file(file_id: str) -> bytes:
    info = core.bot.get_file(file_id)
    return core.bot.download_file(info.file_path)


def handle_file_message(message) -> None:
    if not is_authorized(message):
        return
    if message.content_type in ("voice", "video_note") and handle_voice_note(message):
        return
    handle_file_as_document(message)


def handle_voice_note(message) -> bool:
    """A voice note is a chat message (SPEC modulo-voce §7.1): transcribe, show what was understood, then the
    normal chat turn. False = could not listen: the caller falls back to the document path ``[🔄]``."""
    chat_id = message.chat.id
    if message.content_type == "voice":
        file_id = message.voice.file_id
        mime_type = (message.voice.mime_type or "audio/ogg").split(";")[0].strip().lower()
    else:
        file_id, mime_type = message.video_note.file_id, "video/mp4"
    status_msg = core.bot.reply_to(message, "<i>Ascolto…</i>", parse_mode="HTML")
    try:
        core.bot.send_chat_action(chat_id, "typing")
        audio = _download_telegram_file(file_id)
        text = voice_service.transcribe_note(message, audio, mime_type, core.get_session(chat_id))
    except Exception as exc:
        logger.warning("[🔄] event=voice_note_failed chat_id=%s error=%s fallback=document_path", chat_id, exc)
        text = None
    if not text:
        logger.warning("[🔄] event=voice_note_not_heard chat_id=%s fallback=document_path", chat_id)
        try:
            core.bot.delete_message(chat_id, status_msg.message_id)
        except Exception:  # noqa: BLE001
            pass
        return False
    core.bot.edit_message_text(voice_service.heard_html(text), chat_id=chat_id, message_id=status_msg.message_id,
                               parse_mode="HTML")
    from telegram_bot import actions
    if actions.on_text(chat_id, text):      # a spoken answer to an open action
        return True
    run_chat_turn(message, chat_id, text, spoken=True, quoted=quoted_of(message))
    return True


def _file_info(message) -> tuple[str, str, str | None] | None:
    ct = message.content_type
    if ct == "photo":
        return message.photo[-1].file_id, _PHOTO_MIME, "photo.jpg"
    obj = getattr(message, ct, None)
    if obj is None:
        return None
    default = {"audio": "audio/mpeg", "voice": "audio/ogg", "video": "video/mp4", "video_note": "video/mp4",
               "document": "application/octet-stream"}.get(ct, "application/octet-stream")
    mime = (getattr(obj, "mime_type", None) or default).split(";")[0].strip().lower()
    name = getattr(obj, "file_name", None) or (f"{ct}.{mime.split('/')[-1]}" if ct != "document" else None)
    return obj.file_id, mime, name


def handle_file_as_document(message) -> None:
    """A document or photo goes to the assistant with its caption as the instruction."""
    chat_id = message.chat.id
    session_id = core.get_session(chat_id)
    info = _file_info(message)
    if not info:
        core.bot.reply_to(message, ui.error("Questo tipo di file non lo leggo", ""), parse_mode="HTML")
        return
    file_id, mime_type, filename = info
    is_text_like = mime_type.startswith("text/") or mime_type in (
        "application/json", "application/xml", "application/yaml", "application/x-yaml")
    if mime_type not in ACCEPTED_MIMES and not is_text_like:
        core.bot.reply_to(message, ui.error("Questo formato non lo leggo",
                                            "Mandami foto, PDF, audio, video, documenti Word o LibreOffice, "
                                            "fogli Excel, testo, JSON o CSV."), parse_mode="HTML")
        return
    user_text = (message.caption or "").strip() or _DEFAULT_MSG.get(message.content_type, "Analizza questo file.")
    status_msg = core.bot.reply_to(message, "<i>Leggo il file…</i>", parse_mode="HTML")
    stop_typing = _typing(chat_id)
    accepted = False
    try:
        file_bytes = _download_telegram_file(file_id)
        renderer = ReplyRenderer(chat_id, status_msg.message_id, core.get_session_settings(str(chat_id)))
        with requests.post(
            core.resolve_oracle_document_url(),
            data={"message": user_text, "session_id": session_id, "notify_target": str(chat_id),
                  "client_instructions": core.build_client_instructions_for_chat(str(chat_id)), "client": "telegram",
                  **({"filename": filename} if filename else {})},
            files={"file": (filename or f"attachment.{mime_type.split('/')[-1]}", file_bytes, mime_type)},
            stream=True,
            timeout=(10, float(core.settings.get(core.tg_settings.ORACLE_STREAM_TIMEOUT))),
        ) as res:
            res.raise_for_status()
            accepted = True
            consume_oracle_stream(res, renderer, [], [])
        renderer.finish()
        voice_service.after_reply(chat_id, renderer, spoken=False)
    except Exception as error:
        down = isinstance(error, (requests.ConnectionError, requests.Timeout)) or (
            isinstance(error, requests.HTTPError) and getattr(error.response, "status_code", 0) in _DOWN_STATUSES)
        if down and not accepted:
            # Files are not queued (large, read in the same turn): SPEC oracle-offline §3.
            core.bot.edit_message_text(chat_queue.FILE_OFFLINE_TEXT, chat_id=chat_id,
                                       message_id=status_msg.message_id, parse_mode="HTML")
            return
        logger.warning("event=document_turn_failed chat_id=%s error=%s", chat_id, error)
        core.bot.edit_message_text(ui.error("Non sono riuscita a leggere il file", "Riprova tra poco."),
                                   chat_id=chat_id, message_id=status_msg.message_id, parse_mode="HTML")
    finally:
        stop_typing.set()


# ── vote ─────────────────────────────────────────────────────────────────────

def handle_feedback_callback(call) -> None:
    """👍/👎 on the answer row: saved, then the two vote buttons go away («Ascolta» stays)."""
    parts = str(call.data or "").split(":", 2)
    label = parts[1] if len(parts) > 1 else ""
    if label not in ("good", "bad"):
        core.bot.answer_callback_query(call.id)
        return
    session_id = core.get_session(str(call.message.chat.id))
    ok = core.submit_feedback_to_archive(session_id=session_id, interaction_id=parts[2] if len(parts) > 2 else "",
                                         quality_label="good" if label == "good" else "poor",
                                         quality_score=4 if label == "good" else 2, tags=["telegram_inline"])
    if not ok:
        logger.warning("event=feedback_submit_failed session_id=%s label=%s", session_id, label)
    try:
        core.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                           reply_markup=voice_service.listen_keyboard(False))
    except Exception:  # noqa: BLE001
        pass
    core.bot.answer_callback_query(call.id, "Grazie" if ok else "Non salvato, riprova")
