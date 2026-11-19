"""Hub communication helper — thin wrapper used by the startup registration."""
from __future__ import annotations

import logging
import os
import time

import requests
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_chronos.hub_client")


def register_on_hub(
    hub_api_url: str,
    service_base_url: str,
    *,
    max_attempts: int = 8,
    retry_delay: float = 2.0,
    quiet_success: bool = False,
    extra_capabilities: dict | None = None,
) -> None:
    """Register this service in Hub with retry logic.

    Declared capabilities include the generic ``calendar.create_event`` and
    ``calendar.list_events`` tool endpoints so that Oracle can discover and
    call them through Hub routing without knowing the specific calendar
    backend in use.
    """
    payload = {
        "name": "chronos",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "integration",
        "service_version": os.getenv("CALENDAR_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "integration"],
        "topology_tags": ["layer:domain", "domain:calendar", "status:stable"],
        "capabilities": {
            # Module agent (Oracle operating mode «agents») + module index: what it is for, its rules.
            "when_to_use": "calendar events, the assistant's agenda (reminders, planned jobs), routines and the week plan",
            "manual": "Calendar: agenda/agenda_today read, create_event/calendar_update_event/calendar_delete_event change "
                      "events. Assistant agenda (agenda_assistant*): one-off reminders and planned jobs, move, skip, "
                      "cancel. Coach week plan: coach_week, coach_move, coach_skip, coach_replan. Delete only when the "
                      "owner asks; times in the owner's timezone.",
            "title": "Agenda",
            "tool_endpoints": {
                "calendar.create_event": f"{service_base_url}/api/calendar/events",
                "calendar.list_events": f"{service_base_url}/api/calendar/events/list",
                "calendar.agenda": f"{service_base_url}/api/calendar/agenda",
            },
            "mcp_endpoint": f"{service_base_url.rstrip('/')}/mcp",
            "module_tool_domains": ["calendar", "coach"],
            # LLM use cases (hestia_common.oracle_usecases shape): chain/mode chosen in Oracle → Models.
            "llm_usecases": [{"id": "chronos.agenda", "label": "Agenda · reading requests", "chain": "fast",
                              "help": "Turns a sentence into an appointment or an agenda rule.",
                              "thinking": "auto", "mode": "follow"},
                             {"id": "chronos.coach", "label": "Week plan · message", "chain": "fast",
                              "help": "Writes the message with the week plan starting from the plan already made.",
                              "thinking": "off", "mode": "follow"}],
            **(extra_capabilities or {}),   # WebUI plugin manifest (ui_manifest, ui_version)
        },
    }

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(
                f"{hub_api_url}/registry/register", json=payload, timeout=4
            )
            if resp.status_code < 400:
                if quiet_success:
                    logger.debug(
                        "event=hub_registered_attempt_hub_base_url [HUB] Registered | attempt=%s hub=%s base_url=%s",
                        attempt,
                        hub_api_url,
                        service_base_url,
                    )
                else:
                    logger.info(
                        "event=hub_registered_attempt_hub_base_url [HUB] Registered | attempt=%s hub=%s base_url=%s",
                        attempt,
                        hub_api_url,
                        service_base_url,
                    )
                return
            logger.warning(
                "event=hub_registration_returned_non_success [HUB] Registration returned non-success | attempt=%s status=%s",
                attempt,
                resp.status_code,
            )
        except Exception as exc:
            logger.warning(
                "event=hub_registration_attempt_failed [HUB] Registration attempt %s failed: %s", attempt, exc)

        if attempt < max_attempts:
            time.sleep(retry_delay)

    logger.error(
        "event=hub_all_registration_attempts_failed [HUB] All %s registration attempts failed.", max_attempts)
