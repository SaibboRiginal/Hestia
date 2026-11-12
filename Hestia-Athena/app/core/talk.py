"""«Parla con te»: the assistant writes first, like a person (docs/work/2026-11-12-identita-e-proattivita).

Third output of Athena, next to the system briefs and the life observations (which stay in the evening recap):

1. **when** — inside the agenda window ``athena.talk`` (the owner moves/pauses it there), at most
   ``athena.talk.max_per_day`` times a day (0 = never), at least ``athena.talk.min_gap_hours`` apart, never while
   he is chatting; the minute is not fixed (a person does not write at 09:00 sharp);
2. **why** — the reasons of today, read through Hub: his mood (Psyche), what the areas noticed (signals
   ``alta``/``attenzione``), how long since they last talked;
3. **what** — Oracle writes it (``POST /api/chat/opener``: persona + what it remembers of him); nothing true to
   say → no message;
4. **how** — Hermes delivers it (``kind: athena.talk``), so presence and quiet hours hold; Oracle's awareness line
   gives his answer its context in any chat. What was written is kept (``signals-store`` ``kind=talk``) so she
   does not repeat herself.
"""
from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

import requests

from . import athena_settings as S
from .athena_settings import get_int
from .reflection import DOMAIN_WORDS, local_day
from .shared_imports import import_shared_symbol

SignalReader = import_shared_symbol("hestia_common.signals_client", "SignalReader")

logger = logging.getLogger("hestia_athena.talk")

KIND = "athena.talk"
STORE_KIND = "talk"
CHATTING_SECONDS = 600            # he wrote less than this ago: he is talking, do not cut in
RETRY_AFTER_NOTHING = 90 * 60     # nothing true to say: think again later
RETRY_AFTER_FAILURE = 30 * 60     # model or delivery down
LONG_SILENCE_HOURS = 20


class Talk:
    def __init__(self, hub_api_url: str, *, idle_seconds: Callable[[], int | None],
                 rng: random.Random | None = None) -> None:
        self.hub_api_url = hub_api_url.rstrip("/")
        self.reader = SignalReader(self.hub_api_url)
        self._idle_seconds = idle_seconds
        self._rng = rng or random.Random()
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._next_at: datetime | None = None     # not before this (set after every attempt)
        self._loaded_day = ""
        self._sent: list[dict] = []               # this week's messages, newest first

    # ── Hub ──────────────────────────────────────────────────────────────────
    def _route(self, service: str, method: str, path: str, *, query: dict | None = None, body: Any = None,
               timeout: float = 10) -> tuple[int, Any]:
        resp = self._session.post(
            f"{self.hub_api_url}/route/{service}/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": query or {}, "body": body, "timeout_seconds": timeout},
            timeout=timeout + 4)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    # ── what she already wrote ───────────────────────────────────────────────
    def recent(self, days: int = 7) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        try:
            rows = self.reader.rows(STORE_KIND, ref_id="athena", at_from=since, limit=100)
        except Exception as exc:
            logger.warning("[🔄] event=talk_history_read_failed error=%s fallback=memory", exc)
            return list(self._sent)
        return [{**(r.get("data") or {}), "at": r.get("at")} for r in rows if not r.get("deleted")]

    def _load(self, now: datetime) -> None:
        """Once a day (and at start): what was written, and when the next one may go."""
        day = local_day(now)
        if self._loaded_day == day:
            return
        self._sent = self.recent()
        self._loaded_day = day
        last = _parse(self._sent[0].get("at")) if self._sent else None
        gap = timedelta(hours=get_int(S.TALK_MIN_GAP_HOURS))
        first = now + timedelta(minutes=self._rng.randint(10, 75))
        self._next_at = max(first, last + gap) if last else first

    def sent_today(self, now: datetime) -> int:
        day = local_day(now)
        return sum(1 for row in self._sent if row.get("day") == day)

    # ── when ─────────────────────────────────────────────────────────────────
    def due(self, now: datetime | None = None) -> bool:
        """Cheap check for every loop tick (settings and memory only, except the first of the day)."""
        now = now or datetime.now(timezone.utc)
        limit = get_int(S.TALK_MAX_PER_DAY)
        if limit <= 0:
            return False
        with self._lock:
            self._load(now)
            if self.sent_today(now) >= limit:
                return False
            return self._next_at is None or now >= self._next_at

    def window_closed(self, now: datetime | None = None) -> None:
        """Outside her hours: when they open she waits a little, never the first minute."""
        self._wait(now or datetime.now(timezone.utc), 10 * 60)

    def _wait(self, now: datetime, seconds: int) -> None:
        with self._lock:
            self._next_at = now + timedelta(seconds=seconds + self._rng.randint(0, 900))

    # ── why ──────────────────────────────────────────────────────────────────
    def reasons(self, idle: int | None) -> list[str]:
        out: list[str] = []
        try:
            status, payload = self._route("psyche", "GET", "api/mood/today", timeout=4)
            summary = (payload or {}).get("summary") if status < 400 and isinstance(payload, dict) else None
            if isinstance(summary, dict) and summary.get("mood_word"):
                bits = [str(summary["mood_word"])]
                if summary.get("energy"):
                    bits.append(f"energia {summary['energy']}/5")
                if summary.get("stress"):
                    bits.append(f"stress {summary['stress']}/5")
                causes = [str(c) for c in (summary.get("causes") or [])][:3]
                out.append("Come si sente oggi: " + ", ".join(bits) + (f" (per {', '.join(causes)})" if causes else ""))
        except Exception as exc:
            logger.info("[🔄] event=talk_reason_failed source=mood error=%s fallback=skip", exc)
        try:
            signals = [s for s in self.reader.signals() if s.get("severity") in ("alta", "attenzione")]
            signals.sort(key=lambda s: 0 if s.get("severity") == "alta" else 1)
            for s in signals[:3]:
                out.append(f"{DOMAIN_WORDS.get(s.get('domain'), 'Una sua area')}: {str(s.get('text') or '')[:200]}")
        except Exception as exc:
            logger.info("[🔄] event=talk_reason_failed source=signals error=%s fallback=skip", exc)
        if idle is not None and idle >= LONG_SILENCE_HOURS * 3600:
            out.append(f"Non vi sentite da circa {idle // 3600} ore")
        return out

    # ── the attempt ──────────────────────────────────────────────────────────
    def run(self, trace_id: str, *, force: bool = False) -> dict[str, Any]:
        """One attempt: ``{"status": sent|nothing|chatting|failed, ...}``. ``force`` = the owner asked («Scrivimi
        ora»): past the daily limit and the pause between two messages, never past a failure."""
        now = datetime.now(timezone.utc)
        idle = self._idle_seconds()
        if not force and idle is not None and idle < CHATTING_SECONDS:
            self._wait(now, CHATTING_SECONDS)
            return {"status": "chatting"}
        reasons = self.reasons(idle)
        avoid = [str(r.get("text") or "") for r in (self._sent or self.recent())[:6] if r.get("text")]
        try:
            status, payload = self._route("oracle", "POST", "api/chat/opener",
                                          body={"reasons": reasons, "avoid": avoid}, timeout=90)
        except Exception as exc:
            logger.warning("[🔄] event=talk_oracle_failed trace_id=%s error=%s fallback=retry_later", trace_id, exc)
            self._wait(now, RETRY_AFTER_FAILURE)
            return {"status": "failed", "detail": "modello non disponibile"}
        if status >= 400 or not isinstance(payload, dict):
            logger.warning("[🔄] event=talk_oracle_failed trace_id=%s status=%s fallback=retry_later", trace_id, status)
            self._wait(now, RETRY_AFTER_FAILURE)
            return {"status": "failed", "detail": "modello non disponibile"}
        text = str(payload.get("text") or "").strip()
        if not text:
            logger.info("event=talk_nothing_to_say trace_id=%s reasons=%d", trace_id, len(reasons))
            self._wait(now, RETRY_AFTER_NOTHING)
            return {"status": "nothing", "reasons": reasons}
        row = {"id": uuid4().hex[:16], "day": local_day(now), "text": text, "reasons": reasons,
               "trace_id": trace_id, "trigger": "manual" if force else "periodic"}
        if not self._deliver(row):
            self._wait(now, RETRY_AFTER_FAILURE)
            return {"status": "failed", "detail": "messaggio non consegnato"}
        self._store(row, now)
        with self._lock:
            self._sent.insert(0, {**row, "at": now.isoformat()})
        self._wait(now, get_int(S.TALK_MIN_GAP_HOURS) * 3600)
        logger.info("event=talk_sent trace_id=%s chars=%d reasons=%d trigger=%s", trace_id, len(text), len(reasons),
                    row["trigger"])
        return {"status": "sent", "text": text, "reasons": reasons}

    def _deliver(self, row: dict) -> bool:
        """Hermes is the only one who writes to the owner. No title: it reads like a chat message."""
        event = {"event_type": "service.action_required", "domain": "system",
                 "entity_id": f"athena-talk-{row['id']}",
                 "payload": {"kind": KIND, "service": "athena", "source": "athena", "domain": "talk",
                             "_source": "athena", "_title": "", "_message": row["text"], "level": "info",
                             "target": "owner", "icon": "chat", "tone": "info", "emoji": "💬",
                             # A message of the conversation: clients show it as chat text, never retracted.
                             "_chat": True}}
        try:
            status, payload = self._route("hermes", "POST", "api/events/ingest", body=event, timeout=10)
        except Exception as exc:
            logger.warning("[🔄] event=talk_delivery_failed error=%s fallback=retry_later", exc)
            return False
        if status >= 400:
            logger.warning("[🔄] event=talk_delivery_failed status=%s body=%s fallback=retry_later", status,
                           str(payload)[:200])
            return False
        return True

    def _store(self, row: dict, now: datetime) -> None:
        at = now.isoformat()
        try:
            self._route("archive", "PUT", "api/signals-store/records", body={"rows": [
                {"kind": STORE_KIND, "id": f"athena:talk:{row['id']}", "ref_id": "athena", "parent_id": "talk",
                 "at": at, "data": row, "updated_at": at}]})
        except Exception as exc:   # sent anyway: only the «do not repeat» list of a later day misses it
            logger.warning("[🔄] event=talk_store_failed error=%s fallback=memory_only", exc)


def _parse(value: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)
