"""Calendar creation wizard — multi-step interactive flow via inline buttons.

Responsibilities:
- Date / time parsing helpers
- Wizard step prompts (Telegram messages)
- State machine: title → date → time → location → description → confirm
- Final calendar item creation via Hub
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Any

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot import core
from telegram_bot.services.router import route_service_command

# ── Confirmation keywords ─────────────────────────────────────────────────────

_AFFIRMATIVE = frozenset({
    "si", "sì", "yes", "y", "ok", "conferma", "confirm",
    "sure", "vai", "crea", "create", "esatto", "giusto",
})
_NEGATIVE = frozenset({
    "no", "cancel", "annulla", "stop", "esci", "exit", "n", "nope",
})

# ── Date / time parsing ───────────────────────────────────────────────────────


def _try_parse_date(text: str) -> str | None:
    """Return ISO date string or None."""
    t = text.strip().lower()
    today = date.today()
    shortcuts = {"oggi": today, "today": today,
                 "domani": today + timedelta(days=1),
                 "tomorrow": today + timedelta(days=1),
                 "dopodomani": today + timedelta(days=2),
                 "day after tomorrow": today + timedelta(days=2),
                 "dopo domani": today + timedelta(days=2)}
    if t in shortcuts:
        return shortcuts[t].isoformat()

    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", t)
    if m:
        d_, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d_).isoformat()
        except Exception:
            pass

    m = re.match(r"^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})$", t)
    if m:
        y, mo, d_ = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d_).isoformat()
        except Exception:
            pass

    return None


def _try_parse_time(text: str) -> str | None:
    """Return HH:MM string or None."""
    m = re.match(r"^(\d{1,2})[:\.](\d{2})$", text.strip())
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return f"{h:02d}:{mn:02d}"
    m = re.match(r"^(\d{1,2})$", text.strip())
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    return None


# ── Preview builder ───────────────────────────────────────────────────────────

def _build_calendar_preview(kind: str, data: dict) -> str:
    """Build a human-readable HTML summary of the event being created."""
    kind_label = {"event": "📅 Evento", "task": "✅ Task",
                  "reminder": "⏰ Promemoria"}.get(kind, kind.title())
    lines = [f"<b>{kind_label}</b>"]
    if (title := str(data.get("title", "")).strip()):
        lines.append(f"  <b>Titolo:</b> {escape(title)}")
    date_str, time_str = str(data.get("date_str", "")).strip(), str(
        data.get("time_str", "")).strip()
    if date_str and time_str:
        lines.append(
            f"  <b>Data e ora:</b> {escape(date_str)} alle {escape(time_str)}")
    elif date_str:
        lines.append(f"  <b>Data:</b> {escape(date_str)}")
    if (loc := str(data.get("location", "")).strip()):
        lines.append(f"  <b>Luogo:</b> {escape(loc)}")
    if (desc := str(data.get("description", "")).strip()):
        lines.append(f"  <b>Note:</b> {escape(desc)}")
    return "\n".join(lines)


# ── Keyboard helpers ──────────────────────────────────────────────────────────

def _wizard_cancel_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Annulla", callback_data="cal_cancel"))
    return kb


def _wizard_skip_cancel_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("⏭️ Salta", callback_data="cal_skip"),
        InlineKeyboardButton("❌ Annulla", callback_data="cal_cancel"),
    )
    return kb


# ── Step prompts ──────────────────────────────────────────────────────────────

def _prompt_wizard_title(chat_id: int, kind: str):
    kind_label = {"event": "evento", "task": "task",
                  "reminder": "promemoria"}.get(kind, kind)
    core.bot.send_message(
        chat_id,
        f"✍️ <b>Come si chiama il tuo {kind_label}?</b>\n\n<i>Digita il titolo.</i>",
        parse_mode="HTML",
        reply_markup=_wizard_cancel_keyboard(),
    )


def _prompt_wizard_date(chat_id: int, kind: str):
    kb = InlineKeyboardMarkup(row_width=3)
    kb.row(
        InlineKeyboardButton("📌 Oggi", callback_data="cal_date:today"),
        InlineKeyboardButton("➡️ Domani", callback_data="cal_date:tomorrow"),
        InlineKeyboardButton(
            "⏩ Dopodomani", callback_data="cal_date:day_after"),
    )
    skip_cancel = []
    if kind == "task":
        skip_cancel.append(InlineKeyboardButton(
            "⏭️ Senza scadenza", callback_data="cal_skip"))
    skip_cancel.append(InlineKeyboardButton(
        "❌ Annulla", callback_data="cal_cancel"))
    kb.row(*skip_cancel)
    optional = " (opzionale)" if kind == "task" else ""
    core.bot.send_message(
        chat_id,
        f"📅 <b>Quando{optional}?</b>\n\nSeleziona una data rapida o digitala nel formato <code>GG/MM/AAAA</code>.",
        parse_mode="HTML",
        reply_markup=kb,
    )


def _prompt_wizard_time(chat_id: int):
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(*[
        InlineKeyboardButton(t, callback_data=f"cal_time:{t.replace(':', '')}")
        for t in ["08:00", "09:00", "10:00", "12:00", "15:00", "17:00", "18:00", "19:00", "20:00"]
    ])
    kb.row(
        InlineKeyboardButton("☀️ Tutto il giorno", callback_data="cal_skip"),
        InlineKeyboardButton("❌ Annulla", callback_data="cal_cancel"),
    )
    core.bot.send_message(
        chat_id,
        "🕐 <b>A che ora?</b>\n\nSeleziona un orario o digitalo nel formato <code>HH:MM</code>.",
        parse_mode="HTML",
        reply_markup=kb,
    )


def _prompt_wizard_location(chat_id: int):
    core.bot.send_message(
        chat_id, "📍 <b>Dove?</b> <i>(opzionale)</i>\n\nDigita il luogo o salta.",
        parse_mode="HTML", reply_markup=_wizard_skip_cancel_keyboard(),
    )


def _prompt_wizard_description(chat_id: int):
    core.bot.send_message(
        chat_id, "📝 <b>Note aggiuntive?</b> <i>(opzionale)</i>\n\nAggiungi una descrizione o salta.",
        parse_mode="HTML", reply_markup=_wizard_skip_cancel_keyboard(),
    )


# ── State machine ─────────────────────────────────────────────────────────────

def _wizard_next_step(kind: str, current_step: str) -> str:
    if current_step == "title":
        return "date"
    if current_step == "date":
        return "description" if kind == "task" else "time"
    if current_step == "time":
        return "location" if kind == "event" else "description"
    if current_step == "location":
        return "description"
    return "confirm"


def _show_wizard_step(chat_id: int, kind: str, step: str):
    dispatch = {
        "date": lambda: _prompt_wizard_date(chat_id, kind),
        "time": lambda: _prompt_wizard_time(chat_id),
        "location": lambda: _prompt_wizard_location(chat_id),
        "description": lambda: _prompt_wizard_description(chat_id),
    }
    if step in dispatch:
        dispatch[step]()


def _wizard_advance(chat_id: int, workflow: dict, field_update: dict):
    """Apply *field_update*, advance the wizard step, and show the next prompt."""
    kind = str(workflow.get("kind", "event"))
    current_step = str(workflow.get("step", "title"))
    data = {**dict(workflow.get("data", {})), **field_update}
    next_step = _wizard_next_step(kind, current_step)

    if next_step == "confirm":
        _wizard_show_confirm(chat_id, kind, data)
        return

    core.PENDING_WORKFLOWS[str(chat_id)] = {
        "action": "calendar_create_wizard",
        "step": next_step,
        "kind": kind,
        "data": data,
        "created_at": time.time(),
    }
    _show_wizard_step(chat_id, kind, next_step)


def _wizard_show_confirm(chat_id: int, kind: str, data: dict):
    """Emit the confirmation summary and register a pending confirmation token."""
    preview = _build_calendar_preview(kind, data)
    token = uuid.uuid4().hex[:14]
    core.PENDING_CONFIRMATIONS[token] = {
        "action": "calendar_create_confirm",
        "chat_id": str(chat_id),
        "kind": kind,
        "data": data,
    }
    core.PENDING_WORKFLOWS[str(chat_id)] = {
        "action": "calendar_awaiting_confirm",
        "token": token,
        "created_at": time.time(),
    }
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Crea", callback_data=f"confirm:{token}"),
        InlineKeyboardButton("❌ Annulla", callback_data=f"cancel:{token}"),
    )
    core.bot.send_message(
        chat_id,
        f"📋 <b>Riepilogo — confermi?</b>\n\n{preview}\n\n<i>Premi ✅ Crea per salvare oppure ❌ Annulla.</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )


# ── Text input handler ────────────────────────────────────────────────────────

def handle_calendar_wizard_text(chat_id: int, text: str, workflow: dict):
    """Process a plain-text reply during a wizard step."""
    step = str(workflow.get("step", "title"))
    kind = str(workflow.get("kind", "event"))

    if step == "title":
        t = text.strip()
        if not t:
            core.PENDING_WORKFLOWS[str(chat_id)] = workflow
            core.bot.send_message(chat_id, "⚠️ Il titolo non può essere vuoto. Riprova.",
                                  reply_markup=_wizard_cancel_keyboard())
            return
        _wizard_advance(chat_id, workflow, {"title": t})

    elif step == "date":
        parsed = _try_parse_date(text)
        if not parsed:
            core.PENDING_WORKFLOWS[str(chat_id)] = workflow
            core.bot.send_message(
                chat_id,
                "⚠️ Data non riconosciuta. Usa il formato <code>GG/MM/AAAA</code> "
                "oppure scrivi <i>oggi</i> / <i>domani</i>.",
                parse_mode="HTML",
                reply_markup=_wizard_cancel_keyboard(),
            )
            return
        _wizard_advance(chat_id, workflow, {"date_str": parsed})

    elif step == "time":
        parsed = _try_parse_time(text)
        if not parsed:
            core.PENDING_WORKFLOWS[str(chat_id)] = workflow
            core.bot.send_message(
                chat_id,
                "⚠️ Orario non riconosciuto. Usa il formato <code>HH:MM</code> (es. <code>15:30</code>).",
                parse_mode="HTML",
                reply_markup=_wizard_cancel_keyboard(),
            )
            return
        _wizard_advance(chat_id, workflow, {"time_str": parsed})

    elif step == "location":
        _wizard_advance(chat_id, workflow, {"location": text.strip()})

    elif step == "description":
        _wizard_advance(chat_id, workflow, {"description": text.strip()})


# ── Callback handler ──────────────────────────────────────────────────────────

def handle_calendar_step_callback(call):
    """Handle cal_date:, cal_time:, cal_skip, cal_cancel inline callbacks."""
    raw = str(call.data or "")
    chat_id = call.message.chat.id

    if raw == "cal_cancel":
        core.PENDING_WORKFLOWS.pop(str(chat_id), None)
        try:
            core.bot.edit_message_text("❌ Operazione annullata.",
                                       chat_id=chat_id, message_id=call.message.message_id)
        except Exception:
            core.bot.send_message(chat_id, "❌ Operazione annullata.")
        core.bot.answer_callback_query(call.id, "Annullato")
        return

    workflow = core.PENDING_WORKFLOWS.pop(str(chat_id), None)
    if not workflow or workflow.get("action") != "calendar_create_wizard":
        core.bot.answer_callback_query(call.id, "Operazione scaduta.")
        return

    kind = str(workflow.get("kind", "event"))
    try:
        core.bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
    except Exception:
        pass

    if raw == "cal_skip":
        _wizard_advance(chat_id, workflow, {})
        core.bot.answer_callback_query(call.id, "Campo saltato")
        return

    if raw.startswith("cal_date:"):
        value = raw[len("cal_date:"):]
        today = date.today()
        date_map = {"today": today, "tomorrow": today +
                    timedelta(days=1), "day_after": today + timedelta(days=2)}
        chosen = date_map.get(value)
        if chosen:
            _wizard_advance(chat_id, workflow, {
                            "date_str": chosen.isoformat()})
            core.bot.answer_callback_query(
                call.id, chosen.strftime("%d/%m/%Y"))
        else:
            core.PENDING_WORKFLOWS[str(chat_id)] = workflow
            core.bot.answer_callback_query(call.id, "Data non valida")
        return

    if raw.startswith("cal_time:"):
        value = raw[len("cal_time:"):]
        if len(value) == 4 and value.isdigit():
            time_str = f"{value[:2]}:{value[2:]}"
            _wizard_advance(chat_id, workflow, {"time_str": time_str})
            core.bot.answer_callback_query(call.id, time_str)
        else:
            core.PENDING_WORKFLOWS[str(chat_id)] = workflow
            core.bot.answer_callback_query(call.id, "Orario non valido")
        return

    core.PENDING_WORKFLOWS[str(chat_id)] = workflow
    core.bot.answer_callback_query(call.id, "Azione non riconosciuta")


# ── Calendar item creation ────────────────────────────────────────────────────

def execute_calendar_create_confirm(payload: dict, chat_id: int, message_id: int | None = None):
    """Execute the actual calendar item creation after wizard confirmation."""
    kind = str(payload.get("kind", "event"))
    data = payload.get("data", {})
    date_str = str(data.get("date_str", "")).strip()
    time_str = str(data.get("time_str", "")).strip()
    title = str(data.get("title", "")).strip() or "Senza titolo"
    location = str(data.get("location", "")).strip() or None
    description = str(data.get("description", "")).strip() or None
    all_day = not bool(time_str)

    tz_offset = timezone(timedelta(hours=1))
    if date_str and time_str:
        try:
            dt_start = datetime.fromisoformat(
                f"{date_str}T{time_str}:00").replace(tzinfo=tz_offset)
        except Exception:
            dt_start = datetime.now(tz=timezone.utc)
    elif date_str:
        try:
            dt_start = datetime.fromisoformat(
                f"{date_str}T09:00:00").replace(tzinfo=tz_offset)
        except Exception:
            dt_start = datetime.now(tz=timezone.utc)
    else:
        dt_start = datetime.now(tz=timezone.utc)

    dt_end = dt_start + timedelta(hours=1)

    def _edit_or_send(text: str):
        if message_id:
            try:
                core.bot.edit_message_text(
                    text, chat_id=chat_id, message_id=message_id)
                return
            except Exception:
                pass
        core.bot.send_message(chat_id, text, parse_mode="HTML")

    if kind == "event":
        body = {
            "event": {
                "title": title, "description": description,
                "start_datetime": dt_start.isoformat(), "end_datetime": dt_end.isoformat(),
                "location": location, "timezone": "Europe/Rome", "all_day": all_day,
            },
            "target_providers": [],
        }
        ok, result = route_service_command(
            "chronos", "/api/calendar/events", "POST", {}, body)
        if ok and isinstance(result, dict):
            total = int(result.get("total_created", 0))
            provider_text = f"su {total} provider" if total else "in agenda"
            _edit_or_send(
                f"✅ <b>Evento creato</b> {provider_text}!\n\n<b>{escape(title)}</b>")
        else:
            _edit_or_send(f"⚠️ Creazione fallita: {escape(str(result))}")
    else:
        body = {
            "external_id": None, "source": "hestia", "kind": kind,
            "title": title, "description": description,
            "start_at": dt_start.isoformat(), "end_at": dt_end.isoformat(),
            "all_day": all_day, "location": location,
            "status": "confirmed", "nag_enabled": True,
        }
        ok, result = route_service_command(
            "archive", "/api/calendar/items", "POST", {}, body)
        if ok:
            kind_label = "Task" if kind == "task" else "Promemoria"
            _edit_or_send(
                f"✅ <b>{kind_label} salvato</b>!\n\n<b>{escape(title)}</b>")
        else:
            _edit_or_send(f"⚠️ Salvataggio fallito: {escape(str(result))}")
