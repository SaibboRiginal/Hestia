"""Athena runtime — proactive cognition loop.

Phase 3: observation-driven thinking with LLM strategist.
- Gathers system state via Observer (Hub, Archive, Argus).
- Generates action candidates via Strategist (Oracle LLM).
- Scores each candidate through the relevance gate.
- Emits accepted actions to Hermes and publishes hints to Oracle.
- Archives every thinking cycle for audit and client display.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests

from .consolidator import MemoryConsolidator
from .observer import Observer
from .schemas import (
    ActionCandidate,
    CommitmentResolveRequest,
    ObservationSnapshot,
    RelevanceSignals,
    ThinkingRecord,
    TriggerRequest,
)
from .shared_imports import import_shared_symbol
from .strategist import Strategist

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
            "ATHENA_BRIEF_INTERVAL_SECONDS", 300
        )
        self.emit_threshold = _parse_float_env(
            "ATHENA_RELEVANCE_THRESHOLD", 0.55
        )
        self.hermes_api_url = os.getenv(
            "HERMES_API_URL", "http://hestia_hermes:19005"
        ).rstrip("/")
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api"
        ).rstrip("/")
        self.loop_enabled = _parse_bool_env("ATHENA_LOOP_ENABLED", True)

        self.retrospective_window = _parse_int_env(
            "ATHENA_RETROSPECTIVE_WINDOW", 24
        )
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
            "ATHENA_COMMITMENT_TTL_SECONDS", 86400
        )

        self.oracle_hint_enabled = _parse_bool_env(
            "ATHENA_ORACLE_HINT_ENABLED", True
        )
        self.oracle_hint_route = os.getenv(
            "ATHENA_ORACLE_HINT_ROUTE", "api/athena/hints"
        ).lstrip("/")
        self.oracle_hint_timeout = _parse_int_env(
            "ATHENA_ORACLE_HINT_TIMEOUT_SECONDS", 8
        )

        # Archive routing — thinking records are persisted via Hub → Archive
        self.archive_route = f"{self.hub_api_url}/route/archive"
        self.thinking_archive_enabled = _parse_bool_env(
            "ATHENA_THINKING_ARCHIVE_ENABLED", True
        )
        self.thinking_store_max = _parse_int_env(
            "ATHENA_THINKING_STORE_MAX", 100
        )

        # Phase 3: Observer + Strategist + Consolidator
        self.observer = Observer(hub_api_url=self.hub_api_url)
        self.strategist = Strategist(hub_api_url=self.hub_api_url)
        self.consolidator = MemoryConsolidator(hub_api_url=self.hub_api_url)
        self._consolidation_ran_today: str = ""  # date iso

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
        self._thinking_records: list[dict[str, Any]] = []

    # ── Commitment lifecycle ────────────────────────────────────────────────

    def _prune_commitments_locked(self, now_ts: float | None = None) -> None:
        now = time.time() if now_ts is None else float(now_ts)
        self._open_commitments = {
            brief_id: row
            for brief_id, row in self._open_commitments.items()
            if not bool(row.get("resolved"))
            and float(row.get("expires_at") or 0) > now
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
            "kind": str(brief.get("kind") or "advisory"),
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

        rows.sort(
            key=lambda item: float(item.get("created_at") or 0), reverse=True
        )
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

    # ── Thinking record store ────────────────────────────────────────────────

    def _store_thinking_record(self, record: ThinkingRecord) -> None:
        """Persist a thinking record in-memory and push to Archive."""
        record_dict = record.model_dump()
        with self._lock:
            self._thinking_records.append(record_dict)
            if len(self._thinking_records) > self.thinking_store_max:
                self._thinking_records = self._thinking_records[
                    -self.thinking_store_max :
                ]

        if self.thinking_archive_enabled:
            self._archive_thinking_record(record_dict)

    def _archive_thinking_record(self, record_dict: dict[str, Any]) -> None:
        """Push a thinking record to Archive via Hub routing."""
        try:
            archive_body = {
                "domain": "cognition",
                "entity_id": f"athena-thinking-{record_dict.get('record_id', '')}",
                "payload": {
                    "type": "athena_thinking",
                    "source": "athena",
                    "record": record_dict,
                },
            }
            envelope = {
                "method": "POST",
                "headers": {},
                "query": {},
                "body": archive_body,
                "timeout_seconds": 6,
            }
            resp = requests.post(
                f"{self.archive_route}/api/entities",
                json=envelope,
                timeout=8,
            )
            if resp.status_code >= 400:
                logger.debug(
                    "event=archive_thinking_non200 status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as exc:
            logger.debug(
                "event=archive_thinking_failed_non_fatal error=%s", exc
            )

    def list_thinking_records(
        self, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return recent thinking records (newest first)."""
        with self._lock:
            records = list(self._thinking_records)
        records.reverse()
        return records[: max(1, min(int(limit), self.thinking_store_max))]

    # ── Outcome tracking ─────────────────────────────────────────────────────

    def _record_outcome(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._recent_outcomes.append(payload)
            if len(self._recent_outcomes) > max(5, self.retrospective_window):
                self._recent_outcomes = self._recent_outcomes[
                    -max(5, self.retrospective_window) :
                ]

    def _retrospective_snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = list(self._recent_outcomes[-self.retrospective_window :])

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
            [row for row in recent if str(row.get("outcome") or "") == "failed"]
        )
        accepted_count = len(
            [row for row in recent if bool(row.get("accepted"))]
        )

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

    # ── Observation & thinking ───────────────────────────────────────────────

    def _observe(self) -> ObservationSnapshot:
        """Gather current system state from all observation sources."""
        retrospective = self._retrospective_snapshot()
        return self.observer.snapshot(
            active_commitments=len(self._open_commitments),
            unresolved_commitments=retrospective["unresolved_commitments"],
            recent_failures=retrospective["failed_count"],
            failure_streak=retrospective["failure_streak"],
        )

    def _think(
        self,
        observation: ObservationSnapshot,
        retrospective: dict[str, Any],
    ) -> list[ActionCandidate]:
        """Generate and score action candidates from observation.

        Candidates come from the Strategist (Oracle LLM).  If the strategist
        is disabled or Oracle is unreachable, returns empty — no static
        fallback.  Oracle is a core dependency; its absence is a system
        failure surfaced through logs and monitoring, not papered over.
        """
        if not self.strategist.enabled:
            logger.info(
                "event=strategist_disabled_no_candidates "
                "Strategist disabled — no candidates generated"
            )
            return []

        candidates = self.strategist.reason(observation)
        if not candidates:
            logger.info(
                "event=strategist_no_candidates "
                "Strategist returned no actionable candidates"
            )
            return []

        accepted: list[ActionCandidate] = []
        for candidate in candidates:
            # Apply retrospective boost to candidate signals
            boosted = self._apply_retrospective_to_signals(
                candidate.signals, retrospective
            )
            score = self.score(boosted)
            candidate.score = score
            candidate.signals = boosted
            candidate.accepted = score >= self.emit_threshold

            if candidate.accepted:
                accepted.append(candidate)
                logger.info(
                    "event=action_candidate_accepted "
                    "title=%s kind=%s priority=%s score=%.3f threshold=%.3f",
                    candidate.title,
                    candidate.kind,
                    candidate.priority,
                    score,
                    self.emit_threshold,
                )
            else:
                logger.info(
                    "event=action_candidate_rejected "
                    "title=%s kind=%s score=%.3f threshold=%.3f",
                    candidate.title,
                    candidate.kind,
                    score,
                    self.emit_threshold,
                )

        return accepted

    # ── Brief building (replaces hardcoded _build_brief) ─────────────────────

    def _build_brief_from_candidate(
        self, candidate: ActionCandidate
    ) -> dict[str, Any]:
        """Build a brief payload from an accepted action candidate."""
        now = datetime.now(timezone.utc)
        return {
            "brief_id": candidate.candidate_id,
            "created_at": now.isoformat(),
            "title": candidate.title,
            "summary": candidate.summary,
            "domain": candidate.domain,
            "kind": candidate.kind,
            "target_service": candidate.target_service,
            "target_path": candidate.target_path,
            "priority": candidate.priority,
            "reasoning": candidate.reasoning,
        }

    def _build_fallback_brief(self) -> dict[str, Any]:
        """Minimal fallback brief when no candidates are generated.

        Still uses observed state for the summary instead of being fully
        hardcoded — mentions domain activity if available.
        """
        now = datetime.now(timezone.utc)
        summary = (
            "Consider the highest-impact next action and defer "
            "lower-value interruptions."
        )
        return {
            "brief_id": str(uuid4()),
            "created_at": now.isoformat(),
            "title": "Focus checkpoint",
            "summary": summary,
            "domain": "cognition",
            "kind": "advisory",
        }

    # ── Event emission ───────────────────────────────────────────────────────

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
            "event=focus_brief_emitted "
            "brief_id=%s title=%s score=%.3f threshold=%.3f trace_id=%s",
            brief["brief_id"],
            brief.get("title", ""),
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
            "session_id": str(
                (brief.get("metadata") or {}).get("session_id") or ""
            ).strip()
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
            "headers": {"X-Trace-Id": trace_id},
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
                    "event=athena_oracle_hint_route_failed_non200 "
                    "trace_id=%s status=%s body=%s",
                    trace_id,
                    response.status_code,
                    response.text[:200],
                )
                return False

            routed = response.json() if response.content else {}
            if int((routed or {}).get("status_code", 500)) >= 400:
                logger.warning(
                    "event=athena_oracle_hint_route_failed_payload "
                    "trace_id=%s status_code=%s payload=%s",
                    trace_id,
                    int((routed or {}).get("status_code", 500)),
                    str((routed or {}).get("payload"))[:200],
                )
                return False

            logger.info(
                "event=athena_oracle_hint_published "
                "trace_id=%s hint_id=%s brief_id=%s priority=%s",
                trace_id,
                hint_payload.get("hint_id"),
                brief.get("brief_id"),
                priority,
            )
            return True
        except Exception as error:
            logger.warning(
                "event=athena_oracle_hint_route_failed_exception "
                "trace_id=%s error=%s",
                trace_id,
                error,
            )
            return False

    # ── Main loop ────────────────────────────────────────────────────────────

    def _run_once(self) -> None:
        """Execute one thinking cycle: observe → think → gate → act → archive.

        Also checks if daily memory consolidation should run."""
        run_trace_id = f"athena-{uuid4().hex[:12]}"

        # ── Daily memory consolidation (runs once per day during window) ───
        today = datetime.now().strftime("%Y-%m-%d")
        if (self.consolidator.should_run() and
            self._consolidation_ran_today != today):
            try:
                sessions = self.consolidator.get_active_sessions()
                for session_id in sessions:
                    result = self.consolidator.consolidate(session_id)
                    logger.info(
                        "event=consolidation_complete session=%s facts=%d conflicts=%d",
                        session_id,
                        result.get("facts_extracted", 0),
                        result.get("conflicts_detected", 0),
                    )
                self._consolidation_ran_today = today
            except Exception as exc:
                logger.warning("event=consolidation_failed error=%s", exc)

        retrospective = self._retrospective_snapshot()

        # Phase 1: Observe
        observation = self._observe()

        # Phase 2: Think (LLM via Oracle)
        candidates = self._think(observation, retrospective)

        # Track the cycle
        thinking_record = ThinkingRecord(
            trace_id=run_trace_id,
            trigger="periodic",
            observation=observation,
            candidates=candidates,
            emitted_count=0,
            hint_published=False,
        )

        task = self._task_store.create_task(
            task_type="athena.focus_brief.periodic",
            trace_id=run_trace_id,
            metadata={
                "observation_id": observation.observation_id,
                "candidate_count": len(candidates),
                "emit_threshold": self.emit_threshold,
                "retrospective": retrospective,
            },
        )
        task_id = str(task.get("task_id") or "")
        self._task_store.mark_running(task_id, progress=0.2)

        with self._lock:
            self._ticks += 1

        # ── Process accepted candidates ──────────────────────────────────
        emitted_count = 0
        hint_published = False
        errors: list[str] = []

        if not candidates:
            # No actionable candidates — this is normal, not a failure
            self._task_store.mark_succeeded(
                task_id,
                progress=1.0,
                result={
                    "accepted": False,
                    "candidate_count": 0,
                    "reason": "no_candidates_generated",
                    "trace_id": run_trace_id,
                    "observation_id": observation.observation_id,
                },
            )
            self._record_outcome(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "trace_id": run_trace_id,
                    "accepted": False,
                    "outcome": "no_candidates",
                    "observation_id": observation.observation_id,
                }
            )
            logger.info(
                "event=thinking_cycle_no_candidates "
                "trace_id=%s observation_id=%s",
                run_trace_id,
                observation.observation_id,
            )
        else:
            for candidate in candidates:
                try:
                    self._task_store.mark_running(
                        task_id,
                        progress=0.7,
                        metadata={"phase": "emit", "candidate_id": candidate.candidate_id},
                    )
                    brief = self._build_brief_from_candidate(candidate)
                    self._emit_event(
                        brief=brief,
                        signals=candidate.signals,
                        score=candidate.score,
                        threshold=self.emit_threshold,
                        reason=f"strategist_{candidate.kind}",
                        retrospective=retrospective,
                        trace_id=run_trace_id,
                    )
                    self._publish_oracle_hint(
                        brief=brief,
                        signals=candidate.signals,
                        score=candidate.score,
                        threshold=self.emit_threshold,
                        retrospective=retrospective,
                        trace_id=run_trace_id,
                    )
                    self._register_commitment(
                        brief=brief,
                        score=candidate.score,
                        trace_id=run_trace_id,
                    )
                    emitted_count += 1
                    hint_published = True
                    thinking_record.emitted_count = emitted_count
                    thinking_record.hint_published = True

                    self._record_outcome(
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "brief_id": brief.get("brief_id"),
                            "trace_id": run_trace_id,
                            "accepted": True,
                            "outcome": "emitted",
                            "score": candidate.score,
                            "kind": candidate.kind,
                        }
                    )
                except Exception as error:
                    errors.append(str(error))
                    logger.warning(
                        "event=candidate_emit_failed "
                        "trace_id=%s candidate=%s error=%s",
                        run_trace_id,
                        candidate.candidate_id,
                        error,
                    )

            if errors:
                thinking_record.error = "; ".join(errors)
                with self._lock:
                    self._last_error = thinking_record.error

            self._task_store.mark_succeeded(
                task_id,
                progress=1.0,
                result={
                    "accepted": True,
                    "candidate_count": len(candidates),
                    "emitted_count": emitted_count,
                    "errors": errors,
                    "trace_id": run_trace_id,
                    "observation_id": observation.observation_id,
                },
            )

        with self._lock:
            self._last_score = (
                candidates[0].score if candidates else 0.0
            )

        # Archive this thinking cycle
        self._store_thinking_record(thinking_record)

    def _loop(self) -> None:
        logger.info(
            "event=athena_loop_started "
            "interval_seconds=%s threshold=%.3f strategist=%s",
            self.interval_seconds,
            self.emit_threshold,
            self.strategist.enabled,
        )
        while not self._stop_event.is_set():
            self._run_once()
            self._stop_event.wait(max(1, self.interval_seconds))

    def start(self) -> None:
        if not self.loop_enabled:
            logger.info(
                "event=athena_loop_disabled "
                "Athena loop disabled via ATHENA_LOOP_ENABLED=0"
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
                "strategist_enabled": self.strategist.enabled,
                "thinking_records_stored": len(self._thinking_records),
                "retrospective": retrospective,
            }

    def trigger(self, request: TriggerRequest) -> dict[str, Any]:
        """Manual trigger — observe, think, and optionally emit."""
        trace_id = f"athena-manual-{uuid4().hex[:10]}"
        retrospective = self._retrospective_snapshot()
        observation = self._observe()

        # Manual trigger: build brief from request + observations
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

        candidates = self.strategist.reason(observation) if request.summary else []
        scored_candidates: list[ActionCandidate] = []
        for c in candidates:
            c.score = self.score(c.signals)
            c.accepted = c.score >= self.emit_threshold
            scored_candidates.append(c)

        thinking_record = ThinkingRecord(
            trace_id=trace_id,
            trigger="manual",
            observation=observation,
            candidates=scored_candidates,
            emitted_count=1 if accepted else 0,
            hint_published=False,
        )

        task = self._task_store.create_task(
            task_type="athena.focus_brief.manual",
            trace_id=trace_id,
            metadata={
                "brief_id": brief.get("brief_id"),
                "emit_threshold": self.emit_threshold,
                "accepted": accepted,
                "retrospective": retrospective,
                "observation_id": observation.observation_id,
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
                thinking_record.hint_published = True
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
                thinking_record.error = str(error)
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
                self._store_thinking_record(thinking_record)
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
                "event=manual_brief_skipped_relevance_gate "
                "score=%.3f threshold=%.3f task_id=%s trace_id=%s",
                score,
                self.emit_threshold,
                task_id,
                trace_id,
            )

        self._store_thinking_record(thinking_record)

        return {
            "status": "ok",
            "accepted": accepted,
            "score": score,
            "threshold": self.emit_threshold,
            "brief": brief,
            "trace_id": trace_id,
            "observation_id": observation.observation_id,
        }

    # ── Task store delegates ─────────────────────────────────────────────────

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
