"""Strategist — LLM-powered reasoning via Oracle for Athena's thinking loop.

Design goals for local/resource-constrained execution:
- Compact prompts (never stuff full entity payloads).
- Structured output requested via simple key:value format (easier to parse
  than JSON from smaller local models).
- Single round-trip to Oracle per cycle — no multi-step chain-of-thought
  that burns context.
- Fallback: if Oracle is unavailable the loop still completes with an
  empty candidate set (the relevance gate already provides a baseline).
"""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

import requests

from . import athena_settings as S
from .athena_settings import get_bool, get_float, get_int
from .schemas import ActionCandidate, ObservationSnapshot, RelevanceSignals
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_athena.strategist")

# Enabled / timeout / max candidates: central settings athena.strategist.* (read at use time).
# Model choice belongs to Oracle: use case ``athena.strategia`` (declared in main.LLM_USECASES).


def _build_observation_prompt(snapshot: ObservationSnapshot) -> str:
    """Build a compact observation text for the Oracle prompt.

    Kept deliberately short — local models have limited context windows.
    """
    lines: list[str] = []

    # Service health (most important signal)
    if snapshot.unhealthy_services:
        lines.append(
            tr("Servizi non sani: {0}.", ', '.join(snapshot.unhealthy_services))
        )
    else:
        svc_names = [s.name for s in snapshot.services[:8]] if snapshot.services else []
        if svc_names:
            lines.append(tr("Servizi attivi ({0}): {1}.", len(svc_names), ', '.join(svc_names)))
        else:
            lines.append(tr("Nessun servizio registrato su Hub."))

    # Life domains are not here: they reach the «Vita» track as module signals (reflection.py).

    # Self state
    self_parts = [f"{snapshot.active_commitments} impegni attivi"]
    if snapshot.unresolved_commitments:
        self_parts.append(tr("{0} non risolti", snapshot.unresolved_commitments))
    if snapshot.failure_streak:
        self_parts.append(f"{snapshot.failure_streak} fallimenti consecutivi")
    lines.append(tr("Stato Athena: ") + ", ".join(self_parts))

    if snapshot.recent_errors:
        lines.append(tr("Errori ultima ora: ") + "; ".join(snapshot.recent_errors[:4]))

    if snapshot.quality_issues:
        lines.append(tr("Qualità risposte: ") + "; ".join(snapshot.quality_issues[:4]))

    if snapshot.settings:
        lines.append("IMPOSTAZIONI (chiave=valore [scelte]): " + "; ".join(snapshot.settings))
    if snapshot.presence:
        lines.append(snapshot.presence)

    if snapshot.raw_errors:
        lines.append(tr("Errori osservazione: {0}", ', '.join(snapshot.raw_errors[:3])))

    return "\n".join(lines)


def _build_strategist_prompt(observation_text: str) -> str:
    """Build the Oracle prompt for strategist reasoning.

    English like every hidden text; the fields people read (ACTION, SUMMARY) come in the owner's language.
    Structured key:value output for easier parsing from local models, strictly limited in size.
    """
    # Caveman style: short lines, zero filler. Local models = small context.
    return (
        "You are Athena, the assistant's proactive mind. Retrospective: what goes wrong, what to improve.\n"
        f"OBSERVATIONS:\n{observation_text}\n\n"
        f"Propose at most {get_int(S.STRATEGIST_MAX_CANDIDATES)} actions. Only if the data justifies them.\n"
        "EXACT format for each action:\n"
        "ACTION: <short title>\n"
        "TYPE: advisory|remediation|notification|maintenance|improvement|setting\n"
        "PRIORITY: low|normal|elevated|high\n"
        "DOMAIN: cognition|system|<observed domain>\n"
        "REASON: <1 sentence>\n"
        "SUMMARY: <1 sentence>\n"
        "Only for setting (KEY from SETTINGS):\nKEY: <key>\nVALUE: <new value>\n\n"
        "Rules:\n"
        f"- Write ACTION, REASON and SUMMARY in {S.owner_language()}: the owner reads them.\n"
        "- improvement = a change to the assistant's code/prompts (recurring errors, a domain with negative "
        "feedback). SUMMARY = what to change, concrete, which service.\n"
        "- remediation = a service down/broken now.\n"
        "- setting = change ONE listed setting (e.g. errors/costs of a model or the log level). Only listed keys "
        "and choices; the user confirms.\n"
        "- All normal -> write only: NO_ACTION\n"
        "- No text outside the format. No markdown. No HTML."
    )


# English field names of the prompt → the internal keys (the Italian ones are still read: older models, tests).
_FIELDS = {"type": "tipo", "priority": "priorita", "domain": "dominio", "reason": "motivo", "summary": "riassunto",
           "key": "chiave", "value": "valore", "topic": "tema",
           **{k: k for k in ("tipo", "priorita", "dominio", "motivo", "riassunto", "chiave", "valore", "tema")}}
_ACTION = re.compile(r"(?:ACTION|AZIONE):")


def _parse_candidates(raw: str) -> list[dict[str, str]]:
    """Parse Oracle's response into candidate dicts.

    Uses a simple state-machine parser that splits on ACTION: markers (AZIONE: still read).
    Robust against local model formatting inconsistencies.
    """
    if not raw or not raw.strip():
        return []

    text = raw.strip()
    if "NO_ACTION" in text.upper() or "NESSUNA_AZIONE" in text.upper():
        return []

    candidates: list[dict[str, str]] = []
    blocks = _ACTION.split(text)
    for block in blocks[1:]:  # Skip text before the first ACTION:
        candidate: dict[str, str] = {}
        candidate["title"] = block.split("\n")[0].strip()[:100]

        for line in block.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                field = _FIELDS.get(key.strip().lower())
                if field:
                    candidate[field] = value.strip()[:200]

        if candidate.get("title"):
            candidates.append(candidate)

    return candidates[:max(1, get_int(S.STRATEGIST_MAX_CANDIDATES))]


def _map_to_action_candidates(
    parsed: list[dict[str, str]],
) -> list[ActionCandidate]:
    """Map parsed dicts to ActionCandidate models with default signals."""
    candidates: list[ActionCandidate] = []
    for item in parsed:
        priority = (item.get("priorita") or "normal").strip().lower()
        kind = (item.get("tipo") or "advisory").strip().lower()
        domain = (item.get("dominio") or "cognition").strip().lower()

        # Default signals based on priority
        if priority == "high":
            signals = RelevanceSignals(
                urgency=0.9, usefulness=0.8, novelty=0.5,
                interruption_cost=0.3, confidence=0.7,
            )
        elif priority == "elevated":
            signals = RelevanceSignals(
                urgency=0.7, usefulness=0.7, novelty=0.5,
                interruption_cost=0.2, confidence=0.7,
            )
        elif priority == "low":
            signals = RelevanceSignals(
                urgency=0.2, usefulness=0.4, novelty=0.3,
                interruption_cost=0.1, confidence=0.6,
            )
        else:
            signals = RelevanceSignals()

        candidates.append(
            ActionCandidate(
                domain=domain,
                title=item.get("title", "Azione"),
                summary=item.get("riassunto") or item.get("motivo", ""),
                kind=kind,
                priority=priority,
                reasoning=item.get("motivo", ""),
                setting_key=(item.get("chiave") or "").strip() or None,
                setting_value=(item.get("valore") or "").strip() or None,
                signals=signals,
                score=0.0,  # Scored later by the runtime gate
            )
        )
    return candidates


class Strategist:
    """Thin wrapper around Oracle's LLM for Athena's reasoning cycle.

    All calls go through Hub routing — never direct to Oracle.
    """

    def __init__(self, hub_api_url: str) -> None:
        self.hub_api_url = hub_api_url.rstrip("/")
        self._session = requests.Session()

    @property
    def enabled(self) -> bool:
        return get_bool(S.STRATEGIST_ENABLED)

    def reason(self, snapshot: ObservationSnapshot) -> list[ActionCandidate]:
        """Generate action candidates from an observation snapshot.

        Returns an empty list if strategist is disabled, Oracle is
        unavailable, or the LLM returns no actionable candidates.
        """
        if not self.enabled:
            logger.debug(
                "event=strategist_disabled setting=%s", S.STRATEGIST_ENABLED
            )
            return []

        observation_text = _build_observation_prompt(snapshot)
        prompt = _build_strategist_prompt(observation_text)

        logger.info(
            "event=strategist_reasoning_start observation_chars=%d prompt_chars=%d",
            len(observation_text),
            len(prompt),
        )

        try:
            raw_response = self._call_oracle(prompt)
            if not raw_response:
                return []

            parsed = _parse_candidates(raw_response)
            candidates = _map_to_action_candidates(parsed)

            logger.info(
                "event=strategist_reasoning_complete candidates=%d",
                len(candidates),
            )
            return candidates

        except Exception as exc:
            logger.warning(
                "event=strategist_oracle_call_failed error=%s", exc
            )
            return []

    def _call_oracle(self, prompt: str) -> str | None:
        """Call Oracle's LLM generate endpoint through Hub routing."""
        timeout = get_float(S.STRATEGIST_TIMEOUT)
        body = {
            "prompt": prompt,
            "use_case": "athena.strategia",   # chain chosen in Oracle → Modelli
        }
        envelope = {
            "method": "POST",
            "headers": {},
            "query": {},
            "body": body,
            "timeout_seconds": timeout,
        }
        route_url = f"{self.hub_api_url}/route/oracle/api/llm/generate"
        try:
            resp = self._session.post(
                route_url,
                json=envelope,
                timeout=timeout + 4,
            )
            if resp.status_code != 200:
                logger.warning(
                    "event=strategist_route_failed_non200 status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None

            routed = resp.json() if resp.content else {}
            status_code = int((routed or {}).get("status_code", 500))
            payload = (routed or {}).get("payload")
            if status_code >= 400 or not payload:
                logger.warning(
                    "event=strategist_oracle_error status_code=%s",
                    status_code,
                )
                return None

            if isinstance(payload, dict):
                return str(payload.get("response") or payload.get("text") or "")
            return str(payload)

        except Exception as exc:
            logger.warning(
                "event=strategist_call_exception error=%s", exc
            )
            return None
