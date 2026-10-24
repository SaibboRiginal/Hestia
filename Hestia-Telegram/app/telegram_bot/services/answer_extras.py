"""What comes with an answer besides its text (dossier docs/work/2026-10-24-tutto-brainstorm-cindy, Cindy 9 + 13).

- **changes** frame: the writes made in this turn, «Ho fatto» with one «Annulla: …» button per change that has an
  undo tool. The button is a normal tool button (``t:``, ``actions.tool_button``) with the undo arguments preset,
  so it runs like every other action (confirm card for a delete, same errors, same stale handling).
- **buttons** of the ``hestia-ui`` components: a tap (``ux:<id>``) sends their ``send`` text as the next chat
  message, shown in the chat (a button never runs a tool by itself).
"""
from __future__ import annotations

import logging
from html import escape

from telegram_bot import core, store, ui

logger = logging.getLogger("hestia_telegram.answer_extras")

SEND_PREFIX = "ux:"


def is_callback(data: str) -> bool:
    return str(data or "").startswith(SEND_PREFIX)


def _line(item: dict) -> str:
    title = str(item.get("title") or item.get("tool") or "")
    detail = str(item.get("detail") or "")
    return f"• {escape(title)}" + (f" — <i>{escape(detail[:120])}</i>" if detail else "")


def changes_view(frame: dict) -> tuple[str, object]:
    """``(html, keyboard)`` of a ``changes`` frame (keyboard None when nothing can be undone)."""
    from telegram_bot import actions
    from telegram_bot.menu import model
    items = [i for i in (frame.get("items") or []) if isinstance(i, dict)]
    menu = model.current()
    rows = []
    for item in items:
        undo = item.get("undo") if isinstance(item.get("undo"), dict) else None
        if not undo or not undo.get("tool"):
            continue
        title = str(item.get("title") or item.get("tool"))
        rows.append([actions.tool_button(menu, str(undo["tool"]), args=dict(undo.get("args") or {}),
                                         text=f"{undo.get('label') or ui.CANCEL}: {title}", limit=40)])
    return "<b>Ho fatto</b>\n" + "\n".join(_line(i) for i in items), ui.keyboard(rows)


def send_changes(chat_id, frame: dict) -> None:
    if not (frame.get("items") or []):
        return
    text, markup = changes_view(frame)
    try:
        core.bot.send_message(int(chat_id), text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=answer_changes_send_failed chat_id=%s error=%s", chat_id, exc)


def send_buttons(chat_id, buttons: list[dict]) -> None:
    if not buttons:
        return
    rows = [[ui.button(str(b["label"]), f"{SEND_PREFIX}{store.sid('send:' + str(b.get('send') or b['label']))}",
                       limit=40)] for b in buttons[:8]]
    try:
        core.bot.send_message(int(chat_id), "<i>Scegli</i>", parse_mode="HTML", reply_markup=ui.keyboard(rows))
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=answer_buttons_send_failed chat_id=%s error=%s", chat_id, exc)


def handle_callback(call) -> None:
    raw = store.resolve(call.data[len(SEND_PREFIX):]) or ""
    chat_id = call.message.chat.id
    if not raw.startswith("send:"):
        core.bot.answer_callback_query(call.id, "Questo menu è vecchio")
        return
    core.bot.answer_callback_query(call.id)
    text = raw[5:]
    try:
        core.bot.send_message(chat_id, f"› {escape(text)}", parse_mode="HTML")
    except Exception:  # noqa: BLE001
        pass
    from telegram_bot.services import chat_service
    chat_service.chat_from_text(chat_id, text)
