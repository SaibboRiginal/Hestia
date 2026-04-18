import json
import threading
from typing import Any

import requests

from telegram_bot import core
from telegram_bot.services.command_service import (
    build_commands_keyboard,
    execute_direct_command,
    execute_local_command,
    prompt_tone_presets,
    refresh_command_registry,
    render_direct_command_output,
    route_command_from_metadata,
)


def is_authorized(message) -> bool:
    user_id = str(message.from_user.id)
    if core.ALLOWED_USER_ID and user_id != str(core.ALLOWED_USER_ID):
        print(f"[!] Unauthorized access attempt from user ID: {user_id}")
        core.bot.reply_to(
            message, "⛔ **Access Denied.** This Hestia instance is private.")
        return False
    return True


def send_welcome(message):
    if not is_authorized(message):
        return
    refresh_command_registry(force=False)
    welcome_text = "🏛️ <b>Hestia pronta</b>\nScegli un comando dai pulsanti qui sotto."
    core.bot.reply_to(message, welcome_text, parse_mode="HTML",
                      reply_markup=build_commands_keyboard())


def clear_memory(message):
    if not is_authorized(message):
        return
    execute_local_command("clear", message.chat.id, "")


def handle_confirmation(call):
    try:
        user_id = str(call.from_user.id)
        if core.ALLOWED_USER_ID and user_id != str(core.ALLOWED_USER_ID):
            core.bot.answer_callback_query(call.id, "Azione non autorizzata")
            return

        action, token = call.data.split(":", 1)
        payload = core.PENDING_CONFIRMATIONS.pop(token, None)
        if not payload:
            core.bot.answer_callback_query(call.id, "Richiesta scaduta")
            return

        # Handle cancel action
        if action == "cancel" or action == "cancel_cmd":
            core.bot.edit_message_text(
                "Operazione annullata.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )
            core.bot.answer_callback_query(call.id, "Annullato")
            return

        # Handle clear session confirmation
        if payload.get("action") == "clear":
            chat_id = str(payload.get("chat_id"))
            old_session_id = str(payload.get("session_id"))
            try:
                oracle_chat_url = core.resolve_oracle_chat_url()
                delete_url = f"{oracle_chat_url}/{old_session_id}"
                requests.delete(delete_url, timeout=5)
            except Exception as error:
                print(f"[-] Failed to purge remote history: {error}")

            core.reset_session(chat_id)
            core.reset_session_settings(chat_id)
            core.bot.edit_message_text(
                "🧹 Sessione cancellata e memoria pulita.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )
            core.bot.answer_callback_query(call.id, "Fatto")
            return

        # Handle command confirmation (e.g., notifica_disattiva)
        if payload.get("action") == "notifica_disattiva":
            chat_id = int(payload.get("chat_id"))
            subscription_id = payload.get("subscription_id")
            command = payload.get("command")
            parsed_args = payload.get("parsed_args", {})

            # Execute the command with the parsed arguments
            ok, response = route_command_from_metadata(
                command, chat_id, parsed_args)
            if not ok:
                core.bot.edit_message_text(
                    f"⚠️ Errore: {response}",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                )
                core.bot.answer_callback_query(call.id, "Errore")
                return

            core.bot.edit_message_text(
                "✅ Notifica disattivata con successo.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )
            core.bot.answer_callback_query(call.id, "Notifica disattivata")
            return

        core.bot.answer_callback_query(call.id, "Nessuna azione")
    except Exception as error:
        print(f"[-] Confirmation handler error: {error}")


def handle_arg_picker(call):
    try:
        token = call.data.split(":", 1)[1]
        payload = core.ARG_PICKER_TOKENS.pop(token, None)
        if not payload:
            core.bot.answer_callback_query(call.id, "Opzione scaduta")
            return

        command_name = str(payload.get("command_name", "")).strip().lower()
        arg = str(payload.get("arg", "")).strip().lower()
        value = str(payload.get("value", "")).strip()
        if not command_name or not arg or not value:
            core.bot.answer_callback_query(call.id, "Opzione non valida")
            return

        execute_direct_command(
            command_name, call.message.chat.id, f"{arg}={value}")
        core.bot.answer_callback_query(call.id, "Comando eseguito")
    except Exception as error:
        print(f"[-] Arg picker handler error: {error}")


def handle_run_command(call):
    try:
        command_name = call.data.split(":", 1)[1].strip().lower()
        if not command_name:
            core.bot.answer_callback_query(call.id, "Comando non valido")
            return

        execute_direct_command(command_name, call.message.chat.id, "")
        core.bot.answer_callback_query(call.id, "Comando eseguito")
    except Exception as error:
        print(f"[-] Run command handler error: {error}")


def handle_set_picker(call):
    try:
        payload = str(call.data or "").strip()
        parts = payload.split(":")
        if len(parts) < 3 or parts[0] != "set":
            core.bot.answer_callback_query(call.id, "Azione non valida")
            return

        action = parts[1]
        value = parts[2]
        chat_id = call.message.chat.id

        if action == "param":
            if value == "tone":
                prompt_tone_presets(chat_id)
                core.bot.answer_callback_query(call.id, "Scegli un tone")
                return

            core.PENDING_WORKFLOWS[str(chat_id)] = {
                "action": "set_parameter_value",
                "parameter": value,
            }
            core.bot.send_message(
                chat_id,
                f"Scrivi ora il valore per '{value}'.",
            )
            core.bot.answer_callback_query(call.id, "Parametro selezionato")
            return

        if action == "tone":
            core.set_session_setting(str(chat_id), "tone", value)
            core.bot.send_message(
                chat_id,
                f"✅ Impostazione sessione aggiornata: tone={value}",
            )
            core.bot.answer_callback_query(call.id, "Tone impostato")
            return

        core.bot.answer_callback_query(call.id, "Azione non valida")
    except Exception as error:
        print(f"[-] Set picker handler error: {error}")


def handle_cancel_flow(call):
    try:
        chat_id = str(call.message.chat.id)
        pending = core.PENDING_WORKFLOWS.pop(chat_id, None)
        if not pending:
            core.bot.answer_callback_query(
                call.id, "Nessuna operazione attiva")
            return

        core.bot.edit_message_text(
            "Operazione annullata.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
        )
        core.bot.answer_callback_query(call.id, "Annullato")
    except Exception as error:
        print(f"[-] Cancel flow handler error: {error}")


def _run_notification_shortcut(chat_id: int, session_id: str, user_message: str, status_message_id: int):
    oracle_chat_url = core.resolve_oracle_chat_url()
    oracle_base_url = oracle_chat_url.rsplit("/api/chat", 1)[0]
    compile_url = f"{oracle_base_url}/api/subscriptions/compile"

    response = requests.post(
        compile_url,
        json={
            "message": user_message,
            "session_id": session_id,
            "notify_target": str(chat_id),
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json() or {}

    final_text = str(payload.get("message", "")
                     ).strip() or "Operazione completata."
    core.bot.edit_message_text(
        core.format_for_telegram(final_text),
        chat_id=chat_id,
        message_id=status_message_id,
        parse_mode="HTML",
    )

    signals = payload.get("signals") if isinstance(
        payload.get("signals"), list) else []
    for card in core.build_signal_cards(signals):
        core.bot.send_message(chat_id, card, parse_mode="HTML")


def handle_chat_message(message):
    if not is_authorized(message):
        return

    message_text = str(message.text or "").strip()
    if message_text.startswith("/"):
        command_token, _, command_args = message_text[1:].partition(" ")
        command_name = command_token.split("@")[0].strip().lower()
        if command_name in core.LOCAL_COMMANDS:
            execute_direct_command(command_name, message.chat.id, command_args)
            return
        with core.COMMAND_REGISTRY_LOCK:
            command_exists = command_name in core.COMMAND_REGISTRY
        if command_exists:
            execute_direct_command(command_name, message.chat.id, command_args)
            return

    chat_id = message.chat.id
    user_text = message.text
    pending_flow = core.PENDING_WORKFLOWS.pop(str(chat_id), None)

    if pending_flow and pending_flow.get("action") == "set_parameter_value":
        parameter_name = str(pending_flow.get("parameter", "")).strip().lower()
        if not parameter_name:
            core.bot.reply_to(message, "⚠️ Parametro non valido.")
            return
        core.set_session_setting(
            str(chat_id), parameter_name, str(message.text or "").strip())
        core.bot.reply_to(
            message,
            f"✅ Impostazione sessione aggiornata: {parameter_name}={str(message.text or '').strip()}",
        )
        return

    if pending_flow and pending_flow.get("action") == "command_text_input":
        command_name = str(pending_flow.get(
            "command_name", "")).strip().lower()
        missing_arg = str(pending_flow.get("missing_arg", "")).strip().lower()
        command_meta = pending_flow.get("command") if isinstance(
            pending_flow.get("command"), dict) else None
        parsed_args = dict(pending_flow.get("parsed_args") or {})
        user_value = str(message.text or "").strip()

        if not command_meta or not command_name or not missing_arg:
            core.bot.reply_to(message, "⚠️ Operazione non valida o scaduta.")
            return
        if not user_value:
            core.bot.reply_to(
                message, "⚠️ Valore non valido. Riprova oppure annulla.")
            return

        parsed_args[missing_arg] = user_value
        ok, payload = route_command_from_metadata(
            command_meta, message.chat.id, parsed_args)
        if not ok:
            core.send_user_message(
                message.chat.id,
                f"⚠️ Errore comando /{command_name}: {payload}",
                parse_mode="plain",
            )
            return

        response_mode = str(command_meta.get(
            "response_mode", "raw_json")).strip().lower()
        response_prompt = str(command_meta.get("response_prompt", "")).strip()
        output, parse_mode = render_direct_command_output(
            command_name, payload, response_mode, response_prompt)
        core.send_user_message(message.chat.id, output, parse_mode=parse_mode)
        return

    session_id = core.get_session(chat_id)

    status_msg = core.bot.reply_to(
        message, "⏳ *Inizializzazione richiesta...*", parse_mode="Markdown")

    stop_typing = threading.Event()

    def typing_indicator_loop():
        while not stop_typing.is_set():
            try:
                core.bot.send_chat_action(chat_id, "typing")
            except Exception:
                pass
            stop_typing.wait(4)

    threading.Thread(target=typing_indicator_loop, daemon=True).start()

    try:
        if pending_flow and pending_flow.get("action") == "notification_add":
            _run_notification_shortcut(
                chat_id=chat_id,
                session_id=session_id,
                user_message=str(message.text or "").strip(),
                status_message_id=status_msg.message_id,
            )
            return

        oracle_chat_url = core.resolve_oracle_chat_url()
        with requests.post(
            oracle_chat_url,
            json={
                "message": user_text,
                "session_id": session_id,
                "notify_target": str(chat_id),
                "force_notification_compiler": False,
                "client_instructions": core.build_client_instructions_for_chat(str(chat_id)),
            },
            stream=True,
        ) as res:
            res.raise_for_status()

            final_answer = ""
            streamed_signals: list[dict[str, Any]] = []
            for line in res.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("type") == "status":
                    core.bot.edit_message_text(
                        f"⏳ *{data['content']}*",
                        chat_id=chat_id,
                        message_id=status_msg.message_id,
                        parse_mode="Markdown",
                    )
                elif data.get("type") == "final":
                    final_answer = data.get("reply")
                elif data.get("type") == "signal":
                    streamed_signals.append(data)

        message_parts = core.build_chat_messages(final_answer)
        if not message_parts:
            message_parts = [core.format_for_telegram(final_answer)]

        core.bot.edit_message_text(
            message_parts[0],
            chat_id=chat_id,
            message_id=status_msg.message_id,
            parse_mode="HTML",
        )

        for message_part in message_parts[1:]:
            if not message_part.strip():
                continue
            try:
                core.send_user_message(
                    chat_id, message_part, parse_mode="HTML")
            except Exception:
                core.send_user_message(
                    chat_id, core.strip_markdown(message_part), parse_mode="plain")

        for card in core.build_signal_cards(streamed_signals):
            core.send_user_message(chat_id, card, parse_mode="HTML")

    except Exception as error:
        error_msg = f"⚠️ **Connessione all'Oracle fallita**\n`{error}`"
        core.bot.edit_message_text(
            error_msg,
            chat_id=chat_id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )
    finally:
        stop_typing.set()


# ─────────────────────────────────────────────────────────────────────
#  File / document handling
# ─────────────────────────────────────────────────────────────────────

_PHOTO_MIME = "image/jpeg"


def _download_telegram_file(file_id: str) -> bytes:
    """Download a file from Telegram servers and return its raw bytes."""
    file_info = core.bot.get_file(file_id)
    file_url = (
        f"https://api.telegram.org/file/bot{core.bot.token}/{file_info.file_path}"
    )
    response = requests.get(file_url, timeout=30)
    response.raise_for_status()
    return response.content


def handle_file_message(message):
    """Handle an incoming document or photo message by forwarding it to Oracle."""
    if not is_authorized(message):
        return

    chat_id = message.chat.id
    session_id = core.get_session(chat_id)

    # Determine file_id and mime_type based on message content type.
    if message.content_type == "photo":
        # Telegram sends multiple sizes; pick the highest resolution (last item).
        photo = message.photo[-1]
        file_id = photo.file_id
        mime_type = _PHOTO_MIME
    elif message.content_type == "document":
        doc = message.document
        file_id = doc.file_id
        mime_type = (
            doc.mime_type or "application/octet-stream").split(";")[0].strip().lower()
    else:
        core.bot.reply_to(message, "⚠️ Tipo di file non supportato.")
        return

    # Accept only what Oracle can handle.
    ACCEPTED_MIMES = {
        "image/jpeg", "image/png", "image/webp", "image/gif",
        "image/heic", "image/heif",
        "application/pdf",
    }
    if mime_type not in ACCEPTED_MIMES:
        core.bot.reply_to(
            message,
            f"⚠️ Formato non supportato: <code>{mime_type}</code>\n"
            "Invia un'immagine (JPEG, PNG, WebP) o un PDF.",
            parse_mode="HTML",
        )
        return

    # Caption is the user's instruction; fall back to generic prompt.
    user_text = (message.caption or "").strip() or "Analizza questo documento."

    status_msg = core.bot.reply_to(
        message, "⏳ *Download e analisi documento...*", parse_mode="Markdown"
    )

    stop_typing = threading.Event()

    def typing_loop():
        while not stop_typing.is_set():
            try:
                core.bot.send_chat_action(chat_id, "typing")
            except Exception:
                pass
            stop_typing.wait(4)

    threading.Thread(target=typing_loop, daemon=True).start()

    try:
        file_bytes = _download_telegram_file(file_id)

        oracle_doc_url = core.resolve_oracle_document_url()
        with requests.post(
            oracle_doc_url,
            data={
                "message": user_text,
                "session_id": session_id,
                "notify_target": str(chat_id),
                "client_instructions": core.build_client_instructions_for_chat(str(chat_id)),
            },
            files={
                "file": (f"attachment.{mime_type.split('/')[-1]}", file_bytes, mime_type)},
            stream=True,
            timeout=120,
        ) as res:
            res.raise_for_status()

            final_answer = ""
            for line in res.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("type") == "status":
                    try:
                        core.bot.edit_message_text(
                            f"⏳ *{data['content']}*",
                            chat_id=chat_id,
                            message_id=status_msg.message_id,
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass
                elif data.get("type") == "final":
                    final_answer = str(data.get("reply", "")).strip()

        if not final_answer:
            final_answer = "⚠️ Nessuna risposta ricevuta."

        message_parts = core.build_chat_messages(final_answer)
        core.bot.edit_message_text(
            message_parts[0] if message_parts else final_answer,
            chat_id=chat_id,
            message_id=status_msg.message_id,
            parse_mode="HTML",
        )
        for part in (message_parts[1:] if message_parts else []):
            if part.strip():
                core.send_user_message(chat_id, part, parse_mode="HTML")

    except Exception as error:
        core.bot.edit_message_text(
            f"⚠️ **Analisi documento fallita**\n`{error}`",
            chat_id=chat_id,
            message_id=status_msg.message_id,
            parse_mode="Markdown",
        )
    finally:
        stop_typing.set()
