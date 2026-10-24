"""Impostazioni › Menu: change the menus from Telegram (docs/work/2026-10-23-telegram-da-zero §5.11).

Every change edits the user's layout (Themis ``telegram.menu.layout``), is saved at once and the card is redrawn.
Callback data ``m:…``: ``root`` · ``a:<area>`` · ``p:<area>`` primary list · ``pu|pd|px:<area>:<i>`` up/down/remove ·
``pa:<area>:<page>`` add list · ``pp:<area>:<tool id>`` add · ``rn:<area>`` rename · ``em:<area>`` emoji ·
``ou|od:<area>`` area order · ``mv:<area>:<page>`` move an action · ``mt:<tool id>`` pick target ·
``mto:<tool id>:<area>`` move · ``ra:<area>`` restore area · ``new`` new area · ``reset`` / ``reset:ok`` restore all.
Typed values (rename, emoji, new area) use the chat flow ``{"kind": "menu"}``.
"""
from __future__ import annotations

import copy
import logging
import re

from telegram_bot import core, store, ui
from telegram_bot.menu import model

logger = logging.getLogger("hestia_telegram.menu_editor")

PAGE = 8


# ── layout read / write ──────────────────────────────────────────────────────

def _layout() -> dict:
    return copy.deepcopy(model.layout())


def save(layout: dict) -> bool:
    import telegram_settings as ts
    ok = ts.settings.put(ts.MENU_LAYOUT, layout, actor="user", reason="Telegram · Impostazioni › Menu")
    if ok:
        try:  # use it at once; Themis pushes the same value back
            ts.settings.apply({**ts.settings._stored, ts.MENU_LAYOUT: layout})
        except Exception as exc:  # noqa: BLE001
            logger.info("event=menu_layout_local_apply_failed error=%s", exc)
    logger.info("event=menu_layout_saved ok=%s areas=%d tools=%d", ok, len(layout.get("areas") or {}),
                len(layout.get("tools") or {}))
    return ok


def _area_over(layout: dict, key: str) -> dict:
    return layout.setdefault("areas", {}).setdefault(key, {})


def _place(chat_id, html: str, rows, message_id) -> None:
    from telegram_bot import nav
    nav.place(chat_id, html, ui.keyboard(rows), message_id)


def _failed(chat_id, message_id, back: str) -> None:
    _place(chat_id, ui.error("Non sono riuscita a salvare il menu"), [[ui.button(ui.BACK, back)]], message_id)


# ── cards ────────────────────────────────────────────────────────────────────

def root(chat_id, message_id=None) -> None:
    menu = model.current()
    rows = ui.grid([ui.button(a.button_text, f"m:a:{a.key}", icon=a.icon) for a in menu.all_areas
                    if a.sections or a.key != "altro"])
    rows.append([ui.button("Nuova area", "m:new"), ui.button("Ripristina tutto", "m:reset")])
    rows.append([ui.button("‹ Impostazioni", "n:imp")])
    lines = [ui.note("Scegli un'area per cambiare nome, emoji, ordine e azioni principali.")]
    _place(chat_id, ui.card("Menu", lines, crumbs=["Impostazioni"]), rows, message_id)


def area(chat_id, key: str, message_id=None) -> None:
    menu = model.current()
    a = menu.area(key)
    if not a:
        return root(chat_id, message_id)
    lines = [f"Azioni: {len(a.names)}", "Principali: " + (", ".join(ui.esc(menu.label(n)) for n in a.primary)
                                                       or "nessuna")]
    rows = [[ui.button("Azioni principali", f"m:p:{key}")],
            [ui.button("Rinomina", f"m:rn:{key}"), ui.button("Emoji", f"m:em:{key}")],
            [ui.button("Più su", f"m:ou:{key}"), ui.button("Più giù", f"m:od:{key}")],
            [ui.button("Sposta un'azione", f"m:mv:{key}:0")],
            [ui.button("Ripristina quest'area", f"m:ra:{key}")],
            [ui.button("‹ Menu", "m:root")]]
    _place(chat_id, ui.card(a.label, lines, marker=a.emoji, crumbs=["Menu"]), rows, message_id)


def primary(chat_id, key: str, message_id=None) -> None:
    menu = model.current()
    a = menu.area(key)
    if not a:
        return root(chat_id, message_id)
    rows = []
    for i, name in enumerate(a.primary):
        rows.append([ui.button(menu.label(name), "x:noop", limit=20), ui.button("Su", f"m:pu:{key}:{i}"),
                     ui.button("Giù", f"m:pd:{key}:{i}"), ui.button("Togli", f"m:px:{key}:{i}")])
    rows.append([ui.button("Aggiungi", f"m:pa:{key}:0")])
    rows.append([ui.button(f"‹ {a.label}", f"m:a:{key}")])
    lines = [ui.note("Sono i pulsanti in cima alla card dell'area, in quest'ordine.")]
    if not a.primary:
        lines.append(ui.note("Nessuna: aggiungine una."))
    _place(chat_id, ui.card("Azioni principali", lines, marker=a.emoji, crumbs=["Menu", a.label]), rows,
           message_id)


def _paged(names: list[str], page: int, make, more: str, back: str) -> list:
    chunk = names[page * PAGE:(page + 1) * PAGE]
    rows = [[make(n)] for n in chunk]
    nav_row = []
    if page > 0:
        nav_row.append(ui.button("‹ Prima", more.format(page - 1)))
    if (page + 1) * PAGE < len(names):
        nav_row.append(ui.button(ui.MORE, more.format(page + 1)))
    if nav_row:
        rows.append(nav_row)
    rows.append([ui.button(ui.BACK, back)])
    return rows


def add_list(chat_id, key: str, page: int, message_id=None) -> None:
    menu = model.current()
    a = menu.area(key)
    if not a:
        return root(chat_id, message_id)
    names = [n for n in a.names if n not in a.primary]
    rows = _paged(names, page, lambda n: ui.button(menu.label(n), f"m:pp:{key}:{store.sid(n)}", limit=40),
                  f"m:pa:{key}:{{}}", f"m:p:{key}")
    _place(chat_id, ui.card("Aggiungi alle principali", [], marker=a.emoji, crumbs=["Menu", a.label]), rows,
           message_id)


def move_list(chat_id, key: str, page: int, message_id=None) -> None:
    menu = model.current()
    a = menu.area(key)
    if not a:
        return root(chat_id, message_id)
    rows = _paged(a.names, page, lambda n: ui.button(menu.label(n), f"m:mt:{store.sid(n)}", limit=40),
                  f"m:mv:{key}:{{}}", f"m:a:{key}")
    _place(chat_id, ui.card("Quale azione sposto?", [], marker=a.emoji, crumbs=["Menu", a.label]), rows,
           message_id)


def move_target(chat_id, short: str, message_id=None) -> None:
    menu = model.current()
    name = store.resolve(short)
    current = menu.area_of(name or "")
    if not name or not current:
        return root(chat_id, message_id)
    rows = ui.grid([ui.button(a.button_text, f"m:mto:{short}:{a.key}") for a in menu.all_areas
                    if a.key not in (current.key, "altro")])
    rows.append([ui.button(ui.BACK, f"m:mv:{current.key}:0")])
    _place(chat_id, ui.card(f"Dove sposto «{menu.label(name)}»?", []), rows, message_id)


def ask_text(chat_id, op: str, key: str, message_id=None) -> None:
    menu = model.current()
    a = menu.area(key) if key else None
    question = {"rn": f"Nuovo nome per {a.label if a else 'l area'}?", "em": "Quale emoji? Mandamene una.",
                "new": "Come si chiama la nuova area?"}[op]
    store.set_flow(chat_id, {"kind": "menu", "op": op, "area": key, "message_id": message_id})
    rows = [[ui.button(ui.CANCEL, f"m:a:{key}" if key else "m:root")]]
    _place(chat_id, ui.card(question, [ui.note("Scrivilo qui in chat.")], crumbs=["Menu"]), rows, message_id)


# ── edits ────────────────────────────────────────────────────────────────────

def _set_primary(key: str, names: list[str]) -> bool:
    layout = _layout()
    _area_over(layout, key)["primary"] = names
    return save(layout)


def _area_order(key: str, delta: int) -> bool:
    menu = model.current()
    keys = [a.key for a in menu.all_areas]
    if key not in keys:
        return False
    i = keys.index(key)
    j = max(0, min(len(keys) - 1, i + delta))
    keys[i], keys[j] = keys[j], keys[i]
    layout = _layout()
    for n, k in enumerate(keys):
        _area_over(layout, k)["order"] = (n + 1) * 10
    return save(layout)


def _move(name: str, target: str) -> bool:
    layout = _layout()
    layout.setdefault("tools", {}).setdefault(name, {})["area"] = target
    for over in (layout.get("areas") or {}).values():
        if isinstance(over, dict) and isinstance(over.get("primary"), list) and name in over["primary"]:
            over["primary"].remove(name)
    return save(layout)


def _restore_area(key: str) -> bool:
    layout = _layout()
    (layout.get("areas") or {}).pop(key, None)
    for name, over in list((layout.get("tools") or {}).items()):
        if isinstance(over, dict) and over.get("area") == key:
            layout["tools"].pop(name)
    return save(layout)


def on_text(chat_id, text: str) -> bool:
    flow = store.get_flow(chat_id)
    if not flow or flow.get("kind") != "menu":
        return False
    store.clear_flow(chat_id)
    op, key, mid = flow.get("op"), str(flow.get("area") or ""), flow.get("message_id")
    value = text.strip()
    layout = _layout()
    if op == "rn":
        _area_over(layout, key)["label"] = ui.strip_emoji(value)[:24] or key.capitalize()
    elif op == "em":
        emoji = "".join(ch for ch in value if ui._is_emoji_char(ch))[:8]
        if not emoji:
            _place(chat_id, ui.error("Non è un'emoji", "Manda una sola emoji."),
                   [[ui.button("Riprova", f"m:em:{key}")]], mid)
            return True
        _area_over(layout, key)["emoji"] = emoji
    elif op == "new":
        label = ui.strip_emoji(value)[:24]
        key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:20] or "nuova"
        _area_over(layout, key).update({"label": label or "Nuova area", "emoji": "•", "order": 800})
    if not save(layout):
        _failed(chat_id, mid, "m:root")
        return True
    if op == "new":
        _place(chat_id, ui.card(f"Area «{label}» creata", [ui.note(
            "Comparirà nelle Aree appena le sposti dentro un'azione.")], crumbs=["Menu"]),
            [[ui.button("‹ Menu", "m:root")]], mid)
        return True
    area(chat_id, key, mid)
    return True


# ── callbacks ────────────────────────────────────────────────────────────────

def _int(parts: list[str], i: int) -> int:
    try:
        return max(0, int(parts[i]))
    except (IndexError, ValueError):
        return 0


def handle(call) -> None:
    chat_id, mid = call.message.chat.id, call.message.message_id
    parts = str(call.data or "").split(":")
    op = parts[1] if len(parts) > 1 else "root"
    key = parts[2] if len(parts) > 2 else ""
    try:
        core.bot.answer_callback_query(call.id)
    except Exception:  # noqa: BLE001
        pass
    menu = model.current()
    a = menu.area(key) if key else None
    if op == "a":
        return area(chat_id, key, mid)
    if op == "p":
        return primary(chat_id, key, mid)
    if op in ("pu", "pd", "px") and a:
        names = list(a.primary)
        i = _int(parts, 3)
        if i < len(names):
            if op == "px":
                names.pop(i)
            else:
                j = max(0, min(len(names) - 1, i + (-1 if op == "pu" else 1)))
                names[i], names[j] = names[j], names[i]
            if not _set_primary(key, names):
                return _failed(chat_id, mid, f"m:p:{key}")
        return primary(chat_id, key, mid)
    if op == "pa":
        return add_list(chat_id, key, _int(parts, 3), mid)
    if op == "pp" and a:
        name = store.resolve(parts[3]) if len(parts) > 3 else None
        if name and name not in a.primary:
            if not _set_primary(key, [*a.primary, name][:12]):
                return _failed(chat_id, mid, f"m:p:{key}")
        return primary(chat_id, key, mid)
    if op in ("rn", "em"):
        return ask_text(chat_id, op, key, mid)
    if op == "new":
        return ask_text(chat_id, "new", "", mid)
    if op in ("ou", "od"):
        if not _area_order(key, -1 if op == "ou" else 1):
            return _failed(chat_id, mid, f"m:a:{key}")
        return area(chat_id, key, mid)
    if op == "mv":
        return move_list(chat_id, key, _int(parts, 3), mid)
    if op == "mt":
        return move_target(chat_id, key, mid)
    if op == "mto" and len(parts) > 3:
        name = store.resolve(key)
        if name and not _move(name, parts[3]):
            return _failed(chat_id, mid, "m:root")
        return area(chat_id, parts[3], mid)
    if op == "ra":
        if not _restore_area(key):
            return _failed(chat_id, mid, f"m:a:{key}")
        return area(chat_id, key, mid)
    if op == "reset":
        if key == "ok":
            if not save({}):
                return _failed(chat_id, mid, "m:root")
            return root(chat_id, mid)
        return _place(chat_id, ui.card("Ripristino il menu predefinito?", [ui.note(
            "Nomi, emoji, ordine e azioni principali tornano come all'inizio.")], crumbs=["Menu"]),
            [[ui.button("Ripristina", "m:reset:ok", style="danger"), ui.button(ui.CANCEL, "m:root")]], mid)
    return root(chat_id, mid)
