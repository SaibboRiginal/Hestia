"""Live turns — a chat turn runs on its own, whoever watches it (dossier ``docs/work/2026-11-27-chat-turn-survives``).

Before: the turn was the HTTP response. The owner left the page (phone in the pocket, tab closed, reload), the client
dropped the connection, the Hub closed the upstream and the turn stopped half way; history was saved only at the end,
so both his message and the answer were gone.

Now:

- ``start`` runs the turn's stream in its own thread and keeps every NDJSON line of it in memory; the HTTP response
  only *follows* it (``follow``). A reader that leaves never stops the turn: the answer is finished and saved.
- ``follow`` replays from an offset (0 = the whole turn: a client that comes back rebuilds the thinking steps and
  the text) and sends a ``heartbeat`` line when the turn is silent (a local model waiting in line), so no proxy or
  client read timeout cuts the connection. Clients ignore unknown frame types.
- ``stop`` is the only way to stop a turn («Stop» in the clients); it acts at the next frame of the turn.
- A finished turn stays readable for ``GRACE_S`` (a client that comes back right at the end still gets the final).

Exposed by ``GET /api/chat/live``, ``GET /api/chat/live/stream`` and ``POST /api/chat/stop`` (swagger).
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
import uuid
from typing import Iterator

logger = logging.getLogger("hestia_oracle.live_turns")

HEARTBEAT_S = 15.0          # silence after which a follower gets a heartbeat line
GRACE_S = 120.0             # a finished turn stays readable this long
MAX_EVENTS = 50_000         # lines kept per turn (a runaway stream never fills the memory)
HEARTBEAT_LINE = json.dumps({"type": "heartbeat"}) + "\n"


class Turn:
    """One running (or just finished) chat turn and every line it emitted."""

    def __init__(self, session_id: str, user_message: str = "", client: str = "", kind: str = "chat") -> None:
        self.id = uuid.uuid4().hex[:12]
        self.session_id = session_id
        self.user_message = user_message
        self.client = client
        self.kind = kind
        self.events: list[str] = []
        self.text = ""                 # the answer so far (token frames; the final replaces it)
        self.done = False
        self.stopped = False
        self.started_at = time.time()
        self.ended_at = 0.0
        self._stop = threading.Event()
        self._cond = threading.Condition()

    def push(self, line: str) -> None:
        with self._cond:
            if len(self.events) < MAX_EVENTS:
                self.events.append(line)
            self._track(line)
            self._cond.notify_all()

    def _track(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except (TypeError, ValueError):
            return
        if not isinstance(frame, dict):
            return
        if frame.get("type") == "token":
            self.text += str(frame.get("text") or "")
        elif frame.get("type") == "final":
            self.text = str(frame.get("reply") or self.text)

    def finish(self) -> None:
        with self._cond:
            self.done = True
            self.ended_at = time.time()
            self._cond.notify_all()

    def request_stop(self) -> bool:
        if self.done:
            return False
        self.stopped = True
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        return True

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def snapshot(self) -> dict:
        with self._cond:
            return {"turn_id": self.id, "session_id": self.session_id, "running": not self.done,
                    "stopped": self.stopped, "kind": self.kind, "client": self.client,
                    "user_message": self.user_message, "text": self.text, "events": len(self.events),
                    "started_at": self.started_at, "ended_at": self.ended_at or None}


_lock = threading.Lock()
_by_session: dict[str, list[Turn]] = {}
_this_turn: contextvars.ContextVar["Turn | None"] = contextvars.ContextVar("live_turn", default=None)
STEP_TYPES = ("thinking", "agent")
MAX_STEPS = 200             # reasoning frames saved with one answer
MAX_STEP_CHARS = 4000       # text kept per frame


def _prune(now: float) -> None:
    """Under ``_lock``: drop turns finished more than ``GRACE_S`` ago."""
    for sid in list(_by_session):
        kept = [t for t in _by_session[sid] if not t.done or now - t.ended_at < GRACE_S]
        if kept:
            _by_session[sid] = kept
        else:
            del _by_session[sid]


def _run(turn: Turn, stream: Iterator[str]) -> None:
    _this_turn.set(turn)
    logger.info("event=live_turn_start turn_id=%s session_id=%s kind=%s client=%s",
                turn.id, turn.session_id, turn.kind, turn.client)
    try:
        for line in stream:
            if line:
                turn.push(line if isinstance(line, str) else line.decode("utf-8", "replace"))
            if turn.stop_requested:
                logger.info("event=live_turn_stopped turn_id=%s session_id=%s", turn.id, turn.session_id)
                break
    except Exception as exc:  # the turn's own errors are already frames; this is a crash of the stream itself
        logger.exception("[🔄] event=live_turn_failed turn_id=%s session_id=%s error=%s fallback=error_frame",
                         turn.id, turn.session_id, exc)
        turn.push(json.dumps({"type": "error", "content": str(exc)[:300]}) + "\n")
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 — closing a stopped generator never blocks the end of the turn
                pass
        turn.finish()
        logger.info("event=live_turn_done turn_id=%s session_id=%s lines=%d ms=%d stopped=%s", turn.id,
                    turn.session_id, len(turn.events), int((turn.ended_at - turn.started_at) * 1000), turn.stopped)


def start(session_id: str, stream: Iterator[str], *, user_message: str = "", client: str = "",
          kind: str = "chat") -> Turn:
    """Run *stream* to its end in its own thread (with the caller's context: priority, usage binding…)."""
    turn = Turn(session_id, user_message=user_message, client=client, kind=kind)
    with _lock:
        _prune(time.time())
        _by_session.setdefault(session_id, []).append(turn)
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(_run, turn, stream), name=f"live-turn-{turn.id}", daemon=True).start()
    return turn


def follow(turn: Turn, offset: int = 0, heartbeat_s: float = HEARTBEAT_S) -> Iterator[str]:
    """Every line of *turn* from *offset*, live until it ends; a heartbeat line while it is silent."""
    i = max(0, int(offset or 0))
    while True:
        with turn._cond:
            if i >= len(turn.events) and not turn.done:
                turn._cond.wait(timeout=heartbeat_s)
            batch = turn.events[i:]
            done = turn.done
        if batch:
            i += len(batch)
            yield from batch
        elif done:
            return
        else:
            yield HEARTBEAT_LINE


def current(session_id: str) -> Turn | None:
    """The newest turn of *session_id* still running, else the newest finished within the grace time."""
    with _lock:
        _prune(time.time())
        turns = _by_session.get(session_id) or []
    running = [t for t in turns if not t.done]
    return (running or turns or [None])[-1]


def get(session_id: str, turn_id: str = "") -> Turn | None:
    if not turn_id:
        return current(session_id)
    with _lock:
        return next((t for t in _by_session.get(session_id) or [] if t.id == turn_id), None)


def stop(session_id: str) -> int:
    """Stop every running turn of *session_id* («Stop» in a client). Returns how many were asked to stop."""
    with _lock:
        turns = list(_by_session.get(session_id) or [])
    n = sum(1 for t in turns if t.request_stop())
    if n:
        logger.info("event=live_turn_stop_requested session_id=%s turns=%d", session_id, n)
    return n


def steps() -> list[dict]:
    """The reasoning frames (``thinking`` / ``agent``) the turn running in this thread has sent so far: saved with
    the answer, so the reasoning comes back when the chat is opened again. Empty outside a live turn."""
    turn = _this_turn.get()
    if turn is None:
        return []
    with turn._cond:
        lines = list(turn.events)
    out: list[dict] = []
    for line in lines:
        try:
            frame = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(frame, dict) or frame.get("type") not in STEP_TYPES:
            continue
        if isinstance(frame.get("content"), str) and len(frame["content"]) > MAX_STEP_CHARS:
            frame["content"] = frame["content"][:MAX_STEP_CHARS] + "…"
        out.append(frame)
    return out[-MAX_STEPS:]


def reset() -> None:
    """Tests only."""
    with _lock:
        _by_session.clear()
