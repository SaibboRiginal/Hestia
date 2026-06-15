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
import os
from typing import Any
from uuid import uuid4

import requests

from .schemas import ActionCandidate, ObservationSnapshot, RelevanceSignals

logger = logging.getLogger("hestia_athena.strategist")

STRATEGIST_TIMEOUT = float(os.getenv("ATHENA_STRATEGIST_TIMEOUT_SECONDS", "20"))
STRATEGIST_ENABLED = bool(
    int(os.getenv("ATHENA_STRATEGIST_ENABLED", "1"))
)
STRATEGIST_MAX_CANDIDATES = int(os.getenv("ATHENA_STRATEGIST_MAX_CANDIDATES", "3"))


def _build_observation_prompt(snapshot: ObservationSnapshot) -> str:
    """Build a compact observation text for the Oracle prompt.

    Kept deliberately short — local models have limited context windows.
    """
    lines: list[str] = []

    # Service health (most important signal)
    if snapshot.unhealthy_services:
        lines.append(
            f"Servizi non sani: {', '.join(snapshot.unhealthy_services)}."
        )
    else:
        svc_names = [s.name for s in snapshot.services[:8]] if snapshot.services else []
        if svc_names:
            lines.append(f"Servizi attivi ({len(svc_names)}): {', '.join(svc_names)}.")
        else:
            lines.append("Nessun servizio registrato su Hub.")

    # Domain activity
    for domain in snapshot.domains[:4]:
        parts = [f"Dominio '{domain.domain}': {domain.total_entities} entità"]
        if domain.recent_count:
            parts.append(f"{domain.recent_count} recenti")
        if domain.pending_count:
            parts.append(f"{domain.pending_count} in attesa")
        if domain.sample_titles:
            parts.append(f"esempi: {', '.join(domain.sample_titles[:3])}")
        lines.append(", ".join(parts))

    # Self state
    self_parts = [f"{snapshot.active_commitments} impegni attivi"]
    if snapshot.unresolved_commitments:
        self_parts.append(f"{snapshot.unresolved_commitments} non risolti")
    if snapshot.failure_streak:
        self_parts.append(f"{snapshot.failure_streak} fallimenti consecutivi")
    lines.append("Stato Athena: " + ", ".join(self_parts))

    if snapshot.raw_errors:
        lines.append(f"Errori osservazione: {', '.join(snapshot.raw_errors[:3])}")

    return "\n".join(lines)


def _build_strategist_prompt(observation_text: str) -> str:
    """Build the Oracle prompt for strategist reasoning.

    The prompt is in Italian (Hestia's persona language), requests
    structured key:value output for easier parsing from local models,
    and strictly limits output size.
    """
    return (
        f"Sei Athena, il modulo di cognizione proattiva di Hestia. "
        f"Ecco cosa osservi in questo momento:\n\n"
        f"{observation_text}\n\n"
        f"Basandoti su queste osservazioni, proponi al massimo "
        f"{STRATEGIST_MAX_CANDIDATES} azioni concrete che potresti suggerire "
        f"o eseguire. Per ogni azione, scrivi ESATTAMENTE in questo formato:\n\n"
        f"AZIONE: <titolo breve>\n"
        f"TIPO: advisory|remediation|notification|maintenance\n"
        f"PRIORITA: low|normal|elevated|high\n"
        f"DOMINIO: cognition|system|real_estate|calendar\n"
        f"MOTIVO: <una frase che spiega perché>\n"
        f"RIASSUNTO: <una frase di riassunto>\n\n"
        f"IMPORTANTE:\n"
        f"- Proponi solo azioni GIUSTIFICATE dai dati osservati.\n"
        f"- Se non ci sono anomalie o novità, NON inventare azioni.\n"
        f"- Se tutto è normale, rispondi solo con: NESSUNA_AZIONE\n"
        f"- Massimo {STRATEGIST_MAX_CANDIDATES} azioni.\n"
        f"- Sii conciso. Non aggiungere testo fuori dal formato.\n"
        f"- Non usare markdown o HTML."
    )


def _parse_candidates(raw: str) -> list[dict[str, str]]:
    """Parse Oracle's response into candidate dicts.

    Uses a simple state-machine parser that splits on AZIONE: markers.
    Robust against local model formatting inconsistencies.
    """
    if not raw or not raw.strip():
        return []

    text = raw.strip()
    if "NESSUNA_AZIONE" in text.upper():
        return []

    candidates: list[dict[str, str]] = []
    blocks = text.split("AZIONE:")
    for block in blocks[1:]:  # Skip text before first AZIONE:
        candidate: dict[str, str] = {}
        candidate["title"] = block.split("\n")[0].strip()[:100]

        for line in block.split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                key_lower = key.strip().lower()
                val = value.strip()[:200]
                if key_lower in ("tipo", "priorita", "dominio", "motivo", "riassunto"):
                    candidate[key_lower] = val

        if candidate.get("title"):
            candidates.append(candidate)

    return candidates[:STRATEGIST_MAX_CANDIDATES]


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
        self.enabled = STRATEGIST_ENABLED
        self._session = requests.Session()

    def reason(self, snapshot: ObservationSnapshot) -> list[ActionCandidate]:
        """Generate action candidates from an observation snapshot.

        Returns an empty list if strategist is disabled, Oracle is
        unavailable, or the LLM returns no actionable candidates.
        """
        if not self.enabled:
            logger.debug(
                "event=strategist_disabled Strategist disabled via ATHENA_STRATEGIST_ENABLED=0"
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
        body = {
            "prompt": prompt,
            "model": os.getenv("ATHENA_STRATEGIST_MODEL", ""),
            "provider": os.getenv("ATHENA_STRATEGIST_PROVIDER", ""),
        }
        envelope = {
            "method": "POST",
            "headers": {},
            "query": {},
            "body": body,
            "timeout_seconds": STRATEGIST_TIMEOUT,
        }
        route_url = f"{self.hub_api_url}/route/oracle/api/llm/generate"
        try:
            resp = self._session.post(
                route_url,
                json=envelope,
                timeout=STRATEGIST_TIMEOUT + 4,
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
