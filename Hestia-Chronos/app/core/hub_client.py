"""Hub communication helper — thin wrapper used by the startup registration."""
from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger("hestia_chronos.hub_client")


def register_on_hub(
    hub_api_url: str,
    service_base_url: str,
    *,
    max_attempts: int = 8,
    retry_delay: float = 2.0,
    quiet_success: bool = False,
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
        "capabilities": {
            "tool_endpoints": {
                "calendar.create_event": f"{service_base_url}/api/calendar/events",
                "calendar.list_events": f"{service_base_url}/api/calendar/events/list",
                "calendar.agenda": f"{service_base_url}/api/calendar/agenda",
            },
            "commands": [
                {
                    "command": "agenda",
                    "title": "📅 Agenda",
                    "description": "Mostra gli eventi in agenda nei prossimi 7 giorni",
                    "method": "GET",
                    "path": "/api/calendar/agenda",
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": (
                        "Mostra gli eventi dell'agenda in modo leggibile e cronologico. "
                        "Per ogni evento indica titolo, data/ora, luogo (se presente) e "
                        "una breve descrizione. Raggruppa per giorno. Usa un tono da "
                        "assistente personale, amichevole e conciso."
                    ),
                },
                {
                    "command": "agenda_today",
                    "title": "📋 Agenda di oggi",
                    "description": "Mostra gli eventi di oggi",
                    "method": "GET",
                    "path": "/api/calendar/agenda",
                    "query_template": {"days": 1},
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": (
                        "Mostra gli eventi di oggi in modo conciso. Se non ci sono "
                        "eventi, dillo chiaramente. Usa linguaggio da assistente personale."
                    ),
                },
                {
                    "command": "create_event",
                    "title": "📅 Crea evento",
                    "description": "Crea un nuovo evento nel calendario connesso (Google Calendar, Outlook). Usa per: crea evento, aggiungi appuntamento, imposta promemoria, pianifica riunione.",
                    "method": "POST",
                    "path": "/api/calendar/events",
                    "body_template": {
                        "event": {
                            "title": "$title",
                            "start_datetime": "$start_datetime",
                            "end_datetime": "$end_datetime",
                            "description": "$description",
                            "location": "$location",
                        }
                    },
                    "arguments_schema": {
                        "title": {"type": "string", "required": True, "description": "Titolo o nome dell'evento"},
                        "start_datetime": {"type": "string", "required": True, "description": "Data e ora di inizio nel formato ISO 8601 (YYYY-MM-DDTHH:MM:SS). Risolvi le date relative come 'domani', 'lunedì prossimo' con la data reale."},
                        "end_datetime": {"type": "string", "required": False, "description": "Data e ora di fine nel formato ISO 8601. Se non specificato, usa start_datetime + 1 ora."},
                        "description": {"type": "string", "required": False, "description": "Descrizione o note aggiuntive dell'evento"},
                        "location": {"type": "string", "required": False, "description": "Luogo fisico o virtuale dell'evento"},
                    },
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": (
                        "Conferma la creazione dell'evento con un messaggio breve e naturale. "
                        "Includi titolo, data/ora di inizio. Se il provider ha restituito un link o ID, menzionalo. "
                        "Usa un tono diretto e amichevole."
                    ),
                    "telegram_visible": False,
                },
            ],
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

    logger.error("event=hub_all_registration_attempts_failed [HUB] All %s registration attempts failed.", max_attempts)
