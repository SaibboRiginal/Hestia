# Hestia-Chronos 📅

**Role:** Integration Service — Bidirectional Calendar Gateway
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker · Google Calendar API v3 · Microsoft Graph API
**Port:** 8008

---

## Responsibility

Hestia-Chronos is the bidirectional gateway between Hestia and external calendar providers (Google Calendar and Microsoft Outlook). It provides a unified CRUD API over multiple providers simultaneously, so a single call can create an event in both Google and Outlook at the same time.

This service owns no domain logic — it is a pure integration adapter with provider-specific credential management and a common event schema.

---

## Providers

### Google Calendar
- **Auth:** Service account JSON (`GOOGLE_SERVICE_ACCOUNT_JSON` env var, base64) preferred. Falls back to OAuth user token (`GOOGLE_TOKEN_JSON` env var, base64) with automatic refresh.
- **Setup script:** `scripts/google_oauth_setup.py` — one-time host script for the OAuth user-token flow.
- **API:** Google Calendar API v3 via `google-api-python-client`.

### Microsoft Outlook
- **Auth:** MSAL device-code flow (personal account) or client-credentials flow (organizational M365). Token stored as `OUTLOOK_TOKEN_JSON` env var (base64).
- **Setup script:** `scripts/outlook_oauth_setup.py` — one-time host script for MSAL device-code auth.
- **API:** Microsoft Graph API `https://graph.microsoft.com/v1.0` via `requests`.
- **Target user:** `OUTLOOK_USER_ID` env var selects whose calendar to write to (`me` for personal accounts).

---

## Multi-Provider Dispatch

- `CreateEventRequest.target_providers: list[str]` — list of provider names to target (e.g. `["google", "outlook"]`). **Empty list = all configured and available providers.**
- Failures per provider are collected as `ProviderEventResult` objects and returned in the response without crashing the others.
- `CalendarProviderRegistry` auto-detects which providers are available at startup based on credentials present in env vars.

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

- `main.py`: FastAPI app, Hub registration, route definitions.
- `core/hub_client.py`: Hub registration with retry logic.
- `providers/base.py`: `AbstractCalendarProvider` ABC.
- `providers/google.py`: `GoogleCalendarProvider` — full CRUD via Google Calendar API v3.
- `providers/outlook.py`: `OutlookCalendarProvider` — full CRUD via Microsoft Graph API.
- `providers/registry.py`: `CalendarProviderRegistry` — instantiates and validates all providers at startup.
- `services/calendar_service.py`: `CalendarService` — multi-provider orchestration with per-provider failure isolation.
- `schemas/events.py`: Pydantic event schemas.

---

## Environment Variables

| Variable | Description |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Base64-encoded service account JSON (priority 1) |
| `GOOGLE_TOKEN_JSON` | Base64-encoded OAuth user token JSON (priority 2) |
| `GOOGLE_CALENDAR_ID` | Calendar ID to write to (default: `primary`) |
| `OUTLOOK_CLIENT_ID` | Azure app client ID |
| `OUTLOOK_CLIENT_SECRET` | Azure app client secret |
| `OUTLOOK_TENANT_ID` | Azure tenant ID (`consumers` for personal accounts) |
| `OUTLOOK_TOKEN_JSON` | Base64-encoded MSAL token cache |
| `OUTLOOK_USER_ID` | Graph API user identifier (default: `me`) |
| `HUB_API_URL` | Hub API base URL |
| `CALENDAR_SERVICE_BASE_URL` | This service's public base URL for Hub registration |

---

## Constraints

- Calendar never accesses Archive or any database directly.
- Calendar has no conversation or AI logic — it is a pure I/O adapter.
- Provider failures never propagate to callers — they are collected and returned as structured error results.
- All event times must be provided in ISO 8601 format with explicit timezone.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
