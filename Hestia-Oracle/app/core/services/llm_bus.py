"""LLM bus — one queue for the calls to the LOCAL models (dossier ``docs/work/2026-11-16-bus-llm``).

The owner's PC serves one model call at a time. Without a queue every caller (chat, classifier, Athena, recaps,
module jobs) hits Ollama at once and Ollama serves them in arrival order, so a background job can make the owner's
chat wait. The bus sits in Oracle, the only one that calls models:

- **what waits**: one model call of a local step (``llm_providers.is_local``), not a whole turn. Between two steps
  of a long job a chat call can pass ahead. Cloud steps never wait (no GPU of ours); embeddings never wait
  (tiny, a different model, and memory search inside a chat turn must not queue behind a long generation).
- **workers**: setting ``oracle.bus.locali_insieme`` (default 1) = how many local calls run together. Raise it the
  day the machine serves more (Ollama ``OLLAMA_NUM_PARALLEL``, llama-server ``--parallel``). Live, no restart.
- **priority**: ``chat`` (a turn the owner started: written, spoken, a document he sent) before ``sottofondo``
  (everything else: routines, Athena, recaps, module jobs, Forge). Same priority = arrival order.
  A module call (``/api/llm/generate``) made while an owner turn is waiting for a tool is promoted to ``chat``:
  it is very likely that tool's own work (``owner_waiting``).
- **re-entrant**: a thread that already holds a worker never waits again (no deadlock with one worker).

Priority travels in a context variable: endpoints set it (``priority``), streams re-bind it around every
``next()`` (``bind``), new threads start as ``sottofondo``. Logs: ``event=llm_bus_wait`` when a call waited.
"""
from __future__ import annotations

import contextlib
import contextvars
import itertools
import logging
import threading
import time
from typing import Iterator

logger = logging.getLogger("hestia_oracle.llm_bus")

WORKERS_KEY = "oracle.bus.locali_insieme"
CHAT = "chat"
BACKGROUND = "sottofondo"
_RANK = {CHAT: 0, BACKGROUND: 1}
_LOG_WAIT_MS = 500

_priority: contextvars.ContextVar[str] = contextvars.ContextVar("llm_bus_priority", default=BACKGROUND)
_cond = threading.Condition()
_seq = itertools.count()
_waiting: list[tuple[int, int]] = []     # (rank, seq) of the calls in line
_running = 0
_owner_waiting = 0                        # owner turns now waiting for a tool
_held = threading.local()                 # depth of the worker held by this thread


def workers() -> int:
    """Local calls that may run together (setting, live; never below 1)."""
    try:
        from core.services import oracle_settings
        return max(1, oracle_settings.get_int(WORKERS_KEY, 1))
    except Exception:
        return 1


def current() -> str:
    return _priority.get()


@contextlib.contextmanager
def priority(level: str):
    """Run a block with *level* (``chat`` / ``sottofondo``)."""
    token = _priority.set(level if level in _RANK else BACKGROUND)
    try:
        yield
    finally:
        _priority.reset(token)


def bind(stream: Iterator, level: str) -> Iterator:
    """Re-bind *level* around every ``next()`` of a stream: the web server may resume it from another context."""
    while True:
        token = _priority.set(level if level in _RANK else BACKGROUND)
        try:
            item = next(stream)
        except StopIteration:
            return
        finally:
            _priority.reset(token)
        yield item


def for_origin(origin: dict | None) -> str:
    """``chat`` for a request the owner started (``hestia_common.origin`` level ``utente``), else ``sottofondo``."""
    return CHAT if (origin or {}).get("level") == "utente" else BACKGROUND


@contextlib.contextmanager
def owner_waiting():
    """Mark an owner turn as waiting for a tool (module calls made meanwhile are promoted). No-op otherwise."""
    if _priority.get() != CHAT:
        yield
        return
    global _owner_waiting
    with _cond:
        _owner_waiting += 1
    try:
        yield
    finally:
        with _cond:
            _owner_waiting -= 1


def module_priority(origin: dict | None) -> str:
    """Priority of a module's ``/api/llm/generate`` call: the origin's, promoted while the owner waits for a tool."""
    if for_origin(origin) == CHAT:
        return CHAT
    with _cond:
        return CHAT if _owner_waiting > 0 else BACKGROUND


def _is_local(provider: str) -> bool:
    try:
        from core.services import llm_providers
        return llm_providers.is_local(provider)
    except Exception:
        return False


@contextlib.contextmanager
def slot(provider: str, use_case: str = "", mark: bool = True):
    """Hold one local worker for one model call; cloud providers pass straight through.

    *mark*: remember on this thread that it holds a worker, so a nested call on the same thread does not wait for
    itself. Streams pass ``False``: a generator is resumed from other threads and never nests a model call."""
    if getattr(_held, "depth", 0) or not _is_local(provider):
        yield
        return
    global _running
    level = _priority.get()
    ticket = (_RANK.get(level, 1), next(_seq))
    started = time.monotonic()
    with _cond:
        _waiting.append(ticket)
        try:
            while _running >= workers() or min(_waiting) != ticket:
                _cond.wait(timeout=5.0)    # wake now and then: the worker setting is live
        finally:
            _waiting.remove(ticket)
            _cond.notify_all()
        _running += 1
        ahead = len(_waiting)
    waited = int((time.monotonic() - started) * 1000)
    if waited >= _LOG_WAIT_MS:
        logger.info("event=llm_bus_wait priority=%s use_case=%s provider=%s waited_ms=%d still_waiting=%d",
                    level, use_case, provider, waited, ahead)
    if mark:
        _held.depth = 1
    try:
        yield
    finally:
        if mark:
            _held.depth = 0
        with _cond:
            _running -= 1
            _cond.notify_all()


def status() -> dict:
    """Snapshot for logs and tests: workers, running, waiting per priority."""
    with _cond:
        waiting = {CHAT: 0, BACKGROUND: 0}
        for rank, _ in _waiting:
            waiting[CHAT if rank == 0 else BACKGROUND] += 1
        return {"workers": workers(), "running": _running, "waiting": waiting, "owner_waiting": _owner_waiting}
