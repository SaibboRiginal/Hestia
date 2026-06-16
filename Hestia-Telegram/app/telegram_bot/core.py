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
MCP_API_URL = os.getenv(
    "MCP_API_URL", "http://hestia_mcp:19013").rstrip("/")
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

# ── Feedback prompting ──────────────────────────────────────────────────────
FEEDBACK_PROMPT_RATE = float(os.getenv("TELEGRAM_FEEDBACK_PROMPT_RATE", "0.15"))
FEEDBACK_SNOOZE_DEFAULT_DAYS = int(os.getenv("FEEDBACK_SNOOZE_DEFAULT_DAYS", "7"))
FEEDBACK_ARCHIVE_URL = os.getenv(
    "FEEDBACK_ARCHIVE_URL",
    f"{HUB_API_URL}/route/archive/api/feedback",
)

_feedback_turn_counts: dict[str, int] = {}
_feedback_eligibility_lock = threading.Lock()


def _is_feedback_eligible(message_text: str, has_tools: bool = False) -> bool:
    """Check if this turn should get a feedback prompt."""
    text = str(message_text or "").strip().lower()
    if not text or len(text) < 10:
        return False
    # Skip greetings and trivial messages
    greetings = {"ciao", "hey", "ehi", "buongiorno", "buonasera", "ok", "grazie"}
    if text in greetings or any(text.startswith(g) for g in greetings if len(g) > 3):
        return False
    # Always skip commands
    if text.startswith("/"):
        return False
    return True


def _is_feedback_snoozed(chat_id: str) -> bool:
    """Check if feedback prompting is snoozed for this chat."""
    try:
        resp = requests.get(
            f"{HUB_API_URL}/route/archive/api/memory/active?domain=controls",
            json={
                "method": "GET", "headers": {}, "query": {
                    "domain": "controls",
                }, "body": None, "timeout_seconds": 5,
            },
            timeout=9,
        )
        if resp.status_code != 200:
            return False
        routed = resp.json() if resp.content else {}
        memories = (routed or {}).get("payload", [])
        if not isinstance(memories, list):
            return False
        for mem in memories:
            fact = str(mem.get("fact", "") or mem.get("content", ""))
            if "feedback_prompting_paused_until" in fact:
                # Extract ISO date
                import re as _re
                import datetime as _dt
                match = _re.search(
                    r"feedback_prompting_paused_until=(\S+)", fact)
                if match:
                    try:
                        until = _dt.datetime.fromisoformat(
                            match.group(1).replace("Z", "+00:00"))
                        if until > _dt.datetime.now(_dt.timezone.utc):
                            return True
                    except (ValueError, TypeError):
                        pass
        return False
    except Exception:
        return False


def should_show_feedback_prompt(chat_id: str, message_text: str, has_tools: bool = False) -> bool:
    """Decide whether to show feedback UI after this turn."""
    if not _is_feedback_eligible(message_text, has_tools):
        return False
    if _is_feedback_snoozed(chat_id):
        return False
    with _feedback_eligibility_lock:
        count = _feedback_turn_counts.get(chat_id, 0) + 1
        _feedback_turn_counts[chat_id] = count
    # Always prompt on first eligible turn; afterward at random rate
    if count == 1:
        return True
    import random
    return random.random() < FEEDBACK_PROMPT_RATE


def build_feedback_keyboard(interaction_id: str = "") -> "types.InlineKeyboardMarkup":
    """Build the inline 👍/👎 keyboard for feedback."""
    from telebot import types
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton(
            "👍", callback_data=f"fb:good:{interaction_id}"),
        types.InlineKeyboardButton(
            "👎", callback_data=f"fb:bad:{interaction_id}"),
    )
    return markup


def submit_feedback_to_archive(
    session_id: str,
    interaction_id: str = "",
    quality_label: str = "mixed",
    quality_score: int = None,
    feedback_text: str = "",
    tags: list = None,
) -> bool:
    """Submit a feedback grade to Archive via Hub routing."""
    try:
        body = {
            "session_id": session_id,
            "interaction_id": interaction_id,
            "quality_label": quality_label,
        }
        if quality_score is not None:
            body["quality_score"] = quality_score
        if feedback_text:
            body["feedback_text"] = feedback_text
        if tags:
            body["tags"] = tags
        envelope = {
            "method": "POST",
            "headers": {},
            "query": {},
            "body": body,
            "timeout_seconds": 6,
        }
        resp = requests.post(
            FEEDBACK_ARCHIVE_URL,
            json=envelope,
            timeout=10,
        )
        return resp.status_code < 400
    except Exception:
        return False


def snooze_feedback(chat_id: str, days: int = FEEDBACK_SNOOZE_DEFAULT_DAYS) -> str:
    """Save a snooze preference to Archive. Returns until-ISO string."""
    import datetime as _dt
    until = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=days)
    until_iso = until.isoformat()
    fact = f"feedback_prompting_paused_until={until_iso}"
    try:
        resp = requests.post(
            f"{HUB_API_URL}/route/archive/api/memory",
            json={
                "method": "POST",
                "headers": {},
                "query": {},
                "body": {
                    "domain": "controls",
                    "fact": fact,
                    "memory_class": "durable_user_preference",
                    "owner": str(chat_id),
                },
                "timeout_seconds": 8,
            },
            timeout=12,
        )
        if resp.status_code < 400:
            LOGGER.info(
                "event=feedback_snoozed chat_id=%s until=%s", chat_id, until_iso)
            return until_iso
    except Exception as exc:
        LOGGER.warning("event=feedback_snooze_failed error=%s", exc)
    return ""


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
        try:
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
        except Exception as exc:
            err_text = str(exc or "")
            is_parse_error = "can't parse entities" in err_text.lower()
            if not (normalized_parse_mode == "HTML" and is_parse_error):
                raise

            LOGGER.warning(
                "event=send_user_message_html_parse_error_fallback Parse error while sending HTML, retrying as plain text | chat_id=%s error=%s",
                chat_id,
                err_text,
            )
            fallback_text = message_format.html_to_plain_text(
                part) or "[contenuto non visualizzabile]"
            bot.send_message(
                chat_id,
                fallback_text,
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
