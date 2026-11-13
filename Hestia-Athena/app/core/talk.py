"""«Parla con te»: the assistant writes first, like a person (docs/work/2026-11-12-identita-e-proattivita,
timing and memory: docs/work/2026-11-13-prima-osserva-poi-propone).

Third output of Athena, next to the system briefs and the life observations (which stay in the evening recap):

1. **when** — inside the agenda window ``athena.talk`` (the owner moves/pauses it there), at most
   ``athena.talk.max_per_day`` times a day (0 = never), at least ``athena.talk.min_gap_hours`` apart, never while
   he is chatting. No clock and no dice: she writes when her **drive** to talk passes the bar of
   ``athena.talk.eagerness``. The drive grows with the silence between them and with what she has to say, drops
   when her messages get no answer, and is low in the first days, when she knows little;
2. **why** — the reasons of today, read through Hub: his mood (Psyche), what the areas noticed (signals
   ``alta``/``attenzione``), how long since they last talked; plus the **last days**: how he was, what she wrote
   and whether he answered;
3. **what** — Oracle writes it (``POST /api/chat/opener``: persona + what it remembers of him); nothing true to
   say → no message;
4. **how** — Hermes delivers it (``kind: athena.talk``), so presence and quiet hours hold; Oracle's awareness line
   gives his answer its context in any chat. What was written is kept (``signals-store`` ``kind=talk``) with the
   drive, the reasons and whether he answered.
"""
from __future__ import annotations

import logging
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
RECHECK_SECONDS = 30 * 60         # the drive is weighed again this often (it changes slowly)
LONG_SILENCE_HOURS = 20
ANSWER_WITHIN_HOURS = 12          # no word from him this long after her message = it got no answer
PAST_DAYS = 3                     # how far back «the last days» go

# The drive to talk, 0..1 (no chance in it: the same state gives the same answer).
SILENCE_FULL_HOURS = 36           # after this the silence weighs all it can
W_SILENCE = 0.45
W_MATERIAL = 0.40                 # two true things to say = full weight
BONUS_ANSWERED = 0.10             # he answered her last message
COST_UNANSWERED = 0.25            # for each of her last messages left without answer
KNOWN_FULL_DAYS = 7               # before this she knows little of him: the drive is damped (from half)
BARS = {1: 0.80, 2: 0.65, 3: 0.50, 4: 0.35, 5: 0.20}     # athena.talk.eagerness -> drive needed to write


def drive(*, idle: int | None, material: int, unanswered: int, answered_last: bool, known_days: int) -> float:
    """How much she wants to write now. ``idle`` = seconds since his last chat message (None = unknown),
    ``material`` = true things to say today, ``unanswered`` = her last messages in a row he did not answer."""
    silence = 0.5 if idle is None else min(1.0, idle / (SILENCE_FULL_HOURS * 3600))
    value = W_SILENCE * silence + W_MATERIAL * min(1.0, material / 2)
    value += BONUS_ANSWERED if answered_last else 0.0
    value -= COST_UNANSWERED * max(0, unanswered)
    value *= 0.5 + 0.5 * min(1.0, max(0, known_days) / KNOWN_FULL_DAYS)
    return round(max(0.0, min(1.0, value)), 3)


class Talk:
    def __init__(self, hub_api_url: str, *, idle_seconds: Callable[[], int | None],
                 known_days: Callable[[], int] | None = None) -> None:
        self.hub_api_url = hub_api_url.rstrip("/")
        self.reader = SignalReader(self.hub_api_url)
        self._idle_seconds = idle_seconds
        self._known_days = known_days or (lambda: KNOWN_FULL_DAYS)
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
        self._next_at = max(now, last + gap) if last else now

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
        """Outside her hours: look again later."""
        self._wait(now or datetime.now(timezone.utc), 10 * 60)

    def _wait(self, now: datetime, seconds: int) -> None:
        with self._lock:
            self._next_at = now + timedelta(seconds=seconds)

    # ── why ──────────────────────────────────────────────────────────────────
    def reasons(self, idle: int | None) -> list[str]:
        """What is true today (hidden text for Oracle, English; his words and labels stay as they are)."""
        out: list[str] = []
        try:
            status, payload = self._route("psyche", "GET", "api/mood/today", timeout=4)
            summary = (payload or {}).get("summary") if status < 400 and isinstance(payload, dict) else None
            if isinstance(summary, dict) and summary.get("mood_word"):
                out.append("How they feel today: " + _mood(summary))
        except Exception as exc:
            logger.info("[🔄] event=talk_reason_failed source=mood error=%s fallback=skip", exc)
        try:
            signals = [s for s in self.reader.signals() if s.get("severity") in ("alta", "attenzione")]
            signals.sort(key=lambda s: 0 if s.get("severity") == "alta" else 1)
            for s in signals[:3]:
                out.append(f"{DOMAIN_WORDS.get(s.get('domain'), 'One of their areas')}: {str(s.get('text') or '')[:200]}")
        except Exception as exc:
            logger.info("[🔄] event=talk_reason_failed source=signals error=%s fallback=skip", exc)
        return out

    @staticmethod
    def silence_line(idle: int | None) -> str:
        if idle is not None and idle >= LONG_SILENCE_HOURS * 3600:
            return f"You two have not talked for about {idle // 3600} hours"
        return ""

    # ── the last days ────────────────────────────────────────────────────────
    def _mark_answers(self, now: datetime, idle: int | None) -> None:
        """Did he answer her last message? He wrote after it = yes; a long silence after it = no."""
        row = next((r for r in self._sent if r.get("text") and r.get("answered") is None), None)
        if not row or self._sent[0] is not row:
            return
        at = _parse(row.get("at"))
        if at is None:
            return
        if idle is not None and now - timedelta(seconds=idle) > at:
            row["answered"] = True
        elif now - at >= timedelta(hours=ANSWER_WITHIN_HOURS):
            row["answered"] = False
        else:
            return
        self._store({k: v for k, v in row.items() if k != "at"}, at)
        logger.info("event=talk_answer_marked id=%s answered=%s", row.get("id"), row["answered"])

    def unanswered_streak(self) -> int:
        count = 0
        for row in self._sent:
            if row.get("answered") is False:
                count += 1
            else:
                break
        return count

    def past(self, now: datetime) -> list[str]:
        """The last days in a few lines: how he was, what she wrote and how it went."""
        out: list[str] = []
        today = local_day(now)
        try:
            status, payload = self._route("psyche", "GET", "api/mood/history", query={"days": PAST_DAYS + 1},
                                          timeout=4)
            days = (payload or {}).get("days") if status < 400 and isinstance(payload, dict) else None
            for d in [d for d in (days or []) if isinstance(d, dict) and d.get("date") != today][-PAST_DAYS:]:
                if d.get("mood_word"):
                    out.append(f"{d.get('date')}: they felt {_mood(d)}")
        except Exception as exc:
            logger.info("[🔄] event=talk_past_failed source=mood error=%s fallback=skip", exc)
        for row in [r for r in self._sent if r.get("text")][:4]:
            state = {True: "they answered", False: "no answer"}.get(row.get("answered"), "not answered yet")
            out.append(f"{row.get('day')}: you wrote «{str(row['text'])[:160]}» ({state})")
        streak = self.unanswered_streak()
        if streak:
            out.append(f"Your last {streak} message(s) got no answer: do not insist, change subject or stay quiet")
        return out

    def weigh(self, now: datetime | None = None) -> dict[str, Any]:
        """Her state now: the drive, the bar, the reasons, the last days (also notes whether he answered her)."""
        now = now or datetime.now(timezone.utc)
        idle = self._idle_seconds()
        with self._lock:
            self._load(now)
            self._mark_answers(now, idle)
            streak = self.unanswered_streak()
            answered_last = bool(self._sent and self._sent[0].get("answered") is True)
        reasons = self.reasons(idle)
        known = int(self._known_days() or 0)
        value = drive(idle=idle, material=len(reasons), unanswered=streak, answered_last=answered_last,
                      known_days=known)
        bar = BARS.get(max(1, min(5, get_int(S.TALK_EAGERNESS))), BARS[3])
        silence = self.silence_line(idle)
        return {"drive": value, "bar": bar, "wants": value >= bar, "idle_seconds": idle, "known_days": known,
                "unanswered": streak, "reasons": reasons + ([silence] if silence else []), "past": self.past(now)}

    # ── the attempt ──────────────────────────────────────────────────────────
    def run(self, trace_id: str, *, force: bool = False) -> dict[str, Any]:
        """One attempt: ``{"status": sent|quiet|nothing|chatting|failed, ...}`` (quiet = not enough drive).
        ``force`` = the owner asked («Scrivimi ora»): past the drive, the daily limit and the pause between two
        messages, never past a failure."""
        now = datetime.now(timezone.utc)
        idle = self._idle_seconds()
        if not force and idle is not None and idle < CHATTING_SECONDS:
            self._wait(now, CHATTING_SECONDS)
            return {"status": "chatting"}
        state = self.weigh(now)
        reasons = state["reasons"]
        if not force and not state["wants"]:
            logger.info("event=talk_quiet trace_id=%s drive=%.2f bar=%.2f reasons=%d unanswered=%d known_days=%d",
                        trace_id, state["drive"], state["bar"], len(reasons), state["unanswered"],
                        state["known_days"])
            self._wait(now, RECHECK_SECONDS)
            return {"status": "quiet", "drive": state["drive"], "bar": state["bar"]}
        avoid = [str(r.get("text") or "") for r in (self._sent or self.recent())[:6] if r.get("text")]
        try:
            status, payload = self._route("oracle", "POST", "api/chat/opener",
                                          body={"reasons": reasons, "avoid": avoid, "past": state["past"]},
                                          timeout=90)
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
               "trace_id": trace_id, "trigger": "manual" if force else "periodic", "drive": state["drive"],
               "answered": None}
        if not self._deliver(row):
            self._wait(now, RETRY_AFTER_FAILURE)
            return {"status": "failed", "detail": "messaggio non consegnato"}
        self._store(row, now)
        with self._lock:
            self._sent.insert(0, {**row, "at": now.isoformat()})
        self._wait(now, get_int(S.TALK_MIN_GAP_HOURS) * 3600)
        logger.info("event=talk_sent trace_id=%s chars=%d reasons=%d drive=%.2f trigger=%s", trace_id, len(text),
                    len(reasons), state["drive"], row["trigger"])
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


def _mood(summary: dict) -> str:
    bits = [str(summary.get("mood_word"))]
    if summary.get("energy"):
        bits.append(f"energy {summary['energy']}/5")
    if summary.get("stress"):
        bits.append(f"stress {summary['stress']}/5")
    causes = [str(c) for c in (summary.get("causes") or [])][:3]
    return ", ".join(bits) + (f" (because of {', '.join(causes)})" if causes else "")
