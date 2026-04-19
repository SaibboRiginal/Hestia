"""Command registry management — Hub discovery, revision polling, and Telegram menu setup."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests
from telebot.types import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot import core

logger = logging.getLogger("hestia_telegram.registry")

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
    logger.info("Command registry refreshed | revision=%s commands=%d",
                revision, len(discovered))
    setup_commands()
    return True


def watch_command_registry_loop():
    """Background loop: poll Hub for registry changes and refresh as needed."""
    interval = max(5, core.TELEGRAM_COMMAND_REFRESH_SECONDS)
    while True:
        try:
            refresh_command_registry(force=False)
        except Exception:
            pass
        time.sleep(interval)


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
    """Build the inline command picker keyboard for a chat."""
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton(
            str(meta.get("title", name)).strip()[:62],
            callback_data=f"run:{name}",
        )
        for name, meta in get_visible_command_items(surface="menu")
    ]
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            kb.row(buttons[i], buttons[i + 1])
        else:
            kb.row(buttons[i])
    return kb


def setup_commands():
    """Sync the Telegram native command menu with the current registry."""
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

    commands = [
        BotCommand(
            name, str(meta.get("title", meta.get("description", name))).strip()[:256])
        for name, meta in sorted(visible_map.items())
    ]
    core.bot.set_my_commands(commands)
    if core.ALLOWED_USER_ID and str(core.ALLOWED_USER_ID).isdigit():
        try:
            core.bot.set_my_commands(commands, scope=BotCommandScopeChat(
                chat_id=int(str(core.ALLOWED_USER_ID))))
        except Exception:
            pass
    logger.info("Telegram command menu updated | commands=%d", len(commands))
