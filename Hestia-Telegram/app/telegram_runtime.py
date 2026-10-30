"""Telegram bot entry point: one router for every button and message (docs/work/2026-10-23-telegram-da-zero §5).

Messages, in order: the bottom keyboard (exact words) → `/` commands (doors, aliases, any tool by name) → an open
flow (action, menu editor, chat setting, the assistant's question) → chat. Buttons go by prefix to one handler each;
an unknown or old button never errors: «Questo menu è vecchio» and the current card.
"""
import logging
import threading

from telegram_bot import actions, catalog, core, nav, store
from telegram_bot.menu import editor, model
from telegram_bot.services import answer_extras, assistant_questions, chat_service, chat_settings, voice_service
from telegram_bot.services.control_service import run_control_api
from telegram_bot.services.notifications import handle_callback as handle_notification_callback
from telegram_bot.services.notifications import answer_by_reply as answer_notification_by_reply
from telegram_bot.services.notifications import mark_seen_on_activity as mark_notifications_seen
from telegram_bot.services.presence import touch as presence_touch

logger = logging.getLogger("hestia_telegram")

BOT_DESCRIPTION = ("Il tuo assistente personale. Scrivimi come a una persona, mandami vocali, foto e file, "
                   "oppure usa i pulsanti: Oggi, Aree, Notifiche, Impostazioni.")
BOT_SHORT_DESCRIPTION = "Il tuo assistente personale: agenda, allenamento, spese, casa e molto altro."

# Old prefixes from messages already in the chat.
_OLD_PREFIXES = ("grp:", "run:", "pickarg:", "cal_", "doc_", "cancel_flow")


def _allowed(update) -> bool:
    """Central guard for button callbacks (messages are checked in handlers so unknown users get a reply)."""
    ok = core.is_allowed_user(getattr(update.from_user, "id", ""))
    if ok:
        presence_touch(update, "command")
    else:
        logger.warning("event=unauthorized_callback user_id=%s", getattr(update.from_user, "id", ""))
    return ok


# ── buttons ──────────────────────────────────────────────────────────────────

def _route_callback(call) -> None:
    data = str(call.data or "")
    if data.startswith("n:"):
        nav.handle(call)
    elif data.startswith("t:"):
        actions.handle_tool(call)
    elif data.startswith("f:"):
        actions.handle_flow(call)
    elif data.startswith("m:"):
        editor.handle(call)
    elif data.startswith("set:"):
        chat_settings.handle(call)
    elif data.startswith(("na:", "ntf:")):
        handle_notification_callback(call)
    elif data.startswith(("confirm:", "cancel:", "confirm_cmd:", "cancel_cmd:")):
        chat_service.handle_confirmation(call)
    elif assistant_questions.is_callback(data):
        assistant_questions.handle_callback(call)
    elif answer_extras.is_callback(data):
        answer_extras.handle_callback(call)
    elif data.startswith("fb:"):
        chat_service.handle_feedback_callback(call)
    elif data == voice_service.LISTEN_CALLBACK:
        voice_service.handle_listen_callback(call)
    elif data == "x:noop":
        core.bot.answer_callback_query(call.id)
    else:
        try:
            core.bot.answer_callback_query(call.id, "Questo menu è vecchio")
        except Exception:  # noqa: BLE001
            pass
        nav.stale(call.message.chat.id, call.message.message_id)


def on_callback(call):
    logger.info("event=telegram_callback kind=%s chat_id=%s", str(call.data or "").split(":", 1)[0],
                call.message.chat.id)
    try:
        _route_callback(call)
    except Exception as exc:  # noqa: BLE001 — a button never leaves the spinner turning
        logger.warning("event=telegram_callback_failed data=%s error=%s", call.data, exc)
        try:
            core.bot.answer_callback_query(call.id, "Non riuscito, riprova")
        except Exception:  # noqa: BLE001
            pass


# ── messages ─────────────────────────────────────────────────────────────────

def open_command(chat_id, name: str, args: str = "") -> bool:
    """A `/` command: a door, an alias, a local action or any tool by name. False when unknown."""
    menu = model.current()
    name = model.D.ALIASES.get(name, name)
    if name in ("home", "start"):
        nav.home(chat_id)
        return True
    if name in menu.doors and nav.open_door(chat_id, name):
        return True
    return actions.from_command(chat_id, name, args)


def _end_flow_for_navigation(chat_id) -> None:
    """A tap on the keyboard or a `/` command ends an open action (and says so)."""
    if actions.pending(chat_id):
        actions.cancel(chat_id)
    elif (flow := store.get_flow(chat_id)) and flow.get("kind") in ("menu", "chat_setting"):
        store.clear_flow(chat_id)


def on_file(message):
    if not chat_service.is_authorized(message):
        return
    mark_notifications_seen(message)
    presence_touch(message, "chat")
    # a voice note goes to an open action that asks for a file (e.g. the spoken diary), otherwise to the chat
    if message.content_type in ("photo", "document", "voice", "audio") and actions.on_file(message.chat.id, message):
        return
    chat_service.handle_file_message(message)


def on_message(message):
    if not chat_service.is_authorized(message):
        return
    mark_notifications_seen(message)
    presence_touch(message)
    chat_id = message.chat.id
    text = str(message.text or "").strip()
    if not text:
        return
    menu = model.current()
    door = menu.door_for_text(text)
    if door:
        _end_flow_for_navigation(chat_id)
        nav.open_door(chat_id, door)
        return
    if text.startswith("/"):
        token, _, args = text[1:].partition(" ")
        name = token.split("@")[0].strip().lower()
        if name == "start" and args.strip():          # deep link t.me/<bot>?start=<area|action>
            name, args = args.strip().lower(), ""
            if menu.area(name):
                nav.area(chat_id, name)
                return
        _end_flow_for_navigation(chat_id)
        if open_command(chat_id, name, args):
            return
        core.bot.reply_to(message, "Non conosco questo comando. Scrivimi cosa ti serve, oppure tocca «Aree».")
        return
    if actions.on_text(chat_id, text):
        return
    if editor.on_text(chat_id, text) or chat_settings.on_text(chat_id, text):
        return
    if answer_notification_by_reply(message, text):
        return
    flow = store.get_flow(chat_id)
    if flow and flow.get("kind") == assistant_questions.TEXT_FLOW:
        if assistant_questions.answer_text(message, flow, text):
            return
    chat_service.handle_chat_message(message)


# ── boot ─────────────────────────────────────────────────────────────────────

def register_handlers() -> None:
    core.bot.register_callback_query_handler(on_callback, func=_allowed)
    core.bot.register_message_handler(on_file, content_types=["document", "photo", "audio", "voice", "video",
                                                         "video_note"])
    core.bot.register_message_handler(on_message, func=lambda message: True)


def setup_bot_profile() -> None:
    """`/` menu (8 entries, owner's chat only, set once at boot), bot description in Italian, menu button."""
    from telebot.types import BotCommand, BotCommandScopeChat
    menu = model.current()
    commands = [BotCommand(name, desc) for name, desc in menu.commands]
    owner = core.resolve_notify_target("owner")
    try:
        core.bot.set_my_commands(commands)
        if owner:
            core.bot.set_my_commands(commands, scope=BotCommandScopeChat(int(owner)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=telegram_set_commands_failed error=%s", exc)
    for call, value in ((core.bot.set_my_description, BOT_DESCRIPTION),
                        (core.bot.set_my_short_description, BOT_SHORT_DESCRIPTION)):
        try:
            call(value, language_code="it")
        except Exception as exc:  # noqa: BLE001
            logger.info("event=telegram_profile_skipped error=%s", exc)
    from telegram_bot import webapp
    webapp.set_menu_button()


def run():
    register_handlers()
    threading.Thread(target=run_control_api, daemon=True).start()
    from telegram_settings import settings as telegram_settings
    telegram_settings.start()   # Themis: declare + load values (background, hourly re-assert)

    if catalog.register_with_hub():
        logger.info("event=telegram_service_registered_hub")
    else:
        logger.warning("event=telegram_hub_registration_failed will_retry=keepalive")
    try:
        from hestia_common.startup_utils import start_hub_keepalive
        start_hub_keepalive(catalog.register_with_hub, logger=logger)
    except ImportError:
        logger.warning("[🔄] event=hub_keepalive_unavailable reason=hestia_common_missing")
    try:
        catalog.refresh(force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=telegram_catalog_boot_failed error=%s fallback=lazy", exc)
    setup_bot_profile()
    # Messages queued while the assistant was offline (and this bot was down too) get their answer now.
    from telegram_bot.services.chat_queue import drain_async
    drain_async("startup")
    logger.info("event=telegram_interface_starting")
    core.bot.infinity_polling()


if __name__ == "__main__":
    run()
