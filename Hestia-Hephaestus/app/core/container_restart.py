"""Immune system hands (docs/work/2026-10-19-oracle-offline v3 B): restart a sick module's container.

Argus (diagnosis) decides when and how many times; Hephaestus only does it, with guards: a plain ``hestia_<svc>``
name, never itself (Forge restarts itself after its own deploys), never a service a Forge deploy is restarting right
now (Forge's health check and rollback own that window). After the restart the health check runs through Hub.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..forge import deployer

logger = logging.getLogger(__name__)

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def restart(service: str, forge, reason: str = "", attempt: int = 0) -> dict[str, Any]:
    service = str(service or "").strip().lower()
    if not _NAME.match(service):
        return {"status": "refused", "service": service, "detail": "invalid service name"}
    if service == "hephaestus":
        return {"status": "refused", "service": service, "detail": "self restart is not allowed here"}
    if forge is not None and service in forge.deploying_services():
        logger.info("event=immune_restart_skipped service=%s reason=forge_deploy", service)
        return {"status": "skipped", "service": service, "detail": "a Forge deploy owns this service now"}
    ok, out = deployer.restart_containers([service])
    healthy = False
    if ok and forge is not None:
        healthy = not forge.unhealthy([service])
    logger.info("[🔄] event=immune_restart service=%s attempt=%s restarted=%s healthy=%s reason=%s",
                service, attempt, ok, healthy, str(reason)[:120])
    return {"status": "ok" if ok else "failed", "service": service, "restarted": ok, "healthy": healthy,
            "detail": out[-400:]}
