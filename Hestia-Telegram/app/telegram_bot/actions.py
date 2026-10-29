"""Running an action (docs/work/2026-10-23-telegram-da-zero §5.5): ask what the tool needs, in words and with buttons,
confirm when it writes, run it, show the result in the same message.

One flow per chat, persisted in ``store`` (survives a restart). Callback data:
``t:<tool id>[:<values id>]`` start an action (values preset by a result button) · ``f:v:<n>`` pick button n ·
``f:skip`` · ``f:back`` · ``f:cancel`` · ``f:ok`` confirm · ``f:more`` optional details · ``f:edit`` change the
options of the last result · ``f:retry`` · ``f:quit`` / ``f:stay`` (a sentence written in the middle of a flow).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from telegram_bot import catalog, core, inputs, store, ui, usage
from telegram_bot.menu import model
from telegram_bot.render import Rendered, render

logger = logging.getLogger("hestia_telegram.actions")

_DELETE = re.compile(r"(delete|elimina|remove|rimuovi)", re.I)
_TECH = re.compile(r"(error|exception|traceback|http|\{|\[|=|_id\b|errno|refused|timeout)", re.I)


# ── helpers ──────────────────────────────────────────────────────────────────

def _menu() -> model.Menu:
    return model.current()


def _title(menu: model.Menu, tool: catalog.Tool) -> str:
    return menu.labels.get(tool.name) or ui.label(tool.title, 40)


def _area(menu: model.Menu, tool: catalog.Tool):
    return menu.area_of(tool.name)


def _fields(tool: catalog.Tool) -> dict[str, inputs.Field]:
    return {f.name: f for f in inputs.fields(tool)}


def values_id(args: dict) -> str:
    """Short id of preset values (result buttons carry them)."""
    return store.sid("args:" + json.dumps(args, sort_keys=True, ensure_ascii=False))


def _values_of(short: str) -> dict:
    raw = store.resolve(short) or ""
    if raw.startswith("args:"):
        try:
            value = json.loads(raw[5:])
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}
    return {}


def tool_button(menu: model.Menu, name: str, *, args: dict | None = None, text: str = "", style: str = "",
                limit: int = ui.LABEL_MAX):
    data = f"t:{store.sid(name)}" + (f":{values_id(args)}" if args else "")
    return ui.button(text or menu.label(name), data, style=style, limit=limit)


def _answer(call, text: str = "") -> None:
    try:
        core.bot.answer_callback_query(call.id, text[:190] if text else None)
    except Exception:  # noqa: BLE001
        pass


def _human_problem(payload: Any) -> str:
    """A module's error detail only when it is already a sentence for a person."""
    detail = payload.get("detail") or payload.get("message") or payload.get("error") \
        if isinstance(payload, dict) else payload
    text = str(detail or "").strip()
    if 6 <= len(text) <= 140 and not _TECH.search(text):
        return text if text.endswith(".") else text + "."
    return "Riprova tra poco."


# ── start ────────────────────────────────────────────────────────────────────

def start(chat_id, name: str, message_id: int | None = None, preset: dict | None = None,
          extra: bool = False) -> None:
    """Begin an action: preset values are kept, missing required ones are asked one at a time."""
    tool = catalog.get(name)
    if not tool:
        from telegram_bot import nav
        nav.place(chat_id, ui.card("Azione non disponibile", [ui.note("Questa azione non c'è più. Ecco le aree.")]),
                  None, message_id)
        nav.aree(chat_id)
        return
    fields = _fields(tool)
    values = {k: v for k, v in (preset or {}).items() if v not in (None, "")}
    queue = [f.name for f in fields.values() if f.required and f.name not in values]
    if extra:
        queue += [f.name for f in fields.values() if not f.required and f.name not in values]
    flow = {"kind": "action", "tool": tool.name, "values": values, "queue": queue, "pos": 0,
            "mode": "ask", "message_id": message_id, "extra": extra, "asked": []}
    store.count_use(tool.name)
    usage.tap(tool.name)
    _advance(chat_id, flow)


def _advance(chat_id, flow: dict) -> None:
    tool = catalog.get(flow["tool"])
    if not tool:
        store.clear_flow(chat_id)
        return
    fields = _fields(tool)
    while flow["pos"] < len(flow["queue"]) and flow["queue"][flow["pos"]] in flow["values"]:
        flow["pos"] += 1
    if flow["pos"] < len(flow["queue"]):
        name = flow["queue"][flow["pos"]]
        if name in fields:
            flow["mode"] = "ask"
            _ask(chat_id, flow, tool, fields[name])
            return
        flow["pos"] += 1
        return _advance(chat_id, flow)
    if tool.writes:
        flow["mode"] = "confirm"
        _confirm(chat_id, flow, tool, fields)
        return
    _run(chat_id, flow, tool)


# ── asking ───────────────────────────────────────────────────────────────────

def _picker_values(chat_id, tool: catalog.Tool, f: inputs.Field) -> list[tuple[str, str]]:
    """Real items for an argument declared with ``arg_picker`` (e.g. which subscription)."""
    picker = tool.arg_picker or {}
    source = picker.get("source") if isinstance(picker.get("source"), dict) else {}
    if str(picker.get("arg") or "") != f.name or not source.get("service"):
        return []
    ok, payload = catalog.route(str(source["service"]), str(source.get("path") or ""),
                                str(source.get("method") or "GET"), timeout=10)
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not ok or not isinstance(rows, list):
        return []
    value_field = str(picker.get("value_field") or f.name)
    label_fields = [str(x) for x in picker.get("label_fields") or []]
    out: list[tuple[str, str]] = []
    for row in rows[:12]:
        if not isinstance(row, dict) or not str(row.get(value_field) or "").strip():
            continue
        parts = []
        for lf in label_fields:
            v = row.get(lf)
            if isinstance(v, dict):
                v = ", ".join(str(x) for x in v.values() if str(x).strip())
            if str(v or "").strip():
                parts.append(str(v).strip())
        out.append((" · ".join(parts[:2]) or f"Voce {len(out) + 1}", str(row[value_field])))
    return out


def _ask(chat_id, flow: dict, tool: catalog.Tool, f: inputs.Field, problem: str = "") -> None:
    menu = _menu()
    area = _area(menu, tool)
    total = len(flow["queue"])
    time_step = f.kind == "datetime" and bool(flow.get("date_part"))
    lines: list[str] = []
    question = f.label + ("?" if f.kind in ("bool",) else "")
    if time_step:
        question = f"{f.label}: a che ora?"
    lines.append(f"<b>{ui.esc(question)}</b>")
    if f.help and not time_step:
        lines.append(ui.esc(f.help))
    if f.kind == "file":
        lines.append(ui.note("Mandami un vocale qui in chat." if f.media.startswith("audio")
                             else "Mandami la foto o il file qui in chat."))
    elif f.placeholder and not time_step:
        lines.append(ui.note(f"Es. {f.placeholder}"))
    elif f.kind == "datetime" and not time_step:
        lines.append(ui.note("Scegli il giorno o scrivi «domani 18:30»."))
    if problem:
        lines.append(f"{ui.tone_dot('warning')} {ui.esc(problem)}")
    subtitle = f"Passo {flow['pos'] + 1} di {total}" if total > 1 else ""

    if time_step:
        choices = inputs.time_values()
    else:
        choices = _picker_values(chat_id, tool, f) or inputs.quick_values(f)
    current = flow["values"].get(f.name)
    buttons = []
    for i, (label, value) in enumerate(choices):
        shown = f"• {label}" if current is not None and str(current) == str(value) else label
        buttons.append(ui.button(shown, f"f:v:{i}", limit=32))
    flow["choices"] = [v for _, v in choices]
    per_row = 3 if all(len(lbl) <= 10 for lbl, _ in choices) else 2
    rows = ui.grid(buttons, per_row=per_row)
    nav_row = [ui.button(ui.BACK, "f:back")]
    if not f.required:
        nav_row.append(ui.button(ui.SKIP, "f:skip"))
    nav_row.append(ui.button(ui.CANCEL, "f:cancel"))
    rows.append(nav_row)
    html = ui.card(_title(menu, tool), lines, subtitle=subtitle, marker=area.emoji if area else "",
                   crumbs=[area.label] if area else [])
    from telegram_bot import nav
    flow["message_id"] = nav.place(chat_id, html, ui.keyboard(rows), flow.get("message_id"))
    store.set_flow(chat_id, flow)


def _set_value(chat_id, flow: dict, f: inputs.Field, value: Any, problem: str = "") -> None:
    tool = catalog.get(flow["tool"])
    if f.kind == "datetime":
        if flow.get("date_part"):
            value = f"{flow.pop('date_part')}T{value}:00"
        elif problem == "time":
            flow["date_part"] = str(value)[:10]
            _ask(chat_id, flow, tool, f)
            return
    flow["values"][f.name] = value
    flow["asked"] = [*flow.get("asked", []), f.name]
    flow["pos"] += 1
    _advance(chat_id, flow)


def _current_field(flow: dict) -> tuple[catalog.Tool | None, inputs.Field | None]:
    tool = catalog.get(flow.get("tool", ""))
    if not tool or flow.get("mode") != "ask" or flow["pos"] >= len(flow["queue"]):
        return tool, None
    return tool, _fields(tool).get(flow["queue"][flow["pos"]])


# ── confirm, run, result ─────────────────────────────────────────────────────

def _summary(fields: dict[str, inputs.Field], values: dict) -> list[str]:
    lines = []
    for name, value in values.items():
        f = fields.get(name)
        label = f.label if f else re.sub(r"[_.]+", " ", name).capitalize()
        shown = inputs.shown_value(f, value) if f else str(value)
        lines.append(f"{ui.esc(label)}: {ui.esc(shown[:200])}")
    return lines


def _confirm(chat_id, flow: dict, tool: catalog.Tool, fields: dict[str, inputs.Field]) -> None:
    menu = _menu()
    area = _area(menu, tool)
    title = _title(menu, tool)
    lines = _summary(fields, flow["values"]) or [ui.note("Nessun dato da aggiungere.")]
    if tool.destructive:
        ok_label = "Elimina" if _DELETE.search(tool.name + " " + tool.title) else title
        ok_button = ui.button(ok_label, "f:ok", style="danger")
        lines.append(ui.note("Non si può annullare."))
    else:
        ok_button = ui.button(ui.CONFIRM, "f:ok", style="success")
    rows = [[ok_button, ui.button(ui.CANCEL, "f:cancel")]]
    optional = [n for n, f in fields.items() if not f.required and n not in flow["values"]]
    if optional and not flow.get("extra"):
        rows.append([ui.button("Altri dettagli", "f:more")])
    if flow["queue"]:
        rows.append([ui.button(ui.BACK, "f:back")])
    html = ui.card(title, lines, subtitle="Confermi?", marker=area.emoji if area else "",
                   crumbs=[area.label] if area else [])
    from telegram_bot import nav
    flow["message_id"] = nav.place(chat_id, html, ui.keyboard(rows), flow.get("message_id"))
    store.set_flow(chat_id, flow)


def _run(chat_id, flow: dict, tool: catalog.Tool) -> None:
    from telegram_bot import nav
    menu = _menu()
    area = _area(menu, tool)
    title = _title(menu, tool)
    marker = area.emoji if area else ""
    if flow.get("message_id"):
        nav.place(chat_id, ui.card(title, [ui.note("Un attimo…")], marker=marker), None, flow["message_id"])
    try:
        core.bot.send_chat_action(chat_id, "typing")
    except Exception:  # noqa: BLE001
        pass
    ok, payload = catalog.run(tool, chat_id, flow["values"], timeout=45)
    logger.info("event=telegram_action_run action=%s ok=%s values=%d", tool.name, ok, len(flow["values"]))
    rows: list = []
    if not ok:
        html = ui.error(f"Non sono riuscita: {title}", _human_problem(payload))
        rows.append([ui.button("Riprova", "f:retry")])
    else:
        result = payload if isinstance(payload, Rendered) else render(payload, title, marker)
        html = result.html
        acts = [a for a in result.actions if catalog.get(a.tool)]
        rows += ui.grid([tool_button(menu, a.tool, args=a.args, text=a.label, style=a.style) for a in acts])
        rows += [list(r) for r in result.rows]
        if not tool.writes and any(not f.required for f in inputs.fields(tool)):
            rows.append([ui.button("Cambia", "f:edit")])
        if result.image or result.images or result.document or result.files:
            _media(chat_id, result)
    back = []
    if area:
        back.append(ui.button(f"‹ {area.label}", f"n:a:{area.key}"))
    if ok and tool.writes:
        back.append(ui.button("Di nuovo", f"t:{store.sid(tool.name)}"))
    rows.append(back)
    nav.place(chat_id, html, ui.keyboard(rows), flow.get("message_id"), live=False,
              preview=ok and html.count("<a href") == 1)
    store.set_flow(chat_id, {**flow, "mode": "done"})


def _media(chat_id, result: Rendered) -> None:
    """Images of a result as photo / album, a file as a document (under the card)."""
    try:
        photos = [result.image] if result.image else []
        photos += [i for i in result.images if i not in photos]
        if len(photos) == 1:
            core.bot.send_photo(chat_id, photos[0])
        elif photos:
            from telebot.types import InputMediaPhoto
            core.bot.send_media_group(chat_id, [InputMediaPhoto(p) for p in photos[:10]])
        if result.document:
            name, data = result.document
            core.bot.send_document(chat_id, (name, data))
        for f in result.files:
            ok, blob = catalog.route("archive", f"api/blobs/{f['blob_id']}/base64", timeout=30)
            if not ok or not isinstance(blob, dict) or not blob.get("data_b64"):
                logger.info("[🔄] event=telegram_result_file_missing fallback=card_only")
                continue
            data = base64.b64decode(blob["data_b64"])
            if str(f.get("mime") or blob.get("mime") or "").startswith("image/"):
                core.bot.send_photo(chat_id, data)
            else:
                core.bot.send_document(chat_id, (str(f.get("name") or "file"), data))
    except Exception as exc:  # noqa: BLE001 — the card is already there
        logger.info("event=telegram_result_media_failed error=%s", exc)


# ── typed input ──────────────────────────────────────────────────────────────

def pending(chat_id) -> dict | None:
    flow = store.get_flow(chat_id)
    return flow if flow and flow.get("kind") == "action" and flow.get("mode") in ("ask", "confirm") else None


def on_text(chat_id, text: str) -> bool:
    """A message while an action waits: it fills the current value. True when consumed."""
    flow = pending(chat_id)
    if not flow:
        return False
    tool, f = _current_field(flow)
    if not tool:
        store.clear_flow(chat_id)
        return False
    if flow["mode"] == "confirm":
        low = text.strip().casefold()
        if low in ("sì", "si", "ok", "conferma", "vai", "yes"):
            _run(chat_id, flow, tool)
            return True
        if low in ("no", "annulla", "lascia stare"):
            cancel(chat_id)
            return True
        return _offer_quit(chat_id, flow, tool, text)
    if f is None:
        return False
    if flow.get("date_part") and f.kind == "datetime":
        t = inputs.parse_time(text)
        if not t:
            if _looks_like_chat(text):
                return _offer_quit(chat_id, flow, tool, text)
            _ask(chat_id, flow, tool, f, "Non capisco l'ora: prova «18:30».")
            return True
        _set_value(chat_id, flow, f, t)
        return True
    if f.kind == "file":
        if _looks_like_chat(text):
            return _offer_quit(chat_id, flow, tool, text)
        _ask(chat_id, flow, tool, f, "Aspetto un vocale." if f.media.startswith("audio") else "Aspetto una foto o un file.")
        return True
    ok, value, problem = inputs.parse(f, text)
    if not ok:
        if _looks_like_chat(text):
            return _offer_quit(chat_id, flow, tool, text)
        _ask(chat_id, flow, tool, f, problem)
        return True
    _set_value(chat_id, flow, f, value, problem)
    return True


def _looks_like_chat(text: str) -> bool:
    s = text.strip()
    return s.endswith("?") or len(s.split()) >= 5


def _offer_quit(chat_id, flow: dict, tool: catalog.Tool, text: str) -> bool:
    flow["pending_text"] = text[:3000]
    store.set_flow(chat_id, flow)
    title = _title(_menu(), tool)
    rows = [[ui.button("Sì, esci", "f:quit"), ui.button("No, continuo", "f:stay")]]
    core.bot.send_message(chat_id, ui.card(f"Vuoi uscire da {title}?", [ui.note("Il tuo messaggio va in chat.")]),
                          parse_mode="HTML", reply_markup=ui.keyboard(rows))
    return True


def on_file(chat_id, message) -> bool:
    """A photo or document while an action waits for a file."""
    flow = pending(chat_id)
    tool, f = _current_field(flow) if flow else (None, None)
    if not flow or not f or f.kind != "file":
        return False
    try:
        file_id, mime, name = _file_of(message)
        info = core.bot.get_file(file_id)
        data = core.bot.download_file(info.file_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=telegram_action_file_failed action=%s error=%s", flow["tool"], exc)
        _ask(chat_id, flow, tool, f, "Non riesco a leggere il file, riprova.")
        return True
    b64 = base64.b64encode(data).decode()
    if f.name == "blob_id":
        ok, saved = catalog.route("archive", "api/blobs", "POST", body={
            "owner_module": "chat", "content_type": mime, "data_base64": b64, "meta": {"filename": name}},
            timeout=60)
        if not ok or not isinstance(saved, dict) or not saved.get("blob_id"):
            _ask(chat_id, flow, tool, f, "Non riesco a salvare il file, riprova tra poco.")
            return True
        value: Any = saved["blob_id"]
    else:
        value = {"name": name, "mime": mime, "data_b64": b64}
    _set_value(chat_id, flow, f, value)
    return True


def _file_of(message) -> tuple[str, str, str]:
    if message.content_type == "photo":
        return message.photo[-1].file_id, "image/jpeg", "foto.jpg"
    if message.content_type == "voice":
        return message.voice.file_id, (message.voice.mime_type or "audio/ogg"), "vocale.ogg"
    if message.content_type == "audio":
        return message.audio.file_id, (message.audio.mime_type or "audio/mpeg"), (message.audio.file_name or "audio")
    doc = message.document
    return doc.file_id, (doc.mime_type or "application/octet-stream"), (doc.file_name or "file")


# ── typed commands: /finance_add 12,50 pranzo ────────────────────────────────

def from_command(chat_id, name: str, args_text: str) -> bool:
    tool = catalog.get(name)
    if not tool:
        return False
    fields = _fields(tool)
    preset: dict[str, Any] = {}
    rest = []
    for token in re.findall(r'(\w+)=("[^"]*"|\S+)|(\S+)', args_text or ""):
        key, raw, word = token
        if key:
            f = fields.get(key) or next((x for x in fields.values() if x.label.casefold() == key.casefold()), None)
            if f:
                ok, value, _ = inputs.parse(f, raw.strip('"'))
                if ok:
                    preset[f.name] = value
                    continue
        rest.append(word or f"{key}={raw}")
    free = " ".join(rest).strip()
    if free:
        first = next((f for f in fields.values() if f.required and f.name not in preset), None) or \
            next((f for f in fields.values() if f.kind == "text" and f.name not in preset), None)
        if first:
            ok, value, problem = inputs.parse(first, free)
            if ok and problem != "time":
                preset[first.name] = value
    start(chat_id, tool.name, preset=preset)
    return True


# ── buttons ──────────────────────────────────────────────────────────────────

def cancel(chat_id, message_id: int | None = None) -> None:
    flow = store.clear_flow(chat_id)
    tool = catalog.get(flow.get("tool", "")) if flow else None
    title = _title(_menu(), tool) if tool else "l'azione"
    mid = message_id or (flow or {}).get("message_id")
    from telegram_bot import nav
    area = _area(_menu(), tool) if tool else None
    rows = [[ui.button(f"‹ {area.label}", f"n:a:{area.key}")]] if area else []
    nav.place(chat_id, ui.note(f"Ho lasciato perdere: {title}."), ui.keyboard(rows), mid, live=False)


def handle_tool(call) -> None:
    """``t:<tool id>[:<values id>]``."""
    parts = str(call.data or "").split(":")
    name = store.resolve(parts[1]) if len(parts) > 1 else None
    _answer(call)
    chat_id, mid = call.message.chat.id, call.message.message_id
    if not name:
        from telegram_bot import nav
        nav.stale(chat_id, mid)
        return
    preset = _values_of(parts[2]) if len(parts) > 2 else {}
    start(chat_id, name, mid, preset)


def handle_flow(call) -> None:
    """``f:…`` buttons of the running action."""
    chat_id, mid = call.message.chat.id, call.message.message_id
    parts = str(call.data or "").split(":")
    op = parts[1] if len(parts) > 1 else ""
    flow = store.get_flow(chat_id)
    if not flow or flow.get("kind") != "action":
        _answer(call, "Questa azione è già chiusa")
        from telegram_bot import nav
        nav.stale(chat_id, mid)
        return
    tool = catalog.get(flow["tool"])
    if not tool:
        _answer(call)
        store.clear_flow(chat_id)
        return
    _answer(call)
    if op in ("quit", "stay"):
        try:
            core.bot.delete_message(chat_id, mid)
        except Exception:  # noqa: BLE001
            pass
        if op == "stay":
            return
        text = flow.get("pending_text") or ""
        cancel(chat_id)
        if text:
            from telegram_bot.services import chat_service
            chat_service.chat_from_text(chat_id, text)
        return
    flow["message_id"] = mid
    if op == "cancel":
        cancel(chat_id, mid)
    elif op == "v":
        _, f = _current_field(flow)
        choices = flow.get("choices") or []
        idx = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else -1
        if f is None or not 0 <= idx < len(choices):
            return _advance(chat_id, flow)
        value = choices[idx]
        if f.kind == "bool":
            value = value == "true"
        elif f.kind in ("int", "number"):
            ok, value, _ = inputs.parse(f, str(value))
        elif f.kind == "datetime" and not flow.get("date_part"):
            flow["date_part"] = str(value)[:10]
            return _ask(chat_id, flow, tool, f)
        elif f.kind == "datetime":
            return _set_value(chat_id, flow, f, value)
        elif f.kind == "list":
            value = [value]
        _set_value(chat_id, flow, f, value)
    elif op == "skip":
        flow["pos"] += 1
        flow.pop("date_part", None)
        _advance(chat_id, flow)
    elif op == "back":
        flow.pop("date_part", None)
        if flow["mode"] == "confirm" and flow["queue"]:
            flow["pos"] = len(flow["queue"]) - 1
        elif flow["pos"] > 0:
            flow["pos"] -= 1
        else:
            store.clear_flow(chat_id)
            from telegram_bot import nav
            area = _area(_menu(), tool)
            return nav.area(chat_id, area.key, mid) if area else nav.aree(chat_id, mid)
        flow["values"].pop(flow["queue"][flow["pos"]], None)
        flow["mode"] = "ask"
        _advance(chat_id, flow)
    elif op == "ok" and flow["mode"] == "confirm":
        _run(chat_id, flow, tool)
    elif op == "more":
        fields = _fields(tool)
        flow["queue"] += [n for n, f in fields.items() if not f.required and n not in flow["values"]
                          and n not in flow["queue"]]
        flow["extra"] = True
        flow["mode"] = "ask"
        _advance(chat_id, flow)
    elif op == "edit":
        start(chat_id, tool.name, mid, {k: v for k, v in flow["values"].items()
                                        if k in {f.name for f in inputs.fields(tool) if f.required}}, extra=True)
    elif op == "retry":
        if tool.writes:
            flow["mode"] = "confirm"
            _confirm(chat_id, flow, tool, _fields(tool))
        else:
            _run(chat_id, flow, tool)
    else:
        _advance(chat_id, flow)
