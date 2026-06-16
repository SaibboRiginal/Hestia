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
from telegram_bot.services.command_service import (
    refresh_command_registry,
    register_telegram_service,
)
from telegram_bot.services.control_service import run_control_api


logger = logging.getLogger("hestia_telegram")


@bot.message_handler(commands=["start", "help"])
def on_welcome(message):
    send_welcome(message)


@bot.message_handler(commands=["clear"])
def on_clear(message):
    clear_memory(message)


@bot.message_handler(commands=["feedback"])
def on_feedback(message):
    handle_feedback_command(message)


@bot.message_handler(commands=["snooze_feedback"])
def on_snooze_feedback(message):
    handle_snooze_feedback_command(message)


@bot.callback_query_handler(func=lambda call: call.data.startswith("grp:"))
def on_group_nav(call):
    handle_group_callback(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm:") or call.data.startswith("cancel:") or call.data.startswith("confirm_cmd:") or call.data.startswith("cancel_cmd:"))
def on_confirmation(call):
    handle_confirmation(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("pickarg:"))
def on_arg_picker(call):
    handle_arg_picker(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("run:"))
def on_run_command(call):
    handle_run_command(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set:"))
def on_set_picker(call):
    handle_set_picker(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_flow"))
def on_cancel_flow(call):
    handle_cancel_flow(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("cal_"))
def on_calendar_step(call):
    handle_calendar_step(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("fb:"))
def on_feedback_callback(call):
    handle_feedback_callback(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_"))
def on_doc_callback(call):
    handle_doc_callback(call)


@bot.message_handler(content_types=["document", "photo", "audio", "voice", "video", "video_note"])
def on_file(message):
    handle_file_message(message)


@bot.message_handler(func=lambda message: True)
def on_chat(message):
    handle_chat_message(message)


def run():
    threading.Thread(target=run_control_api, daemon=True).start()

    ok = register_telegram_service()
    if ok:
        logger.info("event=telegram_service_registered_hub Telegram service registered on Hub")
    else:
        logger.warning(
            "event=telegram_hub_registration_failed_will Telegram Hub registration failed (will retry on webhook)")
    refresh_command_registry(force=True)
    logger.info(
        "event=command_registry_update_mode_push Command registry update mode=push (webhook-only after initial sync)"
    )

    logger.info("event=telegram_interface_starting_waiting_messages Telegram interface starting — waiting for messages")
    bot.infinity_polling()


if __name__ == "__main__":
    run()
