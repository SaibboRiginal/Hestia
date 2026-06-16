"""Conversation Auditor — on-demand quality scoring of Oracle chat turns.

Invoked via the athena_audit_conversation MCP tool. Pulls recent chat
history from Archive, scores each assistant turn with the reasoning model,
and persists grades via Archive's feedback_submit endpoint.

Design:
- Single round-trip to the reasoning model per batch (not per turn).
- Compact prompt — only user + assistant content, no metadata.
- On-demand only — no cron, no autonomous loop.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger("hestia_athena.auditor")

AUDITOR_TIMEOUT = float(os.getenv("ATHENA_AUDITOR_TIMEOUT_SECONDS", "40"))
AUDITOR_MODEL = os.getenv("ATHENA_AUDITOR_MODEL", "")
AUDITOR_PROVIDER = os.getenv("ATHENA_AUDITOR_PROVIDER", "")
AUDITOR_MAX_TURNS = int(os.getenv("ATHENA_AUDITOR_MAX_TURNS", "20"))

_JUDGE_PROMPT = (
    "Sei un valutatore di qualità per un assistente AI chiamato Hestia.\n"
    "Valuta OGNI risposta dell'assistente qui sotto su tre dimensioni (1-5):\n"
    "1. stile: niente chiusure pushy, niente offerte di aiuto non richieste, conciso\n"
    "2. accuratezza: i fatti corrispondono ai dati forniti, nessuna allucinazione\n"
    "3. utilita: risponde direttamente alla domanda dell'utente\n\n"
    "Rispondi SOLO con un array JSON di oggetti con questa struttura:\n"
    '{{"turn": <indice 0-based>, "style": <1-5>, "accuracy": <1-5>, '
    '"usefulness": <1-5>, "overall": "<excellent|good|mixed|poor|rejected>", '
    '"notes": "<breve nota>"}}\n\n'
    "CONVERSAZIONE DA VALUTARE:\n"
    "{conversation_text}"
)


class ConversationAuditor:
    """On-demand conversation quality auditor."""

    def __init__(self, hub_api_url: str) -> None:
        self._hub_url = hub_api_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "Hestia-Athena-Auditor/1.0",
        })

    def audit_session(
        self,
        session_id: str,
        limit: int = AUDITOR_MAX_TURNS,
    ) -> dict[str, Any]:
        """Score recent assistant turns for *session_id*.

        Returns a dict with ``turns_scored``, ``scores``, and ``submitted`` counts.
        """
        limit = max(1, min(limit, 100))
        history = self._fetch_chat_history(session_id, limit)
        if not history:
            return {
                "status": "no_history",
                "session_id": session_id,
                "turns_scored": 0,
                "scores": [],
                "submitted": 0,
            }

        assistant_turns = [
            (i, msg)
            for i, msg in enumerate(history)
            if msg.get("role") == "assistant"
        ]
        if not assistant_turns:
            return {
                "status": "no_assistant_turns",
                "session_id": session_id,
                "turns_scored": 0,
                "scores": [],
                "submitted": 0,
            }

        scores = self._score_turns(history, assistant_turns)
        submitted = 0
        for entry in scores:
            if self._submit_score(session_id, entry):
                submitted += 1

        return {
            "status": "ok",
            "session_id": session_id,
            "turns_scored": len(scores),
            "scores": scores,
            "submitted": submitted,
        }

    # ── Private helpers ─────────────────────────────────────────────────────

    def _fetch_chat_history(
        self, session_id: str, limit: int
    ) -> list[dict[str, Any]]:
        """Pull recent chat history from Archive via Hub routing."""
        try:
            route_url = (
                f"{self._hub_url}/route/archive/api/chat/history/"
                f"{session_id}?limit={limit}"
            )
            envelope = {
                "method": "GET",
                "headers": {},
                "query": {"limit": limit},
                "body": None,
                "timeout_seconds": 10,
            }
            resp = self._session.post(
                route_url,
                json=envelope,
                timeout=14,
            )
            if resp.status_code != 200:
                logger.warning(
                    "event=auditor_history_fetch_failed "
                    "status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return []
            routed = resp.json() if resp.content else {}
            payload = (routed or {}).get("payload") if isinstance(routed, dict) else None
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict) and isinstance(payload.get("history"), list):
                return payload["history"]
            return []
        except Exception as exc:
            logger.warning(
                "event=auditor_history_fetch_exception error=%s", exc
            )
            return []

    def _score_turns(
        self,
        full_history: list[dict[str, Any]],
        assistant_turns: list[tuple[int, dict]],
    ) -> list[dict[str, Any]]:
        """Call the reasoning model to score all assistant turns in one batch."""
        conversation_lines: list[str] = []
        for i, msg in enumerate(full_history):
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))[:500]
            if role == "assistant":
                conversation_lines.append(f"[{i}] ASSISTANT: {content}")
            else:
                conversation_lines.append(f"[{i}] USER: {content}")

        conversation_text = "\n".join(conversation_lines)
        prompt = _JUDGE_PROMPT.format(conversation_text=conversation_text)

        try:
            raw = self._call_oracle_llm(prompt)
            if not raw:
                return []
            return self._parse_scores(raw, assistant_turns)
        except Exception as exc:
            logger.warning(
                "event=auditor_scoring_failed error=%s", exc
            )
            return []

    def _call_oracle_llm(self, prompt: str) -> str | None:
        """Call Oracle's LLM generate endpoint via Hub routing."""
        body = {
            "prompt": prompt,
            "model": AUDITOR_MODEL,
            "provider": AUDITOR_PROVIDER,
        }
        envelope = {
            "method": "POST",
            "headers": {},
            "query": {},
            "body": body,
            "timeout_seconds": AUDITOR_TIMEOUT,
        }
        route_url = f"{self._hub_url}/route/oracle/api/llm/generate"
        try:
            resp = self._session.post(
                route_url,
                json=envelope,
                timeout=AUDITOR_TIMEOUT + 4,
            )
            if resp.status_code != 200:
                logger.warning(
                    "event=auditor_oracle_route_failed status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            routed = resp.json() if resp.content else {}
            return (routed or {}).get("payload", {}).get("response", "")
        except Exception as exc:
            logger.warning(
                "event=auditor_oracle_call_exception error=%s", exc
            )
            return None

    @staticmethod
    def _parse_scores(
        raw_response: str,
        assistant_turns: list[tuple[int, dict]],
    ) -> list[dict[str, Any]]:
        """Extract JSON array from LLM response and map to turn indices."""
        # Try JSON array extraction
        try:
            # Find JSON array in response
            match = re.search(r"\[.*\]", raw_response, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, list):
                    return [
                        {
                            "turn": item.get("turn", i),
                            "style": int(item.get("style", 3)),
                            "accuracy": int(item.get("accuracy", 3)),
                            "usefulness": int(item.get("usefulness", 3)),
                            "overall": str(item.get("overall", "mixed")),
                            "notes": str(item.get("notes", ""))[:200],
                        }
                        for i, item in enumerate(parsed)
                        if isinstance(item, dict)
                    ]
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "event=auditor_parse_failed error=%s raw=%s",
                exc,
                raw_response[:300],
            )
        return []

    def _submit_score(
        self,
        session_id: str,
        entry: dict[str, Any],
    ) -> bool:
        """Persist a single score via Archive's feedback_submit (Hub-routed)."""
        try:
            route_url = f"{self._hub_url}/route/archive/api/feedback"
            body = {
                "session_id": session_id,
                "quality_label": entry.get("overall", "mixed"),
                "quality_score": max(
                    entry.get("style", 3),
                    entry.get("accuracy", 3),
                    entry.get("usefulness", 3),
                ),
                "feedback_text": entry.get("notes", ""),
                "tags": [
                    "athena_audit",
                    f"style={entry.get('style', 3)}",
                    f"accuracy={entry.get('accuracy', 3)}",
                    f"usefulness={entry.get('usefulness', 3)}",
                ],
            }
            envelope = {
                "method": "POST",
                "headers": {},
                "query": {},
                "body": body,
                "timeout_seconds": 8,
            }
            resp = self._session.post(
                route_url,
                json=envelope,
                timeout=12,
            )
            return resp.status_code < 400
        except Exception as exc:
            logger.warning(
                "event=auditor_submit_score_failed error=%s", exc
            )
            return False
