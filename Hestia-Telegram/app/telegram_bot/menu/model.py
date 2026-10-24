"""The menu as one data structure, built at run time from three layers (later wins):

1. ``menu.defaults`` (data in this repo), 2. module hints on each tool (``telegram_group`` + ``telegram``),
3. the user's layout (Themis ``telegram.menu.layout``).

A tool that no layer mentions still appears (area from its module, else «Altro»): no layout can lose a function.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from telegram_bot import ui
from telegram_bot.menu import defaults as D

logger = logging.getLogger("hestia_telegram.menu")

OTHER_SECTION = "Altre azioni"


@dataclass
class Area:
    key: str
    label: str
    emoji: str = ""
    order: int = 500
    icon: str = ""                                  # custom emoji id (Telegram Premium owners)
    header: str | None = None                       # tool rendered at the top of the area card
    primary: list[str] = field(default_factory=list)
    sections: dict[str, list[str]] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return [n for names in self.sections.values() for n in names]

    @property
    def button_text(self) -> str:
        return f"{self.emoji} {self.label}".strip() if not self.icon else self.label


@dataclass
class Menu:
    keyboard: list[list[str]]
    doors: dict[str, str]
    commands: list[tuple[str, str]]
    areas: list[Area]
    today: dict[str, list[str]]
    tool_area: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    hidden: set[str] = field(default_factory=set)       # internal tools: reachable typed, never drawn
    all_areas: list[Area] = field(default_factory=list)  # also the empty ones (menu editor)

    def area(self, key: str) -> Area | None:
        return next((a for a in self.all_areas or self.areas if a.key == key), None)

    def area_of(self, tool_name: str) -> Area | None:
        return self.area(self.tool_area.get(tool_name, ""))

    def label(self, tool_name: str) -> str:
        return self.labels.get(tool_name, tool_name)

    def door_for_text(self, text: str) -> str | None:
        """Exact, whole-message match of a bottom keyboard button."""
        wanted = str(text or "").strip().casefold()
        return next((k for k, v in self.doors.items() if v.casefold() == wanted), None)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _commands(raw: Any) -> list[tuple[str, str]]:
    """Layout ``commands``: names (described by the defaults) or ``[name, description]`` pairs."""
    if not isinstance(raw, list) or not raw:
        return list(D.COMMANDS)
    known = dict(D.COMMANDS)
    out: list[tuple[str, str]] = []
    for c in raw:
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            out.append((str(c[0]).lower(), str(c[1])))
        elif isinstance(c, str):
            out.append((c.lower(), known.get(c.lower(), c)))
    return out[:100]


def build(tools: list, layout: dict | None = None) -> Menu:
    layout = layout if isinstance(layout, dict) else {}
    lay_areas = layout.get("areas") if isinstance(layout.get("areas"), dict) else {}
    lay_tools = layout.get("tools") if isinstance(layout.get("tools"), dict) else {}

    areas: dict[str, Area] = {}
    alias: dict[str, str] = {}
    for spec in copy.deepcopy(D.AREAS):
        areas[spec["key"]] = Area(key=spec["key"], label=spec["label"], emoji=spec.get("emoji", ""),
                                  order=_as_int(spec.get("order"), 500))
        for name in [spec["key"], *spec.get("aliases", [])]:
            alias[str(name).lower()] = spec["key"]
    for key, over in lay_areas.items():
        if not isinstance(over, dict):
            continue
        key = str(key).lower()
        area = areas.get(key) or Area(key=key, label=str(over.get("label") or key.capitalize()), order=800)
        area.label = str(over.get("label") or area.label)
        area.emoji = str(over.get("emoji", area.emoji) or "")
        area.icon = str(over.get("icon") or area.icon)
        area.order = _as_int(over.get("order"), area.order)
        areas[key] = area
        alias.setdefault(key, key)

    known = {t.name for t in tools}
    for name in [*lay_tools, *[n for a in lay_areas.values() if isinstance(a, dict) for n in a.get("primary") or []]]:
        if name not in known:
            logger.info("event=menu_layout_unknown tool=%s", name)

    menu = Menu(keyboard=layout.get("keyboard") or copy.deepcopy(D.KEYBOARD),
                doors={**D.DOORS, **(layout.get("doors") or {})},
                commands=_commands(layout.get("commands")),
                areas=[], today={**D.TODAY, **(layout.get("today") or {})})

    placed: list[tuple[str, str, int, Any, bool, Any]] = []
    for t in tools:
        over = lay_tools.get(t.name) if isinstance(lay_tools.get(t.name), dict) else {}
        hints = t.hints or {}
        area_key = (alias.get(str(over.get("area") or "").lower()) or alias.get(t.group)
                    or D.SERVICE_AREAS.get(t.service) or "altro")
        if area_key not in areas:
            area_key = "altro"
        section = str(over.get("section") or hints.get("section") or OTHER_SECTION)
        menu.labels[t.name] = ui.label(over.get("label") or hints.get("label") or t.title)
        if section in D.HIDDEN_SECTIONS:
            menu.hidden.add(t.name)
            continue
        order = _as_int(over.get("order", hints.get("order")), t.index)
        primary = over.get("primary", hints.get("primary"))
        placed.append((t.name, area_key, order, primary, bool(hints.get("summary")), section))
        menu.tool_area[t.name] = area_key

    for name, area_key, order, primary, summary, section in sorted(placed, key=lambda p: p[2]):
        area = areas[area_key]
        area.sections.setdefault(section, []).append(name)
        if summary and not area.header:
            area.header = name

    for area in areas.values():
        over = lay_areas.get(area.key) if isinstance(lay_areas.get(area.key), dict) else {}
        if over.get("header") in menu.tool_area:
            area.header = over["header"]
        if isinstance(over.get("primary"), list):
            area.primary = [n for n in over["primary"] if menu.tool_area.get(n) == area.key or n in known][:12]
        else:
            ranked = [(p[3], p[2], p[0]) for p in placed if p[1] == area.key and p[3]]
            area.primary = [n for _, _, n in sorted(ranked, key=lambda r: (_as_int(r[0], 99), r[1]))][:D.PRIMARY_MAX]
        # sections: by first tool order, «Altre azioni» then «Avanzate» last
        order_of = {n: i for i, n in enumerate(p[0] for p in sorted(placed, key=lambda p: p[2]))}
        area.sections = dict(sorted(
            area.sections.items(),
            key=lambda kv: (kv[0] == D.LAST_SECTION, kv[0] == OTHER_SECTION, min(order_of.get(n, 0) for n in kv[1]))))

    menu.all_areas = sorted(areas.values(), key=lambda a: (a.order, a.label))
    menu.areas = [a for a in menu.all_areas if a.sections]
    return menu


def current() -> Menu:
    from telegram_bot import catalog
    return build(catalog.all_tools(), layout())


def layout() -> dict:
    import telegram_settings as ts
    value = ts.settings.get(ts.MENU_LAYOUT)
    return value if isinstance(value, dict) else {}
