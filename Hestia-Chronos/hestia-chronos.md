# Hestia-Chronos 📅

**Role:** Domain Service — Calendar Workflows and Archive/Notification Orchestration
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker
**Port:** 8008

---

## Responsibility

Hestia-Chronos is the calendar domain service. It exposes domain-facing calendar endpoints, syncs items into Archive, and emits notification events via Hermes.

Chronos no longer owns provider credentials/OAuth flows and no longer calls Google/Outlook APIs directly. Provider-facing operations are delegated to Hecate through Hub-routed calls.

---

## Provider Ownership

- Provider ownership (Google/Outlook auth and runtime loading) belongs to Hecate.
- Chronos forwards CRUD/list/provider-refresh requests to Hecate via Hub routing.
- Credential setup scripts and provider SDK dependencies were moved out of Chronos runtime paths.

## Routing Model

- Chronos receives domain-level calendar requests and routes provider-facing work to Hecate (`/route/hecate/...`).
- Sync workers fetch provider events through Hub-routed Hecate endpoints, then persist normalized events in Archive.
- Notification worker behavior is unchanged: Chronos remains responsible for emitting outbound calendar notifications.

## Dispatch Behavior

- Chronos forwards provider target lists transparently to Hecate.
- Per-provider success/failure details are returned by Hecate and propagated by Chronos.
- Chronos never instantiates provider SDK clients locally.

---

## Data Model

### `CalendarEvent`
```json
{
  "title": "string",
  "description": "string | null",
  "start": "datetime (ISO 8601)",
  "end": "datetime (ISO 8601)",
  "location": "string | null",
  "attendees": ["email@..."],
  "timezone": "string (e.g. Europe/Rome)"
}
```

### `CreateEventResponse`
```json
{
  "results": [
    {
      "provider": "google",
      "success": true,
      "event_id": "...",
      "event_url": "https://calendar.google.com/...",
      "error": null
    },
    {
      "provider": "outlook",
      "success": false,
      "event_id": null,
      "event_url": null,
      "error": "Token expired"
    }
  ]
}
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/calendar/events` | Create event on one or more providers |
| `POST` | `/api/calendar/events/list` | List events across providers |
| `DELETE` | `/api/calendar/events/{event_id}` | Delete an event |
| `PATCH` | `/api/calendar/events/{event_id}` | Update an event |
| `GET` | `/api/calendar/providers` | List available (configured) providers |
| `GET` | `/health` | Service health |

### `POST /api/calendar/events` payload
```json
{
  "event": {
    "title": "Visita medica",
    "start": "2026-04-22T10:30:00",
    "end": "2026-04-22T11:30:00",
    "location": "Via Roma 1, Milano",
    "timezone": "Europe/Rome"
  },
  "target_providers": []
}
```

---

## Document-to-Event Flow

The primary use case is: user sends a document (photo of a letter, PDF) to Telegram → Telegram forwards it to Oracle → Oracle analyst LLM reads the document and extracts a `CalendarEvent`-shaped JSON → Oracle calls Calendar via Hub (`POST /route/calendar/api/calendar/events`) → Calendar writes to configured providers.

```
Telegram  ──(file + caption)──►  Oracle /api/chat/document
                                         │
                              analyst LLM reads document
                                         │
                              extracts CalendarEvent JSON
                                         │
                    Hub /route/calendar/api/calendar/events
                                         │
                               Calendar service
                                   /    \
                             Google   Outlook
```

---

## Internal Architecture (SoC)

- `main.py`: FastAPI app, Hub registration, route definitions, Hub-routed delegation to Hecate.
- `core/hub_client.py`: Hub registration with retry logic.
- `services/sync_worker.py`: Pulls provider events through Hecate and writes Archive calendar items.
- `schemas/events.py`: Pydantic event schemas.

---

## Environment Variables

| Variable | Description |
|---|---|
| `HUB_API_URL` | Hub API base URL |
| `CALENDAR_SERVICE_BASE_URL` | This service's public base URL for Hub registration |
| `ARCHIVE_URL` | Archive base URL for calendar persistence |
| `HERMES_URL` | Hermes base URL for notifications |

---

## Constraints

- Chronos does not own provider OAuth/token lifecycle.
- Chronos always reaches Hecate through Hub routing for provider-facing actions.
- Chronos persists/syncs calendar state in Archive and emits notifications through Hermes.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
