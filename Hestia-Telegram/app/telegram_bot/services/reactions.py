"""Emoji reactions, both ways (docs/work/2026-11-06-hestia-viva F4).

- Hestia → owner: Oracle streams ``{"type":"reaction","emoji"}``; the bot puts it on the owner's message with
  ``setMessageReaction``. Telegram accepts only its own list of emoji: a near one is mapped (😂 → 🤣), anything else
  is skipped (logged), the text answer is never affected.
- Owner → Hestia: a ``message_reaction`` update on one of her messages goes to Oracle ``POST /api/chat/reaction``
  (one history line, so the next turn knows it). The reacted text comes from the answers kept for «Ascolta».
"""
import logging

from telebot import types

from telegram_bot import catalog, core

logger = logging.getLogger("hestia_telegram.reactions")

# Bot API: the emoji a bot may set as a reaction.
ALLOWED = set("👍 👎 ❤ 🔥 🥰 👏 😁 🤔 🤯 😱 🤬 😢 🎉 🤩 🤮 💩 🙏 👌 🕊 🤡 🥱 🥴 😍 🐳 ❤‍🔥 🌚 🌭 💯 🤣 ⚡ 🍌 🏆 💔 🤨 "
              "😐 🍓 🍾 💋 🖕 😈 😴 😭 🤓 👻 👨‍💻 👀 🎃 🙈 😇 😨 🤝 ✍ 🤗 🫡 🎅 🎄 ☃ 💅 🤪 🗿 🆒 💘 🙉 🦄 😘 "
              "💊 🙊 😎 👾 🤷‍♂ 🤷 🤷‍♀ 😡".split())
NEAR = {"😂": "🤣", "😄": "😁", "😃": "😁", "😀": "😁", "😊": "🥰", "🙂": "👌", "✅": "👌", "👋": "🤗",
        "💪": "🔥", "😅": "😁", "🥲": "😢", "😮": "😱", "🫶": "❤", "💙": "❤", "💚": "❤", "💜": "❤", "🧡": "❤"}


def telegram_emoji(emoji: str) -> str:
    """The emoji Telegram accepts for ``emoji`` ("" when there is none close enough)."""
    clean = str(emoji or "").replace("️", "").strip()
    if clean in ALLOWED:
        return clean
    return NEAR.get(clean, "")


def react(chat_id, message_id, emoji: str) -> bool:
    """Put Hestia's reaction on the owner's message."""
    if not message_id:
        return False
    tg = telegram_emoji(emoji)
    if not tg:
        logger.info("[🔄] event=telegram_reaction_skipped emoji=%s reason=not_in_telegram_list", emoji)
        return False
    try:
        core.bot.set_message_reaction(chat_id, int(message_id), [types.ReactionTypeEmoji(tg)])
        return True
    except Exception as exc:  # noqa: BLE001 - a reaction is an extra, the answer is already there
        logger.info("[🔄] event=telegram_reaction_failed chat_id=%s error=%s fallback=none", chat_id, exc)
        return False


def _emoji_of(reactions) -> str:
    for r in reactions or []:
        if getattr(r, "type", "") == "emoji" and getattr(r, "emoji", ""):
            return str(r.emoji)
    return ""


def on_owner_reaction(update) -> None:
    """``message_reaction`` update: the owner reacted (or took the reaction away) on a message of this chat."""
    user = getattr(update, "user", None)
    if not user or not core.is_allowed_user(str(getattr(user, "id", ""))):
        return
    chat_id = update.chat.id
    emoji = _emoji_of(getattr(update, "new_reaction", None))
    from telegram_bot.services import voice_service
    text = voice_service.answer_text(chat_id, update.message_id) or ""
    if not text and not emoji:
        return
    body = {"session_id": core.get_session(str(chat_id)), "emoji": emoji, "text": text}
    ok, detail = catalog.route("oracle", "api/chat/reaction", "POST", body=body, timeout=8)
    if not ok:
        logger.warning("[🔄] event=owner_reaction_not_saved chat_id=%s detail=%s", chat_id, str(detail)[:200])
    else:
        logger.info("event=owner_reaction_saved chat_id=%s emoji=%s", chat_id, emoji or "-")
