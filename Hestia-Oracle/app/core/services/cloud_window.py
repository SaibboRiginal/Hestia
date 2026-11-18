"""Context window of CLOUD models, read from the service itself (dossier docs/work/2026-11-17-output-compatti v1.1).

The owner never sets a window in Hestia: it is read from the provider for every model (local ones by
``core.services.local_window``). Cloud services that declare it in their models API:

- **Gemini**: ``GET {url}/v1beta/models/{model}?key=…`` → ``inputTokenLimit``.
- **OpenAI-compatible cloud services**: ``GET {url}/models`` (Bearer key) → the row of the model:
  ``context_length`` (OpenRouter), ``context_window`` (Groq), ``max_model_len`` (vLLM-based hosts),
  ``max_context_length``.

A service that does not say (Claude through its CLI, Anthropic, DeepSeek) gives 0: the caller uses the provider
type's usual value (``CONTEXT_WINDOW``). Reads happen in the background and are cached for a day, so a call never
waits for them; the first call before a read uses the usual value.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

logger = logging.getLogger("hestia_oracle.cloud_window")

_TTL = 24 * 3600     # a model's window does not change often
_RETRY = 600         # a failed read is tried again after this long
_TIMEOUT = 5.0
_FIELDS = ("context_length", "context_window", "max_model_len", "max_context_length", "inputTokenLimit")

_lock = threading.Lock()
_found: dict[tuple[str, str], int] = {}       # (provider, model) → window read from the service
_read_at: dict[tuple[str, str], float] = {}   # (provider, model) → last read (ok or failed)
_running: set[tuple[str, str]] = set()


def reset() -> None:
    """Forget everything read so far (tests)."""
    with _lock:
        _found.clear(), _read_at.clear(), _running.clear()


def _key(provider: str, model: str) -> tuple[str, str]:
    return str(provider or "").strip().lower(), str(model or "").strip().lower()


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _from_row(row: dict) -> int:
    for name in _FIELDS:
        found = _int(row.get(name))
        if found:
            return found
    return _int((row.get("top_provider") or {}).get("context_length"))   # OpenRouter's nested field


def read(provider: str, model: str) -> int:
    """Ask the service now (blocking, ≤ 5 s). 0 = it does not declare the window or does not answer."""
    from core.services import llm_providers
    ptype = llm_providers.type_of(provider)
    base = llm_providers.url(provider).rstrip("/")
    key = llm_providers.api_key(provider)
    name = str(model or "").strip()
    if not base or not name:
        return 0
    try:
        if ptype == "gemini":
            if not key:
                return 0
            resp = requests.get(f"{base}/v1beta/models/{name.removeprefix('models/')}", params={"key": key},
                                timeout=_TIMEOUT)
            resp.raise_for_status()
            return _from_row(resp.json() or {})
        if ptype == "openai" and not llm_providers.is_local(provider):
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            resp = requests.get(f"{base}/models", headers=headers, timeout=_TIMEOUT)
            resp.raise_for_status()
            for row in (resp.json() or {}).get("data") or []:
                if str(row.get("id") or "").strip().lower() == name.lower():
                    return _from_row(row)
    except Exception as exc:
        logger.debug("event=cloud_window_unavailable provider=%s model=%s error=%s", provider, name, str(exc)[:160])
    return 0


def _refresh(k: tuple[str, str], provider: str, model: str) -> None:
    found = read(provider, model)
    with _lock:
        _running.discard(k)
        _read_at[k] = time.monotonic()
        if found and _found.get(k) != found:
            logger.info("event=cloud_window_read provider=%s model=%s context=%d", k[0], k[1], found)
        if found:
            _found[k] = found


def window(provider: str, model: str) -> int:
    """Window the service declared for *model* (0 = not known yet, or it does not say). Never blocks: a missing or
    old value is read in the background."""
    k = _key(provider, model)
    if not k[0] or not k[1]:
        return 0
    now = time.monotonic()
    with _lock:
        cached = _found.get(k, 0)
        age = now - _read_at.get(k, float("-inf"))
        due = k not in _running and age >= (_TTL if cached else _RETRY)
        if due:
            _running.add(k)
    if due:
        threading.Thread(target=_refresh, args=(k, provider, model), daemon=True, name="cloud-window").start()
    return cached
