"""What an action needs, read from the tool's own JSON Schema (docs/work/2026-10-23-telegram-da-zero §5.5).

Pure functions: a schema property becomes a ``Field`` with a label in words, a kind (choice, yes/no, number, date,
date and time, time, list, file, text), quick values for buttons and a parser for what the user types. Nothing is
ever asked by its technical name.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from hestia_common.i18n import is_yes, month_name, t as tr, weekday_name, word_regex, word_set  # owner language

LABELS = {
    "title": "Title", "name": "Name", "q": "What are you looking for", "query": "What are you looking for", "text": "Text",
    "note": "Note", "notes": "Notes", "description": "Description", "date": "Date", "days": "Days",
    "limit": "How many", "amount": "Amount", "category": "Category", "merchant": "Where", "account": "Account",
    "income": "It's income", "month": "Month", "months": "Months", "place": "Place", "location": "Place",
    "start_datetime": "Start", "end_datetime": "End", "start_at": "Start", "end_at": "End",
    "date_from": "From", "date_to": "Al", "since": "From", "until": "Al", "kind": "Type", "status": "Status",
    "service": "Service", "issue": "Problem", "severity": "Severity", "reason": "Reason", "task_id": "Work",
    "url": "Web address", "subject": "Subject", "body": "Text", "exercise": "Exercise", "template": "Workout plan",
    "routine": "Routine", "product": "Product", "piece": "Item", "outfit": "Outfit", "pieces": "Items",
    "minutes": "Minutes", "km": "Km", "energy": "Energy", "effort": "Effort", "sleep": "Sleep",
    "soreness": "Soreness", "key": "Setting", "value": "Value", "request": "What do you want",
    "fact": "What to remember", "facts": "What to remember", "topic": "Topic", "domain": "Scope",
    "occasion": "Occasion", "season": "Season", "color": "Colour", "colors": "Colours", "brand": "Brand",
    "size": "Size", "price": "Price", "times": "How many times", "per": "Every", "time_minutes": "Minutes available",
    "provider": "Calendar", "event_id": "Event", "ref": "Voice", "occurrence": "Which time", "to": "A",
    "id": "Which", "momento": "Moment", "level": "Level", "contains": "Contains", "candidate_model": "Model",
    "dataset_name": "Dataset", "adapter_name": "Adapter name", "branch": "alt::Branch", "summary": "Summary",
    "paused": "Paused", "dry_run": "Test only", "minutes_dnd": "Minutes", "code": "Code", "type": "Type",
    "recurrence": "Repetition", "favorite": "Favourite", "rating": "Rating", "areas": "Zones", "actives": "pl::Active",
    "temp_c": "Temperature", "rain": "Rain", "styles": "Styles", "count": "How many", "hourly": "Hour by hour",
    "owner": "For whom", "template_id": "Model", "parent": "Linked to", "engine": "Engine", "now": "Right away",
    "weight": "Weight", "measurement": "Measure", "goal": "Goal", "target": "Goal", "scope": "Scope",
    "pain_areas": "Where it hurts", "free_text": "Something else to say", "intent": "What do you want to do", "week": "Week",
    "slots": "When", "outcome": "How it went", "plan_id": "Plan", "slot_id": "Which time",
}

PLACEHOLDERS = {
    "amount": "12,50", "title": "Dinner with Luca", "q": "electricity bill", "query": "blue jacket",
    "start_datetime": "tomorrow 18:30", "start_at": "tomorrow 18:30", "date": "tomorrow or 25/10", "value": "78,4",
    "text": "bench 4x8 62.5", "place": "Home", "request": "add the weather to the recap", "url": "https://…",
    "to": "name@example.com", "facts": "I have the dentist on Tuesdays", "fact": "I prefer the morning",
}

_RELATIVE = (("date.today", 0), ("date.tomorrow", 1), ("date.day_after_tomorrow", 2), ("date.yesterday", -1),
             ("date.day_before_yesterday", -2))


@dataclass
class Field:
    name: str
    label: str
    kind: str                       # choice | bool | int | number | date | datetime | time | list | object | file | text
    required: bool = False
    help: str = ""
    placeholder: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)   # (value, label)
    minimum: float | None = None
    maximum: float | None = None
    default: Any = None
    media: str = ""                 # file fields: contentMediaType (audio/* = ask for a voice note)


def _short_help(desc: str) -> str:
    text = re.split(r"(?<=[.;])\s|\s\(|\s—\s", str(desc or "").strip(), maxsplit=1)[0].strip(" .;:")
    return text if 3 <= len(text) <= 90 else ""


def _humanize(name: str) -> str:
    return re.sub(r"[_.]+", " ", name).strip().capitalize()


def _kind(name: str, spec: dict) -> str:
    typ = spec.get("type")
    typ = typ[0] if isinstance(typ, list) and typ else typ
    fmt = str(spec.get("format") or "").lower()
    desc = str(spec.get("description") or "").lower()
    lname = name.lower()
    if spec.get("contentMediaType") or fmt in ("binary", "byte") or lname in ("blob_id", "photo", "image", "file"):
        return "file"
    if isinstance(spec.get("enum"), list) and spec["enum"]:
        return "choice"
    if typ == "boolean":
        return "bool"
    if typ == "integer":
        return "int"
    if typ == "number":
        return "number"
    if typ == "array":
        return "list"
    if typ == "object":
        return "object"
    if fmt == "date-time" or lname.endswith("_datetime") or lname in ("start_at", "end_at") or \
            ("iso" in desc and ("ora" in desc or "time" in desc or "hh:mm" in desc)):
        return "datetime"
    if fmt == "date" or lname in ("date", "date_from", "date_to", "since", "until", "purchase_date", "opened_at",
                                  "expires_at") or "yyyy-mm-dd" in desc:
        return "date"
    if fmt == "time" or lname.endswith("_time") or "hh:mm" in desc:
        return "time"
    return "text"


def fields(tool) -> list[Field]:
    """Fields of a tool: required ones first, in schema order."""
    from hestia_common import i18n
    from telegram_settings import settings
    lang = i18n.language(settings.get)
    props = tool.properties()
    required = set(tool.required())
    out: list[Field] = []
    for name, spec in props.items():
        kind = _kind(name, spec)
        # the schema's description is English, for the model; people read the help of the people catalog
        desc = i18n.param_help(getattr(tool, "name", ""), name, lang) or str(spec.get("description") or "")
        label = tr(str(spec.get("title") or LABELS.get(name) or _short_help(desc) or _humanize(name)))
        options: list[tuple[str, str]] = []
        if kind == "choice":
            names = spec.get("enumNames") or spec.get("x-labels") or []
            for i, v in enumerate(spec["enum"]):
                shown = names[i] if i < len(names) else _humanize(str(v))
                options.append((str(v), str(shown)))
        examples = spec.get("examples") if isinstance(spec.get("examples"), list) else []
        out.append(Field(name=name, label=label[:40], kind=kind, required=name in required,
                         help=_short_help(desc) if _short_help(desc).lower() != label.lower() else "",
                         placeholder=str(examples[0]) if examples else tr(PLACEHOLDERS.get(name, "")),
                         options=options, minimum=spec.get("minimum"), maximum=spec.get("maximum"),
                         default=spec.get("default"), media=str(spec.get("contentMediaType") or "")))
    out.sort(key=lambda f: not f.required)
    return out


def quick_values(f: Field, today: date | None = None) -> list[tuple[str, str]]:
    """Buttons for a field: (label, value)."""
    today = today or date.today()
    if f.kind == "choice":
        return [(lbl, v) for v, lbl in f.options][:12]
    if f.kind == "bool":
        return [(tr("Yes"), "true"), ("No", "false")]
    if f.kind in ("date", "datetime"):
        return [(tr("Today"), today.isoformat()), (tr("Tomorrow"), (today + timedelta(days=1)).isoformat()),
                (tr("Day after tomorrow"), (today + timedelta(days=2)).isoformat())]
    if f.kind == "time":
        return [(t, t) for t in ("08:00", "09:00", "12:30", "18:00", "20:00")]
    if f.kind == "int":
        lo, hi = f.minimum, f.maximum
        if lo is not None and hi is not None and 0 <= hi - lo <= 5:
            return [(str(i), str(i)) for i in range(int(lo), int(hi) + 1)]
        presets = {"days": ["1", "7", "30"], "limit": ["5", "10", "20"], "minutes": ["15", "30", "60"],
                   "months": ["1", "3", "12"], "count": ["1", "3", "5"], "times": ["1", "2", "3"]}
        return [(v, v) for v in presets.get(f.name, [])]
    return []


def time_values() -> list[tuple[str, str]]:
    return [(t, t) for t in ("08:00", "09:00", "12:30", "15:00", "18:00", "20:00")]


# ── parsing what the user types ──────────────────────────────────────────────

def parse_date(text: str, today: date | None = None) -> date | None:
    today = today or date.today()
    s = str(text or "").strip().lower()
    if not s:
        return None
    for key, delta in _RELATIVE:
        if s in word_set(key):
            return today + timedelta(days=delta)
    for i in range(7):
        if any(s in (wd, wd[:3]) for wd in word_set(f"date.weekday.{i}")):
            return today + timedelta(days=(i - today.weekday()) % 7 or 7)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?", s)
    if m:
        year = int(m[3]) if m[3] else today.year
        year = year + 2000 if year < 100 else year
        try:
            d = date(year, int(m[2]), int(m[1]))
        except ValueError:
            return None
        return d if m[3] or d >= today - timedelta(days=60) else date(year + 1, d.month, d.day)
    m = re.fullmatch(r"(\d{1,2})\s+([^\W\d_]+)(?:\s+(\d{4}))?", s) or re.fullmatch(
        r"([^\W\d_]+)\s+(\d{1,2})(?:\s+(\d{4}))?", s)
    if m and not m[1].isdigit():
        m = [m[0], m[2], m[1], m[3]]
    if m:
        month = next((i for i in range(1, 13) if any(n.startswith(m[2][:3]) for n in word_set(f"date.month.{i}"))), 0)
        if month:
            try:
                return date(int(m[3]) if m[3] else today.year, month, int(m[1]))
            except ValueError:
                return None
    return None


def parse_time(text: str) -> str | None:
    s = word_regex(r"^(?:(?:{0})\s+)+", "date.time_prefix").sub("", str(text or "").strip().lower())
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?", s)
    if not m:
        return None
    h, mi = int(m[1]), int(m[2] or 0)
    return f"{h:02d}:{mi:02d}" if 0 <= h <= 23 and 0 <= mi <= 59 else None


def parse_datetime(text: str, today: date | None = None) -> tuple[str | None, bool]:
    """``("YYYY-MM-DDTHH:MM:00", True)`` or a date alone ``("YYYY-MM-DD", False)`` (time still to ask)."""
    s = str(text or "").strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[T ](\d{1,2}:\d{2})(?::\d{2})?.*", s)
    if m:
        return f"{m[1]}T{parse_time(m[2])}:00", True
    parts = word_regex(r"\s+(?:(?:{0})\s+)?(?=\d{{1,2}}(?:[:.]\d{{2}})?$)", "date.time_prefix").split(s.lower(), maxsplit=1)
    d = parse_date(parts[0], today)
    if d and len(parts) == 2:
        t = parse_time(parts[1])
        if t:
            return f"{d.isoformat()}T{t}:00", True
    if d:
        return d.isoformat(), False
    t = parse_time(s)
    if t:
        return f"{(today or date.today()).isoformat()}T{t}:00", True
    return None, False


def parse(f: Field, text: str) -> tuple[bool, Any, str]:
    """``(ok, value, problem)`` — ``problem`` is a short sentence for the user."""
    s = str(text or "").strip()
    if not s:
        return False, None, tr("Write something, or Cancel.")
    if f.kind == "choice":
        for v, lbl in f.options:
            if s.casefold() in (v.casefold(), lbl.casefold()):
                return True, v, ""
        return False, None, tr("Choose one of the options.")
    if f.kind == "bool":
        low = s.casefold()
        if low == tr("yes").casefold() or is_yes(low):
            return True, True, ""
        if low in word_set("common.no_word"):
            return True, False, ""
        return False, None, tr("Answer yes or no.")
    if f.kind in ("int", "number"):
        m = re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", s.replace("€", "").replace(" ", ""))
        if not m:
            return False, None, tr("Write a number.")
        num = float(m[0].replace(",", "."))
        if f.minimum is not None and num < f.minimum or f.maximum is not None and num > f.maximum:
            return False, None, tr("A number between {0:g} and {1:g}.", f.minimum, f.maximum) if f.minimum is not None \
                and f.maximum is not None else tr("Number out of range.")
        return True, (int(num) if f.kind == "int" else num), ""
    if f.kind == "date":
        d = parse_date(s)
        return (True, d.isoformat(), "") if d else (False, None, tr("I don't understand the date: try «tomorrow» or «25/10»."))
    if f.kind == "time":
        t = parse_time(s)
        return (True, t, "") if t else (False, None, tr("I don't understand the time: try «18:30»."))
    if f.kind == "datetime":
        value, full = parse_datetime(s)
        if not value:
            return False, None, tr("I don't understand: try «tomorrow 18:30» or «25/10 9:00».")
        return True, value, "" if full else "time"
    if f.kind == "list":
        return True, [p.strip() for p in re.split(r"[,;\n]", s) if p.strip()], ""
    if f.kind == "object":
        try:
            value = json.loads(s)
            if isinstance(value, dict):
                return True, value, ""
        except ValueError:
            pass
        pairs = [p.split("=", 1) for p in re.split(r"[;\n]", s) if "=" in p]
        if pairs:
            return True, {k.strip(): v.strip() for k, v in pairs}, ""
        return False, None, tr("Write the changes as «field=value; field=value».")
    return True, s, ""


def shown_value(f: Field, value: Any) -> str:
    """A value as the user reads it in a summary."""
    if value is None or value == "":
        return "—"
    if f.kind == "bool":
        return tr("Yes") if value in (True, "true") else "No"
    if f.kind == "choice":
        return dict(f.options).get(str(value), str(value))
    if f.kind in ("date", "datetime"):
        return human_datetime(str(value))
    if f.kind == "list" and isinstance(value, list):
        return ", ".join(map(str, value))
    if f.kind == "number" and isinstance(value, float):
        return f"{value:.2f}".replace(".", ",").rstrip("0").rstrip(",")
    if f.kind == "file":
        return tr("file received")
    return str(value)


def human_datetime(value: str, today: date | None = None) -> str:
    """``2026-10-25T18:30:00`` → «Sun 25 Oct 18:30» in the owner's language (today/tomorrow in words)."""
    today = today or date.today()
    s = str(value or "")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    d = dt.date()
    if d == today:
        day = tr("today")
    elif d == today + timedelta(days=1):
        day = tr("tomorrow")
    elif d == today - timedelta(days=1):
        day = tr("yesterday")
    else:
        day = f"{weekday_name(d.weekday())[:3]} {d.day} {month_name(d.month)[:3]}" + (
            f" {d.year}" if d.year != today.year else "")
    has_time = "T" in s or " " in s.strip()
    return f"{day} {dt:%H:%M}" if has_time and (dt.hour or dt.minute) else day
