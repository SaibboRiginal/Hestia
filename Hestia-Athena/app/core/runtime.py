from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests

from .schemas import RelevanceSignals, TriggerRequest
from .shared_imports import import_shared_symbol

TaskLifecycleStore = import_shared_symbol(
    "hestia_common.task_lifecycle", "TaskLifecycleStore"
)

logger = logging.getLogger("hestia_athena.runtime")


def _parse_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _parse_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _normalize_01(value: float) -> float:
    return max(0.0, min(1.0, value))


class AthenaRuntime:
    def __init__(self) -> None:
        self.interval_seconds = _parse_int_env(
            "ATHENA_BRIEF_INTERVAL_SECONDS", 300)
        self.emit_threshold = _parse_float_env(
            "ATHENA_RELEVANCE_THRESHOLD", 0.55)
        self.hermes_api_url = os.getenv("HERMES_API_URL", "http://hestia_hermes:19005").rstrip(
            "/"
        )
        self.hub_api_url = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip(
            "/"
        )
        self.loop_enabled = _parse_bool_env("ATHENA_LOOP_ENABLED", True)

        self.retrospective_window = _parse_int_env(
            "ATHENA_RETROSPECTIVE_WINDOW", 24)
        self.retrospective_failure_urgency_boost = _parse_float_env(
            "ATHENA_RETRO_FAILURE_URGENCY_BOOST", 0.07
        )
        self.retrospective_unresolved_urgency_boost = _parse_float_env(
            "ATHENA_RETRO_UNRESOLVED_URGENCY_BOOST", 0.04
        )
        self.retrospective_unresolved_usefulness_boost = _parse_float_env(
            "ATHENA_RETRO_UNRESOLVED_USEFULNESS_BOOST", 0.03
        )
        self.commitment_ttl_seconds = _parse_int_env(
            "ATHENA_COMMITMENT_TTL_SECONDS", 86400)

        self.oracle_hint_enabled = _parse_bool_env(
            "ATHENA_ORACLE_HINT_ENABLED", True)
        self.oracle_hint_route = os.getenv(
            "ATHENA_ORACLE_HINT_ROUTE", "api/athena/hints"
        ).lstrip("/")
        self.oracle_hint_timeout = _parse_int_env(
            "ATHENA_ORACLE_HINT_TIMEOUT_SECONDS", 8)

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ticks = 0
        self._emitted = 0
        self._last_score = 0.0
        self._last_emit_at: str | None = None
        self._last_error: str | None = None
        self._recent_outcomes: list[dict[str, Any]] = []
        self._open_commitments: dict[str, dict[str, Any]] = {}
        self._commitments_lock = threading.Lock()
        self._task_store = TaskLifecycleStore(
            max_tasks=_parse_int_env("ATHENA_TASK_STORE_MAX", 500)
        )

    def _prune_commitments_locked(self, now_ts: float | None = None) -> None:
        now = time.time() if now_ts is None else float(now_ts)
        self._open_commitments = {
            brief_id: row
            for brief_id, row in self._open_commitments.items()
            if not bool(row.get("resolved")) and float(row.get("expires_at") or 0) > now
        }

    def _register_commitment(
        self,
        brief: dict[str, Any],
        score: float,
        trace_id: str,
    ) -> None:
        now = time.time()
        row = {
            "brief_id": str(brief.get("brief_id") or uuid4()),
            "title": str(brief.get("title") or "Focus checkpoint"),
            "summary": str(brief.get("summary") or "").strip(),
            "domain": str(brief.get("domain") or "cognition"),
            "score": float(score),
            "trace_id": str(trace_id),
            "created_at": now,
            "expires_at": now + max(60, self.commitment_ttl_seconds),
            "resolved": False,
            "resolved_at": None,
            "resolution_status": None,
            "resolution_note": None,
        }
        with self._commitments_lock:
            self._prune_commitments_locked(now)
            self._open_commitments[row["brief_id"]] = row

    def list_commitments(
        self, limit: int = 100, include_resolved: bool = False
    ) -> list[dict[str, Any]]:
        with self._commitments_lock:
            self._prune_commitments_locked()
            rows = list(self._open_commitments.values())

        if not include_resolved:
            rows = [row for row in rows if not bool(row.get("resolved"))]

        rows.sort(key=lambda item: float(
            item.get("created_at") or 0), reverse=True)
        return rows[: max(1, min(int(limit), 500))]

    def resolve_commitment(
        self,
        brief_id: str,
        status: str = "resolved",
        note: str | None = None,
    ) -> dict[str, Any] | None:
        normalized = str(brief_id or "").strip()
        if not normalized:
            return None

        with self._commitments_lock:
            self._prune_commitments_locked()
            row = self._open_commitments.get(normalized)
            if not row:
                return None
            row["resolved"] = True
            row["resolved_at"] = datetime.now(timezone.utc).isoformat()
            row["resolution_status"] = str(status or "resolved")
            row["resolution_note"] = str(note or "").strip() or None
            return dict(row)

    def _record_outcome(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._recent_outcomes.append(payload)
            if len(self._recent_outcomes) > max(5, self.retrospective_window):
                self._recent_outcomes = self._recent_outcomes[
                    -max(5, self.retrospective_window):
                ]

    def _retrospective_snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = list(self._recent_outcomes[-self.retrospective_window:])

        with self._commitments_lock:
            self._prune_commitments_locked()
            unresolved = [
                row
                for row in self._open_commitments.values()
                if not bool(row.get("resolved"))
            ]

        failure_streak = 0
        for row in reversed(recent):
            if str(row.get("outcome") or "") == "failed":
                failure_streak += 1
            else:
                break

        failed_count = len(
            [row for row in recent if str(
                row.get("outcome") or "") == "failed"]
        )
        accepted_count = len(
            [row for row in recent if bool(row.get("accepted"))])

        return {
            "window": len(recent),
            "accepted_count": accepted_count,
            "failed_count": failed_count,
            "failure_streak": failure_streak,
            "unresolved_commitments": len(unresolved),
            "unresolved_commitment_ids": [
                str(row.get("brief_id")) for row in unresolved[:10]
            ],
        }

    def _apply_retrospective_to_signals(
        self,
        base_signals: RelevanceSignals,
        retrospective: dict[str, Any],
    ) -> RelevanceSignals:
        adjusted = base_signals.model_copy(deep=True)

        failure_streak = int(retrospective.get("failure_streak") or 0)
        unresolved = int(retrospective.get("unresolved_commitments") or 0)

        adjusted.urgency = _normalize_01(
            adjusted.urgency
            + (self.retrospective_failure_urgency_boost * float(failure_streak))
            + (self.retrospective_unresolved_urgency_boost * float(unresolved))
        )
        adjusted.usefulness = _normalize_01(
            adjusted.usefulness
            + (self.retrospective_unresolved_usefulness_boost * float(unresolved))
        )

        return adjusted

    def score(self, signals: RelevanceSignals) -> float:
        weighted = (
            0.30 * _normalize_01(signals.urgency)
            + 0.25 * _normalize_01(signals.usefulness)
            + 0.20 * _normalize_01(signals.novelty)
            + 0.15 * _normalize_01(signals.confidence)
            + 0.10 * (1.0 - _normalize_01(signals.interruption_cost))
        )
        return round(weighted, 4)

    def _build_brief(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "brief_id": str(uuid4()),
            "created_at": now.isoformat(),
            "title": "Focus checkpoint",
            "summary": "Consider the highest-impact next action and defer lower-value interruptions.",
            "domain": "cognition",
        }

    def _emit_event(
        self,
        brief: dict[str, Any],
        signals: RelevanceSignals,
        score: float,
        threshold: float,
        reason: str,
        retrospective: dict[str, Any],
        trace_id: str,
    ) -> None:
        payload = {
            "event_type": "athena.focus_brief",
            "domain": brief["domain"],
            "entity_id": brief["brief_id"],
            "trace_id": trace_id,
            "payload": {
                "source": "athena",
                "trace_id": trace_id,
                "brief": brief,
                "gate": {
                    "score": score,
                    "threshold": threshold,
                    "accepted": score >= threshold,
                    "signals": signals.model_dump(),
                    "reason": reason,
                },
                "retrospective": retrospective,
            },
        }

        endpoint = f"{self.hermes_api_url}/api/events/ingest"
        response = requests.post(
            endpoint,
            json=payload,
            headers={"X-Trace-Id": trace_id},
            timeout=5,
        )
        response.raise_for_status()

        with self._lock:
            self._emitted += 1
            self._last_emit_at = datetime.now(timezone.utc).isoformat()
            self._last_error = None

        logger.info(
            "event=focus_brief_emitted_brief_id_score_trace_id Focus brief emitted | brief_id=%s score=%.3f threshold=%.3f trace_id=%s",
            brief["brief_id"],
            score,
            threshold,
            trace_id,
        )

    def _publish_oracle_hint(
        self,
        brief: dict[str, Any],
        signals: RelevanceSignals,
        score: float,
        threshold: float,
        retrospective: dict[str, Any],
        trace_id: str,
    ) -> bool:
        if not self.oracle_hint_enabled:
            return False

        priority = "normal"
        if score >= max(0.85, threshold + 0.2):
            priority = "high"
        elif score >= max(0.70, threshold + 0.1):
            priority = "elevated"

        hint_payload = {
            "source": "athena",
            "hint_type": "focus_brief",
            "hint_id": str(brief.get("brief_id") or uuid4()),
            "session_id": str((brief.get("metadata") or {}).get("session_id") or "").strip()
            or None,
            "domain": str(brief.get("domain") or "cognition"),
            "domains": [str(brief.get("domain") or "cognition")],
            "priority": priority,
            "summary": str(brief.get("summary") or "").strip(),
            "brief": brief,
            "gate": {
                "score": score,
                "threshold": threshold,
                "accepted": score >= threshold,
                "signals": signals.model_dump(),
                "reason": "athena_focus_brief_advisory",
            },
            "retrospective": retrospective,
            "trace_id": trace_id,
            "ttl_seconds": max(60, self.commitment_ttl_seconds),
            "metadata": {
                "service": "athena",
                "event": "athena.focus_brief",
            },
        }

        envelope = {
            "method": "POST",
            "headers": {
                "X-Trace-Id": trace_id,
            },
            "query": {},
            "body": hint_payload,
            "timeout_seconds": self.oracle_hint_timeout,
        }
        route_url = f"{self.hub_api_url}/route/oracle/{self.oracle_hint_route}"
        try:
            response = requests.post(
                route_url,
                json=envelope,
                timeout=max(2, self.oracle_hint_timeout + 2),
            )
            if response.status_code != 200:
                logger.warning(
                    "event=athena_oracle_hint_route_failed_non200 trace_id=%s status=%s body=%s",
                    trace_id,
                    response.status_code,
                    response.text[:200],
                )
                return False

            routed = response.json() if response.content else {}
            if int((routed or {}).get("status_code", 500)) >= 400:
                logger.warning(
                    "event=athena_oracle_hint_route_failed_payload trace_id=%s status_code=%s payload=%s",
                    trace_id,
                    int((routed or {}).get("status_code", 500)),
                    str((routed or {}).get("payload"))[:200],
                )
                return False

            logger.info(
                "event=athena_oracle_hint_published trace_id=%s hint_id=%s brief_id=%s priority=%s",
                trace_id,
                hint_payload.get("hint_id"),
                brief.get("brief_id"),
                priority,
            )
            return True
        except Exception as error:
            logger.warning(
                "event=athena_oracle_hint_route_failed_exception trace_id=%s error=%s",
                trace_id,
                error,
            )
            return False

    def _run_once(self) -> None:
        run_trace_id = f"athena-{uuid4().hex[:12]}"
        retrospective = self._retrospective_snapshot()
        brief = self._build_brief()
        base_signals = RelevanceSignals()
        signals = self._apply_retrospective_to_signals(
            base_signals,
            retrospective,
        )
        score = self.score(signals)
        reason = "periodic_focus_brief_retrospective"
        task = self._task_store.create_task(
            task_type="athena.focus_brief.periodic",
            trace_id=run_trace_id,
            metadata={
                "brief_id": brief.get("brief_id"),
                "reason": reason,
                "emit_threshold": self.emit_threshold,
                "retrospective": retrospective,
                "signals_base": base_signals.model_dump(),
                "signals_effective": signals.model_dump(),
            },
        )
        task_id = str(task.get("task_id") or "")
        self._task_store.mark_running(task_id, progress=0.2)

        with self._lock:
            self._ticks += 1
            self._last_score = score

        if score < self.emit_threshold:
            self._task_store.mark_succeeded(
                task_id,
                progress=1.0,
                result={
                    "accepted": False,
                    "score": score,
                    "threshold": self.emit_threshold,
                    "reason": "relevance_gate",
                    "brief_id": brief.get("brief_id"),
                    "trace_id": run_trace_id,
                    "retrospective": retrospective,
                    "signals_base": base_signals.model_dump(),
                    "signals_effective": signals.model_dump(),
                },
            )
            self._record_outcome(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "brief_id": brief.get("brief_id"),
                    "trace_id": run_trace_id,
                    "accepted": False,
                    "outcome": "skipped",
                    "score": score,
                }
            )
            logger.info(
                "event=focus_brief_skipped_relevance_gate_trace_id Focus brief skipped by relevance gate | score=%.3f threshold=%.3f task_id=%s trace_id=%s",
                score,
                self.emit_threshold,
                task_id,
                run_trace_id,
            )
            return

        try:
            self._task_store.mark_running(
                task_id,
                progress=0.7,
                metadata={"phase": "emit"},
            )
            self._emit_event(
                brief=brief,
                signals=signals,
                score=score,
                threshold=self.emit_threshold,
                reason=reason,
                retrospective=retrospective,
                trace_id=run_trace_id,
            )
            self._publish_oracle_hint(
                brief=brief,
                signals=signals,
                score=score,
                threshold=self.emit_threshold,
                retrospective=retrospective,
                trace_id=run_trace_id,
            )
            self._register_commitment(
                brief=brief,
                score=score,
                trace_id=run_trace_id,
            )
            self._task_store.mark_succeeded(
                task_id,
                progress=1.0,
                result={
                    "accepted": True,
                    "score": score,
                    "threshold": self.emit_threshold,
                    "reason": reason,
                    "brief_id": brief.get("brief_id"),
                    "trace_id": run_trace_id,
                    "retrospective": retrospective,
                    "signals_base": base_signals.model_dump(),
                    "signals_effective": signals.model_dump(),
                },
            )
            self._record_outcome(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "brief_id": brief.get("brief_id"),
                    "trace_id": run_trace_id,
                    "accepted": True,
                    "outcome": "emitted",
                    "score": score,
                }
            )
        except Exception as error:
            with self._lock:
                self._last_error = str(error)
            self._task_store.mark_failed(
                task_id,
                error={
                    "message": str(error),
                    "reason": reason,
                    "brief_id": brief.get("brief_id"),
                    "trace_id": run_trace_id,
                },
                progress=1.0,
            )
            self._record_outcome(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "brief_id": brief.get("brief_id"),
                    "trace_id": run_trace_id,
                    "accepted": False,
                    "outcome": "failed",
                    "score": score,
                    "error": str(error),
                }
            )
            logger.warning(
                "event=hermes_emit_failed_trace_id Hermes emit failed | trace_id=%s error=%s",
                run_trace_id,
                error,
            )

    def _loop(self) -> None:
        logger.info(
            "event=athena_loop_started_interval_seconds_threshold Athena loop started | interval_seconds=%s threshold=%.3f",
            self.interval_seconds,
            self.emit_threshold,
        )
        while not self._stop_event.is_set():
            self._run_once()
            self._stop_event.wait(max(1, self.interval_seconds))

    def start(self) -> None:
        if not self.loop_enabled:
            logger.info(
                "event=athena_loop_disabled_athena_loop_enabled Athena loop disabled via ATHENA_LOOP_ENABLED=0"
            )
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="athena-focus-loop",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def status(self) -> dict[str, Any]:
        retrospective = self._retrospective_snapshot()
        with self._lock:
            return {
                "loop_enabled": self.loop_enabled,
                "interval_seconds": self.interval_seconds,
                "emit_threshold": self.emit_threshold,
                "ticks": self._ticks,
                "emitted": self._emitted,
                "last_score": self._last_score,
                "last_emit_at": self._last_emit_at,
                "last_error": self._last_error,
                "hermes_api_url": self.hermes_api_url,
                "oracle_hint_enabled": self.oracle_hint_enabled,
                "oracle_hint_route": self.oracle_hint_route,
                "retrospective": retrospective,
            }

    def trigger(self, request: TriggerRequest) -> dict[str, Any]:
        trace_id = f"athena-manual-{uuid4().hex[:10]}"
        retrospective = self._retrospective_snapshot()
        brief = {
            "brief_id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "title": request.title or "Manual focus brief",
            "summary": request.summary or "Manual Athena trigger",
            "domain": request.domain,
            "metadata": request.metadata,
        }
        score = self.score(request.signals)
        accepted = score >= self.emit_threshold
        task = self._task_store.create_task(
            task_type="athena.focus_brief.manual",
            trace_id=trace_id,
            metadata={
                "brief_id": brief.get("brief_id"),
                "emit_threshold": self.emit_threshold,
                "accepted": accepted,
                "retrospective": retrospective,
            },
        )
        task_id = str(task.get("task_id") or "")
        self._task_store.mark_running(task_id, progress=0.3)
        if accepted:
            try:
                self._task_store.mark_running(
                    task_id,
                    progress=0.7,
                    metadata={"phase": "emit"},
                )
                self._emit_event(
                    brief=brief,
                    signals=request.signals,
                    score=score,
                    threshold=self.emit_threshold,
                    reason="manual_trigger",
                    retrospective=retrospective,
                    trace_id=trace_id,
                )
                self._publish_oracle_hint(
                    brief=brief,
                    signals=request.signals,
                    score=score,
                    threshold=self.emit_threshold,
                    retrospective=retrospective,
                    trace_id=trace_id,
                )
                self._register_commitment(
                    brief=brief,
                    score=score,
                    trace_id=trace_id,
                )
                self._task_store.mark_succeeded(
                    task_id,
                    progress=1.0,
                    result={
                        "accepted": accepted,
                        "score": score,
                        "threshold": self.emit_threshold,
                        "brief_id": brief.get("brief_id"),
                        "reason": "manual_trigger",
                        "trace_id": trace_id,
                        "retrospective": retrospective,
                    },
                )
                self._record_outcome(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "brief_id": brief.get("brief_id"),
                        "trace_id": trace_id,
                        "accepted": True,
                        "outcome": "manual_emitted",
                        "score": score,
                    }
                )
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
                self._task_store.mark_failed(
                    task_id,
                    error={
                        "message": str(error),
                        "brief_id": brief.get("brief_id"),
                        "reason": "manual_trigger",
                        "trace_id": trace_id,
                    },
                    progress=1.0,
                )
                self._record_outcome(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "brief_id": brief.get("brief_id"),
                        "trace_id": trace_id,
                        "accepted": False,
                        "outcome": "manual_failed",
                        "score": score,
                        "error": str(error),
                    }
                )
                return {
                    "status": "error",
                    "accepted": accepted,
                    "score": score,
                    "threshold": self.emit_threshold,
                    "error": str(error),
                }
        else:
            self._task_store.mark_succeeded(
                task_id,
                progress=1.0,
                result={
                    "accepted": accepted,
                    "score": score,
                    "threshold": self.emit_threshold,
                    "brief_id": brief.get("brief_id"),
                    "reason": "relevance_gate",
                    "trace_id": trace_id,
                    "retrospective": retrospective,
                },
            )
            self._record_outcome(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "brief_id": brief.get("brief_id"),
                    "trace_id": trace_id,
                    "accepted": False,
                    "outcome": "manual_skipped",
                    "score": score,
                }
            )
            logger.info(
                "event=manual_brief_skipped_relevance_gate_trace_id Manual brief skipped by relevance gate | score=%.3f threshold=%.3f task_id=%s trace_id=%s",
                score,
                self.emit_threshold,
                task_id,
                trace_id,
            )

        return {
            "status": "ok",
            "accepted": accepted,
            "score": score,
            "threshold": self.emit_threshold,
            "brief": brief,
            "trace_id": trace_id,
        }

    def list_tasks(
        self,
        limit: int = 100,
        task_type: str | None = None,
        lifecycle_state: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._task_store.list_tasks(
            limit=limit,
            task_type=task_type,
            lifecycle_state=lifecycle_state,
        )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._task_store.get_task(task_id)
