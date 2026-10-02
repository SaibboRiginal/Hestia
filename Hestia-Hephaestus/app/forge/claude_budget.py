"""Claude Pro budget window — spend only the leftover weekly quota.

The Pro plan has a weekly limit that resets at a fixed moment. Policy:

- On-demand (the user asks): always allowed.
- Autonomous (Athena/Argus) tasks on the ``claude`` engine wait in state
  ``scheduled`` and start only:
    * at night (``night`` interval, local time) during the last
      ``window_hours`` before the weekly reset, max ``night_max_tasks`` per night;
    * any time, without cap, in the last ``final_hours`` before the reset
      (whatever is left would be lost anyway).
- When Claude reports the usage limit, everything pauses until the reset.

The real remaining % is not exposed to programs, so the policy is time-based
plus the limit signal from Claude itself.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
         "lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6}
_LIMIT_PATTERN = re.compile(r"usage limit|limit reached|rate.?limit|quota|limite di utilizzo", re.I)


def _parse_hhmm(text: str) -> time:
    hh, _, mm = str(text).strip().partition(":")
    return time(int(hh) % 24, int(mm or 0) % 60)


@dataclass
class ClaudeSchedule:
    reset_day: str = "mon"          # weekday of the weekly reset (mon..sun / lun..dom)
    reset_time: str = "09:00"       # local time of the reset
    tz: str = "Europe/Rome"
    window_hours: int = 48          # autonomous use only in the last N hours before reset
    night: str = "00:00-07:00"      # allowed local hours inside the window
    night_max_tasks: int = 3        # cap per night (not applied in final hours)
    final_hours: int = 6            # last N hours: any time, no cap

    def validate(self) -> "ClaudeSchedule":
        if self.reset_day.lower()[:3] not in _DAYS:
            raise ValueError(f"reset_day must be one of {sorted(set(_DAYS))}")
        _parse_hhmm(self.reset_time)
        start, _, end = self.night.partition("-")
        _parse_hhmm(start), _parse_hhmm(end)
        ZoneInfo(self.tz)
        self.window_hours = max(1, int(self.window_hours))
        self.final_hours = max(0, min(int(self.final_hours), self.window_hours))
        self.night_max_tasks = max(0, int(self.night_max_tasks))
        return self


@dataclass
class ClaudeBudgetState:
    blocked_until: str | None = None          # ISO: usage limit hit -> wait for reset
    night_starts: dict[str, int] = field(default_factory=dict)   # night key -> tasks started


class ClaudeBudget:
    def __init__(self, schedule: ClaudeSchedule, state: ClaudeBudgetState | None = None):
        self.schedule = schedule.validate()
        self.state = state or ClaudeBudgetState()

    # ── time math ───────────────────────────────────────────────────────────
    def _tz(self) -> ZoneInfo:
        return ZoneInfo(self.schedule.tz)

    def now(self) -> datetime:
        return datetime.now(self._tz())

    def next_reset(self, now: datetime | None = None) -> datetime:
        now = (now or self.now()).astimezone(self._tz())
        target_day = _DAYS[self.schedule.reset_day.lower()[:3]]
        reset_t = _parse_hhmm(self.schedule.reset_time)
        days_ahead = (target_day - now.weekday()) % 7
        candidate = datetime.combine(now.date() + timedelta(days=days_ahead), reset_t, tzinfo=self._tz())
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    def _in_night(self, now: datetime) -> tuple[bool, str]:
        start_s, _, end_s = self.schedule.night.partition("-")
        start, end = _parse_hhmm(start_s), _parse_hhmm(end_s)
        t = now.timetz().replace(tzinfo=None)
        if start <= end:
            inside = start <= t < end
            key_date = now.date()
        else:  # crosses midnight, e.g. 23:00-06:00
            inside = t >= start or t < end
            key_date = now.date() if t >= start else now.date() - timedelta(days=1)
        return inside, key_date.isoformat()

    # ── policy ──────────────────────────────────────────────────────────────
    def status(self, now: datetime | None = None) -> dict[str, Any]:
        now = (now or self.now()).astimezone(self._tz())
        reset = self.next_reset(now)
        hours_left = (reset - now).total_seconds() / 3600
        in_night, night_key = self._in_night(now)
        used_tonight = self.state.night_starts.get(night_key, 0)

        if self.state.blocked_until and now < datetime.fromisoformat(self.state.blocked_until):
            phase, allowed, reason = "exhausted", False, "quota esaurita: attendo il reset settimanale"
        elif hours_left <= self.schedule.final_hours:
            phase, allowed, reason = "final", True, "ultime ore prima del reset: uso tutto il residuo"
        elif hours_left <= self.schedule.window_hours and in_night:
            allowed = used_tonight < self.schedule.night_max_tasks
            phase = "night"
            reason = ("finestra notturna" if allowed
                      else f"tetto notturno raggiunto ({used_tonight}/{self.schedule.night_max_tasks})")
        else:
            phase, allowed, reason = "closed", False, "fuori finestra (notti prima del reset)"
        return {
            "phase": phase, "allowed": allowed, "reason": reason,
            "next_reset": reset.isoformat(), "hours_to_reset": round(hours_left, 1),
            "used_tonight": used_tonight, "schedule": asdict(self.schedule),
            "blocked_until": self.state.blocked_until,
        }

    def can_start(self, now: datetime | None = None) -> tuple[bool, str]:
        st = self.status(now)
        return st["allowed"], st["reason"]

    def record_start(self, now: datetime | None = None) -> None:
        now = (now or self.now()).astimezone(self._tz())
        _, key = self._in_night(now)
        self.state.night_starts[key] = self.state.night_starts.get(key, 0) + 1
        # keep only recent nights
        for old in sorted(self.state.night_starts)[:-14]:
            self.state.night_starts.pop(old, None)

    def mark_exhausted(self, now: datetime | None = None) -> str:
        reset = self.next_reset(now)
        self.state.blocked_until = reset.isoformat()
        return self.state.blocked_until

    @staticmethod
    def looks_like_limit(text: str) -> bool:
        return bool(_LIMIT_PATTERN.search(str(text or "")))
