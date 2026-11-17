"""Areas of Hestia as people see them, and tool texts written for people (dossier
docs/work/2026-10-29-revisione-e-test-frontend §6, proposal 1).

A person never reads module names (Hercules, Hecate…) or text written for the model. Every client groups tools by
**area** (Training, Home, Expenses…) and shows a short **summary**:

- ``area_of(tool, module)``: the tool's ``telegram_group`` when it names an area (or one of its aliases), else the
  module's default area, else «other»;
- ``for_people(tool)``: the tool's own ``summary`` when the module wrote one (``MCPTool(summary=…)``), else the
  first sentence of its description without the notes meant for the model (parentheses, «NOT», parameter hints).

Telegram's menus (``Hestia-Telegram/app/telegram_bot/menu/defaults.py``) use the same ``AREAS`` and
``SERVICE_AREAS``; the emoji are for Telegram only, web clients draw ``icon``.
"""
from __future__ import annotations

import re

from .i18n import bare, t

# Areas in order. `aliases`: other module group names that mean the same area.
AREAS = [
    {"key": "day", "label": "alt::Day", "emoji": "📅", "icon": "calendar", "order": 10,
     "aliases": ["planning", "agenda", "calendar", "chat", "weather"]},
    {"key": "deadlines", "label": "Deadlines", "emoji": "⏳", "icon": "clock", "order": 15, "aliases": ["kairos"]},
    {"key": "training", "label": "Training", "emoji": "🏋️", "icon": "dumbbell", "order": 20,
     "aliases": ["fitness", "gym"]},
    {"key": "nutrition", "label": "Nutrition", "emoji": "🥗", "icon": "leaf", "order": 25,
     "aliases": ["food", "diet", "demeter"]},
    {"key": "selfcare", "label": "Self care", "emoji": "✨", "icon": "sparkle", "order": 30,
     "aliases": ["self care", "hygieia"]},
    {"key": "mood", "label": "Mood", "emoji": "😊", "icon": "smile", "order": 33, "aliases": ["psyche"]},
    {"key": "people", "label": "People", "emoji": "👥", "icon": "heart", "order": 35, "aliases": ["hera"]},
    {"key": "wardrobe", "label": "Wardrobe", "emoji": "👕", "icon": "shirt", "order": 40, "aliases": []},
    {"key": "expenses", "label": "Expenses", "emoji": "💶", "icon": "wallet", "order": 50,
     "aliases": ["finance", "money"]},
    {"key": "houses", "label": "alt::Houses", "emoji": "🏠", "icon": "home", "order": 60,
     "aliases": ["real_estate", "houses for sale"]},
    {"key": "home", "label": "Home", "emoji": "💡", "icon": "zap", "order": 65, "aliases": ["smart_home", "lares"]},
    {"key": "mail", "label": "Mail", "emoji": "✉️", "icon": "mail", "order": 70, "aliases": ["email"]},
    {"key": "memory", "label": "Memory", "emoji": "🧠", "icon": "bookmark", "order": 80,
     "aliases": ["preferences", "web", "search"]},
    {"key": "documents", "label": "Documents", "emoji": "📄", "icon": "file", "order": 82, "aliases": ["calliope"]},
    {"key": "notifications", "label": "Notifications", "emoji": "🔔", "icon": "bell", "order": 85,
     "aliases": ["alerts"]},
    {"key": "development", "label": "Development", "emoji": "🛠", "icon": "code", "order": 90, "aliases": ["forge"]},
    {"key": "look", "label": "Images and look", "emoji": "🎨", "icon": "palette", "order": 95,
     "aliases": ["images", "appearance", "apollo", "aphrodite"]},
    {"key": "system", "label": "System", "emoji": "⚙️", "icon": "settings", "order": 100,
     "aliases": ["settings", "webui", "🌐 webui", "health"]},
    {"key": "other", "label": "Other", "emoji": "•", "icon": "more", "order": 999, "aliases": []},
]

# Last resort when a tool declares no area: its module.
SERVICE_AREAS = {
    "chronos": "day", "hecate": "day", "athena": "day", "hercules": "training",
    "hygieia": "selfcare", "wardrobe": "wardrobe", "plutus": "expenses", "scout": "houses", "iris": "mail",
    "oracle": "memory", "atlas": "memory", "archive": "memory", "hephaestus": "development", "metis": "development",
    "argus": "system", "themis": "system", "hub": "system", "mcp": "system", "echo": "system",
    "hermes": "notifications", "telegram": "system", "webui": "system", "apollo": "look", "aphrodite": "look",
    "lares": "home", "hera": "people", "demeter": "nutrition", "calliope": "documents", "kairos": "deadlines",
    "psyche": "mood",
}

# What people call each part of Hestia (the WebUI plugin titles say the same): never the module's name.
MODULE_LABELS = {
    "hub": "System map", "archive": "Archive", "argus": "System health", "athena": "Thoughts",
    "chronos": "Agenda", "hecate": "Accounts and devices", "hephaestus": "Development", "hermes": "Notifications",
    "iris": "Email", "metis": "Improvement", "oracle": "Assistant", "themis": "Settings", "mcp": "Commands",
    "echo": "Voice", "atlas": "Web search", "scout": "alt::Houses", "hercules": "Training",
    "hygieia": "Self care", "wardrobe": "Wardrobe", "plutus": "Expenses", "kairos": "Deadlines", "hera": "People",
    "demeter": "Nutrition", "lares": "Home", "apollo": "Images", "aphrodite": "Look",
    "calliope": "Documents", "psyche": "Mood", "webui": "Site", "telegram": "Telegram", "dummy": "alt::Test",
}


def module_label(name: str) -> str:
    """People's name for a module («hygieia» → «Self care»); unknown names stay as they are."""
    return MODULE_LABELS.get(str(name or "").lower(), str(name or ""))


_BY_KEY = {a["key"]: a for a in AREAS}
# People type an area by its key, its English name, its Italian name or an alias.
_ALIAS = {alias.lower(): a["key"] for a in AREAS
          for alias in [a["key"], bare(a["label"]), t(a["label"], lang="it"), *a["aliases"]]}


def area(key: str) -> dict:
    """The area record (key, label, icon, order…); unknown keys are «Other»."""
    return _BY_KEY.get(_ALIAS.get(str(key or "").strip().lower(), ""), _BY_KEY["other"])


def area_of(tool: dict, module: str = "") -> dict:
    """Area of a tool descriptor: its ``telegram_group`` when it names one, else the module's, else «Other»."""
    group = str(tool.get("telegram_group") or tool.get("group") or "").strip().lower()
    if group in _ALIAS:
        return _BY_KEY[_ALIAS[group]]
    return _BY_KEY[SERVICE_AREAS.get(str(module or tool.get("module") or "").lower(), "other")]


_PARENS = re.compile(r"\s*\([^()]*\)")
_CAPS = re.compile(r"\b([A-ZÀ-Ý]{2,})\b")
_KEEP_CAPS = {"AI", "PDF", "MCP", "ICS", "CSV", "JSON", "OK", "IVA", "PIN", "TV", "UV", "WC", "PC", "RCA", "F24",
              "IMU", "TARI", "GPS", "SMS", "LLM", "URL", "ID", "HA"}


def _soften(word: str) -> str:
    return word if word in _KEEP_CAPS else word.lower()


def for_people(tool: dict | str, limit: int = 160, lang: str | None = None) -> str:
    """A short text for people: the tool's own ``summary``, else its text in the people catalog
    (``hestia_common.i18n``, by ``name``/``command``, in ``lang``), else its description cleaned of model notes
    (descriptions are English, written for the model)."""
    from hestia_common import i18n
    lang = lang or i18n.current()
    if isinstance(tool, dict):
        own = str(tool.get("summary") or "").strip()
        if own:
            return i18n.t(own, lang=lang)[:limit]
        listed = i18n.tool_summary(str(tool.get("name") or tool.get("command") or ""), lang)
        if listed:
            return listed[:limit]
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
