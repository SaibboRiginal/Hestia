"""Results without the model (docs/work/2026-10-23-telegram-da-zero §6): a tool's JSON → one card, same layout
every time.

1. The module's optional ``display`` block (``hestia_common.display``): title, subtitle, lines, items, actions.
2. Otherwise a generic renderer: lists become items, scalar fields «Etichetta: valore», technical keys omitted,
   dates and numbers in Italian, empty values never shown («n/d» never appears).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from telegram_bot import ui
from telegram_bot.inputs import human_datetime

MAX_CHARS = 3600
MAX_ITEMS = 15
MAX_FIELDS = 10

TITLE_KEYS = ("title", "name", "label", "summary", "subject", "display_name", "text", "fact", "description", "message")
META_KEYS = ("when", "start", "start_at", "start_datetime", "date", "time", "due", "at", "amount", "price", "total",
             "category", "status", "location", "place", "address", "from", "sender", "score", "count", "value",
             "brand", "kind", "type", "state")
URL_KEYS = ("url", "link", "href", "web_link", "html_link")
LIST_KEYS = ("items", "results", "events", "rows", "data", "list", "entries", "tasks", "listings", "messages",
             "products", "routines", "pieces", "outfits", "transactions", "sessions", "activities", "tools",
             "documents", "notifications", "memories", "facts", "logs", "services", "settings", "suggestions")
SKIP_KEYS = {"status", "ok", "tool", "params", "trace_id", "session_id", "notify_target", "raw", "debug", "schema",
             "display", "_meta", "meta", "version", "revision", "etag", "hash", "embedding", "html", "body_html"}

FIELD_LABELS = {
    "total": "Totale", "count": "Quanti", "amount": "Importo", "spent": "Speso", "budget": "Budget",
    "remaining": "Rimane", "date": "Data", "when": "Quando", "start": "Inizio", "end": "Fine", "next": "Prossimo",
    "status": "Stato", "state": "Stato", "location": "Luogo", "place": "Luogo", "note": "Nota", "notes": "Note",
    "category": "Categoria", "temperature": "Temperatura", "temp_c": "Temperatura", "weather": "Meteo",
    "updated_at": "Aggiornato", "created_at": "Creato", "last": "Ultimo", "goal": "Obiettivo", "streak": "Serie",
    "week": "Settimana", "month": "Mese", "score": "Punteggio", "message": "Messaggio", "detail": "Dettaglio",
    "summary": "Riepilogo", "reason": "Motivo", "description": "Descrizione", "price": "Prezzo", "size": "Taglia",
    "enabled": "Attivo", "active": "Attivo", "paused": "In pausa", "mode": "Modalità", "level": "Livello",
}

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$")
_ID_KEY = re.compile(r"(^|_)(id|uuid|ref|key|hash|token)$")


@dataclass
class Action:
    label: str
    tool: str
    args: dict = field(default_factory=dict)
    style: str = ""


@dataclass
class Rendered:
    html: str
    actions: list[Action] = field(default_factory=list)
    image: str = ""
    images: list[str] = field(default_factory=list)
    rows: list = field(default_factory=list)        # extra ready-made button rows (copy, url) from local actions
    document: tuple | None = None                   # (filename, bytes) sent as a file under the card
    files: list[dict] = field(default_factory=list)  # Archive blobs {blob_id, name, mime} (photo or document)


def _label_of(key: str) -> str:
    return FIELD_LABELS.get(key, re.sub(r"[_.]+", " ", key).strip().capitalize())


def value_text(value: Any, key: str = "") -> str:
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if isinstance(value, bool):
        return "Sì" if value else "No"
    if isinstance(value, float):
        text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        text = text.rstrip("0").rstrip(",")
        return f"{text} €" if key in ("amount", "price", "total", "spent", "budget", "remaining") else text
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".") if abs(value) >= 10000 else str(value)
    if isinstance(value, str):
        s = value.strip()
        if _ISO.match(s):
            return human_datetime(s)
        return s
    if isinstance(value, list):
        parts = [value_text(v) for v in value if not isinstance(v, (dict, list))]
        return ", ".join(p for p in parts if p)[:200]
    if isinstance(value, dict):
        title = _title_of(value)
        return title or ""
    return str(value)


def _title_of(obj: dict) -> str:
    for k in TITLE_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return ui.strip_emoji(v.strip())[:120]
    return ""


def _url_of(obj: dict) -> str:
    for k in URL_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    return ""


def _item_line(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ui.item(value_text(obj) or str(obj))
    title = _title_of(obj) or next((value_text(v, k) for k, v in obj.items()
                                    if k not in SKIP_KEYS and not _ID_KEY.search(k) and value_text(v, k)), "—")
    used = next((k for k in TITLE_KEYS if obj.get(k) and ui.strip_emoji(str(obj.get(k)))[:120] == title), None)
    meta: list[str] = []
    for k in META_KEYS:
        if k == used or k not in obj:
            continue
        text = value_text(obj[k], k)
        if text and len(text) <= 40 and text != title:
            meta.append(text)
        if len(meta) == 2:
            break
    return ui.item(title, meta, _url_of(obj))


def _list_in(payload: dict) -> tuple[str, list] | None:
    for k in LIST_KEYS:
        if isinstance(payload.get(k), list):
            return k, payload[k]
    lists = [(k, v) for k, v in payload.items() if isinstance(v, list) and v and isinstance(v[0], dict)]
    return lists[0] if len(lists) == 1 else None


def _items(rows: list, limit: int = MAX_ITEMS) -> list[str]:
    lines = [_item_line(r) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(ui.note(f"e altri {len(rows) - limit}"))
    return lines


def _fields(obj: dict, skip: set[str] = frozenset()) -> list[str]:
    lines: list[str] = []
    for k, v in obj.items():
        if k in SKIP_KEYS or k in skip or k.startswith("_") or _ID_KEY.search(k):
            continue
        if isinstance(v, dict):
            inner = _title_of(v)
            if inner:
                lines.append(f"{ui.esc(_label_of(k))}: {ui.esc(inner)}")
            else:
                sub = [f"{_label_of(sk)} {value_text(sv, sk)}" for sk, sv in v.items()
                       if not isinstance(sv, (dict, list)) and value_text(sv, sk) and not _ID_KEY.search(sk)][:3]
                if sub:
                    lines.append(f"{ui.esc(_label_of(k))}: {ui.esc(' · '.join(sub))}")
            continue
        if isinstance(v, list) and v and isinstance(v[0], dict):
            lines.append(f"{ui.esc(_label_of(k))}:")
            lines.extend(_items(v, 5))
            continue
        text = value_text(v, k)
        if text:
            if len(text) > 300:
                text = text[:300].rsplit(" ", 1)[0] + "…"
            lines.append(f"{ui.esc(_label_of(k))}: {ui.esc(text)}")
        if len(lines) >= MAX_FIELDS * 2:
            break
    return lines


def _display(block: dict, title: str, marker: str) -> Rendered:
    lines = [ui.esc(str(x)) for x in block.get("lines") or [] if str(x or "").strip()]
    for it in block.get("items") or []:
        if isinstance(it, dict):
            line = ui.item(str(it.get("title") or ""), [str(m) for m in it.get("meta") or []], str(it.get("url") or ""))
            dot = ui.tone_dot(it.get("tone"))
            lines.append(line.replace("• ", f"{dot} ", 1) if dot else line)
        else:
            lines.append(ui.item(str(it)))
    html = ui.card(str(block.get("title") or title), lines, subtitle=str(block.get("subtitle") or ""),
                   marker="" if block.get("tone") else marker, tone=block.get("tone"),
                   footer=str(block.get("footer") or ""))
    actions = [Action(label=str(a.get("label") or ""), tool=str(a.get("tool") or ""),
                      args=a.get("args") if isinstance(a.get("args"), dict) else {}, style=str(a.get("style") or ""))
               for a in block.get("actions") or [] if isinstance(a, dict) and a.get("label") and a.get("tool")]
    images = [str(i) for i in block.get("images") or [] if str(i).startswith("http")]
    files = [f for f in block.get("files") or [] if isinstance(f, dict) and f.get("blob_id")][:10]
    return Rendered(_cap(html), actions, image=str(block.get("image") or ""), images=images, files=files)


def _cap(html: str) -> str:
    if len(html) <= MAX_CHARS:
        return html
    cut = html[:MAX_CHARS].rsplit("\n", 1)[0]
    return cut + "\n" + ui.note("… continua: chiedimelo in chat per il resto.")


def render(payload: Any, title: str = "", marker: str = "") -> Rendered:
    """Any tool answer → a card. ``title``: the action's name; ``marker``: its area emoji."""
    if isinstance(payload, str):
        s = payload.strip()
        if s[:1] in "{[":
            try:
                return render(json.loads(s), title, marker)
            except ValueError:
                pass
        body = ui.esc(s[:MAX_CHARS]) if s else ui.note("Fatto.")
        return Rendered(ui.card(title, [body], marker=marker))
    if isinstance(payload, list):
        if not payload:
            return Rendered(ui.card(title, [ui.note("Niente da mostrare.")], marker=marker))
        return Rendered(_cap(ui.card(title, _items(payload), marker=marker)))
    if not isinstance(payload, dict):
        return Rendered(ui.card(title, [ui.esc(value_text(payload) or "Fatto.")], marker=marker))
    if isinstance(payload.get("display"), dict):
        return _display(payload["display"], title, marker)
    if isinstance(payload.get("result"), (dict, list)) and len(payload) <= 3:
        return render(payload["result"], title, marker)
    found = _list_in(payload)
    lines: list[str] = []
    subtitle = ""
    message = payload.get("message") or payload.get("detail") or payload.get("text")
    if isinstance(message, str) and message.strip() and len(message) < 600:
        lines.append(ui.esc(ui.strip_emoji(message.strip()) or message.strip()))
    skip = {"message", "detail", "text"}
    if found:
        key, rows = found
        skip.add(key)
        scalar = _fields(payload, skip)
        lines.extend(scalar[:6])
        lines.extend(_items(rows) if rows else [ui.note("Niente da mostrare.")])
    else:
        lines.extend(_fields(payload, skip))
    if not lines:
        lines = [ui.note("Fatto.")]
    if payload.get("ok") is False or str(payload.get("status") or "").lower() in ("error", "failed"):
        return Rendered(_cap(ui.card(title, lines, tone="danger")))
    return Rendered(_cap(ui.card(title, lines, subtitle=subtitle, marker=marker)))
