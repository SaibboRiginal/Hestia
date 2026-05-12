import os
import threading
from typing import Any
from pathlib import Path
import sys
import logging

import requests
import telebot

import message_format
import session_store
from command_catalog import telegram_local_commands

try:
    from hestia_common.logging_utils import setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    # Docker image layout: /code/hestia_common, app runs from /code/app.
    if str(_workspace_root) not in sys.path:
        sys.path.insert(0, str(_workspace_root))
    # Local workspace layout: <root>/Hestia-Shared/hestia_common.
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if _shared_pkg.exists() and str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging

LOGGER, LOG_BUFFER = setup_service_logging("hestia_telegram")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN. Check your .env file!")

ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
bot = telebot.TeleBot(TELEGRAM_TOKEN)

HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
ORACLE_API_URL = os.getenv(
    "ORACLE_API_URL", "http://hestia_oracle:19004/api/chat")
ORACLE_FORMAT_API_URL = os.getenv(
    "ORACLE_FORMAT_API_URL", "http://hestia_oracle:19004/api/format")

STATE_FILE = "data/telegram_state.json"
SESSION_SETTINGS_FILE = "data/session_settings.json"

TELEGRAM_ORACLE_CLIENT_INSTRUCTIONS = os.getenv(
    "TELEGRAM_ORACLE_CLIENT_INSTRUCTIONS",
    "Rispondi in modo conciso (massimo 6-8 righe), personale e caldo. Parla in prima persona femminile e usa il nome Mark quando naturale.",
)

TELEGRAM_CONTROL_PORT = int(os.getenv("TELEGRAM_CONTROL_PORT", "8010"))
TELEGRAM_BASE_URL = os.getenv(
    "TELEGRAM_BASE_URL", f"http://hestia_telegram:{TELEGRAM_CONTROL_PORT}"
).rstrip("/")
TELEGRAM_LOCALE = os.getenv("TELEGRAM_LOCALE", "it")

TELEGRAM_HIDDEN_COMMAND_SERVICES = {
    item.strip().lower()
    for item in os.getenv("TELEGRAM_HIDDEN_COMMAND_SERVICES", "scout").split(",")
    if item.strip()
}
TELEGRAM_HIDDEN_DYNAMIC_COMMANDS = {
    item.strip().lower()
    for item in os.getenv(
        "TELEGRAM_HIDDEN_DYNAMIC_COMMANDS",
        "notifica_attiva,notifica_disattiva,notifiche_attive",
    ).split(",")
    if item.strip()
}

PENDING_CONFIRMATIONS: dict[str, dict] = {}
COMMAND_REGISTRY: dict[str, dict[str, Any]] = {}
COMMAND_REGISTRY_REVISION = -1
COMMAND_REGISTRY_LOCK = threading.Lock()
ARG_PICKER_TOKENS: dict[str, dict[str, Any]] = {}
PENDING_WORKFLOWS: dict[str, dict[str, Any]] = {}
LOCAL_COMMANDS = {item["command"]: item for item in telegram_local_commands()}

# Alert buffering for grouping consecutive alerts into one message
ALERT_BUFFER: dict[str, list[dict]] = {}  # chat_id -> [alerts]
ALERT_BUFFER_LOCK = threading.Lock()
ALERT_BUFFER_TIMERS: dict[str, threading.Timer] = {}  # chat_id -> timer
ALERT_BUFFER_WINDOW = float(os.getenv("ALERT_BUFFER_WINDOW_SECONDS", "0.8"))


def resolve_oracle_chat_url() -> str:
    try:
        response = requests.get(f"{HUB_API_URL}/registry/services", timeout=4)
        if response.status_code == 200:
            services = response.json().get("services", []) or []
            for service in services:
                if str(service.get("name", "")).strip().lower() == "oracle":
                    base_url = str(service.get("base_url", "")).rstrip("/")
                    if base_url:
                        return f"{base_url}/api/chat"
    except Exception:
        pass
    return ORACLE_API_URL


def resolve_oracle_document_url() -> str:
    """Return the Oracle document analysis endpoint URL via Hub service registry."""
    try:
        response = requests.get(f"{HUB_API_URL}/registry/services", timeout=4)
        if response.status_code == 200:
            services = response.json().get("services", []) or []
            for service in services:
                if str(service.get("name", "")).strip().lower() == "oracle":
                    base_url = str(service.get("base_url", "")).rstrip("/")
                    if base_url:
                        return f"{base_url}/api/chat/document"
    except Exception:
        pass
    base = ORACLE_API_URL.rsplit("/api/chat", 1)[0]
    return f"{base}/api/chat/document"


def get_session(chat_id: str) -> str:
    return session_store.get_session(STATE_FILE, str(chat_id))


def reset_session(chat_id: str):
    session_store.reset_session(STATE_FILE, str(chat_id))


def get_session_settings(chat_id: str) -> dict[str, Any]:
    return session_store.get_session_settings(SESSION_SETTINGS_FILE, str(chat_id))


def set_session_setting(chat_id: str, key: str, value: str):
    session_store.set_session_setting(
        SESSION_SETTINGS_FILE, str(chat_id), key, value)


def reset_session_settings(chat_id: str):
    session_store.reset_session_settings(SESSION_SETTINGS_FILE, str(chat_id))


def build_client_instructions_for_chat(chat_id: str) -> str:
    return session_store.build_client_instructions_for_chat(
        SESSION_SETTINGS_FILE,
        TELEGRAM_ORACLE_CLIENT_INSTRUCTIONS,
        str(chat_id),
    )


def format_for_telegram(text: str) -> str:
    return message_format.format_for_telegram(text)


def build_chat_messages(raw_markdown: str) -> list[str]:
    return message_format.build_chat_messages(raw_markdown)


def strip_markdown(text: str) -> str:
    return message_format.strip_markdown(text)


def build_signal_cards(signals: list[dict]) -> list[str]:
    return message_format.build_signal_cards(signals)


def format_payload_raw(payload: Any) -> str:
    return message_format.format_payload_raw(payload)


def build_delivery_messages(text: str, parse_mode: str = "HTML") -> tuple[list[str], str | None]:
    return message_format.build_delivery_messages(text, parse_mode)


def send_user_message(chat_id: str | int, text: str, parse_mode: str = "HTML", disable_web_page_preview: bool = True):
    messages, normalized_parse_mode = build_delivery_messages(text, parse_mode)
    if not messages:
        return

    LOGGER.debug(
        "event=send_user_message_chat_id_parts_parse_mode send_user_message | chat_id=%s parts=%d parse_mode=%s",
        chat_id,
        len(messages),
        normalized_parse_mode,
    )
    for part in messages:
        if not str(part).strip():
            continue
        if normalized_parse_mode:
            bot.send_message(
                chat_id,
                part,
                parse_mode=normalized_parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        else:
            bot.send_message(
                chat_id,
                part,
                disable_web_page_preview=disable_web_page_preview,
            )


def buffer_alert(
    chat_id: str,
    entity_payload: dict[str, Any],
    domain: str = "",
    entity_id: str = "",
    trace_id: str | None = None,
):
    """Add alert to buffer and schedule flush if needed"""
    with ALERT_BUFFER_LOCK:
        if chat_id not in ALERT_BUFFER:
            ALERT_BUFFER[chat_id] = []

        ALERT_BUFFER[chat_id].append({
            "payload": entity_payload,
            "domain": domain,
            "entity_id": entity_id,
            "trace_id": str(trace_id or "").strip(),
        })

        # Cancel existing timer for this chat if any
        if chat_id in ALERT_BUFFER_TIMERS:
            ALERT_BUFFER_TIMERS[chat_id].cancel()

        # Schedule flush after buffer window
        def flush_alerts():
            with ALERT_BUFFER_LOCK:
                ALERT_BUFFER_TIMERS.pop(chat_id, None)
            flush_buffered_alerts(chat_id)

        timer = threading.Timer(ALERT_BUFFER_WINDOW, flush_alerts)
        timer.daemon = True
        ALERT_BUFFER_TIMERS[chat_id] = timer
        timer.start()


def flush_buffered_alerts(chat_id: str):
    """Send all buffered alerts as a conversational message flow"""
    with ALERT_BUFFER_LOCK:
        alerts = ALERT_BUFFER.pop(chat_id, [])

    if not alerts:
        return

    from telegram_bot.services.control_service import format_multiple_alerts_with_oracle, build_alert_fallback_message

    trace_id = next(
        (str(a.get("trace_id") or "").strip()
         for a in alerts if str(a.get("trace_id") or "").strip()),
        "",
    )
    message = format_multiple_alerts_with_oracle(
        alerts,
        chat_id=chat_id,
        trace_id=trace_id or None,
    )
    if not message:
        for alert in alerts:
            try:
                fallback = build_alert_fallback_message(
                    alert.get("payload", {}),
                    alert.get("domain", ""),
                    alert.get("entity_id", ""),
                )
                send_user_message(chat_id, fallback, parse_mode="HTML")
            except Exception:
                pass
        return

    try:
        send_user_message(chat_id, message, parse_mode="HTML")
    except Exception as e:
        LOGGER.warning(
            "event=failed_send_buffered_alert_message Failed to send buffered alert message: %s", e)
