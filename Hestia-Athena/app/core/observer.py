"""Observer — gathers system state from Hub, Archive, and self for Athena's
thinking loop.

Design: each observation source is a small, independent method that returns a
partial snapshot. Failures are isolated per source and logged — a single
unavailable service never blocks the full observation cycle.

Domain discovery is dynamic: Athena queries Hub's service registry and extracts
managed domains from topology tags (e.g. ``domain:real_estate``, ``domain:calendar``)
registered by domain-layer modules. No static domain list — if Hub is unreachable,
domains are simply empty and the error is logged.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

from .schemas import DomainEntitySummary, ObservationSnapshot, ServiceSnapshot

logger = logging.getLogger("hestia_athena.observer")

OBSERVE_TIMEOUT = float(os.getenv("ATHENA_OBSERVE_TIMEOUT_SECONDS", "8"))
OBSERVE_ENTITY_WINDOW_HOURS = int(os.getenv("ATHENA_OBSERVE_ENTITY_WINDOW_HOURS", "24"))


def _extract_managed_domain(topology_tags: list[str]) -> str | None:
    """Extract the managed domain from topology tags like ``domain:real_estate``.

    Returns the first ``domain:...`` tag found, or None if the service isn't
    registered as a domain-layer module.
    """
    for tag in topology_tags:
        tag_lower = tag.strip().lower()
        if tag_lower.startswith("domain:") and len(tag_lower) > 7:
            return tag_lower[7:].strip()
    return None


def _extract_layer(topology_tags: list[str]) -> str | None:
    """Extract the architectural layer from topology tags like ``layer:domain``."""
    for tag in topology_tags:
        tag_lower = tag.strip().lower()
        if tag_lower.startswith("layer:") and len(tag_lower) > 6:
            return tag_lower[6:].strip()
    return None


class Observer:
    """Gathers system state from Hub-routed service endpoints.

    Every cross-service call goes through Hub routing (never direct
    container-to-container HTTP) per the architecture contract.
    """

    def __init__(self, hub_api_url: str) -> None:
        self.hub_api_url = hub_api_url.rstrip("/")
        self.archive_route = f"{self.hub_api_url}/route/archive"
        self.argus_route = f"{self.hub_api_url}/route/argus"
        self._session = requests.Session()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _route_get(
        self, route_base: str, path: str, params: dict | None = None
    ) -> dict[str, Any] | None:
        url = f"{route_base}/{path.lstrip('/')}"
        try:
            resp = self._session.get(
                url, params=params or {}, timeout=OBSERVE_TIMEOUT
            )
            if resp.status_code < 400:
                return resp.json() if resp.content else {}
            logger.debug(
                "event=observer_route_get_non200 route=%s status=%s body=%s",
                url,
                resp.status_code,
                resp.text[:200],
            )
        except Exception as exc:
            logger.debug(
                "event=observer_route_get_failed route=%s error=%s", url, exc
            )
        return None

    def _route_post(
        self, route_base: str, path: str, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        url = f"{route_base}/{path.lstrip('/')}"
        try:
            envelope = {
                "method": "POST",
                "headers": {},
                "query": {},
                "body": body,
                "timeout_seconds": OBSERVE_TIMEOUT,
            }
            resp = self._session.post(
                url, json=envelope, timeout=OBSERVE_TIMEOUT + 2
            )
            if resp.status_code < 400:
                routed = resp.json() if resp.content else {}
                payload = (routed or {}).get("payload")
                if isinstance(payload, dict):
                    return payload
                return routed
            logger.debug(
                "event=observer_route_post_non200 route=%s status=%s body=%s",
                url,
                resp.status_code,
                resp.text[:200],
            )
        except Exception as exc:
            logger.debug(
                "event=observer_route_post_failed route=%s error=%s", url, exc
            )
        return None

    # ── Domain discovery from Hub tags ────────────────────────────────────────

    def _discover_domains_from_services(
        self, services: list[dict[str, Any]]
    ) -> dict[str, str]:
        """Map domain name → owning service name from Hub service topology tags.

        A service like Scout registers with ``topology_tags: [layer:domain,
        domain:real_estate, status:stable]``.  This method extracts
        ``real_estate`` → ``scout``.

        Only services with ``layer:domain`` are considered domain managers.
        If multiple services claim the same domain, the last one wins
        (registrations are idempotent per service name anyway).
        """
        domain_map: dict[str, str] = {}
        for svc in services:
            if not isinstance(svc, dict):
                continue
            ttags = svc.get("topology_tags") or []
            if not isinstance(ttags, list):
                continue
            layer = _extract_layer(ttags)
            if layer != "domain":
                continue
            domain = _extract_managed_domain(ttags)
            if domain:
                service_name = str(svc.get("name", "")).strip().lower()
                if service_name:
                    domain_map[domain] = service_name
        return domain_map

    # ── Service health ─────────────────────────────────────────────────────────

    def observe_services(self) -> tuple[list[ServiceSnapshot], list[str]]:
        """Query Hub for registered services and their health via Argus."""
        services: list[ServiceSnapshot] = []
        unhealthy: list[str] = []

        hub_services_data = self._route_get(
            f"{self.hub_api_url}", "/api/registry/services"
        )
        raw_services: list[dict[str, Any]] = []
        if hub_services_data:
            raw_list = (
                hub_services_data.get("services")
                or hub_services_data.get("data")
                or []
            )
            if isinstance(raw_list, list):
                raw_services = raw_list

        for entry in raw_services:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip().lower()
            if not name:
                continue
            ttags = entry.get("topology_tags") or []
            ttags_list = [
                str(t).strip().lower()
                for t in (ttags if isinstance(ttags, list) else [])
                if str(t).strip()
            ]
            managed_domain = _extract_managed_domain(ttags_list)
            services.append(
                ServiceSnapshot(
                    name=name,
                    base_url=str(entry.get("base_url", "")),
                    service_type=str(entry.get("service_type", "")),
                    tags=[
                        str(t).strip().lower()
                        for t in (entry.get("tags") or [])
                        if str(t).strip()
                    ],
                    topology_tags=ttags_list,
                    managed_domain=managed_domain,
                )
            )

        # Check health via Argus
        argus_status = self._route_get(
            self.argus_route, "/api/argus/status"
        )
        if argus_status:
            svc_health = argus_status.get("services") or {}
            if isinstance(svc_health, dict):
                for svc_name, svc_data in svc_health.items():
                    status = str(
                        (svc_data or {}).get("status", "unknown")
                    ).lower()
                    for snap in services:
                        if snap.name == svc_name.lower():
                            snap.status = status
                            break
                    if status not in ("up", "ok", "healthy"):
                        unhealthy.append(svc_name.lower())

        return services, unhealthy

    # ── Entity domains ─────────────────────────────────────────────────────────

    def observe_domains(
        self, services: list[ServiceSnapshot] | None = None
    ) -> list[DomainEntitySummary]:
        """Query Archive for entity domain activity.

        Domains are discovered dynamically from Hub service topology tags
        (e.g. ``domain:real_estate`` on Scout).  Every domain-layer service
        is observed.  If no domain services are registered or Hub is
        unreachable, returns an empty list — no static fallback.
        """
        domain_map: dict[str, str] = {}  # domain → owning_service
        if services:
            for snap in services:
                if snap.managed_domain:
                    domain_map[snap.managed_domain] = snap.name

        if not domain_map:
            logger.info(
                "event=observer_no_domains_discovered "
                "No domain-layer services found in Hub registry"
            )
            return []

        summaries: list[DomainEntitySummary] = []
        for domain, owner in domain_map.items():
            summary = self._observe_single_domain(domain, owner)
            if summary:
                summaries.append(summary)

        return summaries

    def _observe_single_domain(
        self, domain: str, owner_service: str = "unknown"
    ) -> DomainEntitySummary | None:
        """Query Archive for entities in a single domain.

        Uses Hub routing to Archive's entity search endpoint.  Only fetches
        counts and a few sample titles — never pulls full payloads.
        """
        search_body = {
            "domain": domain,
            "limit": 10,
            "offset": 0,
            "order_by": "updated_at",
            "order_dir": "desc",
        }
        result = self._route_post(
            self.archive_route, "/api/entities/search", search_body
        )
        if not result:
            return None

        entities = (
            result.get("entities")
            or result.get("items")
            or result.get("results")
            or []
        )
        if not isinstance(entities, list):
            return DomainEntitySummary(domain=domain, total_entities=0)

        total = int(result.get("total") or len(entities))
        sample_titles: list[str] = []
        pending_count = 0
        recent_count = 0

        for ent in entities:
            if not isinstance(ent, dict):
                continue
            payload = ent.get("payload") or ent
            if isinstance(payload, dict):
                title = str(
                    payload.get("title")
                    or payload.get("name")
                    or ent.get("entity_id", "")
                )[:80]
                if title:
                    sample_titles.append(title)
                if payload.get("pending_steps"):
                    steps = payload.get("pending_steps")
                    if isinstance(steps, dict) and any(
                        bool(v) for v in steps.values()
                    ):
                        pending_count += 1
            updated = str(ent.get("updated_at") or ent.get("created_at") or "")
            if updated:
                try:
                    updated_dt = datetime.fromisoformat(
                        updated.replace("Z", "+00:00")
                    )
                    age_hours = (
                        datetime.now(timezone.utc) - updated_dt
                    ).total_seconds() / 3600
                    if age_hours <= OBSERVE_ENTITY_WINDOW_HOURS:
                        recent_count += 1
                except (ValueError, TypeError):
                    pass

        return DomainEntitySummary(
            domain=domain,
            total_entities=total,
            recent_count=recent_count,
            pending_count=pending_count,
            sample_titles=sample_titles[:5],
        )

    # ── Self-observation ────────────────────────────────────────────────────────

    def observe_self(
        self,
        active_commitments: int,
        unresolved_commitments: int,
        recent_failures: int,
        failure_streak: int,
    ) -> dict[str, Any]:
        """Package Athena's own runtime state as observation context."""
        return {
            "active_commitments": active_commitments,
            "unresolved_commitments": unresolved_commitments,
            "recent_failures": recent_failures,
            "failure_streak": failure_streak,
        }

    # ── Full snapshot ──────────────────────────────────────────────────────────

    def snapshot(
        self,
        active_commitments: int = 0,
        unresolved_commitments: int = 0,
        recent_failures: int = 0,
        failure_streak: int = 0,
    ) -> ObservationSnapshot:
        """Gather a complete observation snapshot.

        All source-level failures are isolated — one down service won't block
        the rest of the observation cycle.
        """
        errors: list[str] = []

        services, unhealthy = self.observe_services()
        if not services:
            errors.append("no_services_from_hub")

        domains = self.observe_domains(services=services)
        if not domains:
            errors.append("no_domain_data_from_archive")

        self_state = self.observe_self(
            active_commitments=active_commitments,
            unresolved_commitments=unresolved_commitments,
            recent_failures=recent_failures,
            failure_streak=failure_streak,
        )

        return ObservationSnapshot(
            services=services,
            unhealthy_services=unhealthy,
            domains=domains,
            active_commitments=self_state["active_commitments"],
            unresolved_commitments=self_state["unresolved_commitments"],
            recent_failures=self_state["recent_failures"],
            failure_streak=self_state["failure_streak"],
            raw_errors=errors,
        )
