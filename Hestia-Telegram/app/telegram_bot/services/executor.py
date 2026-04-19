"""Command execution — routing, argument flows, document handlers, local commands.

This is the top-level coordinator for command dispatch. It imports from
all other service modules and orchestrates the full execution lifecycle.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from html import escape
from typing import Any

import requests
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot import core
from telegram_bot.services.calendar_wizard import (
    _AFFIRMATIVE,  # re-exported for chat_service
    _NEGATIVE,      # re-exported for chat_service
    _prompt_wizard_title,
    execute_calendar_create_confirm,
    handle_calendar_step_callback,
    handle_calendar_wizard_text,
)
from telegram_bot.services.formatters import (
    format_documents_list,
    render_direct_command_output,
)
from telegram_bot.services.registry import (
    build_commands_keyboard,
    get_visible_command_items,
    refresh_command_registry,
)
from telegram_bot.services.router import (
    extract_required_args,
    parse_command_arguments,
    route_command_from_metadata,
    route_service_command,
)

# Make _AFFIRMATIVE and _NEGATIVE importable from this module for backward compat
__all__ = [
    "_AFFIRMATIVE", "_NEGATIVE",
    "COMMAND_ALIASES", "TONE_PRESETS",
    "prompt_set_parameter_picker", "prompt_tone_presets",
    "start_text_input_flow",
    "open_arg_picker",
    "execute_local_command", "execute_direct_command",
    "handle_doc_callback", "_execute_delete_document",
    "prompt_clear_confirmation",
    # Re-exports from sub-modules (backward compat for chat_service / telegram_runtime)
    "build_commands_keyboard", "refresh_command_registry",
    "render_direct_command_output", "route_command_from_metadata",
    "execute_calendar_create_confirm",
    "handle_calendar_step_callback", "handle_calendar_wizard_text",
]

COMMAND_ALIASES: dict[str, str] = {
    "scout_list": "scout_listings",
}

TONE_PRESETS = [
    ("warm", "Caldo"),
    ("neutral", "Neutro"),
    ("direct", "Diretto"),
    ("formal", "Formale"),
]

# ── UI prompt helpers ─────────────────────────────────────────────────────────


def _cancel_input_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Annulla", callback_data="cancel_flow"))
    return kb


def prompt_set_parameter_picker(chat_id: int):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎙️ Tone", callback_data="set:param:tone"),
        InlineKeyboardButton(
            "📝 Custom Prompt", callback_data="set:param:custom_prompt"),
    )
    core.bot.send_message(
        chat_id, "Scegli il parametro da impostare:", reply_markup=kb)


def prompt_tone_presets(chat_id: int):
    kb = InlineKeyboardMarkup(row_width=2)
    for tone_value, tone_label in TONE_PRESETS:
        kb.add(InlineKeyboardButton(
            tone_label, callback_data=f"set:tone:{tone_value}"))
    core.bot.send_message(
        chat_id, "Seleziona un preset di tone:", reply_markup=kb)


# ── Argument input flows ──────────────────────────────────────────────────────

def start_text_input_flow(
    chat_id: int,
    command_name: str,
    command_meta: dict[str, Any],
    missing_arg: str,
    parsed_args: dict[str, Any] | None = None,
):
    """Ask the user to type the missing argument in the next message."""
    core.PENDING_WORKFLOWS[str(chat_id)] = {
        "action": "command_text_input",
        "command_name": str(command_name or "").strip().lower(),
        "command": command_meta,
        "missing_arg": str(missing_arg or "").strip().lower(),
        "parsed_args": dict(parsed_args or {}),
        "created_at": time.time(),
    }
    pretty_name = str(missing_arg or "valore").replace("_", " ").strip()
    core.bot.send_message(
        chat_id,
        f"✍️ Inserisci ora il valore per <b>{pretty_name}</b> nel prossimo messaggio.",
        parse_mode="HTML",
        reply_markup=_cancel_input_keyboard(),
    )


def open_arg_picker(chat_id: int, command_name: str, command: dict[str, Any], missing_arg: str):
    """Show an inline picker loaded from an arg_picker source, or fall back to text flow."""
    from telegram_bot.services.formatters import _build_subscription_picker_label

    arg_picker = command.get("arg_picker") if isinstance(
        command.get("arg_picker"), dict) else {}
    source = arg_picker.get("source") if isinstance(
        arg_picker.get("source"), dict) else {}
    picker_arg = str(arg_picker.get("arg", "")).strip().lower()

    if not source or picker_arg != missing_arg:
        start_text_input_flow(chat_id, command_name, command, missing_arg)
        return

    ok, payload = route_command_from_metadata(source, chat_id, {})
    if not ok or not isinstance(payload, list) or not payload:
        start_text_input_flow(chat_id, command_name, command, missing_arg)
        return

    value_field = str(arg_picker.get(
        "value_field", missing_arg)).strip() or missing_arg
    label_fields = arg_picker.get("label_fields") if isinstance(
        arg_picker.get("label_fields"), list) else []

    kb = InlineKeyboardMarkup()
    count = 0
    for item in payload[:10]:
        if not isinstance(item, dict):
            continue
        value = str(item.get(value_field, "")).strip()
        if not value:
            continue

        if missing_arg == "subscription_id":
            label_text = _build_subscription_picker_label(item, value)
        else:
            label_parts = [str(item[f]).strip()
                           for f in label_fields if f in item and str(item[f]).strip()]
            label_text = " | ".join(
                label_parts[:3]) if label_parts else f"Opzione {count + 1}"

        token = uuid.uuid4().hex[:12]
        core.ARG_PICKER_TOKENS[token] = {
            "command_name": command_name, "arg": missing_arg, "value": value}
        kb.add(InlineKeyboardButton(str(label_text or value)
               [:60], callback_data=f"pickarg:{token}"))
        count += 1

    if count == 0:
        core.bot.send_message(chat_id, "ℹ️ Nessuna opzione valida trovata.")
        return

    pretty_arg_name = "notifica" if missing_arg == "subscription_id" else missing_arg
    core.bot.send_message(
        chat_id, f"Seleziona {pretty_arg_name}:", reply_markup=kb)


# ── Document list + handlers ──────────────────────────────────────────────────

def _handle_documents_list(chat_id: int):
    """Fetch and display the archived documents list."""
    try:
        resp = requests.post(
            f"{core.HUB_API_URL}/route/archive/api/documents",
            json={"method": "GET", "query": {"chat_id": str(chat_id), "limit": 20},
                  "headers": {}, "body": {}, "timeout_seconds": 10},
            timeout=12,
        )
        resp.raise_for_status()
        docs = resp.json().get("payload") or []
    except Exception as exc:
        core.bot.send_message(
            chat_id,
            f"⚠️ Impossibile recuperare i documenti.\n<code>{escape(str(exc)[:200])}</code>",
            parse_mode="HTML",
        )
        return

    html, keyboard = format_documents_list(docs)
    core.bot.send_message(
        chat_id, html, parse_mode="HTML", reply_markup=keyboard)


def _execute_delete_document(document_id: str, chat_id: int):
    """Perform the actual document deletion via Hub → Archive."""
    try:
        resp = requests.post(
            f"{core.HUB_API_URL}/route/archive/api/documents/{document_id}",
            json={"method": "DELETE", "query": {}, "headers": {},
                  "body": {}, "timeout_seconds": 10},
            timeout=12,
        )
        resp.raise_for_status()
        core.bot.send_message(
            chat_id, "🗑️ Documento eliminato.", parse_mode="HTML")
    except Exception as exc:
        core.bot.send_message(
            chat_id,
            f"⚠️ Impossibile eliminare.\n<code>{escape(str(exc)[:200])}</code>",
            parse_mode="HTML",
        )


def handle_group_callback(call):
    """Handle ``grp:<key>`` callback queries for the submenu navigation."""
    from telegram_bot.services.registry import GROUP_ORDER, build_commands_keyboard, build_group_commands_keyboard

    group_key = call.data[len("grp:"):]
    if group_key == "__main__":
        kb = build_commands_keyboard()
        core.bot.edit_message_text(
            "🏛️ <b>Hestia</b> — scegli una categoria:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        label = next((lbl for k, lbl, _ in GROUP_ORDER if k ==
                     group_key), group_key.capitalize())
        kb = build_group_commands_keyboard(group_key)
        core.bot.edit_message_text(
            f"<b>{label}</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=kb,
        )
    core.bot.answer_callback_query(call.id)


def handle_doc_callback(call):
    """Route ``doc_pin:`` and ``doc_del:`` callback queries."""
    chat_id = call.message.chat.id
    data = call.data or ""
    hub_url = core.HUB_API_URL

    if data.startswith("doc_pin:"):
        doc_id = data[len("doc_pin:"):]
        try:
            resp = requests.post(
                f"{hub_url}/route/archive/api/documents/{doc_id}",
                json={"method": "GET", "query": {}, "headers": {},
                      "body": {}, "timeout_seconds": 8},
                timeout=10,
            )
            resp.raise_for_status()
            current_doc = resp.json().get("payload", {})
            new_permanent = not bool(current_doc.get("is_permanent", False))

            patch_resp = requests.post(
                f"{hub_url}/route/archive/api/documents/{doc_id}/permanent",
                json={"method": "PATCH", "query": {}, "headers": {},
                      "body": {"is_permanent": new_permanent}, "timeout_seconds": 8},
                timeout=10,
            )
            patch_resp.raise_for_status()
            status_msg = "📌 Documento reso <b>permanente</b>." if new_permanent else "📎 Documento tornato <b>temporaneo</b>."
            try:
                core.bot.answer_callback_query(call.id, "✅ Aggiornato")
            except Exception:
                pass
            core.bot.send_message(chat_id, status_msg, parse_mode="HTML")
        except Exception as exc:
            try:
                core.bot.answer_callback_query(call.id, "⚠️ Errore")
            except Exception:
                pass
            core.bot.send_message(
                chat_id,
                f"⚠️ Impossibile aggiornare il documento.\n<code>{escape(str(exc)[:200])}</code>",
                parse_mode="HTML",
            )
        return

    if data.startswith("doc_del:"):
        doc_id = data[len("doc_del:"):]
        token = uuid.uuid4().hex[:10]
        core.PENDING_CONFIRMATIONS[token] = {
            "action": "delete_document", "document_id": doc_id,
            "chat_id": chat_id, "created_at": time.time(),
        }
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✅ Sì, elimina", callback_data=f"confirm:{token}"),
            InlineKeyboardButton("❌ Annulla", callback_data=f"cancel:{token}"),
        ]])
        try:
            core.bot.answer_callback_query(call.id)
        except Exception:
            pass
        core.bot.send_message(
            chat_id,
            "🗑️ <b>Vuoi eliminare questo documento?</b>\nL'operazione non può essere annullata.",
            parse_mode="HTML", reply_markup=kb,
        )
        return

    try:
        core.bot.answer_callback_query(call.id)
    except Exception:
        pass


# ── Clear confirmation ────────────────────────────────────────────────────────

def prompt_clear_confirmation(chat_id: int):
    """Ask the user to confirm clearing the session / chat history."""
    old_session_id = core.get_session(str(chat_id))
    token = uuid.uuid4().hex[:12]
    core.PENDING_CONFIRMATIONS[token] = {
        "action": "clear", "chat_id": str(chat_id), "session_id": old_session_id,
    }
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("✅ Conferma", callback_data=f"confirm:{token}"),
        InlineKeyboardButton("❌ Annulla", callback_data=f"cancel:{token}"),
    )
    core.bot.send_message(
        chat_id, "Vuoi davvero cancellare la memoria di questa chat?", reply_markup=kb)


# ── Local command execution ───────────────────────────────────────────────────

def execute_local_command(command_name: str, chat_id: int, raw_args_text: str):
    """Execute a locally-handled command (no Hub routing)."""
    normalized = str(command_name or "").strip().lower()
    args_text = str(raw_args_text or "").strip()

    if normalized == "start":
        refresh_command_registry(force=False)
        core.bot.send_message(
            chat_id, "🏛️ <b>Hestia pronta</b>\nScegli un comando dai pulsanti qui sotto.",
            parse_mode="HTML", reply_markup=build_commands_keyboard(),
        )
        return

    if normalized == "help":
        refresh_command_registry(force=False)
        lines = ["📘 <b>Guida comandi</b>", "Comandi principali disponibili:"]
        for cmd_name, cmd_meta in get_visible_command_items(surface="help"):
            title = str(cmd_meta.get("title", cmd_name)).strip() or cmd_name
            args_help = str(cmd_meta.get("arguments_help", "")).strip()
            usage = f"/{cmd_name}" + (f" {args_help}" if args_help else "")
            lines.append(f"• <b>{usage}</b> — {title}")
        core.bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
        return

    if normalized == "clear":
        prompt_clear_confirmation(chat_id)
        return

    if normalized == "set":
        if not args_text:
            prompt_set_parameter_picker(chat_id)
            return
        if "=" in args_text:
            key, _, value = args_text.partition("=")
            if not key.strip() or not value.strip():
                core.bot.send_message(
                    chat_id, "Uso: /set <parametro> (poi inserisci il valore nel prossimo messaggio)")
                return
            normalized_key = re.sub(r"[^a-z0-9_]", "", key.strip().lower())
            if len(normalized_key) < 2:
                core.bot.send_message(chat_id, "Parametro non valido.")
                return
            core.set_session_setting(
                str(chat_id), normalized_key, value.strip())
            core.bot.send_message(
                chat_id, f"✅ Impostazione sessione aggiornata: {normalized_key}={value.strip()}")
            return
        normalized_key = re.sub(r"[^a-z0-9_]", "", args_text.strip().lower())
        if len(normalized_key) < 2:
            core.bot.send_message(chat_id, "Parametro non valido.")
            return
        core.PENDING_WORKFLOWS[str(chat_id)] = {
            "action": "set_parameter_value", "parameter": normalized_key, "created_at": time.time(),
        }
        core.bot.send_message(
            chat_id, f"✍️ Scrivi ora il valore per <b>{normalized_key}</b> nel prossimo messaggio.",
            parse_mode="HTML", reply_markup=_cancel_input_keyboard(),
        )
        return

    if normalized == "settings":
        settings = core.get_session_settings(str(chat_id))
        if not settings:
            core.bot.send_message(
                chat_id, "Nessuna impostazione sessione attiva.")
            return
        lines = ["<b>Impostazioni sessione</b>"]
        for key, value in settings.items():
            lines.append(f"• <b>{key}</b>: {value}")
        core.bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")
        return

    if normalized == "reset_settings":
        core.reset_session_settings(str(chat_id))
        core.bot.send_message(chat_id, "🧹 Impostazioni sessione resettate.")
        return

    if normalized == "notifica_add":
        core.PENDING_WORKFLOWS[str(chat_id)] = {
            "action": "notification_add", "created_at": time.time(),
        }
        core.bot.send_message(
            chat_id,
            "Dimmi che notifica vuoi creare (dominio, evento, filtri).",
            reply_markup=_cancel_input_keyboard(),
        )
        return

    if normalized == "notifica_get":
        execute_direct_command("notifiche_attive", chat_id, "")
        return

    if normalized == "notifica_remove":
        execute_direct_command("notifica_disattiva", chat_id, args_text)
        return

    if normalized in ("create_event", "create_task", "create_reminder"):
        kind_map = {"create_event": "event",
                    "create_task": "task", "create_reminder": "reminder"}
        kind = kind_map[normalized]
        core.PENDING_WORKFLOWS[str(chat_id)] = {
            "action": "calendar_create_wizard", "step": "title",
            "kind": kind, "data": {}, "created_at": time.time(),
        }
        _prompt_wizard_title(chat_id, kind)
        return

    if normalized == "documents":
        _handle_documents_list(chat_id)
        return


# ── Dynamic command execution ─────────────────────────────────────────────────

def execute_direct_command(command_name: str, chat_id: int, raw_args_text: str):
    """Dispatch a command: local → registry → Hub routing."""
    normalized = str(command_name or "").strip().lower()
    if normalized in COMMAND_ALIASES:
        normalized = COMMAND_ALIASES[normalized]

    if normalized in core.LOCAL_COMMANDS:
        execute_local_command(normalized, chat_id, raw_args_text)
        return

    with core.COMMAND_REGISTRY_LOCK:
        command = core.COMMAND_REGISTRY.get(normalized)
    if not command:
        print(f"[-] Command not available: {command_name} → {normalized}")
        core.bot.send_message(chat_id, "Comando non disponibile.")
        return

    if str(command.get("response_mode", "")).strip().lower() == "telegram_local":
        execute_local_command(normalized, chat_id, raw_args_text)
        return

    parsed_args = parse_command_arguments(raw_args_text)
    required_args = extract_required_args(
        str(command.get("arguments_help", "")).strip())
    missing = [arg for arg in required_args if arg not in parsed_args]
    if missing:
        missing_arg = missing[0]
        arg_picker = command.get("arg_picker") if isinstance(
            command.get("arg_picker"), dict) else {}
        if arg_picker and str(arg_picker.get("arg", "")).strip().lower() == missing_arg:
            open_arg_picker(chat_id, command_name, command, missing_arg)
        else:
            start_text_input_flow(chat_id, normalized,
                                  command, missing_arg, parsed_args)
        return

    # Special case: notifica_disattiva requires confirmation
    if normalized == "notifica_disattiva":
        subscription_id = parsed_args.get("subscription_id")
        if not subscription_id:
            core.bot.send_message(chat_id, "⚠️ ID notifica non valido.")
            return
        token = uuid.uuid4().hex[:12]
        core.PENDING_CONFIRMATIONS[token] = {
            "action": "notifica_disattiva", "chat_id": str(chat_id),
            "subscription_id": subscription_id, "command": command, "parsed_args": parsed_args,
        }
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton(
                "✅ Disattiva", callback_data=f"confirm_cmd:{token}"),
            InlineKeyboardButton(
                "❌ Annulla", callback_data=f"cancel_cmd:{token}"),
        )
        short_id = str(subscription_id)[:8]
        core.bot.send_message(
            chat_id,
            f"⚠️ Sei sicuro di voler disattivare la notifica selezionata (<code>{short_id}</code>)?",
            parse_mode="HTML", reply_markup=kb,
        )
        return

    ok, payload = route_command_from_metadata(command, chat_id, parsed_args)
    if not ok:
        print(f"[CMD] Command /{normalized} failed: {payload}")
        core.bot.send_message(
            chat_id, f"⚠️ Errore comando /{normalized}: {payload}")
        return

    response_mode = str(command.get(
        "response_mode", "oracle_natural")).strip().lower()
    response_prompt = str(command.get("response_prompt", "")).strip()
    print(f"[CMD] Rendering /{normalized} response_mode={response_mode}")

    command_title = str(command.get("title", "")).strip()

    # Send a pending status message; animate via typing indicator while rendering
    pending_msg = None
    stop_typing = threading.Event()

    if command_title:
        pending_msg = core.bot.send_message(
            chat_id,
            f"⌛ <i>{escape(command_title)}...</i>",
            parse_mode="HTML",
        )

        def _typing_loop():
            while not stop_typing.is_set():
                try:
                    core.bot.send_chat_action(chat_id, "typing")
                except Exception:
                    pass
                stop_typing.wait(4)

        threading.Thread(target=_typing_loop, daemon=True).start()

    output, parse_mode = render_direct_command_output(
        normalized, payload, response_mode, response_prompt)
    print(
        f"[CMD] Output for /{normalized}: {len(output)} chars, parse_mode={parse_mode}")

    stop_typing.set()

    if pending_msg:
        try:
            core.bot.edit_message_text(
                f"<b>{escape(command_title)}</b>",
                chat_id=chat_id,
                message_id=pending_msg.message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass

    core.send_user_message(chat_id, output, parse_mode=parse_mode)
