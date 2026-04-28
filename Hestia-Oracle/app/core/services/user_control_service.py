"""UserControlService — durable user controllability surface (P1-9).

Responsibilities:
- Persist/read user controls via Archive memory rows (Hub-routed).
- Allow direct API updates with validation.
- Extract control updates from free-form conversation using the scribe model.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_CONTROL_DOMAIN = "user_controls"
_CONTROL_CLASS = "durable_user_preference"
_CONTROL_PREFIX = "[CONTROL]"
_ALLOWED_AGGRESSIVENESS = {"low", "normal", "high"}
_DEFAULT_CATEGORIES = ["alerts", "tasks", "reminders", "insights"]

_EXTRACT_PROMPT = """
You are Hestia's control extractor.

Given a user message, extract ONLY durable controllability updates.
If there is no clear control change, output NONE.

Control schema (partial object allowed):
{
  "proactive_enabled": true|false,
  "allowed_categories": ["alerts","tasks","reminders","insights", "..."],
  "quiet_hours": {
    "enabled": true|false,
    "start": "HH:MM",
    "end": "HH:MM"
  },
  "reminder_aggressiveness": "low"|"normal"|"high",
  "dont_ask_again": ["topic1", "topic2"],
  "reset_scope": "primary"|"branch"
}

Rules:
- Output ONLY JSON object or NONE.
- Do not invent fields outside schema.
- Use 24h HH:MM format for quiet hours when present.

USER MESSAGE:
{user_message}
"""


class UserControlService:
    """Durable control storage and extraction."""

    def __init__(self, hub_client, scribe_agent, fallback_scribe_agent) -> None:
        self._hub = hub_client
        self._scribe = scribe_agent
        self._fallback_scribe = fallback_scribe_agent

    @staticmethod
    def _defaults() -> dict:
        return {
            "proactive_enabled": True,
            "allowed_categories": list(_DEFAULT_CATEGORIES),
            "quiet_hours": {
                "enabled": False,
                "start": "22:00",
                "end": "07:00",
            },
            "reminder_aggressiveness": "normal",
            "dont_ask_again": [],
            "reset_scope": "primary",
        }

    def _ask(self, prompt: str) -> str:
        try:
            return self._scribe.ask(prompt).strip()
        except Exception:
            try:
                return self._fallback_scribe.ask(prompt).strip()
            except Exception:
                return "NONE"

    def _list_control_rows(self) -> list[dict]:
        rows = self._hub.get(
            f"/memory/active?domain={_CONTROL_DOMAIN}&memory_class={_CONTROL_CLASS}",
            default=[],
        ) or []
        if not rows:
            rows = self._hub.get(
                f"/memory/active?domain={_CONTROL_DOMAIN}", default=[]) or []
        if not isinstance(rows, list):
            return []
        return rows

    @staticmethod
    def _parse_control_fact(fact: str) -> dict | None:
        text = str(fact or "").strip()
        if not text.startswith(_CONTROL_PREFIX):
            return None
        payload = text[len(_CONTROL_PREFIX):].strip()
        try:
            data = json.loads(payload)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _normalize_hhmm(value: str) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip().replace(".", ":")
        if not re.match(r"^\d{1,2}:\d{2}$", value):
            return None
        hh, mm = value.split(":", 1)
        try:
            h = int(hh)
            m = int(mm)
        except ValueError:
            return None
        if h < 0 or h > 23 or m < 0 or m > 59:
            return None
        return f"{h:02d}:{m:02d}"

    def _normalize_patch(self, patch: dict) -> dict:
        out: dict = {}

        if isinstance(patch.get("proactive_enabled"), bool):
            out["proactive_enabled"] = bool(patch["proactive_enabled"])

        allowed_categories = patch.get("allowed_categories")
        if isinstance(allowed_categories, list):
            cleaned = []
            seen = set()
            for item in allowed_categories:
                value = str(item).strip().lower()
                if not value or value in seen:
                    continue
                seen.add(value)
                cleaned.append(value)
            if cleaned:
                out["allowed_categories"] = cleaned

        quiet = patch.get("quiet_hours")
        if isinstance(quiet, dict):
            q: dict = {}
            if isinstance(quiet.get("enabled"), bool):
                q["enabled"] = bool(quiet.get("enabled"))
            start = self._normalize_hhmm(
                str(quiet.get("start", ""))) if "start" in quiet else None
            end = self._normalize_hhmm(
                str(quiet.get("end", ""))) if "end" in quiet else None
            if start:
                q["start"] = start
            if end:
                q["end"] = end
            if q:
                out["quiet_hours"] = q

        aggressiveness = str(
            patch.get("reminder_aggressiveness", "")).strip().lower()
        if aggressiveness in _ALLOWED_AGGRESSIVENESS:
            out["reminder_aggressiveness"] = aggressiveness

        dont_ask_again = patch.get("dont_ask_again")
        if isinstance(dont_ask_again, list):
            cleaned = []
            seen = set()
            for item in dont_ask_again:
                value = str(item).strip().lower()
                if not value or value in seen:
                    continue
                seen.add(value)
                cleaned.append(value)
            out["dont_ask_again"] = cleaned

        reset_scope = str(patch.get("reset_scope", "")).strip().lower()
        if reset_scope in {"primary", "branch"}:
            out["reset_scope"] = reset_scope

        return out

    @staticmethod
    def _merge(base: dict, patch: dict) -> dict:
        merged = dict(base)
        for key, value in patch.items():
            if key == "quiet_hours" and isinstance(value, dict):
                existing = dict(merged.get("quiet_hours") or {})
                existing.update(value)
                merged["quiet_hours"] = existing
            else:
                merged[key] = value
        return merged

    def _save_controls(self, controls: dict, source: str) -> bool:
        fact = f"{_CONTROL_PREFIX} {json.dumps(controls, ensure_ascii=False)}"
        payload = {
            "fact": fact,
            "domain": _CONTROL_DOMAIN,
            "weight": 1.0,
            "memory_class": _CONTROL_CLASS,
            "meta": {"source": source},
        }
        try:
            self._hub.post("/memory", payload)
            return True
        except Exception as exc:
            logger.warning("Control save failed: %s", exc)
            return False

    def get_controls(self) -> dict:
        rows = self._list_control_rows()
        parsed: list[tuple[int, dict]] = []
        for row in rows:
            fact_data = self._parse_control_fact(str(row.get("fact", "")))
            if not fact_data:
                continue
            row_id = int(row.get("id", 0) or 0)
            parsed.append((row_id, fact_data))

        controls = self._defaults()
        if not parsed:
            return controls

        _, latest = sorted(parsed, key=lambda x: x[0])[-1]
        normalized = self._normalize_patch(latest)
        return self._merge(controls, normalized)

    def update_controls(self, patch: dict, source: str = "api") -> tuple[dict, bool]:
        normalized = self._normalize_patch(patch or {})
        if not normalized:
            current = self.get_controls()
            return current, False

        current = self.get_controls()
        merged = self._merge(current, normalized)
        saved = self._save_controls(merged, source=source)
        return merged, saved

    def extract_and_save_controls(self, user_message: str) -> list[dict]:
        prompt = _EXTRACT_PROMPT.format(user_message=user_message)
        raw = self._ask(prompt)
        if not raw or raw.strip().upper() == "NONE":
            return []

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned).rstrip("`\n ")

        try:
            candidate = json.loads(cleaned)
        except Exception:
            return []
        if not isinstance(candidate, dict):
            return []

        controls, saved = self.update_controls(candidate, source="scribe")
        if not saved:
            return []

        return [{
            "event": "user.controls.updated",
            "message": "Controlli utente aggiornati.",
            "data": controls,
        }]
