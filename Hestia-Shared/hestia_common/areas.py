"""Areas of Hestia as people see them, and tool texts written for people (dossier
docs/work/2026-10-29-revisione-e-test-frontend §6, proposal 1).

A person never reads module names (Hercules, Hecate…) or text written for the model. Every client groups tools by
**area** (Allenamento, Casa, Spese…) and shows a short **summary**:

- ``area_of(tool, module)``: the tool's ``telegram_group`` when it names an area (or one of its aliases), else the
  module's default area, else «altro»;
- ``for_people(tool)``: the tool's own ``summary`` when the module wrote one (``MCPTool(summary=…)``), else the
  first sentence of its description without the notes meant for the model (parentheses, «NON», parameter hints).

Telegram's menus (``Hestia-Telegram/app/telegram_bot/menu/defaults.py``) use the same ``AREAS`` and
``SERVICE_AREAS``; the emoji are for Telegram only, web clients draw ``icon``.
"""
from __future__ import annotations

import re

# Areas in order. `aliases`: older or module group names that mean the same area.
AREAS = [
    {"key": "giornata", "label": "Giornata", "emoji": "📅", "icon": "calendar", "order": 10,
     "aliases": ["pianificazione", "agenda", "calendario", "chat", "meteo"]},
    {"key": "scadenze", "label": "Scadenze", "emoji": "⏳", "icon": "clock", "order": 15,
     "aliases": ["deadlines", "kairos"]},
    {"key": "allenamento", "label": "Allenamento", "emoji": "🏋️", "icon": "dumbbell", "order": 20,
     "aliases": ["fitness", "palestra"]},
    {"key": "alimentazione", "label": "Alimentazione", "emoji": "🥗", "icon": "leaf", "order": 25,
     "aliases": ["cibo", "food", "dieta", "demeter"]},
    {"key": "selfcare", "label": "Cura di sé", "emoji": "✨", "icon": "sparkle", "order": 30,
     "aliases": ["self care", "hygieia"]},
    {"key": "umore", "label": "Umore", "emoji": "😊", "icon": "smile", "order": 33,
     "aliases": ["mood", "psyche", "come sto"]},
    {"key": "persone", "label": "Persone", "emoji": "👥", "icon": "heart", "order": 35, "aliases": ["people", "hera"]},
    {"key": "guardaroba", "label": "Guardaroba", "emoji": "👕", "icon": "shirt", "order": 40, "aliases": ["wardrobe"]},
    {"key": "spese", "label": "Spese", "emoji": "💶", "icon": "wallet", "order": 50, "aliases": ["finanze", "soldi"]},
    {"key": "case", "label": "Immobili", "emoji": "🏠", "icon": "home", "order": 60,
     "aliases": ["immobiliare", "case in vendita"]},
    {"key": "casa", "label": "Casa", "emoji": "💡", "icon": "zap", "order": 65, "aliases": ["home", "domotica", "lares"]},
    {"key": "posta", "label": "Posta", "emoji": "✉️", "icon": "mail", "order": 70, "aliases": ["email", "mail"]},
    {"key": "memoria", "label": "Memoria", "emoji": "🧠", "icon": "bookmark", "order": 80,
     "aliases": ["preferenze", "web", "ricerca"]},
    {"key": "documenti", "label": "Documenti", "emoji": "📄", "icon": "file", "order": 82,
     "aliases": ["documents", "calliope"]},
    {"key": "notifiche", "label": "Notifiche", "emoji": "🔔", "icon": "bell", "order": 85, "aliases": ["avvisi"]},
    {"key": "sviluppo", "label": "Sviluppo", "emoji": "🛠", "icon": "code", "order": 90, "aliases": ["forge"]},
    {"key": "aspetto", "label": "Immagini e aspetto", "emoji": "🎨", "icon": "palette", "order": 95,
     "aliases": ["immagini", "images", "appearance", "apollo", "aphrodite"]},
    {"key": "sistema", "label": "Sistema", "emoji": "⚙️", "icon": "settings", "order": 100,
     "aliases": ["impostazioni", "webui", "🌐 webui", "salute"]},
    {"key": "altro", "label": "Altro", "emoji": "•", "icon": "more", "order": 999, "aliases": []},
]

# Last resort when a tool declares no area: its module.
SERVICE_AREAS = {
    "chronos": "giornata", "hecate": "giornata", "athena": "giornata", "hercules": "allenamento",
    "hygieia": "selfcare", "wardrobe": "guardaroba", "plutus": "spese", "scout": "case", "iris": "posta",
    "oracle": "memoria", "atlas": "memoria", "archive": "memoria", "hephaestus": "sviluppo", "metis": "sviluppo",
    "argus": "sistema", "themis": "sistema", "hub": "sistema", "mcp": "sistema", "echo": "sistema",
    "hermes": "notifiche", "telegram": "sistema", "webui": "sistema", "apollo": "aspetto", "aphrodite": "aspetto",
    "lares": "casa", "hera": "persone", "demeter": "alimentazione", "calliope": "documenti", "kairos": "scadenze",
    "psyche": "umore",
}

# What people call each part of Hestia (the WebUI plugin titles say the same): never the module's name.
MODULE_LABELS = {
    "hub": "Mappa del sistema", "archive": "Archivio", "argus": "Salute del sistema", "athena": "Pensieri",
    "chronos": "Agenda", "hecate": "Account e dispositivi", "hephaestus": "Sviluppo", "hermes": "Notifiche",
    "iris": "Email", "metis": "Miglioramento", "oracle": "Assistente", "themis": "Impostazioni", "mcp": "Comandi",
    "echo": "Voce", "atlas": "Ricerca sul web", "scout": "Immobili", "hercules": "Allenamento",
    "hygieia": "Self care", "wardrobe": "Guardaroba", "plutus": "Spese", "kairos": "Scadenze", "hera": "Persone",
    "demeter": "Alimentazione", "lares": "Casa", "apollo": "Immagini", "aphrodite": "Aspetto",
    "calliope": "Documenti", "psyche": "Umore", "webui": "Sito", "telegram": "Telegram", "dummy": "Prova",
}


def module_label(name: str) -> str:
    """People's name for a module («hygieia» → «Self care»); unknown names stay as they are."""
    return MODULE_LABELS.get(str(name or "").lower(), str(name or ""))


_BY_KEY = {a["key"]: a for a in AREAS}
_ALIAS = {alias.lower(): a["key"] for a in AREAS for alias in [a["key"], a["label"], *a["aliases"]]}


def area(key: str) -> dict:
    """The area record (key, label, icon, order…); unknown keys are «Altro»."""
    return _BY_KEY.get(_ALIAS.get(str(key or "").strip().lower(), ""), _BY_KEY["altro"])


def area_of(tool: dict, module: str = "") -> dict:
    """Area of a tool descriptor: its ``telegram_group`` when it names one, else the module's, else «Altro»."""
    group = str(tool.get("telegram_group") or tool.get("group") or "").strip().lower()
    if group in _ALIAS:
        return _BY_KEY[_ALIAS[group]]
    return _BY_KEY[SERVICE_AREAS.get(str(module or tool.get("module") or "").lower(), "altro")]


_PARENS = re.compile(r"\s*\([^()]*\)")
_CAPS = re.compile(r"\b([A-ZÀ-Ý]{2,})\b")
_KEEP_CAPS = {"AI", "PDF", "MCP", "ICS", "CSV", "JSON", "OK", "IVA", "PIN", "TV", "UV", "WC", "PC", "RCA", "F24",
              "IMU", "TARI", "GPS", "SMS", "LLM", "URL", "ID", "HA"}


def _soften(word: str) -> str:
    return word if word in _KEEP_CAPS else word.lower()


def for_people(tool: dict | str, limit: int = 160) -> str:
    """A short text for people: the tool's own ``summary``, else its description cleaned of model notes."""
    if isinstance(tool, dict):
        own = str(tool.get("summary") or "").strip()
        if own:
            return own[:limit]
        text = str(tool.get("description") or "")
    else:
        text = str(tool or "")
    text = _PARENS.sub("", _PARENS.sub("", " ".join(text.split())))   # notes for the model, nested once
    # first sentence (a colon list or «—» aside stays only when the sentence is short)
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    first = _CAPS.sub(lambda m: _soften(m.group(1)), first)
    for sep in (" — ", " - ", ": "):
        head, _, _tail = first.partition(sep)
        if _tail and len(first) > limit:
            first = head
    first = re.sub(r"\s+([,.;:])", r"\1", first).strip(" ,;:—-")
    if len(first) > limit:
        first = first[:limit - 1].rsplit(" ", 1)[0] + "…"
    if first and not first.endswith((".", "!", "?", "…")):
        first += "."
    return first[:1].upper() + first[1:]
