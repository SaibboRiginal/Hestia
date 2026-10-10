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

from .consolidator import CONSOLIDATION_WINDOW_DEFAULT, MemoryConsolidator
from .observer import Observer
from .skill_curator import SkillCurator
from .schemas import (
    ActionCandidate,
    CommitmentResolveRequest,
    ObservationSnapshot,
    RelevanceSignals,
    ThinkingRecord,
    TriggerRequest,
)
from . import athena_settings as S
from .athena_settings import get_bool, get_float, get_int
from .shared_imports import import_shared_symbol
from .strategist import Strategist

TaskLifecycleStore = import_shared_symbol(
    "hestia_common.task_lifecycle", "TaskLifecycleStore"
)
AgendaClient = import_shared_symbol("hestia_common.agenda_client", "AgendaClient")
agenda_template = import_shared_symbol("hestia_common.agenda_client", "template")
daily_window = import_shared_symbol("hestia_common.agenda_client", "daily_window")
PresenceClient = import_shared_symbol("hestia_common.presence_client", "PresenceClient")

# Assistant-agenda windows (Chronos). The user moves/skips/pauses them there;
# missing window or Chronos down → default-hour fallback. The hours below are only the
# defaults registered once (idempotent by key, user edits win): not env, not settings.
WINDOW_CONSOLIDATION = "athena.consolidation"
WINDOW_SKILL_CURATION = "athena.skill_curation"
WINDOW_THINKING = "athena.thinking"
SKILL_CURATION_WINDOW_DEFAULT = (5, 7)
THINKING_WINDOW_DEFAULT = (0, 0)

logger = logging.getLogger("hestia_athena.runtime")


def _normalize_01(value: float) -> float:
    return max(0.0, min(1.0, value))


class AthenaRuntime:
    def __init__(self) -> None:
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api"
        ).rstrip("/")
        # Oracle route for hints: infrastructure (path), stays in env.
        self.oracle_hint_route = os.getenv(
            "ATHENA_ORACLE_HINT_ROUTE", "api/athena/hints"
        ).lstrip("/")

        # Archive routing — thinking records are persisted via Hub → Archive
        self.archive_route = f"{self.hub_api_url}/route/archive"

        # Phase 3: Observer + Strategist + Consolidator
        self.observer = Observer(hub_api_url=self.hub_api_url)
        self.strategist = Strategist(hub_api_url=self.hub_api_url)
        self.consolidator = MemoryConsolidator(hub_api_url=self.hub_api_url)
        self._consolidation_ran_today: str = ""  # date iso

        # Skill curator (Plan P3b-10 — Hermes Agent pattern)
        self.skill_curator = SkillCurator(
            hub_api_url=self.hub_api_url,
            embed_fn=self._embed_text,
            oracle_route=self.oracle_hint_route,
        )
        self._skill_curation_ran_today: str = ""

        # Assistant agenda: when Athena works is data the user can edit.
        self.agenda = AgendaClient("athena", self.hub_api_url)
        # Assistant presence (Chronos): when to think, plus the state in the observation.
        self.presence = PresenceClient("athena", self.hub_api_url)
        self._thinking_paused_logged = False

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
            max_tasks=get_int(S.TASK_STORE_MAX)  # apply=restart
        )
        self._thinking_records: list[dict[str, Any]] = []

        self._loop_paused_logged = False
        self._forge_day = ""
        self._forge_titles: set[str] = set()
        self._setting_day = ""
        self._setting_keys: set[str] = set()

    # ── Central settings (Themis): read at use time, so changes apply live ──

    @property
    def loop_enabled(self) -> bool:
        return get_bool(S.LOOP_ENABLED)

    @property
    def interval_seconds(self) -> int:
        return get_int(S.LOOP_INTERVAL)

    @property
    def idle_required_seconds(self) -> int:
        """Idle-only cognition: run cycles only when the user is not chatting."""
        return get_int(S.LOOP_IDLE_SECONDS)

    @property
    def emit_threshold(self) -> float:
        return get_float(S.GATE_THRESHOLD)

    @property
    def retrospective_window(self) -> int:
        return max(1, get_int(S.RETRO_WINDOW))

    @property
    def retrospective_failure_urgency_boost(self) -> float:
        return get_float(S.RETRO_FAILURE_URGENCY_BOOST)

    @property
    def retrospective_unresolved_urgency_boost(self) -> float:
        return get_float(S.RETRO_UNRESOLVED_URGENCY_BOOST)

    @property
    def retrospective_unresolved_usefulness_boost(self) -> float:
        return get_float(S.RETRO_UNRESOLVED_USEFULNESS_BOOST)

    @property
    def commitment_ttl_seconds(self) -> int:
        return get_int(S.COMMITMENT_TTL)

    @property
    def oracle_hint_enabled(self) -> bool:
        return get_bool(S.HINTS_ENABLED)

    @property
    def oracle_hint_timeout(self) -> int:
        return get_int(S.HINTS_TIMEOUT)

    @property
    def thinking_archive_enabled(self) -> bool:
        return get_bool(S.THINKING_ARCHIVE_ENABLED)

    @property
    def thinking_store_max(self) -> int:
        return max(1, get_int(S.THINKING_STORE_MAX))

    @property
    def forge_enabled(self) -> bool:
        """Improvement hand-off to Hephaestus Forge."""
        return get_bool(S.FORGE_ENABLED)

    @property
    def forge_max_per_day(self) -> int:
        return get_int(S.FORGE_MAX_PER_DAY)

    # ── Forge hand-off (improvement candidates) ─────────────────────────────

    def _send_to_forge(self, candidate: Any, trace_id: str) -> bool:
        """Hand an accepted ``improvement`` to Hephaestus Forge.  Forge's
        per-engine autonomy policy (set by the user from the client) decides
        whether it starts coding or waits for approval; merge always waits.
        Capped per day and deduplicated by title."""
        if not self.forge_enabled:
            return False
        today = datetime.now(timezone.utc).date().isoformat()
        key = str(candidate.title or "").strip().lower()[:80]
        with self._lock:
            if self._forge_day != today:
                self._forge_day, self._forge_titles = today, set()
            if key in self._forge_titles or len(self._forge_titles) >= self.forge_max_per_day:
                return False
            self._forge_titles.add(key)
        body = {
            "request": f"{candidate.title}. {candidate.summary}".strip()[:1500],
            "source": "athena",
            "requested_by": "athena.strategist",
            "context": f"reason: {candidate.reasoning}\ndomain: {candidate.domain}\ntrace_id: {trace_id}",
        }
        try:
            resp = requests.post(
                f"{self.hub_api_url}/route/hephaestus/api/hephaestus/forge/tasks",
                json={"method": "POST", "headers": {}, "query": {}, "body": body, "timeout_seconds": 10},
                timeout=12)
            ok = resp.ok and int((resp.json() or {}).get("status_code", 500)) < 400
        except Exception as exc:
            logger.warning("[🔄] event=athena_forge_handoff_failed title=%s error=%s", key, exc)
            ok = False
        if not ok:
            with self._lock:
                self._forge_titles.discard(key)
        logger.info("event=athena_forge_handoff title=%s ok=%s trace_id=%s", key, ok, trace_id)
        return ok

    # ── Settings proposals (Themis → Hermes → the user decides) ─────────────

    def _propose_setting(self, candidate: Any, trace_id: str) -> bool:
        """Ask Themis to propose a setting change: never applied without the user's answer.
        Themis validates the value and skips duplicates; capped per day (setting)."""
        key = str(candidate.setting_key or "").strip()
        if not key or candidate.setting_value is None:
            return False
        cap = int(S.settings.get(S.PROPOSALS_PER_DAY) or 0)
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            if self._setting_day != today:
                self._setting_day, self._setting_keys = today, set()
            if key in self._setting_keys or len(self._setting_keys) >= cap:
                return False
            self._setting_keys.add(key)
        body = {"key": key, "value": candidate.setting_value, "proposer": "athena",
                "reason": (candidate.reasoning or candidate.summary or "")[:400]}
        status = 0
        try:
            resp = requests.post(
                f"{self.hub_api_url}/route/themis/api/settings/proposals",
                json={"method": "POST", "headers": {}, "query": {}, "body": body, "timeout_seconds": 10},
                timeout=12)
            status = int((resp.json() or {}).get("status_code", 500)) if resp.ok else resp.status_code
        except Exception as exc:
            logger.warning("[🔄] event=athena_setting_proposal_failed key=%s error=%s", key, exc)
        ok = 0 < status < 400
        if not ok:
            with self._lock:
                self._setting_keys.discard(key)
        logger.info("event=athena_setting_proposal key=%s status=%s trace_id=%s", key, status, trace_id)
        return ok

    # ── Embedding helper ────────────────────────────────────────────────────

    def _embed_text(self, text: str) -> list[float]:
        """Embed *text* via Oracle's embedding endpoint (Hub routing).

        Rulebook 1.2 organ model: ONLY Oracle owns model calls.
        Athena routes all LLM/embedding through Oracle via Hub.
        """
        try:
            resp = requests.post(
                f"{self.hub_api_url}/route/oracle/api/embed",
                json={"text": text},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            if isinstance(data.get("payload"), dict):   # Hub route envelope
                data = data["payload"]
            embedding = data.get("embedding")
            if isinstance(embedding, list):
                return list(embedding)
        except Exception as exc:
            logger.warning("event=athena_embed_via_oracle_failed error=%s", exc)
        return []

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

        response = requests.post(
            f"{self.hub_api_url}/route/hermes/api/events/ingest",
            json={
                "method": "POST",
                "headers": {"X-Trace-Id": trace_id},
                "query": {},
                "body": payload,
                "timeout_seconds": 5,
            },
            timeout=6,
        )
        response.raise_for_status()
        routed = response.json() if response.content else {}
        if int((routed or {}).get("status_code", 500)) >= 400:
            raise RuntimeError(
                f"Hermes route returned status {routed.get('status_code')}: {str(routed.get('payload'))[:200]}"
            )

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

    # ── Assistant agenda ─────────────────────────────────────────────────────

    def _agenda_rules(self) -> list[dict]:
        # Default hours only: Chronos keeps the user's edits (move/skip/pause) over these.
        c_start, c_end = CONSOLIDATION_WINDOW_DEFAULT
        s_start, s_end = SKILL_CURATION_WINDOW_DEFAULT
        t_start, t_end = THINKING_WINDOW_DEFAULT
        return [
            daily_window(WINDOW_CONSOLIDATION, "Athena: consolidamento memoria",
                         c_start, c_end,
                         description="Estrae fatti dalle sessioni recenti e risolve conflitti di memoria "
                                     "(una volta al giorno dentro la finestra)."),
            daily_window(WINDOW_SKILL_CURATION, "Athena: cura delle skill",
                         s_start, s_end,
                         description="Crea/aggiorna/depreca skill dalle conversazioni (una volta al giorno)."),
            daily_window(WINDOW_THINKING, "Athena: retrospettiva in idle",
                         t_start, t_end,
                         description="Cicli di pensiero (osserva → valuta → proponi) solo quando non stai "
                                     "chattando. Salta/metti in pausa per fermare Athena."),
        ]

    def _window_open(self, key: str, fallback) -> bool:
        try:
            return self.agenda.is_open(key, fallback)
        except Exception as exc:
            logger.warning("[🔄] event=athena_window_check_failed key=%s error=%s", key, exc)
            return bool(fallback())

    # ── Main loop ────────────────────────────────────────────────────────────

    def _run_once(self) -> None:
        """Execute one thinking cycle: observe → think → gate → act → archive.

        Also checks if daily memory consolidation should run."""
        run_trace_id = f"athena-{uuid4().hex[:12]}"

        # ── Daily memory consolidation (runs once per day during window) ───
        today = datetime.now().strftime("%Y-%m-%d")
        heavy_ok = self._heavy_allowed()
        if (self._consolidation_ran_today != today and heavy_ok and
                self._window_open(WINDOW_CONSOLIDATION, self.consolidator.should_run)):
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

        # ── Daily skill curation (Plan P3b-10 — Hermes Agent pattern) ──────
        if (self._skill_curation_ran_today != today and heavy_ok and
                self._window_open(WINDOW_SKILL_CURATION, lambda: True)):
            try:
                summary = self.skill_curator.run_cycle()
                if any(v > 0 for v in summary.values()):
                    logger.info(
                        "event=skill_curation_complete created=%d updated=%d "
                        "deprecated=%d merged=%d deleted=%d promoted=%d",
                        summary.get("created", 0),
                        summary.get("updated", 0),
                        summary.get("deprecated", 0),
                        summary.get("merged", 0),
                        summary.get("deleted", 0),
                        summary.get("promoted", 0),
                    )
                self._skill_curation_ran_today = today
            except Exception as exc:
                logger.warning("event=skill_curation_failed error=%s", exc)

        # ── Thinking cycles only inside the agenda window ───────────────────
        if not self._window_open(WINDOW_THINKING, lambda: True):
            if not self._thinking_paused_logged:
                logger.info("event=athena_thinking_window_closed window=%s", WINDOW_THINKING)
                self._thinking_paused_logged = True
            return
        self._thinking_paused_logged = False

        retrospective = self._retrospective_snapshot()

        # Phase 1: Observe
        observation = self._observe()
        observation.presence = self.presence.context_line()

        # Phase 2: Think (LLM via Oracle) — reported as a light activity of the assistant
        with self.presence.activity("athena.thinking", label="Athena pensa", load="light", resource="gpu",
                                    ttl_seconds=900):
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
                    if candidate.kind == "improvement":
                        self._send_to_forge(candidate, run_trace_id)
                    elif candidate.kind == "setting":
                        self._propose_setting(candidate, run_trace_id)
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
            if not self.loop_enabled:
                # Switched off by the user (setting athena.loop.enabled): idle, re-check soon.
                if not self._loop_paused_logged:
                    logger.info("event=athena_loop_disabled setting=%s", S.LOOP_ENABLED)
                    self._loop_paused_logged = True
                self._stop_event.wait(60)
                continue
            if self._loop_paused_logged:
                logger.info("event=athena_loop_enabled setting=%s", S.LOOP_ENABLED)
                self._loop_paused_logged = False
            wait = self._light_work_wait()
            if wait:
                self._stop_event.wait(wait)
                continue
            self._run_once()
            self._stop_event.wait(max(1, self.interval_seconds))

    def _light_work_wait(self) -> int:
        """Seconds to wait before thinking (0 = go). The assistant presence decides (effect
        ``work.light``: the user is "Sveglio" → defer); Chronos down → old Oracle idle check."""
        state = self.presence.get()
        if state:
            effect = (state.get("effects") or {}).get("work.light", "allow")
            if effect == "defer":
                logger.debug("event=athena_cycle_deferred_presence state=%s", state.get("base"))
                return 60
            return 0
        idle = self._user_idle_seconds()
        if idle is not None and idle < self.idle_required_seconds:
            # [🔄] presence unknown: user is chatting, leave the (local) model to Oracle, retry soon.
            logger.debug("[🔄] event=athena_cycle_deferred_user_active idle_seconds=%s", idle)
            return max(30, min(self.interval_seconds, self.idle_required_seconds - idle))
        return 0

    def _heavy_allowed(self) -> bool:
        """Memory consolidation / skill curation use the local model for a while: they need the
        presence effect ``work.heavy`` allow or local (unknown presence → their windows decide)."""
        return self.presence.effect("work.heavy") in ("allow", "local")

    def _user_idle_seconds(self) -> int | None:
        """Seconds since the last real user chat (Oracle /api/activity).
        None = unknown (no chat yet or Oracle unreachable) → treated as idle."""
        if self.idle_required_seconds <= 0:
            return None
        try:
            resp = requests.post(
                f"{self.hub_api_url}/route/oracle/api/activity",
                json={"method": "GET", "headers": {}, "query": {}, "body": None, "timeout_seconds": 5},
                timeout=7)
            payload = (resp.json() or {}).get("payload") if resp.ok else None
            idle = (payload or {}).get("idle_seconds")
            return int(idle) if idle is not None else None
        except Exception:
            return None

    def _wait_for_oracle(self, timeout: float = 60.0) -> bool:
        """Poll Hub until Oracle is registered. Returns True if found."""
        import time as _time
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            try:
                resp = requests.get(
                    f"{self.hub_api_url}/registry/services", timeout=5)
                if resp.ok:
                    services = resp.json().get("services", [])
                    for svc in services:
                        if svc.get("name") == "oracle":
                            logger.info(
                                "event=athena_oracle_found "
                                "Oracle found in Hub registry")
                            return True
            except Exception:
                pass
            _time.sleep(2)
        logger.warning(
            "event=athena_oracle_not_found "
            "Oracle not found in Hub registry after %.0fs", timeout)
        return False

    def start(self) -> None:
        # The thread always starts: athena.loop.enabled is live and checked every cycle.
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.agenda.register_async(self._agenda_rules, templates=lambda: [agenda_template(
            "reflect", "Fai riflettere Athena su un tema", service="athena", path="/api/athena/trigger",
            type="task", types=["task", "job"], icon="brain",
            fields={"title": {"type": "string", "label": "Tema", "description": "Tema (es. 'spese di casa')"},
                    "summary": {"type": "string", "label": "Dettagli", "format": "textarea", "description": "Cosa deve considerare"}},
            required=["title"], body={"domain": "cognition"}, title="Athena: {title}",
            description="Athena analizza il tema all'orario scelto e ti propone idee o azioni.")])
        # Wait for Oracle inside the loop thread: blocking here would hold the
        # FastAPI startup (and /health) for up to 60 s.
        self._thread = threading.Thread(
            target=lambda: (self._wait_for_oracle(), self._loop()),
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
                "hub_api_url": self.hub_api_url,
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
