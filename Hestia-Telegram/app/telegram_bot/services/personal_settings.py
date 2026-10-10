"""Personal chat settings shared by every client (Themis, owner Oracle).

Tone and personal instructions shape Oracle's answers, so they live in Themis as
``oracle.chat.tone`` / ``oracle.chat.instructions`` (scope user) and Oracle applies them
itself. Telegram reads and writes its own layer (scope ``client``/``telegram``): the
/settings menu keeps working, the value is the same one the WebUI shows.
Presentation options (reasoning display, notices, streaming…) stay local to Telegram.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import quote

import requests

logger = logging.getLogger("hestia_telegram.personal_settings")

HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
CLIENT = "telegram"
KEYS = {"tone": "oracle.chat.tone", "custom_prompt": "oracle.chat.instructions"}
_TTL = 20.0
_cache: dict[str, tuple[float, Any]] = {}


def _themis(method: str, path: str, *, query: dict | None = None, body: Any = None, timeout: float = 4) -> tuple[int, Any]:
    resp = requests.post(f"{HUB_API_URL}/route/themis/{path.lstrip('/')}", json={
        "method": method, "headers": {}, "query": query or {}, "body": body, "timeout_seconds": timeout},
        timeout=timeout + 3)
    resp.raise_for_status()
    routed = resp.json() or {}
    return int(routed.get("status_code", 500)), routed.get("payload")


def overlay(local: dict[str, Any]) -> dict[str, Any]:
    """Local Telegram settings + the shared personal values (Themis wins). Themis down → local."""
    out = dict(local or {})
    for name, key in KEYS.items():
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < _TTL:
            out[name] = hit[1]
            continue
        try:
            status, payload = _themis("GET", f"api/settings/key/{quote(key, safe='')}", query={"client": CLIENT})
            if status < 400 and isinstance(payload, dict):
                _cache[key] = (time.monotonic(), payload.get("value"))
                out[name] = payload.get("value")
        except Exception as exc:
            logger.warning("[🔄] event=personal_settings_read_failed key=%s error=%s fallback=local", key, exc)
    return out


def set_value(name: str, value: str) -> bool:
    """User change from the /settings menu → Themis (scope client/telegram)."""
    key = KEYS[name]
    _cache.pop(key, None)
    try:
        if name == "custom_prompt" and not value:
            status, _ = _themis("DELETE", f"api/settings/key/{quote(key, safe='')}",
                                query={"scope": "client", "scope_id": CLIENT, "actor": CLIENT})
        else:
            status, _ = _themis("PUT", f"api/settings/key/{quote(key, safe='')}", body={
                "value": value, "scope": "client", "scope_id": CLIENT, "actor": CLIENT})
    except Exception as exc:
        logger.warning("[🔄] event=personal_settings_write_failed key=%s error=%s", key, exc)
        return False
    if status >= 400:
        logger.warning("event=personal_settings_write_rejected key=%s status=%s", key, status)
        return False
    return True


def reset() -> None:
    """/settings reset: drop Telegram's own layer (profile defaults apply again)."""
    for key in KEYS.values():
        _cache.pop(key, None)
        try:
            _themis("DELETE", f"api/settings/key/{quote(key, safe='')}",
                    query={"scope": "client", "scope_id": CLIENT, "actor": CLIENT})
        except Exception as exc:
            logger.warning("[🔄] event=personal_settings_reset_failed key=%s error=%s", key, exc)
