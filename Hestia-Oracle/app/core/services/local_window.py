"""Context window of the LOCAL runtimes, read from the program itself (dossier
docs/work/2026-11-12-contesto-e-scorciatoie §3.1).

The owner sets the window once, in the program that runs the model (Ollama, LM Studio, llama-server…).
Oracle reads it from there instead of imposing its own number:

- **Ollama**: ``GET /api/ps`` → ``context_length`` of the loaded model. With the setting on «automatico»
  Oracle sends no ``num_ctx``, so Ollama keeps its own. Only when Ollama's own window is smaller than
  ``FLOOR`` (a bare install: 4096) Oracle asks for ``FLOOR``, because the prompts of an assistant with tools
  never fit under it (a cut prompt loses instructions without any error).
- **OpenAI-compatible local servers**: LM Studio ``/api/v0/models`` (``loaded_context_length``),
  llama-server ``/props`` (``n_ctx``), vLLM ``/v1/models`` (``max_model_len``).

A number in the setting ``oracle.provider.ollama.num_ctx`` still wins (forced). Everything here is best
effort and cached: a runtime that does not answer never blocks or slows a call.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

logger = logging.getLogger("hestia_oracle.local_window")

FLOOR = 8192          # smallest window an assistant with tools can work in; also the fallback before the first read
_TTL = 30.0           # seconds between two reads of the same runtime
_RECHECK = 6 * 3600   # a window found too small is read again after this long (the owner may have raised it)
_TIMEOUT = 2.0

_lock = threading.Lock()
_loaded: dict[str, int] = {}        # Ollama model → context_length seen in /api/ps
_native: dict[str, int] = {}        # Ollama model → window Ollama chose by itself (seen after a call without num_ctx)
_sent: dict[str, int] = {}          # Ollama model → num_ctx Oracle sent on its last call (0 = none)
_native_at: dict[str, float] = {}   # Ollama model → when its own window was read
_last_model = ""
_read_at: dict[str, float] = {}     # runtime address → last read
_openai: dict[tuple[str, str], int] = {}   # (address, model) → window of an OpenAI-compatible local server


def _base(model: str) -> str:
    """``gemma3:latest`` and ``gemma3`` are the same model for Ollama."""
    model = str(model or "").strip().lower()
    return model[:-len(":latest")] if model.endswith(":latest") else model


def reset() -> None:
    """Forget everything read so far (tests; a changed setting re-reads by itself)."""
    global _last_model
    with _lock:
        _loaded.clear(), _native.clear(), _native_at.clear(), _sent.clear(), _read_at.clear(), _openai.clear()
        _last_model = ""


def _forced() -> int:
    from core.services import oracle_settings
    return oracle_settings.forced_num_ctx()


# ── Ollama ────────────────────────────────────────────────────────────────────────────────────────────
def ollama_num_ctx(model: str = "") -> int:
    """``num_ctx`` to send with a call to *model* (0 = send none: Ollama keeps its own window)."""
    forced = _forced()
    if forced:
        return forced
    with _lock:
        key = _base(model) or _last_model
        native = _native.get(key, 0)
        if 0 < native < FLOOR and time.monotonic() - _native_at.get(key, 0.0) >= _RECHECK:
            _native.pop(key, None)                    # one call without num_ctx: Ollama shows its window again
            native = 0
    return FLOOR if 0 < native < FLOOR else 0


def ollama_window(model: str = "") -> int:
    """Window the Ollama model really runs with (budget, compaction, gauge)."""
    forced = _forced()
    if forced:
        return forced
    with _lock:
        key = _base(model) or _last_model
        native, loaded = _native.get(key, 0), _loaded.get(key, 0)
        if not key and _loaded:                       # no call yet: any model Ollama has in memory
            loaded = max(_loaded.values())
    if native:
        return max(native, FLOOR)
    return loaded or FLOOR


def source(model: str = "") -> str:
    """Where the Ollama window comes from: ``setting`` (forced) · ``runtime`` (read) · ``floor`` (Ollama's own is
    too small, Oracle asks for the minimum) · ``default`` (not read yet)."""
    if _forced():
        return "setting"
    with _lock:
        key = _base(model) or _last_model
        native, loaded = _native.get(key, 0), _loaded.get(key, 0) or (max(_loaded.values()) if not key and _loaded else 0)
    if 0 < native < FLOOR:
        return "floor"
    return "runtime" if native or loaded else "default"


def note_call(model: str, sent: int, address: str = "") -> None:
    """After every Ollama call: remember what was sent and re-read the loaded window in the background."""
    global _last_model
    key = _base(model)
    if not key:
        return
    with _lock:
        _last_model = key
        _sent[key] = int(sent or 0)
        due = key not in _native or time.monotonic() - _read_at.get(address or "ollama", 0.0) >= _TTL
    if due:
        threading.Thread(target=refresh_ollama, args=(address,), daemon=True, name="ollama-window").start()


def refresh_ollama(address: str = "") -> dict[str, int]:
    """Read ``/api/ps`` once. A model loaded by a call that sent no ``num_ctx`` shows Ollama's own window."""
    from core.services import llm_providers
    base = (address or llm_providers.ollama_host()).split("/api/")[0].rstrip("/")
    try:
        models = (requests.get(f"{base}/api/ps", timeout=_TIMEOUT).json() or {}).get("models") or []
    except Exception as exc:
        logger.debug("event=local_window_ps_unavailable address=%s error=%s", base, exc)
        with _lock:
            _read_at[address or "ollama"] = time.monotonic()
        return {}
    seen: dict[str, int] = {}
    for m in models:
        name = _base(m.get("name") or m.get("model") or "")
        try:
            ctx = int(m.get("context_length") or 0)
        except (TypeError, ValueError):
            ctx = 0
        if name and ctx > 0:
            seen[name] = ctx
    with _lock:
        _read_at[address or "ollama"] = time.monotonic()
        _loaded.clear()
        _loaded.update(seen)
        for name, ctx in seen.items():
            if _sent.get(name, -1) == 0:
                _native_at[name] = time.monotonic()
            if _sent.get(name, -1) == 0 and _native.get(name) != ctx:
                _native[name] = ctx
                _native_at[name] = time.monotonic()
                logger.info("event=local_window_read runtime=ollama model=%s context=%d%s", name, ctx,
                            f" below_floor=true asking={FLOOR}" if ctx < FLOOR else "")
    return seen


# ── OpenAI-compatible local servers ──────────────────────────────────────────────────────────────────
def _get(url: str) -> Any:
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _probe_openai(address: str, model: str) -> int:
    root = address.rstrip("/")
    root = root[:-3].rstrip("/") if root.endswith("/v1") else root
    want = str(model or "").strip().lower()
    try:                                              # LM Studio
        rows = (_get(f"{root}/api/v0/models") or {}).get("data") or []
        for row in rows:
            if str(row.get("id") or "").lower() == want or (not want and row.get("state") == "loaded"):
                found = _int(row.get("loaded_context_length")) or _int(row.get("max_context_length"))
                if found:
                    return found
    except Exception:
        pass
    try:                                              # llama-server
        props = _get(f"{root}/props") or {}
        found = _int((props.get("default_generation_settings") or {}).get("n_ctx")) or _int(props.get("n_ctx"))
        if found:
            return found
    except Exception:
        pass
    try:                                              # vLLM and friends
        rows = (_get(f"{root}/v1/models") or {}).get("data") or []
        for row in rows:
            if not want or str(row.get("id") or "").lower() == want:
                found = _int(row.get("max_model_len")) or _int((row.get("meta") or {}).get("n_ctx_train"))
                if found:
                    return found
    except Exception:
        pass
    return 0


def openai_window(address: str, model: str = "") -> int:
    """Window of a local OpenAI-compatible server (0 = it does not say)."""
    address = str(address or "").strip()
    if not address:
        return 0
    key = (address, str(model or "").strip().lower())
    now = time.monotonic()
    with _lock:
        fresh = now - _read_at.get(f"{address}|{key[1]}", 0.0) < _TTL * 2
        cached = _openai.get(key, 0)
    if fresh:
        return cached
    found = _probe_openai(address, model)
    with _lock:
        _read_at[f"{address}|{key[1]}"] = now
        if found:
            if _openai.get(key) != found:
                logger.info("event=local_window_read runtime=openai address=%s model=%s context=%d", address, key[1], found)
            _openai[key] = found
        return _openai.get(key, 0)


# ── any provider ────────────────────────────────────────────────────────────────────────────────────
def window_of(provider: str, model: str = "") -> tuple[int, str]:
    """``(window, source)`` of a named provider: local ones are read from their program."""
    from core.services import llm_providers
    ptype = llm_providers.type_of(provider) or str(provider or "").strip().lower()
    if ptype == "ollama":
        return ollama_window(model), source(model)
    if ptype in ("openai", "llamacpp") and llm_providers.is_local(provider):
        found = openai_window(llm_providers.url(provider), model)
        if found:
            return found, "runtime"
        forced = _forced()
        return (forced, "setting") if forced else (FLOOR, "default")
    return 0, "provider"
