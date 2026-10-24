"""Every action Telegram can run: all of Hestia's tools (through Hestia-MCP) plus Telegram's own local actions.

Nothing is hidden (docs/work/2026-10-23-telegram-da-zero §5.9): where an action is shown is decided by the menu
(``telegram_bot.menu.model``), not here.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from telegram_bot import core

logger = logging.getLogger("hestia_telegram.catalog")

AUTO_ARGS = {"session_id", "notify_target", "chat_id"}     # filled by Telegram, never asked


@dataclass
class Tool:
    name: str
    title: str
    description: str = ""
    service: str = ""
    group: str = ""                       # module's area key (telegram_group)
    hints: dict = field(default_factory=dict)   # module's telegram hints (section, primary, summary, label, order)
    schema: dict = field(default_factory=dict)
    writes: bool = False
    destructive: bool = False
    arg_picker: dict = field(default_factory=dict)
    handler: Callable[..., Any] | None = None   # local action: handler(chat_id, args) → payload or Reply
    index: int = 0                        # declaration order

    @property
    def local(self) -> bool:
        return self.handler is not None

    @property
    def command(self) -> str:
        return re.sub(r"[^a-z0-9_]", "_", self.name.lower())

    def properties(self) -> dict[str, dict]:
        props = self.schema.get("properties") if isinstance(self.schema.get("properties"), dict) else {}
        return {k: (v if isinstance(v, dict) else {}) for k, v in props.items() if k not in AUTO_ARGS}

    def required(self) -> list[str]:
        req = self.schema.get("required") if isinstance(self.schema.get("required"), list) else []
        props = self.properties()
        return [str(r) for r in req if str(r) in props]


_DESTRUCTIVE = re.compile(r"(delete|elimina|annulla|cancel|remove|rollback|reject|rifiuta|revoke|disattiva)", re.I)

_lock = threading.Lock()
_tools: dict[str, Tool] = {}
_revision: int | None = None


def from_mcp(tool: dict, index: int = 0) -> Tool | None:
    from hestia_common.mcp_client import hestia_meta
    name = str(tool.get("name") or "").strip()
    if not name:
        return None
    meta = hestia_meta(tool)
    annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
    method = str(meta.get("method") or "GET").upper()
    writes = not bool(annotations.get("readOnlyHint", method == "GET"))
    destructive = bool(annotations.get("destructiveHint")) or method == "DELETE" or \
        (writes and bool(_DESTRUCTIVE.search(name)))
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    return Tool(name=name, title=str(tool.get("title") or meta.get("title") or name), index=index,
                description=str(tool.get("description") or ""), service=str(meta.get("service") or ""),
                group=str(meta.get("telegram_group") or "").strip().lower(),
                hints=meta.get("telegram") if isinstance(meta.get("telegram"), dict) else {},
                schema=schema, writes=writes, destructive=destructive,
                arg_picker=meta.get("arg_picker") if isinstance(meta.get("arg_picker"), dict) else {})


_client = None


def _mcp():
    from hestia_common.mcp_client import MCPClient
    global _client
    if _client is None:
        _client = MCPClient(core.HUB_API_URL, client="telegram", cache_ttl=0)
    return _client


def fetch_revision() -> int | None:
    try:
        response = requests.get(f"{core.HUB_API_URL}/registry/revision", timeout=5)
        return int((response.json() or {}).get("revision", 0)) if response.status_code == 200 else None
    except Exception:
        return None


def refresh(force: bool = False) -> bool:
    """Reload the tools when Hub's registry changed. True when the list was replaced."""
    global _revision
    revision = fetch_revision()
    if not force and (revision is None or revision == _revision) and _tools:
        return False
    remote = [t for i, raw in enumerate(_mcp().list_tools(refresh=True)) if (t := from_mcp(raw, i))]
    from telegram_bot import local_actions
    merged = {t.name: t for t in remote}
    for i, t in enumerate(local_actions.tools()):
        t.index = 10_000 + i
        merged.setdefault(t.name, t)
    with _lock:
        _tools.clear()
        _tools.update(merged)
        if revision is not None:
            _revision = revision
    logger.info("event=telegram_catalog_refreshed tools=%d local=%d revision=%s",
                len(remote), len(merged) - len(remote), revision)
    return True


def set_tools(tools: list[Tool]) -> None:
    """Tests and offline start: replace the catalog."""
    with _lock:
        _tools.clear()
        _tools.update({t.name: t for t in tools})


def all_tools() -> list[Tool]:
    with _lock:
        if _tools:
            return list(_tools.values())
    try:
        refresh(force=True)
    except Exception as exc:  # noqa: BLE001 — Hestia-MCP down: local actions only
        logger.warning("[🔄] event=telegram_catalog_unavailable error=%s", exc)
        from telegram_bot import local_actions
        set_tools(local_actions.tools())
    with _lock:
        return list(_tools.values())


def get(name: str) -> Tool | None:
    name = str(name or "")
    for t in all_tools():
        if t.name == name:
            return t
    for t in all_tools():
        if t.command == name.lower():
            return t
    return None


def run(tool: Tool, chat_id, args: dict[str, Any], timeout: float = 30) -> tuple[bool, Any]:
    """Run a tool with the given values (session and chat filled in). ``(ok, payload)``."""
    if tool.local:
        try:
            return True, tool.handler(chat_id, dict(args))
        except Exception as exc:  # noqa: BLE001
            logger.warning("event=local_action_failed action=%s error=%s", tool.name, exc)
            return False, str(exc) if getattr(exc, "user_facing", False) else ""
    session_id = core.get_session(str(chat_id))
    values = dict(args)
    props = (tool.schema.get("properties") or {}) if isinstance(tool.schema, dict) else {}
    if "session_id" in props:
        values.setdefault("session_id", session_id)
    if "chat_id" in props:
        values.setdefault("chat_id", str(chat_id))
    return _mcp().call(tool.name, values, session_id=session_id, notify_target=str(chat_id),
                       service=tool.service, origin_client="telegram", timeout=timeout)


def route(service: str, path: str, method: str = "GET", *, query: dict | None = None, body: Any = None,
          timeout: float = 20) -> tuple[bool, Any]:
    """A plain Hub route (picker sources, Hermes inbox, local actions)."""
    try:
        response = requests.post(f"{core.HUB_API_URL}/route/{service}/{path.lstrip('/')}", json={
            "method": method.upper(), "headers": {}, "query": query or {}, "body": body,
            "timeout_seconds": timeout}, timeout=timeout + 5)
        if response.status_code != 200:
            return False, response.text[:300]
        routed = response.json() or {}
        ok = int(routed.get("status_code", 500)) < 400
        return ok, routed.get("payload")
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=hub_route_failed service=%s path=%s error=%s", service, path, exc)
        return False, str(exc)


def register_with_hub() -> bool:
    """Register Telegram with Hub (notify endpoint, queue drain, voice uses, registry webhook)."""
    from telegram_bot.services.voice_service import capabilities as voice_capabilities
    payload = {
        "name": "telegram", "base_url": core.TELEGRAM_BASE_URL, "health_endpoint": "/health",
        "service_type": "integration", "service_version": "2.0.0", "tags": ["integration", "messaging", "chat"],
        "topology_tags": ["layer:client", "domain:ui", "status:stable"],
        "capabilities": {
            "interface": "telegram",
            "hub_events_webhook": "/api/events/registry-changed",
            "notify_endpoint": "/api/notify",          # Hermes delivers every notification here
            "chat_queue_drain": "/api/chat-queue/drain",  # Chronos calls it when the assistant is back
            **voice_capabilities(),
        },
    }
    try:
        response = requests.post(f"{core.HUB_API_URL}/registry/register", json=payload, timeout=6)
        if response.status_code == 200:
            return True
        logger.warning("event=hub_registration_non_success status=%s", response.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("event=hub_registration_failed error=%s", exc)
    return False
