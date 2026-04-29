"""Command registry management — Hub discovery, refresh, and Telegram menu setup."""
from __future__ import annotations

import logging
import threading
from typing import Any

import requests
from telebot.types import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot import core

logger = logging.getLogger("hestia_telegram.registry")

# ── setup_commands debounce ───────────────────────────────────────────────────
_SETUP_COMMANDS_COOLDOWN_SEC = 60
_setup_commands_lock = threading.Lock()
_setup_commands_last_run: float = 0.0

# ── Group definitions (order matters for display) ─────────────────────────────
# Each tuple: (group_key, display_label, short_description)
GROUP_ORDER: list[tuple[str, str, str]] = [
    ("notifiche",      "🔔 Notifiche",      "Gestisci notifiche proattive"),
    ("immobiliare",    "🏠 Immobiliare",    "Cerca e monitora annunci"),
    ("pianificazione", "📅 Pianificazione", "Crea eventi, task e promemoria"),
    ("documenti",      "📎 Documenti",      "Documenti caricati e archiviati"),
    ("sistema",        "⚙️ Sistema",        "Stato e diagnostica del sistema"),
    ("impostazioni",   "⚙️ Impostazioni",   "Sessione, tono e preferenze"),
    ("altro",          "🔧 Altro",          "Altri comandi disponibili"),
]

# ── Hub discovery ─────────────────────────────────────────────────────────────


def discover_commands_from_hub() -> dict[str, dict[str, Any]]:
    """Fetch the full command list from Hub and index by command name."""
    try:
        response = requests.get(
            f"{core.HUB_API_URL}/discovery/commands", params={"client": "telegram"}, timeout=6
        )
        if response.status_code != 200:
            logger.warning(
                "Hub command discovery returned non-200 | status=%s", response.status_code)
            return {}
        discovered: dict[str, dict[str, Any]] = {}
        for item in response.json().get("commands", []) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("command", "")).strip().lower()
            if name:
                discovered[name] = item
        logger.debug("Discovered %d commands from Hub", len(discovered))
        return discovered
    except Exception as exc:
        logger.warning("Hub command discovery failed: %s", exc)
        return {}


def fetch_registry_revision() -> int | None:
    """Return the current registry revision number from Hub."""
    try:
        response = requests.get(
            f"{core.HUB_API_URL}/registry/revision", timeout=5)
        if response.status_code != 200:
            return None
        return int((response.json() or {}).get("revision", 0))
    except Exception:
        return None


def refresh_command_registry(force: bool = False) -> bool:
    """Refresh the in-memory command registry if the Hub revision has changed.

    Returns True if the registry was actually updated.
    """
    revision = fetch_registry_revision()
    if revision is None and not force:
        return False
    if not force and revision is not None and revision == core.COMMAND_REGISTRY_REVISION:
        return False

    discovered = discover_commands_from_hub()
    with core.COMMAND_REGISTRY_LOCK:
        core.COMMAND_REGISTRY = discovered
        if revision is not None:
            core.COMMAND_REGISTRY_REVISION = revision
    if force:
        logger.info("Command registry refreshed | revision=%s commands=%d",
                    revision, len(discovered))
    else:
        logger.debug("Command registry refreshed | revision=%s commands=%d",
                     revision, len(discovered))
    setup_commands()
    return True


def register_telegram_service() -> bool:
    """Register this Telegram service with the Hub."""
    payload = {
        "name": "telegram",
        "base_url": core.TELEGRAM_BASE_URL,
        "health_endpoint": "/health",
        "service_type": "integration",
        "service_version": "1.0.0",
        "tags": ["integration", "messaging", "chat"],
        "capabilities": {
            "interface": "telegram",
            "hub_events_webhook": "/api/events/registry-changed",
        },
    }
    try:
        response = requests.post(
            f"{core.HUB_API_URL}/registry/register", json=payload, timeout=6)
        if response.status_code == 200:
            return True
        logger.warning("Hub registration non-success | status=%s",
                       response.status_code)
        return False
    except Exception as exc:
        logger.warning("Hub registration request failed: %s", exc)
        return False


# ── Telegram menu / command list ──────────────────────────────────────────────

def get_local_command_items(surface: str = "menu") -> list[tuple[str, dict[str, Any]]]:
    """Return local commands filtered by surface (``"menu"`` or ``"help"``)."""
    visible: list[tuple[str, dict[str, Any]]] = []
    for name, meta in sorted(core.LOCAL_COMMANDS.items()):
        if not bool(meta.get("telegram_visible", True)):
            continue
        if surface == "menu" and meta.get("telegram_menu_visible") is False:
            continue
        if surface == "help" and meta.get("telegram_help_visible") is False:
            continue
        visible.append((name, meta))
    return visible


def get_visible_command_items(surface: str = "menu") -> list[tuple[str, dict[str, Any]]]:
    """Return all user-visible commands (local + dynamic) filtered by surface."""
    visible_map: dict[str, dict[str, Any]] = dict(
        get_local_command_items(surface=surface))

    with core.COMMAND_REGISTRY_LOCK:
        registry_items = sorted(core.COMMAND_REGISTRY.items())

    for name, meta in registry_items:
        if name in core.TELEGRAM_HIDDEN_DYNAMIC_COMMANDS:
            continue
        service = str(meta.get("service", "")).strip().lower()
        response_mode = str(
            meta.get("response_mode", "raw_json")).strip().lower()
        explicitly_visible = bool(meta.get("telegram_visible", False))
        if service in core.TELEGRAM_HIDDEN_COMMAND_SERVICES and not explicitly_visible:
            continue
        if response_mode == "raw_json" and not explicitly_visible:
            continue
        if surface == "menu" and meta.get("telegram_menu_visible") is False:
            continue
        if surface == "help" and meta.get("telegram_help_visible") is False:
            continue
        if name not in visible_map:
            visible_map[name] = meta

    return sorted(visible_map.items())


def build_commands_keyboard() -> InlineKeyboardMarkup:
    """Build the main category keyboard — one button per non-empty group."""
    grouped = get_grouped_commands()
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton(label, callback_data=f"grp:{key}")
        for key, label, _ in GROUP_ORDER
        if key in grouped
    ]
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            kb.row(buttons[i], buttons[i + 1])
        else:
            kb.row(buttons[i])
    return kb


def build_group_commands_keyboard(group_key: str) -> InlineKeyboardMarkup:
    """Build the command list keyboard for a single group, with a Back button."""
    grouped = get_grouped_commands()
    kb = InlineKeyboardMarkup(row_width=1)
    for name, meta in (grouped.get(group_key) or []):
        title = str(meta.get("title", name)).strip()[:62]
        kb.add(InlineKeyboardButton(title, callback_data=f"run:{name}"))
    kb.add(InlineKeyboardButton("← Indietro", callback_data="grp:__main__"))
    return kb


def _infer_group(name: str, meta: dict) -> str | None:
    """Return the group key for a command, or 'altro' as catch-all fallback."""
    explicit = str(meta.get("group", "")).strip().lower()
    if explicit:
        return explicit
    service = str(meta.get("service", "")).strip().lower()
    if service == "scout" or name.startswith("scout_"):
        return "immobiliare"
    if service in ("chronos", "ingest"):
        return "pianificazione"
    if service == "argus":
        return "sistema"
    if service == "archive":
        # Archive commands are mostly notification/subscription management
        return "notifiche"
    # Catch-all: any remaining visible command appears under "Altro"
    return "altro"


def get_grouped_commands() -> dict[str, list[tuple[str, dict]]]:
    """Return all visible menu commands bucketed by group key."""
    groups: dict[str, list[tuple[str, dict]]] = {}
    for name, meta in get_visible_command_items(surface="menu"):
        group = _infer_group(name, meta)
        if group:
            groups.setdefault(group, []).append((name, meta))
    return groups


def setup_commands():
    """Sync the Telegram native command menu with the current registry.

    Calls to set_my_commands are debounced: no more than one call every
    _SETUP_COMMANDS_COOLDOWN_SEC seconds to avoid Telegram 429 errors when
    multiple services register in quick succession.
    """
    global _setup_commands_last_run
    with _setup_commands_lock:
        now = time.time()
        if now - _setup_commands_last_run < _SETUP_COMMANDS_COOLDOWN_SEC:
            logger.debug("setup_commands skipped (cooldown)")
            return
        _setup_commands_last_run = now

    visible_map: dict[str, dict[str, Any]] = {}

    for name, meta in sorted(core.LOCAL_COMMANDS.items()):
        if bool(meta.get("telegram_visible", True)):
            visible_map[name] = meta

    with core.COMMAND_REGISTRY_LOCK:
        registry_items = sorted(core.COMMAND_REGISTRY.items())

    for name, meta in registry_items:
        if name in core.TELEGRAM_HIDDEN_DYNAMIC_COMMANDS:
            continue
        service = str(meta.get("service", "")).strip().lower()
        response_mode = str(
            meta.get("response_mode", "raw_json")).strip().lower()
        explicitly_visible = bool(meta.get("telegram_visible", False))
        if service in core.TELEGRAM_HIDDEN_COMMAND_SERVICES and not explicitly_visible:
            continue
        if response_mode == "raw_json" and not explicitly_visible:
            continue
        if name not in visible_map:
            visible_map[name] = meta

    def _command_sort_key(item: tuple[str, dict]) -> tuple[int, str]:
        name = item[0]
        if name == "help":
            return (0, "")
        return (1, name)

    commands = [
        BotCommand(
            name, str(meta.get("title", meta.get("description", name))).strip()[:256])
        for name, meta in sorted(visible_map.items(), key=_command_sort_key)
    ]
    try:
        core.bot.set_my_commands(commands)
    except Exception as e:
        logger.warning("set_my_commands failed (global scope): %s", e)
        return
    if core.ALLOWED_USER_ID and str(core.ALLOWED_USER_ID).isdigit():
        try:
            core.bot.set_my_commands(commands, scope=BotCommandScopeChat(
                chat_id=int(str(core.ALLOWED_USER_ID))))
        except Exception:
            pass
    logger.debug("Telegram command menu updated | commands=%d", len(commands))
