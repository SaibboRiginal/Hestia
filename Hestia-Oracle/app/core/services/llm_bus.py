"""LLM bus — one queue for the calls to the LOCAL models (dossier ``docs/work/2026-11-16-bus-llm``).

The owner's PC serves one model call at a time. Without a queue every caller (chat, classifier, Athena, recaps,
module jobs) hits Ollama at once and Ollama serves them in arrival order, so a background job can make the owner's
chat wait. The bus sits in Oracle, the only one that calls models:

- **what waits**: one model call of a local step (``llm_providers.is_local``), not a whole turn. Between two steps
  of a long job a chat call can pass ahead. Cloud steps never wait (no GPU of ours); embeddings never wait
  (tiny, a different model, and memory search inside a chat turn must not queue behind a long generation).
- **workers**: setting ``oracle.bus.local_workers`` (default 1) = how many local calls run together. Raise it the
  day the machine serves more (Ollama ``OLLAMA_NUM_PARALLEL``, llama-server ``--parallel``). Live, no restart.
- **priority**: ``chat`` (a turn the owner started: written, spoken, a document he sent) before ``background``
  (everything else: routines, Athena, recaps, module jobs, Forge). Same priority = arrival order.
  A module call (``/api/llm/generate``) made while an owner turn is waiting for a tool is promoted to ``chat``:
  it is very likely that tool's own work (``owner_waiting``).
- **re-entrant**: a thread that already holds a worker never waits again (no deadlock with one worker).
- **deadline** (dossier ``2026-11-18-real-test-problems`` A): a call carries its caller's deadline (Hub header
  ``X-Hestia-Deadline``). If it is still in line when the caller has given up, it never runs (``Expired``): no answer
  nobody reads, no pile of abandoned calls.
- **the owner goes first, even over a running call**: when an owner turn finds every worker busy with background
  work, the newest background call is asked to stop (``Preempted``, its connection to the model is closed so the GPU
  is free); the chain puts it back in line and it runs again after the owner. Providers that cannot be interrupted
  simply finish (``cancel_requested`` is only read by those that can, today Ollama).

Priority travels in a context variable: endpoints set it (``priority``), streams re-bind it around every
``next()`` (``bind``), new threads start as ``background``. Logs: ``event=llm_bus_wait`` when a call waited.
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

WORKERS_KEY = "oracle.bus.local_workers"
CHAT = "chat"
BACKGROUND = "background"
_RANK = {CHAT: 0, BACKGROUND: 1}
_LOG_WAIT_MS = 500

_priority: contextvars.ContextVar[str] = contextvars.ContextVar("llm_bus_priority", default=BACKGROUND)
_cond = threading.Condition()
_seq = itertools.count()
_waiting: list[tuple[int, int]] = []     # (rank, seq) of the calls in line
_running = 0
_owner_waiting = 0                        # owner turns now waiting for a tool
_held = threading.local()                 # depth of the worker held by this thread + its stop request
_running_calls: dict[int, dict] = {}      # seq → {"rank", "cancel": Event} of the calls holding a worker
_deadline: contextvars.ContextVar[float] = contextvars.ContextVar("llm_bus_deadline", default=0.0)
DEADLINE_HEADER = "x-hestia-deadline"
_DEADLINE_MARGIN_S = 1.0                  # a call that could only start in the last second is not worth starting


class Expired(Exception):
    """The caller gave up before the call could run (its deadline passed while in line)."""


class Preempted(Exception):
    """The owner's turn took the worker: the call stopped and goes back in line."""


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
    """Run a block with *level* (``chat`` / ``background``)."""
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


@contextlib.contextmanager
def deadline(at: float | None):
    """Run a block whose model calls must start before *at* (epoch seconds; 0/None = no deadline)."""
    token = _deadline.set(float(at or 0.0))
    try:
        yield
    finally:
        _deadline.reset(token)


def deadline_from_headers(headers: dict | None) -> float:
    """The caller's deadline from the Hub header (``X-Hestia-Deadline``, epoch seconds), else 0."""
    for key, value in (headers or {}).items():
        if str(key).lower() == DEADLINE_HEADER:
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def cancel_requested() -> bool:
    """True when the call this thread runs was asked to stop for the owner (providers that can, check it)."""
    ev = getattr(_held, "cancel", None)
    return bool(ev is not None and ev.is_set())


def check_cancel() -> None:
    """Raise ``Preempted`` when the call this thread runs was asked to stop."""
    if cancel_requested():
        raise Preempted("the owner's turn needs the model")


def _preempt_for_owner() -> None:
    """Under ``_cond``: every worker busy → ask the newest background call to stop (it goes back in line)."""
    if _running < workers():
        return
    background = [(seq, c) for seq, c in _running_calls.items() if c["rank"] > 0 and not c["cancel"].is_set()]
    if not background:
        return
    seq, call = max(background, key=lambda x: x[0])
    call["cancel"].set()
    logger.info("[🔄] event=llm_bus_preempt use_case=%s provider=%s reason=owner_turn",
                call.get("use_case", ""), call.get("provider", ""))


def for_origin(origin: dict | None) -> str:
    """``chat`` for a request the owner started (``hestia_common.origin`` level ``user``), else ``background``."""
    return CHAT if (origin or {}).get("level") == "user" else BACKGROUND


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
    itself. Streams pass ``False``: a generator is resumed from other threads and never nests a model call.
    Raises ``Expired`` when the caller's deadline passes while the call is in line."""
    if getattr(_held, "depth", 0) or not _is_local(provider):
        yield
        return
    global _running
    level = _priority.get()
    rank = _RANK.get(level, 1)
    ticket = (rank, next(_seq))
    until = _deadline.get()
    started = time.monotonic()
    cancel = threading.Event()
    with _cond:
        _waiting.append(ticket)
        try:
            preempted = False
            while _running >= workers() or min(_waiting) != ticket:
                if rank == 0 and not preempted:
                    _preempt_for_owner()
                    preempted = True
                left = (until - _DEADLINE_MARGIN_S - time.time()) if until else 5.0
                if until and left <= 0:
                    logger.warning("[🔄] event=llm_bus_expired priority=%s use_case=%s provider=%s waited_ms=%d",
                                   level, use_case, provider, int((time.monotonic() - started) * 1000))
                    raise Expired(f"the caller stopped waiting before {use_case or 'the call'} could run")
                _cond.wait(timeout=max(0.05, min(5.0, left)))    # wake now and then: the worker setting is live
        finally:
            _waiting.remove(ticket)
            _cond.notify_all()
        _running += 1
        _running_calls[ticket[1]] = {"rank": rank, "cancel": cancel, "use_case": use_case, "provider": provider}
        ahead = len(_waiting)
    waited = int((time.monotonic() - started) * 1000)
    if waited >= _LOG_WAIT_MS:
        logger.info("event=llm_bus_wait priority=%s use_case=%s provider=%s waited_ms=%d still_waiting=%d",
                    level, use_case, provider, waited, ahead)
    if mark:
        _held.depth = 1
        _held.cancel = cancel
    try:
        yield
    finally:
        if mark:
            _held.depth = 0
            _held.cancel = None
        with _cond:
            _running -= 1
            _running_calls.pop(ticket[1], None)
            _cond.notify_all()


def busy_with_background() -> bool:
    """Every worker is busy and none with the owner: an owner turn would wait (status line for the clients)."""
    with _cond:
        return _running >= workers() and not any(c["rank"] == 0 for c in _running_calls.values())


def status() -> dict:
    """Snapshot for logs and tests: workers, running, waiting per priority."""
    with _cond:
        waiting = {CHAT: 0, BACKGROUND: 0}
        for rank, _ in _waiting:
            waiting[CHAT if rank == 0 else BACKGROUND] += 1
        return {"workers": workers(), "running": _running, "waiting": waiting, "owner_waiting": _owner_waiting}
