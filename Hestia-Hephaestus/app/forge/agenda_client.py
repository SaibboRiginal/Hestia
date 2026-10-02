"""Forge ↔ assistant agenda (Chronos) — rules as data, editable by the user.

Forge registers its Claude Pro windows in the assistant agenda and asks Chronos
whether they are open. If the user moves/skips/cancels them in the agenda,
Forge follows. Chronos unreachable → callers fall back to the built-in schedule.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..core.shared_imports import import_shared_symbol
from .claude_budget import ClaudeSchedule, _DAYS, _parse_hhmm

_SharedAgendaClient = import_shared_symbol("hestia_common.agenda_client", "AgendaClient")

logger = logging.getLogger("hestia_hephaestus.forge.agenda")

OWNER = "hephaestus"
KEY_NIGHTS = "forge.claude_nights"
KEY_FINAL = "forge.claude_final"
_RRULE_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


class AgendaClient(_SharedAgendaClient):
    """Shared assistant-agenda client + Forge specifics (Claude windows, task mirror)."""

    def __init__(self, hub_api_url: str):
        super().__init__(OWNER, hub_api_url)

    # ── Claude windows ──────────────────────────────────────────────────────
    @staticmethod
    def claude_rules(s: ClaudeSchedule) -> list[dict]:
        """Translate the budget schedule into two weekly agenda windows."""
        reset_wd = _DAYS[s.reset_day.lower()[:3]]
        reset_t = _parse_hhmm(s.reset_time)
        night_start_s, _, night_end_s = s.night.partition("-")
        n_start, n_end = _parse_hhmm(night_start_s), _parse_hhmm(night_end_s)
        # Reference week anchored on a Monday; reset at its weekday/time.
        ref_monday = datetime(2026, 1, 5)
        reset = datetime.combine(ref_monday.date() + timedelta(days=reset_wd), reset_t) + timedelta(days=7)
        window_open = reset - timedelta(hours=s.window_hours)
        days: list[str] = []
        for offset in range(-1, 10):
            day = (reset - timedelta(days=offset)).date()
            n_s = datetime.combine(day, n_start)
            n_e = datetime.combine(day + timedelta(days=1 if n_end <= n_start else 0), n_end)
            if n_e > window_open and n_s < reset:
                code = _RRULE_DAYS[n_s.weekday()]
                if code not in days:
                    days.append(code)
        night_len_min = int(((datetime.combine(ref_monday, n_end) - datetime.combine(ref_monday, n_start))
                             .total_seconds() // 60) % (24 * 60)) or 24 * 60
        first_night = datetime.combine(ref_monday.date(), n_start)
        final_start = reset - timedelta(hours=s.final_hours)
        rules = [{
            "key": KEY_NIGHTS, "type": "window", "title": "Claude Pro: notti prima del reset",
            "description": f"Lavoro automatico su Claude Pro (max {s.night_max_tasks}/notte). Salta una notte per bloccarla.",
            "start_at": first_night.isoformat(), "end_at": (first_night + timedelta(minutes=night_len_min)).isoformat(),
            "recurrence": f"FREQ=WEEKLY;BYDAY={','.join(days) or 'SU'}", "tz": s.tz,
            "params": {"night_max_tasks": s.night_max_tasks},
        }]
        if s.final_hours > 0:
            rules.append({
                "key": KEY_FINAL, "type": "window", "title": "Claude Pro: ultime ore prima del reset",
                "description": "Usa tutto il residuo settimanale.",
                "start_at": (final_start - timedelta(days=7)).isoformat(),
                "end_at": (reset - timedelta(days=7)).isoformat(),
                "recurrence": "FREQ=WEEKLY", "tz": s.tz,
            })
        return rules

    def register_claude_windows(self, s: ClaudeSchedule, force: bool = False) -> bool:
        """Idempotent defaults. ``force`` (schedule changed from Forge settings) updates them."""
        try:
            rules = self.claude_rules(s)
            if force:
                for rule in rules:
                    status, _ = self._call("PATCH", f"api/agenda/items/{rule['key']}", body={
                        **{k: rule[k] for k in ("title", "description", "start_at", "end_at", "recurrence")},
                        "params": rule.get("params"), "status": "confirmed", "by": OWNER})
                    if status == 404:
                        force = False
                        break
            if not force:
                status, _ = self._call("POST", "api/agenda/register", body={"owner": OWNER, "rules": rules})
                return status < 400
            return True
        except Exception as exc:
            logger.warning("[🔄] event=forge_agenda_register_failed error=%s", exc)
            return False

    # ── Forge tasks mirrored in the agenda (key forge.task.<id>) ────────────
    @staticmethod
    def task_key(task_id: str) -> str:
        return f"forge.task.{task_id}"

    def show_task(self, task_id: str, title: str, start_at: str, description: str = "") -> None:
        self.show(self.task_key(task_id), f"Forge: {title[:80]}", start_at, description=description[:500],
                  params={"task_id": task_id})

    def hide_task(self, task_id: str) -> None:
        self.done(self.task_key(task_id))
