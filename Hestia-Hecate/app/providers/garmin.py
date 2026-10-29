"""Garmin Connect (B10, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4): fully automatic, or nothing.

Garmin has no official API for personal use: the ``garminconnect`` library logs in like the Garmin Connect app and
keeps OAuth tokens (``garth``) in ``HECATE_GARMIN_TOKENS`` (default ``/code/data/garmin``, a data folder, never in
git). The password is used once and never stored: Marko types it in the secret form (Hermes «Collega Garmin») or
sets ``GARMIN_EMAIL``/``GARMIN_PASSWORD`` in Hecate's ``.env``; a two-step code (MFA) is asked with a second form.

``day(date)`` returns one normalised day: sleep, steps, resting heart rate, body battery, HRV, training readiness,
stress and the activities of the day. The daily agenda job pushes it as the ``wearable.daily`` feed
(``hestia_common.feeds``): Hecate does not decide what the numbers mean.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("hecate.garmin")

TOKENS_DIR = Path(os.getenv("HECATE_GARMIN_TOKENS", "/code/data/garmin"))
ACTIVITY_KINDS = {"running": "corsa", "trail_running": "corsa", "treadmill_running": "corsa", "track_running": "corsa",
                  "cycling": "bici", "road_biking": "bici", "mountain_biking": "bici", "indoor_cycling": "bici",
                  "gravel_cycling": "bici", "walking": "camminata", "hiking": "camminata",
                  "lap_swimming": "nuoto", "open_water_swimming": "nuoto", "swimming": "nuoto",
                  "strength_training": "forza"}


class GarminError(RuntimeError):
    pass


def _default_factory(email: str | None = None, password: str | None = None):
    try:
        from garminconnect import Garmin
    except ModuleNotFoundError as exc:          # optional dependency (requirements.txt): explain, never crash
        raise GarminError("libreria garminconnect non installata") from exc
    if email:
        return Garmin(email, password, return_on_mfa=True)
    return Garmin()


def _ms_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _num(value: Any, integer: bool = False):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return int(round(n)) if integer else round(n, 2)


def normalise_sleep(raw: Any) -> dict | None:
    dto = (raw or {}).get("dailySleepDTO") if isinstance(raw, dict) else None
    if not isinstance(dto, dict) or not dto.get("sleepTimeSeconds"):
        return None
    scores = dto.get("sleepScores") or {}
    overall = scores.get("overall") if isinstance(scores, dict) else None
    return {"start": _ms_iso(dto.get("sleepStartTimestampGMT")), "end": _ms_iso(dto.get("sleepEndTimestampGMT")),
            "minutes": _num(dto.get("sleepTimeSeconds"), True) // 60,
            "deep_minutes": (_num(dto.get("deepSleepSeconds"), True) or 0) // 60,
            "rem_minutes": (_num(dto.get("remSleepSeconds"), True) or 0) // 60,
            "awake_minutes": (_num(dto.get("awakeSleepSeconds"), True) or 0) // 60,
            "score": _num((overall or {}).get("value"), True) if isinstance(overall, dict) else None}


def normalise_activity(a: dict) -> dict:
    key = str(((a.get("activityType") or {}).get("typeKey")) or "").lower()
    seconds = _num(a.get("duration"))
    meters = _num(a.get("distance"))
    return {"id": str(a.get("activityId") or ""), "kind": ACTIVITY_KINDS.get(key, "altro"), "type": key,
            "name": str(a.get("activityName") or "")[:120], "start": a.get("startTimeLocal"),
            "minutes": int(seconds // 60) if seconds else None, "km": round(meters / 1000, 2) if meters else None,
            "calories": _num(a.get("calories"), True), "avg_hr": _num(a.get("averageHR"), True),
            "training_load": _num(a.get("activityTrainingLoad"))}


class GarminService:
    def __init__(self, tokens_dir: Path = TOKENS_DIR, *, factory: Callable[..., Any] = _default_factory,
                 env: Callable[[str], str | None] = os.getenv):
        self.dir = Path(tokens_dir)
        self.factory = factory
        self.env = env
        self._client = None
        self._pending = None          # (client, state) while a two-step code is awaited
        self._lock = threading.Lock()
        self.last_sync: dict = {}
        self.last_error = ""

    # ── account ──────────────────────────────────────────────────────────────
    def has_tokens(self) -> bool:
        return self.dir.is_dir() and any(self.dir.iterdir())

    def status(self) -> dict:
        env_creds = bool(self.env("GARMIN_EMAIL") and self.env("GARMIN_PASSWORD"))
        return {"connected": self.has_tokens() or env_creds, "tokens": self.has_tokens(), "env_credentials": env_creds,
                "waiting_code": self._pending is not None, "last_sync": self.last_sync, "last_error": self.last_error}

    def _save(self, client) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        client.garth.dump(str(self.dir))
        self._client = client

    def login(self, email: str, password: str) -> dict:
        """First step: email + password (never stored). → ``{status: connected | needs_code}``."""
        if not email or not password:
            raise GarminError("servono email e password di Garmin Connect")
        with self._lock:
            client = self.factory(email, password)
            result = client.login()
            state = result[0] if isinstance(result, tuple) else None
            if state == "needs_mfa":
                self._pending = (client, result[1])
                logger.info("event=garmin_login_needs_code")
                return {"status": "needs_code"}
            self._pending = None
            self._save(client)
        logger.info("event=garmin_connected")
        return {"status": "connected"}

    def login_code(self, code: str) -> dict:
        with self._lock:
            if not self._pending:
                raise GarminError("nessun accesso in attesa del codice: ricomincia da «Collega Garmin»")
            client, state = self._pending
            client.resume_login(state, str(code).strip())
            self._pending = None
            self._save(client)
        logger.info("event=garmin_connected step=code")
        return {"status": "connected"}

    def forget(self) -> dict:
        with self._lock:
            for f in self.dir.glob("*") if self.dir.is_dir() else []:
                f.unlink()
            self._client = None
            self._pending = None
        logger.info("event=garmin_forgotten")
        return self.status()

    def client(self):
        with self._lock:
            if self._client is not None:
                return self._client
            if self.has_tokens():
                c = self.factory()
                c.login(str(self.dir))
                self._client = c
                return c
        email, password = self.env("GARMIN_EMAIL"), self.env("GARMIN_PASSWORD")
        if email and password:
            out = self.login(email, password)
            if out["status"] == "connected":
                return self._client
            raise GarminError("Garmin chiede un codice: collegalo dalla notifica «Collega Garmin»")
        raise GarminError("Garmin non collegato")

    # ── data ─────────────────────────────────────────────────────────────────
    def day(self, d: date) -> dict:
        c = self.client()
        iso = d.isoformat()
        out: dict[str, Any] = {"date": iso, "source": "garmin"}

        def part(name: str, fn: Callable[[], Any]) -> Any:
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 — one missing part never drops the day
                logger.warning("[🔄] event=garmin_part_failed part=%s date=%s error=%s fallback=skip", name, iso, exc)
                return None

        out["sleep"] = normalise_sleep(part("sleep", lambda: c.get_sleep_data(iso)))
        stats = part("stats", lambda: c.get_stats(iso)) or {}
        if isinstance(stats, dict):
            out["steps"] = _num(stats.get("totalSteps"), True)
            out["resting_hr"] = _num(stats.get("restingHeartRate"), True)
            out["stress_avg"] = _num(stats.get("averageStressLevel"), True)
            bb = {"high": _num(stats.get("bodyBatteryHighestValue"), True),
                  "low": _num(stats.get("bodyBatteryLowestValue"), True),
                  "morning": _num(stats.get("bodyBatteryAtWakeTime"), True)}
            out["body_battery"] = bb if any(v is not None for v in bb.values()) else None
        hrv = part("hrv", lambda: c.get_hrv_data(iso)) or {}
        summary = hrv.get("hrvSummary") if isinstance(hrv, dict) else None
        if isinstance(summary, dict):
            out["hrv"] = {"last_night": _num(summary.get("lastNightAvg"), True),
                          "status": str(summary.get("status") or "").lower() or None}
        ready = part("readiness", lambda: c.get_training_readiness(iso))
        ready = ready[0] if isinstance(ready, list) and ready else ready
        if isinstance(ready, dict):
            out["readiness"] = _num(ready.get("score"), True)
        acts = part("activities", lambda: c.get_activities_by_date(iso, iso)) or []
        out["activities"] = [normalise_activity(a) for a in acts if isinstance(a, dict)]
        return {k: v for k, v in out.items() if v not in (None, {}, [])} | {"activities": out["activities"]}
