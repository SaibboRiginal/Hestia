import threading

from telegram_bot.core import bot, TELEGRAM_COMMAND_REFRESH_SECONDS
from telegram_bot.services.chat_service import (
    clear_memory,
    handle_arg_picker,
    handle_chat_message,
    handle_cancel_flow,
    handle_confirmation,
    handle_run_command,
    handle_set_picker,
    send_welcome,
)
from telegram_bot.services.command_service import (
    refresh_command_registry,
    register_telegram_service,
    watch_command_registry_loop,
)
from telegram_bot.services.control_service import run_control_api


@bot.message_handler(commands=["start", "help"])
def on_welcome(message):
    send_welcome(message)


@bot.message_handler(commands=["clear"])
def on_clear(message):
    clear_memory(message)


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


@bot.message_handler(func=lambda message: True)
def on_chat(message):
    handle_chat_message(message)


def run():
    threading.Thread(target=run_control_api, daemon=True).start()

    register_telegram_service()
    refresh_command_registry(force=True)

    if TELEGRAM_COMMAND_REFRESH_SECONDS > 0:
        threading.Thread(target=watch_command_registry_loop,
                         daemon=True).start()

    print("[*] Telegram interface starting... Waiting for messages.")
    bot.infinity_polling()


if __name__ == "__main__":
    run()
