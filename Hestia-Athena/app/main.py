import logging
import os
import threading
import time
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests
from fastapi import FastAPI
from pydantic import BaseModel, Field

from .core.service_contract import HestiaServiceBase, ServiceDescriptor

try:
    from hestia_common.logging_utils import setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging

logger, log_buffer = setup_service_logging("hestia_athena")


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


def _normalize_01(value: float) -> float:
    return max(0.0, min(1.0, value))


class RelevanceSignals(BaseModel):
    urgency: float = Field(default=0.3, ge=0.0, le=1.0)
    usefulness: float = Field(default=0.6, ge=0.0, le=1.0)
    novelty: float = Field(default=0.5, ge=0.0, le=1.0)
    interruption_cost: float = Field(default=0.2, ge=0.0, le=1.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class TriggerRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    domain: str = "cognition"
    signals: RelevanceSignals = Field(default_factory=RelevanceSignals)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AthenaService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, Any]:
        return {
            "focus_brief_loop": True,
            "relevance_gate_fields": [
                "urgency",
                "usefulness",
                "novelty",
                "interruption_cost",
                "confidence",
            ],
            "event_emit_endpoint": "/api/events/ingest",
            "status_endpoint": "/api/athena/status",
            "manual_trigger_endpoint": "/api/athena/trigger",
        }


class AthenaRuntime:
    def __init__(self) -> None:
        self.interval_seconds = _parse_int_env(
            "ATHENA_BRIEF_INTERVAL_SECONDS", 300)
        self.emit_threshold = _parse_float_env(
            "ATHENA_RELEVANCE_THRESHOLD", 0.55)
        self.hermes_api_url = os.getenv(
            "HERMES_API_URL", "http://hestia_hermes:19005").rstrip("/")
        self.loop_enabled = os.getenv("ATHENA_LOOP_ENABLED", "1") != "0"
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ticks = 0
        self._emitted = 0
        self._last_score = 0.0
        self._last_emit_at: str | None = None
        self._last_error: str | None = None

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
    ) -> None:
        payload = {
            "event_type": "athena.focus_brief",
            "domain": brief["domain"],
            "entity_id": brief["brief_id"],
            "payload": {
                "source": "athena",
                "brief": brief,
                "gate": {
                    "score": score,
                    "threshold": threshold,
                    "accepted": score >= threshold,
                    "signals": signals.model_dump(),
                    "reason": reason,
                },
            },
        }

        endpoint = f"{self.hermes_api_url}/api/events/ingest"
        response = requests.post(endpoint, json=payload, timeout=5)
        response.raise_for_status()

        with self._lock:
            self._emitted += 1
            self._last_emit_at = datetime.now(timezone.utc).isoformat()
            self._last_error = None

        logger.info(
            "Focus brief emitted | brief_id=%s score=%.3f threshold=%.3f",
            brief["brief_id"],
            score,
            threshold,
        )

    def _run_once(self) -> None:
        brief = self._build_brief()
        signals = RelevanceSignals()
        score = self.score(signals)
        reason = "periodic_focus_brief"

        with self._lock:
            self._ticks += 1
            self._last_score = score

        if score < self.emit_threshold:
            logger.info(
                "Focus brief skipped by relevance gate | score=%.3f threshold=%.3f",
                score,
                self.emit_threshold,
            )
            return

        try:
            self._emit_event(
                brief=brief,
                signals=signals,
                score=score,
                threshold=self.emit_threshold,
                reason=reason,
            )
        except Exception as error:
            with self._lock:
                self._last_error = str(error)
            logger.warning("Hermes emit failed: %s", error)

    def _loop(self) -> None:
        logger.info(
            "Athena loop started | interval_seconds=%s threshold=%.3f",
            self.interval_seconds,
            self.emit_threshold,
        )
        while not self._stop_event.is_set():
            self._run_once()
            self._stop_event.wait(max(1, self.interval_seconds))

    def start(self) -> None:
        if not self.loop_enabled:
            logger.info("Athena loop disabled via ATHENA_LOOP_ENABLED=0")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="athena-focus-loop")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def status(self) -> dict[str, Any]:
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
            }

    def trigger(self, request: TriggerRequest) -> dict[str, Any]:
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
        if accepted:
            try:
                self._emit_event(
                    brief=brief,
                    signals=request.signals,
                    score=score,
                    threshold=self.emit_threshold,
                    reason="manual_trigger",
                )
            except Exception as error:
                with self._lock:
                    self._last_error = str(error)
                return {
                    "status": "error",
                    "accepted": accepted,
                    "score": score,
                    "threshold": self.emit_threshold,
                    "error": str(error),
                }
        else:
            logger.info(
                "Manual brief skipped by relevance gate | score=%.3f threshold=%.3f",
                score,
                self.emit_threshold,
            )

        return {
            "status": "ok",
            "accepted": accepted,
            "score": score,
            "threshold": self.emit_threshold,
            "brief": brief,
        }


SERVICE_NAME = os.getenv("SERVICE_NAME", "athena")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_athena:19009")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "core")
SERVICE_TAGS = [
    tag.strip().lower()
    for tag in os.getenv("SERVICE_TAGS", SERVICE_TYPE).split(",")
    if tag.strip()
]

service = AthenaService(
    ServiceDescriptor(
        name=SERVICE_NAME,
        base_url=SERVICE_BASE_URL,
        service_type=SERVICE_TYPE,
        service_version=SERVICE_VERSION,
        tags=SERVICE_TAGS,
    )
)
runtime = AthenaRuntime()

app = FastAPI(title="Hestia Athena", version=SERVICE_VERSION)


@app.on_event("startup")
def startup() -> None:
    try:
        service.register_to_hub(timeout_seconds=4)
        logger.info("Registered on Hub | name=%s base_url=%s",
                    SERVICE_NAME, SERVICE_BASE_URL)
    except Exception as error:
        logger.warning("Hub registration failed (non-fatal): %s", error)
    runtime.start()


@app.on_event("shutdown")
def shutdown() -> None:
    runtime.stop()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "service_type": service.descriptor.service_type,
        "tags": service.descriptor.tags,
    }


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_athena",
        "count": len(rows),
        "logs": rows,
    }


@app.get("/api/athena/status")
def athena_status() -> dict[str, Any]:
    return {"status": "ok", "runtime": runtime.status()}


@app.post("/api/athena/trigger")
def athena_trigger(request: TriggerRequest) -> dict[str, Any]:
    return runtime.trigger(request)
