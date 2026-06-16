"""Athena Memory Consolidator — daily per-user memory analysis.

Runs once per day (configurable window). For each active user:
  1. Reads chat history since last consolidation from Archive
  2. Calls Oracle LLM to extract durable facts and detect patterns
  3. Cross-session consolidation: conflict detection, reinforcement, decay
  4. Writes consolidated memories to Archive
  5. Publishes insights as Athena hints to Oracle
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger("hestia_athena.consolidator")

# ── Config ──────────────────────────────────────────────────────────────────

_CONSOLIDATION_WINDOW_START = int(os.getenv("ATHENA_CONSOLIDATION_WINDOW_START", "3"))   # 3 AM
_CONSOLIDATION_WINDOW_END = int(os.getenv("ATHENA_CONSOLIDATION_WINDOW_END", "5"))       # 5 AM
_CONSOLIDATION_ACTIVE_DAYS = int(os.getenv("ATHENA_CONSOLIDATION_ACTIVE_DAYS", "7"))     # Users active in last 7 days
_CONSOLIDATION_LOOKBACK_HOURS = int(os.getenv("ATHENA_CONSOLIDATION_LOOKBACK_HOURS", "24"))
_ORACLE_LLM_TIMEOUT = int(os.getenv("ATHENA_CONSOLIDATION_ORACLE_TIMEOUT_SEC", "30"))
_PREFERENCE_DECAY_DAYS = int(os.getenv("ATHENA_PREFERENCE_DECAY_DAYS", "90"))
_PREFERENCE_REINFORCE_THRESHOLD = int(os.getenv("ATHENA_PREFERENCE_REINFORCE_THRESHOLD", "3"))


class MemoryConsolidator:
    """Daily per-user memory analysis and consolidation."""

    def __init__(self, hub_api_url: str):
        self._hub_url = hub_api_url.rstrip("/")
        self._archive_route = f"{self._hub_url}/route/archive"
        self._oracle_route = f"{self._hub_url}/route/oracle"
        self._last_consolidation: dict[str, float] = {}  # session_id → timestamp

    # ── Scheduling ──────────────────────────────────────────────────────────

    def should_run(self) -> bool:
        """Return True if we're within the configured consolidation window."""
        now = datetime.now()
        return _CONSOLIDATION_WINDOW_START <= now.hour < _CONSOLIDATION_WINDOW_END

    def get_active_sessions(self) -> list[str]:
        """Return session IDs with activity in the last N days."""
        try:
            since = (datetime.now() - timedelta(days=_CONSOLIDATION_ACTIVE_DAYS)).isoformat()
            resp = requests.get(
                f"{self._archive_route}/chat/history/all",
                params={"since": since},
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            payload = resp.json().get("payload", resp.json())
            sessions = payload if isinstance(payload, list) else payload.get("sessions", [])
            return [s for s in sessions if isinstance(s, str)]
        except Exception as exc:
            logger.warning("event=consolidator_get_sessions_failed error=%s", exc)
            return []

    def needs_consolidation(self, session_id: str) -> bool:
        """Check if enough time has passed since last consolidation for this session."""
        last = self._last_consolidation.get(session_id, 0)
        return (time.time() - last) > (_CONSOLIDATION_LOOKBACK_HOURS * 3600)

    # ── Consolidation ───────────────────────────────────────────────────────

    def consolidate(self, session_id: str) -> dict[str, Any]:
        """Run full consolidation for one user session. Returns summary dict."""
        self._last_consolidation[session_id] = time.time()
        result = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "facts_extracted": 0,
            "conflicts_detected": 0,
            "patterns_reinforced": 0,
            "preferences_decayed": 0,
        }

        try:
            # 1. Read chat history since last consolidation
            messages = self._fetch_chat_history(session_id)
            if not messages:
                return result

            # 2. Read existing active memories
            existing_memories = self._fetch_active_memories()

            # 3. Call Oracle LLM for extraction + analysis
            analysis = self._analyze_with_oracle(session_id, messages, existing_memories)
            if not analysis:
                return result

            # 4. Process extracted facts
            facts = analysis.get("facts", [])
            for fact in facts:
                if self._save_memory(session_id, fact):
                    result["facts_extracted"] += 1

            # 5. Detect and resolve conflicts
            conflicts = analysis.get("conflicts", [])
            for conflict in conflicts:
                self._resolve_conflict(conflict)
                result["conflicts_detected"] += 1

            # 6. Reinforce repeated patterns
            patterns = analysis.get("patterns", [])
            for pattern in patterns:
                self._reinforce_pattern(pattern)
                result["patterns_reinforced"] += 1

            # 7. Decay old unused preferences
            decayed = self._decay_old_preferences(existing_memories)
            result["preferences_decayed"] = decayed

            # 8. Publish hint to Oracle
            if result["facts_extracted"] > 0 or result["conflicts_detected"] > 0:
                self._publish_hint(session_id, analysis)

        except Exception as exc:
            logger.warning("event=consolidator_session_failed session=%s error=%s", session_id, exc)

        return result

    # ── Private helpers ─────────────────────────────────────────────────────

    def _fetch_chat_history(self, session_id: str) -> list[dict]:
        try:
            resp = requests.get(
                f"{self._archive_route}/chat/history/{session_id}",
                params={"limit": 200},
                timeout=10,
            )
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload.get("payload", payload.get("messages", []))
            return []
        except Exception:
            return []

    def _fetch_active_memories(self) -> list[dict]:
        try:
            resp = requests.get(
                f"{self._archive_route}/memory/active",
                params={"memory_class": "durable_user_preference"},
                timeout=10,
            )
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload.get("payload", [])
            return []
        except Exception:
            return []

    def _analyze_with_oracle(self, session_id: str, messages: list[dict],
                             existing_memories: list[dict]) -> dict | None:
        """Call Oracle LLM to extract facts, detect conflicts, identify patterns."""
        history_text = "\n".join(
            f"{'User' if m.get('role') == 'user' else 'Hestia'}: {str(m.get('content', ''))[:300]}"
            for m in messages[-50:]  # Last 50 messages
        )
        existing_text = "\n".join(
            f"[ID:{m.get('id')}] {m.get('fact', '')}" for m in existing_memories[:30]
        ) or "(nessuna memoria esistente)"

        prompt = (
            "You are Hestia's memory consolidator. Analyze the conversation and extract "
            "durable facts, detect conflicts with existing memories, and identify "
            "reinforced patterns. Output ONLY valid JSON.\n\n"
            "CONVERSATION:\n{history}\n\n"
            "EXISTING MEMORIES:\n{existing}\n\n"
            "Return JSON with:\n"
            '{{"facts": [{{"fact": "...", "domain": "general", "confidence": 0.8}}],\n'
            ' "conflicts": [{{"old_id": 1, "new_fact": "...", "resolution": "replace_new"}}],\n'
            ' "patterns": [{{"fact": "...", "occurrences": 3, "domains": ["scout"]}}],\n'
            ' "summary": "one-line summary of what changed"}}\n\n'
            "Rules:\n"
            "- facts: only durable, reusable facts (not temporary chat topics)\n"
            "- conflicts: when new info contradicts an existing memory ID\n"
            "- patterns: facts mentioned multiple times across sessions\n"
            "- If nothing new, return empty arrays\n"
        ).format(history=history_text, existing=existing_text)

        try:
            resp = requests.post(
                f"{self._oracle_route}/api/llm/generate",
                json={"prompt": prompt, "model": os.getenv("ATHENA_STRATEGIST_MODEL", ""),
                      "provider": os.getenv("ATHENA_STRATEGIST_PROVIDER", "")},
                timeout=_ORACLE_LLM_TIMEOUT,
            )
            if resp.status_code == 200:
                payload = resp.json()
                raw = payload.get("payload", payload).get("response", "")
                return json.loads(self._extract_json(raw))
        except Exception as exc:
            logger.warning("event=consolidator_oracle_call_failed error=%s", exc)
        return None

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Extract JSON object from LLM output that may have surrounding text."""
        raw = raw.strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1 and e > s:
            return raw[s:e + 1]
        return raw

    def _save_memory(self, session_id: str, fact: dict) -> bool:
        try:
            resp = requests.post(
                f"{self._archive_route}/memory",
                json={
                    "fact": fact.get("fact", ""),
                    "domain": fact.get("domain", "general"),
                    "weight": fact.get("confidence", 0.8),
                    "memory_class": "durable_user_preference",
                },
                timeout=8,
            )
            return resp.status_code < 400
        except Exception:
            return False

    def _resolve_conflict(self, conflict: dict) -> None:
        old_id = conflict.get("old_id")
        resolution = conflict.get("resolution", "replace_new")
        if resolution == "replace_new" and old_id:
            try:
                requests.patch(
                    f"{self._archive_route}/memory/{old_id}",
                    json={"is_active": False},
                    timeout=8,
                )
            except Exception:
                pass

    def _reinforce_pattern(self, pattern: dict) -> None:
        occurrences = int(pattern.get("occurrences", 0))
        if occurrences < _PREFERENCE_REINFORCE_THRESHOLD:
            return
        try:
            requests.post(
                f"{self._archive_route}/memory",
                json={
                    "fact": f"[REINFORCED x{occurrences}] {pattern.get('fact', '')}",
                    "domain": pattern.get("domains", ["general"])[0] if pattern.get("domains") else "general",
                    "weight": min(1.0, 0.5 + (occurrences * 0.1)),
                    "memory_class": "durable_user_preference",
                },
                timeout=8,
            )
        except Exception:
            pass

    def _decay_old_preferences(self, existing_memories: list[dict]) -> int:
        """Reduce weight of preferences not mentioned in >90 days. Returns count decayed."""
        decayed = 0
        cutoff = (datetime.now() - timedelta(days=_PREFERENCE_DECAY_DAYS)).isoformat()
        for mem in existing_memories:
            updated_at = mem.get("updated_at", mem.get("created_at", ""))
            if updated_at and updated_at < cutoff:
                current_weight = float(mem.get("weight", 1.0))
                if current_weight <= 0.2:
                    # Fully deprecate
                    try:
                        requests.patch(
                            f"{self._archive_route}/memory/{mem.get('id')}",
                            json={"is_active": False},
                            timeout=8,
                        )
                        decayed += 1
                    except Exception:
                        pass
                else:
                    # Reduce weight
                    try:
                        requests.patch(
                            f"{self._archive_route}/memory/{mem.get('id')}",
                            json={"weight": round(current_weight * 0.7, 2)},
                            timeout=8,
                        )
                        decayed += 1
                    except Exception:
                        pass
        return decayed

    def _publish_hint(self, session_id: str, analysis: dict) -> None:
        summary = analysis.get("summary", "Memory consolidation completed.")
        try:
            requests.post(
                f"{self._oracle_route}/api/athena/hints",
                json={
                    "hint_type": "memory_consolidation",
                    "session_id": session_id,
                    "summary": summary,
                    "priority": "low",
                    "domains": ["general"],
                    "brief": {
                        "facts_extracted": len(analysis.get("facts", [])),
                        "conflicts_resolved": len(analysis.get("conflicts", [])),
                        "patterns_reinforced": len(analysis.get("patterns", [])),
                    },
                    "ttl_seconds": 86400,
                },
                timeout=8,
            )
        except Exception as exc:
            logger.debug("event=consolidator_hint_publish_failed error=%s", exc)
