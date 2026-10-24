"""Navigation cards (docs/work/2026-10-23-telegram-da-zero §5.1–5.4): Home, Oggi, Aree, area card, all actions,
Notifiche, Impostazioni. One live navigation message per chat, edited in place; opening a new one collapses the old.

Callback data (≤ 64 bytes, short ids from ``store``):
``n:oggi`` · ``n:aree`` · ``n:a:<area>`` · ``n:all:<area>:<page>`` · ``n:s:<area>:<section>:<page>`` · ``n:ntf`` ·
``n:nd:<id>`` · ``n:imp`` · ``n:voce`` · ``t:<tool id>`` (run an action, ``actions``) · ``x:noop``.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from telebot.types import KeyboardButton, ReplyKeyboardMarkup

from telegram_bot import catalog, core, store, ui
from telegram_bot.inputs import MONTHS, WEEKDAYS
from telegram_bot.menu import model
from telegram_bot.render import render

logger = logging.getLogger("hestia_telegram.nav")

CARD_DELETE_WINDOW = 47 * 3600     # Telegram refuses deleting bot messages older than 48 h


# ── placing messages ─────────────────────────────────────────────────────────

def place(chat_id, html: str, markup=None, message_id: int | None = None, *, live: bool = True,
          preview: bool = False) -> int | None:
    """Edit ``message_id`` in place, or send a new live card (collapsing the previous one)."""
    if message_id:
        try:
            core.bot.edit_message_text(html, chat_id=chat_id, message_id=message_id, parse_mode="HTML",
                                       reply_markup=markup, disable_web_page_preview=not preview)
            if live:
                store.set_card(chat_id, message_id)
            return message_id
        except Exception as exc:
            err = str(exc).lower()
            if "not modified" in err:
                return message_id
            if "parse entities" in err:
                try:
                    core.bot.edit_message_text(ui.plain(html), chat_id=chat_id, message_id=message_id,
                                               reply_markup=markup)
                    return message_id
                except Exception:  # noqa: BLE001
                    pass
            logger.info("event=card_edit_failed chat_id=%s error=%s fallback=new_message", chat_id, exc)
    if live:
        collapse(chat_id)
    try:
        sent = core.bot.send_message(chat_id, html, parse_mode="HTML", reply_markup=markup,
                                     disable_web_page_preview=not preview)
    except Exception as exc:
        if "parse entities" not in str(exc).lower():
            raise
        sent = core.bot.send_message(chat_id, ui.plain(html), reply_markup=markup)
    mid = getattr(sent, "message_id", None)
    if live and mid:
        store.set_card(chat_id, mid)
    return mid


def collapse(chat_id) -> None:
    """The previous navigation card goes away (deleted when Telegram allows, else its buttons are removed)."""
    card = store.get_card(chat_id)
    if not card:
        return
    store.drop_card(chat_id)
    try:
        if time.time() - float(card.get("at", 0)) < CARD_DELETE_WINDOW:
            core.bot.delete_message(chat_id, card["message_id"])
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        core.bot.edit_message_reply_markup(chat_id, card["message_id"], reply_markup=None)
    except Exception:  # noqa: BLE001
        pass


def reply_keyboard(menu: model.Menu) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True,
                             input_field_placeholder="Scrivimi o tocca un pulsante")
    for row in menu.keyboard:
        kb.row(*[KeyboardButton(menu.doors.get(k, k)) for k in row if menu.doors.get(k, k)])
    return kb


def back_row(*buttons) -> list:
    return [b for b in buttons if b is not None]


# ── Home ─────────────────────────────────────────────────────────────────────

def _today_words(d: date | None = None) -> str:
    d = d or date.today()
    return f"{WEEKDAYS[d.weekday()].capitalize()} {d.day} {MONTHS[d.month - 1]}"


def _counts() -> dict:
    ok, payload = catalog.route("hermes", "api/notifications/counts", query={"client": "telegram"}, timeout=6)
    return payload if ok and isinstance(payload, dict) else {}


def _next_event(chat_id) -> str:
    tool = catalog.get("agenda_today")
    if not tool:
        return ""
    ok, payload = catalog.run(tool, chat_id, {}, timeout=8)
    rows = payload.get("events") or payload.get("items") if isinstance(payload, dict) else payload
    if not ok or not isinstance(rows, list):
        return ""
    from telegram_bot.render import _item_line
    for row in rows:
        if isinstance(row, dict):
            return _item_line(row)[2:]
    return ""


def home(chat_id) -> None:
    """``/start``: greeting + what is next, with the bottom keyboard (the four doors)."""
    menu = model.current()
    lines = []
    nxt = _next_event(chat_id)
    if nxt:
        lines.append(f"• Prossimo: {nxt}")
    counts = _counts()
    waiting = int(counts.get("pending") or 0) or int(counts.get("unread") or 0)
    if waiting:
        lines.append(f"• {waiting} notific{'a' if waiting == 1 else 'he'} da vedere")
    lines.append(ui.note("Scrivimi quello che ti serve, oppure usa i pulsanti qui sotto."))
    html = ui.card("Ciao", lines, subtitle=_today_words())
    core.bot.send_message(chat_id, html, parse_mode="HTML", reply_markup=reply_keyboard(menu),
                          disable_web_page_preview=True)


# ── Oggi ─────────────────────────────────────────────────────────────────────

def oggi(chat_id, message_id: int | None = None) -> None:
    menu = model.current()
    parts: list[str] = [ui.title_line(f"Oggi — {_today_words().lower()}", marker=_emoji(menu, "giornata"))]
    for name in menu.today.get("tools") or []:
        tool = catalog.get(name)
        if not tool:
            continue
        ok, payload = catalog.run(tool, chat_id, {}, timeout=12)
        if not ok:
            continue
        body = render(payload, "").html.strip()
        if body:
            parts.append(body)
    if len(parts) == 1:
        parts.append(ui.note("Niente in programma."))
    buttons = [ui.button(menu.label(n), f"t:{store.sid(n)}") for n in menu.today.get("actions") or []
               if catalog.get(n)]
    rows = ui.grid(buttons) + [[ui.button("Aggiorna", "n:oggi")]]
    place(chat_id, "\n\n".join(parts), ui.keyboard(rows), message_id)


def _emoji(menu: model.Menu, key: str) -> str:
    area = menu.area(key)
    return area.emoji if area else ""


# ── Aree ─────────────────────────────────────────────────────────────────────

def aree(chat_id, message_id: int | None = None) -> None:
    menu = model.current()
    rows: list = []
    frequent = store.most_used(4, set(menu.tool_area))
    lines = []
    if frequent:
        lines.append(ui.note("Usate spesso"))
        rows += ui.grid([ui.button(menu.label(n), f"t:{store.sid(n)}") for n in frequent])
    rows += ui.grid([ui.button(a.button_text, f"n:a:{a.key}", icon=a.icon) for a in menu.areas
                     if a.key != "altro" or a.sections])
    place(chat_id, ui.card("Aree", lines), ui.keyboard(rows), message_id)


def area(chat_id, key: str, message_id: int | None = None) -> None:
    menu = model.current()
    a = menu.area(key)
    if not a:
        return aree(chat_id, message_id)
    lines: list[str] = []
    if a.header and (tool := catalog.get(a.header)):
        ok, payload = catalog.run(tool, chat_id, {}, timeout=12)
        if ok:
            body = render(payload, "").html.strip()
            if body:
                lines.append(body)
    primary = [ui.button(menu.label(n), f"t:{store.sid(n)}", style="primary" if i == 0 else "")
               for i, n in enumerate(a.primary) if catalog.get(n)]
    rows = ui.grid(primary)
    if len(a.names) > len(primary):
        rows.append([ui.button("Tutte le azioni ›", f"n:all:{a.key}:0")])
    rows.append([ui.button("‹ Aree", "n:aree")])
    place(chat_id, ui.card(a.label, lines, marker=a.emoji), ui.keyboard(rows), message_id)


def all_actions(chat_id, key: str, page: int = 0, message_id: int | None = None) -> None:
    menu = model.current()
    a = menu.area(key)
    if not a:
        return aree(chat_id, message_id)
    sections = list(a.sections)
    if len(sections) > 1:
        rows = [[ui.button(f"{name} ({len(a.sections[name])})", f"n:s:{a.key}:{i}:0", limit=32)]
                for i, name in enumerate(sections)]
        rows.append([ui.button(f"‹ {a.label}", f"n:a:{a.key}")])
        place(chat_id, ui.card("Tutte le azioni", [], marker=a.emoji, crumbs=[a.label]), ui.keyboard(rows),
              message_id)
        return
    section(chat_id, key, 0, page, message_id)


def section(chat_id, key: str, index: int, page: int = 0, message_id: int | None = None) -> None:
    menu = model.current()
    a = menu.area(key)
    if not a or not a.sections:
        return aree(chat_id, message_id)
    names = list(a.sections.values())[min(index, len(a.sections) - 1)]
    title = list(a.sections)[min(index, len(a.sections) - 1)]
    start = page * ui.LIST_PAGE
    chunk = names[start:start + ui.LIST_PAGE]
    rows = [[ui.button(menu.label(n), f"t:{store.sid(n)}", limit=40)] for n in chunk]
    nav_row = []
    if page > 0:
        nav_row.append(ui.button("‹ Prima", f"n:s:{a.key}:{index}:{page - 1}"))
    if start + ui.LIST_PAGE < len(names):
        nav_row.append(ui.button(ui.MORE, f"n:s:{a.key}:{index}:{page + 1}"))
    if nav_row:
        rows.append(nav_row)
    back = f"n:all:{a.key}:0" if len(a.sections) > 1 else f"n:a:{a.key}"
    rows.append([ui.button(ui.BACK, back)])
    crumbs = [a.label] + (["Tutte le azioni"] if len(a.sections) == 1 else [])
    place(chat_id, ui.card(title if len(a.sections) > 1 else "Tutte le azioni", [], marker=a.emoji,
                           crumbs=crumbs if len(a.sections) == 1 else [a.label]), ui.keyboard(rows), message_id)


# ── Notifiche ────────────────────────────────────────────────────────────────

def notifiche(chat_id, message_id: int | None = None) -> None:
    ok, payload = catalog.route("hermes", "api/notifications",
                                query={"filter": "unread", "limit": 8, "client": "telegram"}, timeout=8)
    items = payload.get("items") if ok and isinstance(payload, dict) else []
    if not ok:
        place(chat_id, ui.error("Non riesco a leggere le notifiche adesso"),
              ui.keyboard([[ui.button("Riprova", "n:ntf")]]), message_id)
        return
    lines: list[str] = []
    rows: list = []
    for n in items or []:
        if not isinstance(n, dict):
            continue
        title = n.get("title") or str(n.get("message") or "")[:60] or "Notifica"
        dot = ui.tone_dot(ui.LEVEL_TONE.get(str(n.get("level") or "info")))
        when = render_when(n.get("created_at"))
        lines.append(f"{dot} {ui.esc(ui.strip_emoji(title))}" + (f" · <i>{ui.esc(when)}</i>" if when else ""))
        if n.get("pending"):
            rows.append([ui.button(f"Rispondi: {ui.strip_emoji(title)}", f"n:nd:{store.sid(str(n.get('id')))}",
                                   limit=40)])
    if not lines:
        lines.append(ui.note("Niente di nuovo."))
    menu = model.current()
    if menu.area("notifiche"):
        rows.append([ui.button("Avvisi automatici ›", "n:a:notifiche")])
    rows.append([ui.button("Aggiorna", "n:ntf")])
    place(chat_id, ui.card("Notifiche", lines, marker=_emoji(menu, "notifiche")), ui.keyboard(rows), message_id)


def render_when(value: Any) -> str:
    from telegram_bot.inputs import human_datetime
    return human_datetime(str(value)) if value else ""


def notification_detail(chat_id, short: str, message_id: int | None = None) -> None:
    nid = store.resolve(short)
    ok, payload = catalog.route("hermes", "api/notifications", query={"filter": "pending", "limit": 50,
                                                                         "client": "telegram"}, timeout=8)
    item = next((n for n in (payload or {}).get("items", []) if str(n.get("id")) == nid), None) \
        if ok and isinstance(payload, dict) else None
    if not item:
        place(chat_id, ui.card("Notifiche", [ui.note("Questa notifica non aspetta più una risposta.")]),
              ui.keyboard([[ui.button(ui.BACK, "n:ntf")]]), message_id)
        return
    from telegram_bot.services.notifications import action_buttons
    html = ui.card(item.get("title") or "Notifica", [ui.esc(item.get("message") or "")],
                   tone=ui.LEVEL_TONE.get(str(item.get("level") or "info")))
    rows = action_buttons(str(item.get("id")), item.get("actions") or [])
    rows.append([ui.button(ui.BACK, "n:ntf")])
    place(chat_id, html, ui.keyboard(rows), message_id)


# ── Impostazioni ─────────────────────────────────────────────────────────────

def impostazioni(chat_id, message_id: int | None = None) -> None:
    from telegram_bot.services import voice_service
    voice = "sì" if voice_service.is_live(chat_id) else "no"
    rows = [
        [ui.button("Chat", "set:menu"), ui.button("Menu", "m:root")],
        [ui.button(f"Risposte a voce: {voice}", "n:voce")],
    ]
    if catalog.get("settings_search"):
        rows.append([ui.button("Tutte le impostazioni", f"t:{store.sid('settings_search')}")])
    lines = [ui.note("Chat: tono, modalità, ragionamento. Menu: come sono disposti pulsanti e aree.")]
    place(chat_id, ui.card("Impostazioni", lines), ui.keyboard(rows), message_id)


def toggle_voice(chat_id, message_id: int | None = None) -> None:
    from telegram_bot.services import voice_service
    voice_service.set_live(chat_id, not voice_service.is_live(chat_id))
    impostazioni(chat_id, message_id)


# ── callbacks ────────────────────────────────────────────────────────────────

def handle(call) -> None:
    """``n:…`` buttons."""
    chat_id, mid = call.message.chat.id, call.message.message_id
    parts = str(call.data or "").split(":")
    try:
        core.bot.answer_callback_query(call.id)
    except Exception:  # noqa: BLE001
        pass
    what = parts[1] if len(parts) > 1 else ""
    if what == "oggi":
        oggi(chat_id, mid)
    elif what == "aree":
        aree(chat_id, mid)
    elif what == "a" and len(parts) > 2:
        area(chat_id, parts[2], mid)
    elif what == "all" and len(parts) > 2:
        all_actions(chat_id, parts[2], _int(parts, 3), mid)
    elif what == "s" and len(parts) > 3:
        section(chat_id, parts[2], _int(parts, 3), _int(parts, 4), mid)
    elif what == "ntf":
        notifiche(chat_id, mid)
    elif what == "nd" and len(parts) > 2:
        notification_detail(chat_id, parts[2], mid)
    elif what == "imp":
        impostazioni(chat_id, mid)
    elif what == "voce":
        toggle_voice(chat_id, mid)
    else:
        aree(chat_id, mid)


def _int(parts: list[str], i: int) -> int:
    try:
        return max(0, int(parts[i]))
    except (IndexError, ValueError):
        return 0


def stale(chat_id, message_id: int | None = None) -> None:
    """An old or unknown button: its menu loses the buttons, the current Aree card takes its place."""
    if message_id:
        try:
            core.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
    aree(chat_id)


def open_door(chat_id, door: str) -> bool:
    """A bottom keyboard button or its `/` command."""
    if door == "oggi":
        oggi(chat_id)
    elif door == "aree":
        aree(chat_id)
    elif door == "notifiche":
        notifiche(chat_id)
    elif door == "impostazioni":
        impostazioni(chat_id)
    else:
        return False
    return True
