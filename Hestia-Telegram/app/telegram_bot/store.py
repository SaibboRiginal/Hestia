"""Small persisted state of the Telegram client (``data/telegram_ui.json``), so buttons and half-filled actions
survive a restart (docs/work/2026-10-23-telegram-da-zero §5.8).

- ``sid(value)``: a stable 6-char id for anything a button must carry (tool names, notification ids…): callback data
  never gets cut at 64 bytes and the same value always gives the same id.
- ``flow`` per chat: the action being filled (tool, values, step), with a TTL.
- ``card`` per chat: the live navigation message (the previous one is collapsed when a new one opens).
- ``usage``: how often each action is run from Telegram (Aree shows the most used).
- ``pending``: questions and approvals waiting for a tap, by token.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("hestia_telegram.store")

PATH = os.getenv("TELEGRAM_UI_STATE_FILE", "data/telegram_ui.json")
FLOW_TTL = 24 * 3600
ID_TTL = 30 * 24 * 3600

_lock = threading.RLock()
_state: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _state
    if _state is None:
        try:
            with open(PATH, encoding="utf-8") as fh:
                _state = json.load(fh)
        except (OSError, ValueError):
            _state = {}
        for key in ("ids", "flows", "cards", "usage", "pending"):
            _state.setdefault(key, {})
    return _state


def _save() -> None:
    try:
        os.makedirs(os.path.dirname(PATH) or ".", exist_ok=True)
        tmp = f"{PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_state, fh, ensure_ascii=False)
        os.replace(tmp, PATH)
    except OSError as exc:
        logger.warning("[🔄] event=ui_state_save_failed error=%s", exc)


def reset_for_tests(path: str | None = None) -> None:
    global _state, PATH
    with _lock:
        _state = None
        if path:
            PATH = path


# ── short ids ────────────────────────────────────────────────────────────────

def sid(value: str) -> str:
    """Stable short id of ``value`` (remembered so it can be resolved back)."""
    raw = str(value)
    short = base64.b32encode(hashlib.sha1(raw.encode()).digest()).decode()[:6].lower()
    with _lock:
        st = _load()
        known = st["ids"].get(short)
        if not known or known[0] != raw or time.time() - known[1] > 86400:
            st["ids"][short] = [raw, time.time()]
            _prune(st)
            _save()
    return short


def resolve(short: str) -> str | None:
    with _lock:
        hit = _load()["ids"].get(str(short))
    return hit[0] if hit else None


def _prune(st: dict) -> None:
    now = time.time()
    for k in [k for k, v in st["ids"].items() if now - float(v[1]) > ID_TTL]:
        st["ids"].pop(k, None)
    for k in [k for k, v in st["flows"].items() if now - float(v.get("at", 0)) > FLOW_TTL]:
        st["flows"].pop(k, None)
    for k in [k for k, v in st["pending"].items() if now - float(v.get("at", 0)) > ID_TTL]:
        st["pending"].pop(k, None)


# ── flows ────────────────────────────────────────────────────────────────────

def get_flow(chat_id) -> dict | None:
    with _lock:
        flow = _load()["flows"].get(str(chat_id))
        if flow and time.time() - float(flow.get("at", 0)) > FLOW_TTL:
            _load()["flows"].pop(str(chat_id), None)
            _save()
            return None
        return dict(flow) if flow else None


def set_flow(chat_id, flow: dict) -> None:
    with _lock:
        _load()["flows"][str(chat_id)] = {**flow, "at": time.time()}
        _save()


def clear_flow(chat_id) -> dict | None:
    with _lock:
        flow = _load()["flows"].pop(str(chat_id), None)
        _save()
        return flow


# ── pending answers (assistant questions, approvals) by token ────────────────

def put_pending(token: str, entry: dict) -> None:
    with _lock:
        _load()["pending"][str(token)] = {**entry, "at": time.time()}
        _save()


def get_pending(token: str) -> dict | None:
    with _lock:
        hit = _load()["pending"].get(str(token))
        return dict(hit) if hit else None


def pop_pending(token: str) -> dict | None:
    with _lock:
        hit = _load()["pending"].pop(str(token), None)
        _save()
        return hit


# ── live navigation card ─────────────────────────────────────────────────────

def get_card(chat_id) -> dict | None:
    with _lock:
        hit = _load()["cards"].get(str(chat_id))
        return dict(hit) if hit else None


def set_card(chat_id, message_id: int) -> None:
    with _lock:
        _load()["cards"][str(chat_id)] = {"message_id": int(message_id), "at": time.time()}
        _save()


def drop_card(chat_id) -> None:
    with _lock:
        _load()["cards"].pop(str(chat_id), None)
        _save()


# ── usage ────────────────────────────────────────────────────────────────────

def count_use(name: str) -> None:
    with _lock:
        usage = _load()["usage"]
        usage[name] = int(usage.get(name, 0)) + 1
        _save()


def most_used(limit: int = 3, among: set[str] | None = None) -> list[str]:
    with _lock:
        usage = dict(_load()["usage"])
    names = [n for n, _ in sorted(usage.items(), key=lambda kv: -kv[1]) if among is None or n in among]
    return names[:limit]
