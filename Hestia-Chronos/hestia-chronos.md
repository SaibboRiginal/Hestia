# Hestia-Chronos 📅

**Role:** Domain Service — Calendar Workflows and Archive/Notification Orchestration
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker
**Port:** 8008

---

## Responsibility

Hestia-Chronos is the calendar domain service. It exposes domain-facing calendar endpoints, syncs items into Archive, and emits notification events via Hermes.

Chronos scope is calendar only. It is not the email-domain service.

Chronos no longer owns provider credentials/OAuth flows and no longer calls Google/Outlook APIs directly. Provider-facing operations are delegated to Hecate through Hub-routed calls.

---

## Provider Ownership

- Provider ownership (Google/Outlook auth and runtime loading) belongs to Hecate.
- Chronos forwards CRUD/list/provider-refresh requests to Hecate via Hub routing.
- Chronos must not contain provider token.json, credentials.json, or OAuth client secrets as its runtime source of truth.
- Credential setup scripts and provider SDK dependencies live in Hecate or host-side setup flows, not in Chronos runtime paths.

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
| `POST` | `/api/calendar/sync` | Run a Hecate → Archive calendar sync now (background; agenda job `chronos.calendar_sync`) |
| `POST` | `/api/module/maintenance/reconcile` | Run standardized module maintenance reconcile |
| `POST` | `/api/maintenance/reconcile` | Compatibility alias for module maintenance reconcile |
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
- If Google/Outlook fetch is failing, inspect Hecate provider configuration and Hub-routed Hecate logs first.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.

## Reminder & agenda behaviour (fixes)

- Reminder times shown in `CHRONOS_DISPLAY_TZ` / `TZ` (default Europe/Rome) with Italian month names; titles,
  locations and descriptions are HTML-escaped. All-day events (date-only) are flagged `all_day`.
- `GET /api/calendar/agenda` window starts at local midnight (today's past and all-day events included).
- Provider syncs no longer overwrite the user's `nag_enabled` choice; a rescheduled event (new `start_at`) resets
  `last_notified_bucket` so it is reminded again.

## Assistant agenda (Hestia's own calendar)

A second calendar, owned by Chronos, where **Hestia and its modules plan their own work**. Stored in Archive
`calendar_items` with `source=hestia` (+ `meta` JSON). It is **not** synced to Google/Outlook, never shown in
`/api/calendar/agenda` (your agenda) and never nagged as a reminder — but you and every module can read it.

### Item types

| Type | Meaning | Example |
|---|---|---|
| `event` | informational / planned | "Forge: sviluppo X" (scheduled Claude task) |
| `task` | one-off action executed at `start_at` (retried up to `CHRONOS_AGENDA_MAX_ATTEMPTS`, then `failed`) | a repair Argus/Hephaestus planned for tonight |
| `job` | recurring action (RRULE) | "Scout: controlla le email ogni 30 min" |
| `window` | recurring period in which something is allowed (RRULE + duration) | "Claude Pro: notti prima del reset" |

Actions are `{service, method, path, body, query, timeout_seconds}` executed **through Hub** by the agenda worker
(`CHRONOS_AGENDA_TICK_SECONDS`, 60). Recurring jobs fire only their latest due occurrence (no storm after downtime).
Recurrence is evaluated in local wall time (`tz`, default `CHRONOS_DISPLAY_TZ`/`TZ`/Europe/Rome), DST-safe.

### Rules are data

- Modules **register defaults** with `POST /api/agenda/register {owner, rules:[{key, type, title, start_at, end_at,
  recurrence, action, params}]}` — idempotent by `key`.
- Anything the **user** edits (`by=user`) becomes `user_modified` and is never overwritten by its module;
  a rule the user cancelled stays cancelled.
- Modules ask `GET /api/agenda/windows/{key}` → `{exists, active, until, skipped_now, next_open, params}` instead of
  hardcoding times. Missing key or Chronos down → the module uses its built-in fallback.
- You (Telegram): "cosa hai in programma?", "sposta la finestra Claude a sabato notte", "salta stanotte",
  "annulla quel task", "eseguilo ora".

### Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/agenda?days=7&owner=&type=&past_hours=` or `?start=&end=&include_done=` | Expanded occurrences (`skipped`, `moved`, `status`, `recurring`, `created_by`, `run`) |
| GET | `/api/agenda/items` | Raw items (`include_cancelled`) |
| POST | `/api/agenda/items` | Create (on demand) `{title, type, owner, start_at, end_at, recurrence, description, action, key, params, tz, parent?}` |
| POST | `/api/agenda/register` | Module defaults (idempotent, user edits preserved) |
| PATCH | `/api/agenda/items/{ref}` | Move/change (`start_at` keeps duration), pause (`status=paused`), `by` |
| DELETE | `/api/agenda/items/{ref}` | Cancel (cascades to linked children; `PATCH status=cancelled` does the same) |
| POST | `/api/agenda/items/{ref}/skip` | Dismiss one occurrence (default: current/next); a one-off is cancelled |
| POST | `/api/agenda/items/{ref}/unskip` | Restore an occurrence |
| POST | `/api/agenda/items/{ref}/run` | Execute the action now |
| GET | `/api/agenda/windows/{key}` | Window open now? |
| GET | `/api/agenda/templates` | What each module lets the user create (calendar wizard "Da un modulo…") |
| POST | `/api/agenda/templates` | Module declares its templates `{owner, templates}` (in memory; re-asserted hourly by `register_async`) |
| POST | `/api/agenda/templates/{owner}/{id}/create` | Create from a template `{values, start_at, end_at?, recurrence?, type?}` → item `created_by=user`, owner = module, key `<owner>.tpl.<id>.<rand>` |
| POST | `/api/agenda/items/{ref}/move` | Move ONE occurrence `{occurrence, start_at, end_at?, reset?}` (exception kept in `meta.overrides`, same key → modules/jobs follow it); one-off items move entirely |
| GET | `/api/agenda/items/{ref}/links` | Parent + children of an item |
| POST | `/api/agenda/items/{ref}/link` | Link to a parent `{parent}` (empty = unlink; cycles refused) |
| POST | `/api/agenda/items/{ref}/fail` | A module reports the work behind the item failed `{detail}` → `failed` + parent marked |
| POST | `/api/agenda/parse` | Natural-language quick add `{text, tz?}` → `draft {title, type, start_at, end_at, recurrence, description}` (Oracle `/api/llm/generate` through Hub, Chronos validates; nothing created) |
| GET | `/api/agenda/ics?days=60&past_days=7&owner=&types=event,task,window` | Read-only iCalendar feed (expanded occurrences, skips/moves applied; jobs excluded by default) |

**Run log**: every execution (tick or "run now") is appended to `meta.runs` (last 50:
`{occurrence, ok, detail, at, by, duration_ms}`); occurrences expose `run` so the calendar shows ok/failed per
occurrence and can keep past failures visible. `last_result` stays (last run of the rule).

**Links (generic, `meta.parent`)**: an item may name a parent key. Cancelling the parent cancels its live
children (`by=cascade:<key>`, recursive); a child that fails (tick after `max_attempts`, or `/fail`) or that the
user cancels marks the parent (`last_result` + run log entry `by=link:<child>`; a one-off parent becomes
`failed`, a recurring one keeps running). Forge links its task mirror `forge.task.<id>` to `agenda_parent`.

`ref` = numeric id or stable key. MCP tools: `agenda_assistente`, `agenda_assistente_aggiungi` (`parent`),
`agenda_assistente_sposta`, `agenda_assistente_sposta_occorrenza`, `agenda_assistente_salta`,
`agenda_assistente_ripristina`, `agenda_assistente_annulla`, `agenda_assistente_esegui`,
`agenda_assistente_modelli`, `agenda_assistente_da_modello`, `agenda_assistente_collega`. Oracle turns a
successful write of these into an `agenda.planned` notice (calendar pages reload live).

### Who plans what (registered rules)

Every module registers its defaults at boot (and re-asserts them hourly, idempotent) with the shared client
`hestia_common/agenda_client.py`. Missing rule or Chronos down → the module falls back to its env schedule, so
nothing stops; a rule the user **paused/cancelled** is a decision and is respected (no fallback).

| Key | Type | Owner | Default | What happens |
|---|---|---|---|---|
| `scout.email_cycle` | job | scout | every `SCOUT_POLL_INTERVAL_SECONDS` (30 min) | `POST scout /api/scout/cycle` — email → listings cycle |
| `chronos.calendar_sync` | job | chronos | every `CHRONOS_SYNC_POLL_SECONDS` (15 min) | `POST chronos /api/calendar/sync` — Hecate → Archive sync |
| `athena.consolidation` | window | athena | daily 03–05 | memory consolidation, once a day inside the window |
| `athena.skill_curation` | window | athena | daily 05–07 | skill curation, once a day inside the window |
| `athena.thinking` | window | athena | all day | idle thinking cycles; skip/pause to silence Athena |
| `metis.training` | window | metis | daily 01–06 | non-user LoRA trainings start here |
| `metis.train.<job>` | task | metis | next `metis.training` opening | `POST metis /api/metis/lora/train` (schedule=now) |
| `forge.claude_nights` / `forge.claude_final` | window | hephaestus | nights before the Claude Pro reset / final hours | autonomous Claude Code tasks |
| `forge.task.<id>` | event | hephaestus | live | Forge task mirror: ⏳ da approvare, 🌙 programmato, 🔨 in lavorazione, 👀 da rivedere; completed when the task ends. Cancel a scheduled one → task rejected; move it later → Forge waits |
| `hephaestus.repair.<id>` | event/task | hephaestus | now / +15 min × attempt | repair awaiting approval, or retry of a failed repair (`POST /api/hephaestus/remediate/{id}/retry`); last failure → Forge code-fix task |
| `assistant.sleep` | window | chronos | daily 01–07 | the night: presence goes to «Sonno profondo» (if `chronos.presence.use_sleep_window`) |
| `argus.repair.<service>` | task | argus | +10 min, doubling (max 6 h) | `POST argus /api/argus/recheck/{service}`: still down → new repair request + next recheck; recovery closes it |

## Assistant presence (activity state)

SPEC `docs/work/2026-10-10-assistant-presence`. Chronos keeps the assistant's general state, like a person:
**facts (signals) → states (data) → effects**. Consumers never test a state name, they ask an *effect*
(`hestia_common.presence_client`), so a new state needs no code change anywhere.

- **Signals**: `user.last_interaction` (pings from Oracle chat, Telegram, WebUI actions), activities
  (`activity.<key>`: label, load light/heavy/maintenance, resource, ttl), `manual.dnd`, facts such as
  `resource.claude_quota_left` (Forge) and `health.degraded_services` (Argus). Derived: `user.idle_minutes`,
  `activity.heavy_count`, `activity.maintenance_count`, `agenda.window.<key>`, `setting.<name>`, `clock.*`.
- **States** = Themis setting `chronos.presence.states` (object keyed by state): `kind` base/overlay, `priority`,
  `label`, `emoji`, `help`, `when` (OR groups of AND clauses `{signal, op, value}`, `$name` →
  `chronos.presence.<name>`), `effects`, `notice`. One base (highest priority that matches) + every matching overlay.
  Core (editable, not deletable): `awake`, `idle`, `dnd`. Built-in optional: `nap`, `deep_sleep`, `busy`,
  `eating`, `tired`. Modules may add their own with `POST /api/presence/states/register`.
- **Effects**: `work.light`/`work.heavy` (allow < local < defer), `llm.claude` (allow < save < deny),
  `notify.level` (all < important < urgent), `chat.style` (normal < brief), `chat.notice` (text). Overlays combine
  "most restrictive wins".
- **Night** = agenda window `assistant.sleep` (owner chronos, daily 01–07): move/skip it from the calendar.
- **Evaluation** on every signal change, setting change and agenda tick. A change stores snapshot + history in
  Archive (`/api/presence-store`), emits Hermes event `assistant.state_changed` (only to subscribers) and, when
  `notify.level` relaxes, asks Hermes to release held notifications as one digest.
- **Settings** (group Presenza): `enabled`, `idle_after` 5, `nap_after` 45, `sleep_after` 180 (0 = night only),
  `use_sleep_window`, `dnd_default_duration` 120, `tired_quota` 25 %, `tired_degraded` 2, `count_ui_actions`,
  `oracle_context_line`, `states` (advanced).
- **MCP**: `stato`, `nondisturbare`, `disturbami` (Telegram group sistema).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/presence` | Current state: base, overlays, label, effects, last interaction, activities |
| `POST` | `/api/presence/ping` | User interaction `{client, kind}` |
| `POST` | `/api/presence/activity` | Start an activity `{key, label, load, resource, kind, module, ttl_seconds}` |
| `DELETE` | `/api/presence/activity/{key}` | Stop an activity |
| `PUT`/`DELETE` | `/api/presence/signals/{key}` | Set/clear a fact `{value, meta, ttl_seconds}` |
| `POST`/`DELETE` | `/api/presence/dnd` | Do not disturb on (`minutes`, default setting) / off |
| `GET` | `/api/presence/states` | Effective state definitions (settings + module-declared) |
| `POST` | `/api/presence/states/register` | Module-declared states `{owner, states}` |
| `GET` | `/api/presence/history` | Last state changes |

