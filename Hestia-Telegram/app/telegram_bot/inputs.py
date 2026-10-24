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

LABELS = {
    "title": "Titolo", "name": "Nome", "q": "Cosa cerchi", "query": "Cosa cerchi", "text": "Testo",
    "note": "Nota", "notes": "Note", "description": "Descrizione", "date": "Data", "days": "Giorni",
    "limit": "Quanti", "amount": "Importo", "category": "Categoria", "merchant": "Dove", "account": "Conto",
    "income": "È un'entrata", "month": "Mese", "months": "Mesi", "place": "Luogo", "location": "Luogo",
    "start_datetime": "Inizio", "end_datetime": "Fine", "start_at": "Inizio", "end_at": "Fine",
    "date_from": "Dal", "date_to": "Al", "since": "Dal", "until": "Al", "kind": "Tipo", "status": "Stato",
    "service": "Servizio", "issue": "Problema", "severity": "Gravità", "reason": "Motivo", "task_id": "Lavoro",
    "url": "Indirizzo web", "subject": "Oggetto", "body": "Testo", "exercise": "Esercizio", "template": "Scheda",
    "routine": "Routine", "product": "Prodotto", "piece": "Capo", "outfit": "Outfit", "pieces": "Capi",
    "minutes": "Minuti", "km": "Km", "energy": "Energia", "effort": "Fatica", "sleep": "Sonno",
    "soreness": "Indolenzimento", "key": "Impostazione", "value": "Valore", "request": "Cosa vuoi",
    "fact": "Cosa ricordare", "facts": "Cosa ricordare", "topic": "Argomento", "domain": "Ambito",
    "occasion": "Occasione", "season": "Stagione", "color": "Colore", "colors": "Colori", "brand": "Marca",
    "size": "Taglia", "price": "Prezzo", "times": "Quante volte", "per": "Ogni", "time_minutes": "Minuti a disposizione",
    "provider": "Calendario", "event_id": "Evento", "ref": "Voce", "occurrence": "Quale volta", "to": "A",
    "id": "Quale", "momento": "Momento", "level": "Livello", "contains": "Contiene", "candidate_model": "Modello",
    "dataset_name": "Dataset", "adapter_name": "Nome adattatore", "branch": "Branch", "summary": "Riepilogo",
    "paused": "In pausa", "dry_run": "Solo prova", "minutes_dnd": "Minuti", "code": "Codice", "type": "Tipo",
    "recurrence": "Ripetizione", "favorite": "Preferito", "rating": "Voto", "areas": "Zone", "actives": "Attivi",
    "temp_c": "Temperatura", "rain": "Pioggia", "styles": "Stili", "count": "Quanti", "hourly": "Ora per ora",
    "owner": "Per chi", "template_id": "Modello", "parent": "Collegata a", "engine": "Motore", "now": "Subito",
    "weight": "Peso", "measurement": "Misura", "goal": "Obiettivo", "target": "Obiettivo", "scope": "Ambito",
    "pain_areas": "Dove fa male", "free_text": "Altro da dire", "intent": "Cosa vuoi fare", "week": "Settimana",
    "slots": "Quando", "outcome": "Com'è andata", "plan_id": "Piano", "slot_id": "Quale volta",
}

PLACEHOLDERS = {
    "amount": "12,50", "title": "Cena con Luca", "q": "bolletta luce", "query": "giacca blu",
    "start_datetime": "domani 18:30", "start_at": "domani 18:30", "date": "domani o 25/10", "value": "78,4",
    "text": "panca 4x8 62,5", "place": "Casa", "request": "aggiungi il meteo al recap", "url": "https://…",
    "to": "nome@esempio.it", "facts": "ho il dentista il martedì", "fact": "preferisco la mattina",
}

WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
WEEKDAYS_PLAIN = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
          "novembre", "dicembre"]


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
    props = tool.properties()
    required = set(tool.required())
    out: list[Field] = []
    for name, spec in props.items():
        kind = _kind(name, spec)
        desc = str(spec.get("description") or "")
        label = str(spec.get("title") or LABELS.get(name) or _short_help(desc) or _humanize(name))
        options: list[tuple[str, str]] = []
        if kind == "choice":
            names = spec.get("enumNames") or spec.get("x-labels") or []
            for i, v in enumerate(spec["enum"]):
                shown = names[i] if i < len(names) else _humanize(str(v))
                options.append((str(v), str(shown)))
        examples = spec.get("examples") if isinstance(spec.get("examples"), list) else []
        out.append(Field(name=name, label=label[:40], kind=kind, required=name in required,
                         help=_short_help(desc) if _short_help(desc).lower() != label.lower() else "",
                         placeholder=str(examples[0]) if examples else PLACEHOLDERS.get(name, ""),
                         options=options, minimum=spec.get("minimum"), maximum=spec.get("maximum"),
                         default=spec.get("default")))
    out.sort(key=lambda f: not f.required)
    return out


def quick_values(f: Field, today: date | None = None) -> list[tuple[str, str]]:
    """Buttons for a field: (label, value)."""
    today = today or date.today()
    if f.kind == "choice":
        return [(lbl, v) for v, lbl in f.options][:12]
    if f.kind == "bool":
        return [("Sì", "true"), ("No", "false")]
    if f.kind in ("date", "datetime"):
        return [("Oggi", today.isoformat()), ("Domani", (today + timedelta(days=1)).isoformat()),
                ("Dopodomani", (today + timedelta(days=2)).isoformat())]
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
    rel = {"oggi": 0, "domani": 1, "dopodomani": 2, "ieri": -1, "l'altro ieri": -2, "altroieri": -2}
    if s in rel:
        return today + timedelta(days=rel[s])
    for names in (WEEKDAYS, WEEKDAYS_PLAIN):
        for i, wd in enumerate(names):
            if s in (wd, wd[:3]):
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
    m = re.fullmatch(r"(\d{1,2})\s+([a-zà]+)(?:\s+(\d{4}))?", s)
    if m:
        month = next((i + 1 for i, name in enumerate(MONTHS) if name.startswith(m[2][:3])), 0)
        if month:
            try:
                return date(int(m[3]) if m[3] else today.year, month, int(m[1]))
            except ValueError:
                return None
    return None


def parse_time(text: str) -> str | None:
    s = str(text or "").strip().lower().replace("alle ", "").replace("ore ", "")
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
    parts = re.split(r"\s+(?:alle\s+|ore\s+)?(?=\d{1,2}(?:[:.]\d{2})?$)", s.lower(), maxsplit=1)
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
        return False, None, "Scrivi qualcosa, oppure Annulla."
    if f.kind == "choice":
        for v, lbl in f.options:
            if s.casefold() in (v.casefold(), lbl.casefold()):
                return True, v, ""
        return False, None, "Scegli una delle opzioni."
    if f.kind == "bool":
        low = s.casefold()
        if low in ("sì", "si", "s", "yes", "true", "1", "vero"):
            return True, True, ""
        if low in ("no", "n", "false", "0", "falso"):
            return True, False, ""
        return False, None, "Rispondi sì o no."
    if f.kind in ("int", "number"):
        m = re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", s.replace("€", "").replace(" ", ""))
        if not m:
            return False, None, "Scrivi un numero."
        num = float(m[0].replace(",", "."))
        if f.minimum is not None and num < f.minimum or f.maximum is not None and num > f.maximum:
            return False, None, f"Un numero tra {f.minimum:g} e {f.maximum:g}." if f.minimum is not None \
                and f.maximum is not None else "Numero fuori dai limiti."
        return True, (int(num) if f.kind == "int" else num), ""
    if f.kind == "date":
        d = parse_date(s)
        return (True, d.isoformat(), "") if d else (False, None, "Non capisco la data: prova «domani» o «25/10».")
    if f.kind == "time":
        t = parse_time(s)
        return (True, t, "") if t else (False, None, "Non capisco l'ora: prova «18:30».")
    if f.kind == "datetime":
        value, full = parse_datetime(s)
        if not value:
            return False, None, "Non capisco: prova «domani 18:30» o «25/10 9:00»."
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
        return False, None, "Scrivi le modifiche come «campo=valore; campo=valore»."
    return True, s, ""


def shown_value(f: Field, value: Any) -> str:
    """A value as the user reads it in a summary."""
    if value is None or value == "":
        return "—"
    if f.kind == "bool":
        return "Sì" if value in (True, "true") else "No"
    if f.kind == "choice":
        return dict(f.options).get(str(value), str(value))
    if f.kind in ("date", "datetime"):
        return human_datetime(str(value))
    if f.kind == "list" and isinstance(value, list):
        return ", ".join(map(str, value))
    if f.kind == "number" and isinstance(value, float):
        return f"{value:.2f}".replace(".", ",").rstrip("0").rstrip(",")
    if f.kind == "file":
        return "file ricevuto"
    return str(value)


def human_datetime(value: str, today: date | None = None) -> str:
    """``2026-10-25T18:30:00`` → «dom 25 ott 18:30» (oggi/domani in words)."""
    today = today or date.today()
    s = str(value or "")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    d = dt.date()
    if d == today:
        day = "oggi"
    elif d == today + timedelta(days=1):
        day = "domani"
    elif d == today - timedelta(days=1):
        day = "ieri"
    else:
        day = f"{WEEKDAYS[d.weekday()][:3]} {d.day} {MONTHS[d.month - 1][:3]}" + (
            f" {d.year}" if d.year != today.year else "")
    has_time = "T" in s or " " in s.strip()
    return f"{day} {dt:%H:%M}" if has_time and (dt.hour or dt.minute) else day
