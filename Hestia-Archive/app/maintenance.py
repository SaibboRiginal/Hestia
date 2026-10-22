"""Data epoch and the short maintenance window of a rollback (backup SPEC §3.4).

- **Epoch**: an id that changes whenever the whole database is replaced (rollback, undo). Every module store
  answer carries it; a module whose mirror was built under another epoch drops the mirror and reloads, so it
  never writes stale rows back. Kept in a file of the backup volume: the database itself is what gets replaced.
- **Gate**: while the databases are renamed, every request except health and backup status gets 503
  (modules already retry: ``[🔄]``); requests in flight are waited for first.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

from starlette.responses import JSONResponse

BACKUP_DIR = Path(os.getenv("ARCHIVE_BACKUP_DIR", "/code/backups"))
_EPOCH_FILE = BACKUP_DIR / "epoch"
_lock = threading.Lock()
_epoch: str | None = None


def epoch() -> str:
    global _epoch
    with _lock:
        if _epoch is None:
            try:
                _epoch = _EPOCH_FILE.read_text(encoding="utf-8").strip() or None
            except OSError:
                _epoch = None
            if _epoch is None:
                _epoch = _write(uuid.uuid4().hex[:12])
        return _epoch


def new_epoch() -> str:
    global _epoch
    with _lock:
        _epoch = _write(uuid.uuid4().hex[:12])
        return _epoch


def _write(value: str) -> str:
    try:
        _EPOCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        _EPOCH_FILE.write_text(value, encoding="utf-8")
    except OSError:
        pass                              # tests / no volume: the in-memory epoch still works
    return value


class Gate:
    OPEN_PATHS = ("/health", "/api/backup/status")

    def __init__(self):
        self.closed = False
        self.inflight = 0
        self._lock = threading.Lock()

    def close(self, wait_seconds: float = 20) -> None:
        self.closed = True
        deadline = time.monotonic() + wait_seconds
        while self.inflight > 0 and time.monotonic() < deadline:
            time.sleep(0.1)

    def open(self) -> None:
        self.closed = False

    async def middleware(self, request, call_next):
        path = request.url.path
        if path in self.OPEN_PATHS:
            return await call_next(request)
        if self.closed:
            return JSONResponse({"detail": "archivio in manutenzione per pochi secondi, riprova"}, status_code=503,
                                headers={"Retry-After": "5"})
        with self._lock:
            self.inflight += 1
        try:
            return await call_next(request)
        finally:
            with self._lock:
                self.inflight -= 1


gate = Gate()
