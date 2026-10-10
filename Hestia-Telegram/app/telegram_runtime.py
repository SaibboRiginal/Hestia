import logging
import threading

from telegram_bot.core import bot
from telegram_bot.services.chat_service import (
    clear_memory,
    handle_arg_picker,
    handle_calendar_step,
    handle_chat_message,
    handle_cancel_flow,
    handle_confirmation,
    handle_doc_callback,
    handle_feedback_callback,
    handle_feedback_command,
    handle_file_message,
    handle_run_command,
    handle_set_picker,
    handle_snooze_feedback_command,
    send_welcome,
)
from telegram_bot.services.executor import handle_group_callback
from telegram_bot.services.notifications import handle_callback as handle_notification_callback
from telegram_bot.services.notifications import mark_seen_on_activity as mark_notifications_seen
from telegram_bot.services.command_service import (
    refresh_command_registry,
    register_telegram_service,
)
from telegram_bot.services.control_service import run_control_api


logger = logging.getLogger("hestia_telegram")


def _allowed(update) -> bool:
    """Central guard for button callbacks (messages are checked in handlers
    so unknown users get an explanatory reply)."""
    from telegram_bot import core as _core

    ok = _core.is_allowed_user(getattr(update.from_user, "id", ""))
    if not ok:
        logger.warning("event=unauthorized_callback user_id=%s", getattr(update.from_user, "id", ""))
    return ok

# Last user message per chat_id for /retry (Plan 8a)
_last_user_message: dict[int, object] = {}


@bot.message_handler(commands=["start", "help"])
def on_welcome(message):
    send_welcome(message)


@bot.message_handler(commands=["clear"])
def on_clear(message):
    clear_memory(message)


@bot.message_handler(commands=["retry"])
def on_retry(message):
    """Re-process the last user message (Plan 8a)."""
    chat_id = message.chat.id
    last_msg = _last_user_message.get(chat_id)
    if last_msg is None:
        bot.reply_to(message, "⚠️ Nessun messaggio precedente da riprocessare.")
        return
    # Re-dispatch through the same handler that processed the original
    if hasattr(last_msg, 'content_type') and getattr(last_msg, 'content_type') in (
        "document", "photo", "audio", "voice", "video", "video_note",
    ):
        handle_file_message(last_msg)
    else:
        handle_chat_message(last_msg)


@bot.message_handler(commands=["feedback"])
def on_feedback(message):
    handle_feedback_command(message)


@bot.message_handler(commands=["snooze_feedback"])
def on_snooze_feedback(message):
    handle_snooze_feedback_command(message)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("grp:")))
def on_group_nav(call):
    logger.info("event=callback_group_nav data=%s chat_id=%s", call.data, call.message.chat.id)
    handle_group_callback(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("confirm:") or call.data.startswith("cancel:") or call.data.startswith("confirm_cmd:") or call.data.startswith("cancel_cmd:")))
def on_confirmation(call):
    handle_confirmation(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("pickarg:")))
def on_arg_picker(call):
    handle_arg_picker(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("run:")))
def on_run_command(call):
    logger.info("event=callback_run_command data=%s chat_id=%s", call.data, call.message.chat.id)
    handle_run_command(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("set:")))
def on_set_picker(call):
    logger.info("event=callback_set_picker data=%s chat_id=%s", call.data, call.message.chat.id)
    handle_set_picker(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("cancel_flow")))
def on_cancel_flow(call):
    handle_cancel_flow(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("cal_")))
def on_calendar_step(call):
    handle_calendar_step(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("ntf:")))
def on_notification_callback(call):
    logger.info("event=callback_notification data=%s chat_id=%s", call.data, call.message.chat.id)
    handle_notification_callback(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("fb:")))
def on_feedback_callback(call):
    handle_feedback_callback(call)


@bot.callback_query_handler(func=lambda call: _allowed(call) and (call.data.startswith("doc_")))
def on_doc_callback(call):
    handle_doc_callback(call)


@bot.message_handler(content_types=["document", "photo", "audio", "voice", "video", "video_note"])
def on_file(message):
    _last_user_message[message.chat.id] = message
    mark_notifications_seen(message)
    handle_file_message(message)


@bot.message_handler(func=lambda message: True)
def on_chat(message):
    _last_user_message[message.chat.id] = message
    mark_notifications_seen(message)
    handle_chat_message(message)


def run():
    threading.Thread(target=run_control_api, daemon=True).start()

    ok = register_telegram_service()
    if ok:
        logger.info("event=telegram_service_registered_hub Telegram service registered on Hub")
    else:
        logger.warning(
            "event=telegram_hub_registration_failed_will Telegram Hub registration failed (will retry on webhook)")
    # Hub keeps its registry in memory: re-register periodically so a Hub
    # restart doesn't make Telegram unreachable for Hermes dispatch.
    try:
        from hestia_common.startup_utils import start_hub_keepalive
        start_hub_keepalive(register_telegram_service, logger=logger)
    except ImportError:
        logger.warning("[🔄] event=hub_keepalive_unavailable reason=hestia_common_missing")
    refresh_command_registry(force=True)
    logger.info(
        "event=command_registry_update_mode_push Command registry update mode=push (webhook-only after initial sync)"
    )

    logger.info("event=telegram_interface_starting_waiting_messages Telegram interface starting — waiting for messages")
    bot.infinity_polling()


if __name__ == "__main__":
    run()
