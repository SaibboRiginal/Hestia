from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

TASK_STATE_QUEUED = "queued"
TASK_STATE_RUNNING = "running"
TASK_STATE_SUCCEEDED = "succeeded"
TASK_STATE_FAILED = "failed"
TASK_STATE_CANCELED = "canceled"

_ALLOWED_STATES = {
    TASK_STATE_QUEUED,
    TASK_STATE_RUNNING,
    TASK_STATE_SUCCEEDED,
    TASK_STATE_FAILED,
    TASK_STATE_CANCELED,
}
_TERMINAL_STATES = {
    TASK_STATE_SUCCEEDED,
    TASK_STATE_FAILED,
    TASK_STATE_CANCELED,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_progress(progress: float | int | None, fallback: float = 0.0) -> float:
    if progress is None:
        return max(0.0, min(1.0, float(fallback)))
    try:
        value = float(progress)
    except Exception:
        return max(0.0, min(1.0, float(fallback)))
    return max(0.0, min(1.0, value))


@dataclass
class TaskRecord:
    task_id: str
    task_type: str
    lifecycle_state: str = TASK_STATE_QUEUED
    progress: float = 0.0
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "lifecycle_state": self.lifecycle_state,
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "metadata": dict(self.metadata or {}),
            "result": dict(self.result or {}) if self.result is not None else None,
            "error": dict(self.error or {}) if self.error is not None else None,
        }


class TaskLifecycleStore:
    def __init__(self, max_tasks: int = 500) -> None:
        self._max_tasks = max(50, int(max_tasks))
        self._lock = Lock()
        self._records: dict[str, TaskRecord] = {}
        self._order: list[str] = []

    def create_task(
        self,
        task_type: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        progress: float | int | None = 0.0,
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        task_id = str(uuid4())
        record = TaskRecord(
            task_id=task_id,
            task_type=str(task_type or "task"),
            lifecycle_state=TASK_STATE_QUEUED,
            progress=_normalize_progress(progress, fallback=0.0),
            created_at=now,
            updated_at=now,
            session_id=str(session_id).strip() if session_id else None,
            trace_id=str(trace_id).strip() if trace_id else None,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._records[task_id] = record
            self._order.append(task_id)
            self._evict_if_needed_locked()
            return record.as_dict()

    def mark_running(
        self,
        task_id: str,
        progress: float | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self._transition(
            task_id=task_id,
            lifecycle_state=TASK_STATE_RUNNING,
            progress=progress,
            metadata=metadata,
        )

    def mark_succeeded(
        self,
        task_id: str,
        progress: float | int | None = 1.0,
        result: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self._transition(
            task_id=task_id,
            lifecycle_state=TASK_STATE_SUCCEEDED,
            progress=progress,
            result=result,
            metadata=metadata,
        )

    def mark_failed(
        self,
        task_id: str,
        error: str | dict[str, Any],
        progress: float | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = error if isinstance(error, dict) else {"message": str(error)}
        return self._transition(
            task_id=task_id,
            lifecycle_state=TASK_STATE_FAILED,
            progress=progress,
            error=payload,
            metadata=metadata,
        )

    def mark_canceled(
        self,
        task_id: str,
        reason: str | None = None,
        progress: float | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = {"reason": str(reason).strip()} if reason else {
            "reason": "canceled"}
        return self._transition(
            task_id=task_id,
            lifecycle_state=TASK_STATE_CANCELED,
            progress=progress,
            error=payload,
            metadata=metadata,
        )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(str(task_id))
            return record.as_dict() if record else None

    def list_tasks(
        self,
        limit: int = 50,
        task_type: str | None = None,
        lifecycle_state: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(int(limit), self._max_tasks))
        filter_type = str(task_type).strip() if task_type else ""
        filter_state = str(lifecycle_state).strip() if lifecycle_state else ""

        with self._lock:
            rows: list[dict[str, Any]] = []
            for task_id in reversed(self._order):
                record = self._records.get(task_id)
                if not record:
                    continue
                if filter_type and record.task_type != filter_type:
                    continue
                if filter_state and record.lifecycle_state != filter_state:
                    continue
                rows.append(record.as_dict())
                if len(rows) >= normalized_limit:
                    break
            return rows

    def _transition(
        self,
        task_id: str,
        lifecycle_state: str,
        progress: float | int | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if lifecycle_state not in _ALLOWED_STATES:
            raise ValueError(f"unsupported lifecycle state: {lifecycle_state}")

        with self._lock:
            record = self._records.get(str(task_id))
            if not record:
                return None

            now = _utc_now_iso()
            record.lifecycle_state = lifecycle_state
            record.updated_at = now

            if progress is not None:
                record.progress = _normalize_progress(
                    progress, fallback=record.progress)

            if lifecycle_state == TASK_STATE_RUNNING and not record.started_at:
                record.started_at = now

            if lifecycle_state in _TERMINAL_STATES:
                if not record.started_at:
                    record.started_at = now
                record.finished_at = now
                if progress is None:
                    record.progress = 1.0 if lifecycle_state == TASK_STATE_SUCCEEDED else record.progress

            if metadata:
                record.metadata.update(metadata)
            if result is not None:
                record.result = dict(result)
                record.error = None
            if error is not None:
                record.error = dict(error)

            return record.as_dict()

    def _evict_if_needed_locked(self) -> None:
        while len(self._order) > self._max_tasks:
            oldest = self._order.pop(0)
            self._records.pop(oldest, None)
