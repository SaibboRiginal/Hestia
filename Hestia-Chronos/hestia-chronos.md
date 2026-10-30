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
The flat shape of the `create_event` / `calendar_create_event` tools is accepted too: `{title, start_datetime,
end_datetime?, description?, location?, provider?, calendar_id?}` is wrapped into `event` (`provider` →
`target_providers`); no end = one hour after the start (before 2026-10-30 every assistant call was a 422).

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
| `CALENDAR_PORT`, `CALENDAR_SERVICE_VERSION`, `STARTUP_WAIT_TIMEOUT_SECONDS`, `LOG_LEVEL` | Bootstrap / infrastructure |
| `CHRONOS_UI_DIST` | WebUI plugin bundle folder (Dockerfile sets `/ui/dist`, outside the `app/` dev mount) |
| `TZ` | Container timezone (default Europe/Rome): reminder times, agenda wall time, "today" of `/api/calendar/agenda` |

Everything tunable is a Themis setting (see **Settings** below); env keeps only infrastructure.

## Settings (Themis, owner `chronos`)

One `SettingsClient("chronos")` (`app/core/presence_settings.py`); agenda/calendar/reminder keys are declared in
`app/core/chronos_settings.py`. All `apply=live`: read at use time, loops re-read them every iteration.

| Key | Default | Group | What |
|---|---|---|---|
| `chronos.agenda.tick_seconds` (adv.) | 60 s (15–600) | Agenda | Agenda worker tick |
| `chronos.agenda.max_attempts` (adv.) | 5 | Agenda | Retries of a one-off `task` before `failed` |
| `chronos.sync.notify_new` | on | Calendario | Notice for a new future event found in Google/Outlook |
| `chronos.sync.look_ahead_days` | 30 | Calendario | Days ahead imported by the sync |
| `chronos.sync.look_back_days` (adv.) | 1 | Calendario | Days back re-read by the sync |
| `chronos.sync.calendar_id` (adv.) | `primary` | Calendario | Provider calendar id read by the sync |
| `chronos.reminders.look_ahead_hours` | 26 h | Promemoria | First reminder ("1d" bucket upper bound; then 2 h and 30 min) |
| `chronos.reminders.poll_seconds` (adv.) | 300 s | Promemoria | Reminder worker poll |
| `chronos.catchup.max_age_hours` | 6 h (0–48) | Agenda | After «Non disponibile», missed work younger than this is redone, older is only listed |
| `chronos.flex.gap_minutes` | 15 min | Agenda | Margin kept from your events by flexible activities |
| `chronos.coach.day_start` / `day_end` | 07:00 / 22:00 | Piano della settimana | Window where the weekly plan may place blocks |
| `chronos.coach.buffer_minutes` | 15 | Piano della settimana | Free minutes kept around calendar events |
| `chronos.coach.max_blocks_per_day` / `max_minutes_per_day` | 2 / 120 | Piano della settimana | Daily load limits of the plan |
| `chronos.presence.*` | see Assistant presence | Presenza | Presence engine |
| `chronos.log.level` (adv.) | `LOG_LEVEL` | Diagnostica | Log level |

Not settings on purpose: the **sync frequency** is the recurrence of the agenda job `chronos.calendar_sync`
(code default 15 min; the user moves it in the agenda, and **pausing/cancelling it turns calendar sync off**, also
at boot — there is no separate on/off switch); the **timezone** is the container `TZ`.

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

- Reminder times shown in `TZ` (default Europe/Rome) with Italian month names; titles,
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
| `task` | one-off action executed at `start_at` (retried up to `chronos.agenda.max_attempts`, then `failed`) | a repair Argus/Hephaestus planned for tonight |
| `job` | recurring action (RRULE) | "Controlla le email nuove ogni 15 min" |
| `window` | recurring period in which something is allowed (RRULE + duration) | "Claude Pro: notti prima del reset" |

Actions are `{service, method, path, body, query, timeout_seconds}` executed **through Hub** by the agenda worker
(setting `chronos.agenda.tick_seconds`, 60 s). Recurring jobs fire only their latest due occurrence (no storm after downtime).
Recurrence is evaluated in local wall time (`tz`, default `TZ`/Europe/Rome), DST-safe.

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
| POST | `/api/agenda/retire` | `{owner, keys}` → `{retired}`: a module cancels default rules it no longer declares. Only rules with that `owner` **and** `created_by` = the module; marked `params.retired_by_module=true` and cancelled (`by=module:<owner>`); user-created items and already-cancelled ones untouched (`hestia_common.agenda_client.AgendaClient.retire`) |
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
| POST | `/api/agenda/parse` | Natural-language quick add `{text, tz?}` → `draft {title, type, start_at, end_at, recurrence, description}` (Oracle `/api/llm/generate` through Hub, use case `chronos.agenda` declared in the Hub registration; Chronos validates; nothing created) |
| GET | `/api/agenda/ics?days=60&past_days=7&owner=&types=event,task,window` | Read-only iCalendar feed (expanded occurrences, skips/moves applied; jobs excluded by default) |
| GET | `/api/agenda/runs?owner=&status=ok\|failed\|skipped&since=\|hours=&limit=100` | Every recorded run of jobs/tasks (from `meta.runs`) + skipped past occurrences, newest first, with `summary {ok, failed, skipped, avg_ms, failed_items}` and `owners` (rules registered per module: active / paused / failed / changed by the user, per type) — plugin page *Esecuzioni* |
| GET | `/api/agenda/logs?service=&at=&minutes=5&level=&contains=` | A module's logs around an occurrence: Chronos reads `{service}/api/logs` through Hub (its in-memory buffer, last 2000 lines) and keeps `at ± minutes` (1–120); `{service, from, to, count, oldest, logs}`; module unreachable → 502 (`[🔄] event=agenda_logs_failed`) — Agenda *Log del modulo* |
| GET | `/api/agenda/standard` | Standard activities: every default rule a module declared (not user items, not retired) with `state` eliminata / fallita / in pausa / modificata / attiva, `can_restore`, `flex`; plus `templates` and `counts` |
| POST | `/api/agenda/standard/{key}/restore` | Put a standard activity back as the module declares it: status confirmed, `user_modified` off, declared fields re-applied (404 = not a module default) |
| GET | `/api/agenda/runs/failed?hours=24` | Chips `[{id: key, label, owner, at, detail, state: late}]` of jobs whose last run failed (or stopped `failed`) — source of the quick action *Riprova job* |

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
`agenda_assistente_modelli`, `agenda_assistente_da_modello`, `agenda_assistente_collega`. Standard activities: `agenda_standard`, `agenda_standard_ripristina` (Telegram, WebUI). Oracle turns a
successful write of these into an `agenda.planned` notice (calendar pages reload live).

### Flexible activities (`params.flex`, dossier `docs/work/2026-10-20-recap-giornaliero` §3.8)

A recurring job or task may carry `params.flex = {earliest: "HH:MM", latest: "HH:MM"}` (`job_rule(..., flex=)`, or the
calendar editor «Orario flessibile»). The nominal time stays the one you see and move. When it falls on one of your
events (calendar items of every source but `hestia`, all-day ones excluded) or closer than `chronos.flex.gap_minutes`,
the tick fires it after the event (chained events walked through), else before it, else at the end of the range
(`services/flex.py`, deterministic). The run records `flex {from, at, reason}` («dopo Cena»), shown in the
occurrence details; log `event=agenda_flex_moved`. Calendar unreadable → nominal time (`[🔄] event=agenda_flex_calendar_failed`).
An occurrence you moved by hand never flexes. First user: the evening recap `athena.recap.evening` (21:30, 20:00–23:30).

### Standard activities (dossier `docs/work/2026-10-20-recap-giornaliero` §3.9)

Chronos keeps in memory the last rule set each module declared (`register`). Page **Attività standard**
(`chronos-standard`, under Agenda, order 152) lists them with their state; one you deleted, paused, that stopped for
errors or that you changed comes back with **Ripristina** (`POST /api/agenda/standard/{key}/restore`). The page also
lists the templates of each module («Da aggiungere», created from the calendar wizard).

### Recap piece

`GET /api/module/recap` piece «Agenda» (`services/day_view.py`): your events of the day, assistant tasks done /
skipped / failed and jobs that failed (a job that works is not news); next: tomorrow's events and tasks.

### Who plans what (registered rules)

Every module registers its defaults at boot (and re-asserts them hourly, idempotent) with the shared client
`hestia_common/agenda_client.py`. Missing rule or Chronos down → the module falls back to its env schedule, so
nothing stops; a rule the user **paused/cancelled** is a decision and is respected (no fallback).
A rule a module no longer needs is removed with `retire` (e.g. Scout's old `scout.email_cycle`, retired 2026-10-19
when mail moved to push). No module polls mail: they subscribe to Iris.

| Key | Type | Owner | Default | What happens |
|---|---|---|---|---|
| `hecate.mail_watch` | job | hecate | every `hecate.mail.watch_interval` (15 min; `hecate.mail.safety_interval` 6 h with Gmail Pub/Sub) | `POST hecate /api/gateway/mail/watch/run` — the one mailbox check; new mail → Iris → subscribed modules |
| `hecate.mail_watch_renew` | job | hecate | daily 04:10, only when Gmail Pub/Sub is configured | `POST hecate /api/gateway/mail/watch/renew` — renews Gmail push (expires after 7 days) |
| `plutus.daily` | job | plutus | daily 21:00 | `POST plutus /api/finance/alerts/run` — budget alerts + recurring detection |
| `plutus.review` | job | plutus | 1st of the month 09:00 | `POST plutus /api/finance/review/run` — monthly review (only if `plutus.review.enabled`) |
| `plutus.statement_reminder` | job | plutus | days 3, 6, 9 of the month 10:00 | `POST plutus /api/finance/reminders/run` — «carica l'estratto» if last month's statement is missing (only if enabled) |
| `athena.recap.evening` | job | athena | daily 21:30, flexible 20:00–23:30 | `POST athena /api/athena/recap` — the evening recap (nothing on a quiet day) |
| `chronos.calendar_sync` | job | chronos | every 15 min (edit/pause in the agenda) | `POST chronos /api/calendar/sync` — Hecate → Archive sync |
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

## Export and import of the agenda (`/api/transfer/*`, dossier `docs/work/2026-10-20-import-export`)

One section `agenda` (`services/agenda_transfer.py`): items the user created and module rules the user changed
(moved, edited, paused, cancelled). Untouched module defaults stay home (every Hestia registers its own); run state
(last run, attempts, run log) is never exported and the target's is kept. An imported module rule is marked
`user_modified`, so its module will not overwrite it. «Sostituisci» cancels the user's own items that are only here.
Calendar items synced from Google/Outlook are not exported. Settings travel through Themis.

## WebUI plugin — inside view (2026-10-18, dossier `docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2)

Core module (`kind: "core"`, WebUI *Sistema* section, order 150), `api_prefix` `/api/agenda/` (Chronos' own
agenda routes: no duplicate endpoints):
- page **Agenda di Hestia** (`chronos-agenda`, order 150, since 2026-10-19; `/calendar` redirects to
  `/p/chronos/agenda`): the calendar moved from the WebUI (`ui/src/agenda.ts` + `ui/src/cal/`) with the same
  behaviour (month/week/day/list, mini calendar, filters, popover details, editor with recurrence, wizard *Da un
  modulo…*, quick add, drag & drop, skip/move one occurrence or the whole series, run now, *Chiedi a Hestia*
  through the host assistant, *Apri in Sviluppo* for Forge items). Edits are sent `by=user`. *Log del modulo*
  reads `GET /api/agenda/logs`; the phone ICS feed stays a WebUI path (`/api/webui/agenda/feed.ics?key=`).
- page **Esecuzioni** (`chronos-runs`): runs of the assistant agenda (riuscito / fallito / saltato, time, module,
  duration, started by the agenda or by hand, error detail), filters by outcome / period / module, *Riprova* on a
  failed run, and **Regole per modulo** (what each module registered, paused, stopped, changed by the user); it
  sits under Agenda (order 151). Each item keeps its last 50 runs.
- widget **Job falliti** (`chronos-failed-widget`, s/m, auto): jobs failed in the last 24 h with *Riprova*.
- quick action **Riprova job** (dynamic: `source` `/api/agenda/runs/failed`, `POST /api/agenda/items/{id}/run`
  = the existing run-now). When a manual run of a rule stopped as `failed` works, the rule goes back on (recurring →
  `confirmed`, one-off → `completed`, `reactivated: true`, `event=agenda_reactivated`); a `paused` rule stays paused
  (Marko's choice, 2026-10-19).
- Chronos down → «Chronos non raggiungibile».

Bundle `ui/` → Dockerfile Node stage → `/ui/dist/webui/chronos.js`; manifest keys in the Hub registration
(`register_on_hub(extra_capabilities=…)`).

## Assistant presence (activity state)

SPEC `docs/work/2026-10-10-assistant-presence`. Chronos keeps the assistant's general state, like a person:
**facts (signals) → states (data) → effects**. Consumers never test a state name, they ask an *effect*
(`hestia_common.presence_client`), so a new state needs no code change anywhere.

- **Signals**: `user.last_interaction` (pings from Oracle chat, Telegram, WebUI actions), activities
  (`activity.<key>`: label, load light/heavy/maintenance, resource, ttl), `manual.dnd`, facts such as
  `resource.claude_quota_left` (Forge) and `health.degraded_services` (Argus). Derived: `user.idle_minutes`,
  `activity.heavy_count`, `activity.maintenance_count`, `agenda.window.<key>`, `setting.<name>`, `clock.*`.
- **States** = Themis setting `chronos.presence.states` (object keyed by state): `kind` base/overlay, `priority`,
  `label`, `emoji` (Telegram), `icon` + `tone` (WebUI stroke icon and colour: success · warning · danger · info · accent · muted), `help`, `when` (OR groups of AND clauses `{signal, op, value}`, `$name` →
  `chronos.presence.<name>`), `effects`, `notice`. One base (highest priority that matches) + every matching overlay.
  Core (editable, not deletable): `awake`, `idle`, `dnd`. Built-in optional: `nap`, `deep_sleep`, `busy`,
  `eating`, `tired`, `oracle_offline` («⏳ Non disponibile», signal `oracle.offline` from Argus when Oracle is down past
  `argus.oracle.grace`; effects `work.light`/`work.heavy` defer, `chat.reply` queued; SPEC
  `docs/work/2026-10-19-oracle-offline`), `oracle_limited` («Limitato», icon `battery-low`, signal `oracle.limited`
  from Argus when only fallback models answer; effects `work.heavy` defer, `chat.style` brief). Modules may add their own with `POST /api/presence/states/register`.
- **Effects**: `work.light`/`work.heavy` (allow < local < defer), `llm.claude` (allow < save < deny),
  `notify.level` (all < important < urgent), `chat.style` (normal < brief), `chat.reply` (live < queued: chat
  clients queue what Oracle cannot answer), `chat.notice` (text). Overlays combine
  "most restrictive wins".
- **Night** = agenda window `assistant.sleep` (owner chronos, daily 01–07): move/skip it from the calendar.
- **Evaluation** on every signal change, setting change and agenda tick. A change stores snapshot + history in
  Archive (`/api/presence-store`), emits Hermes event `assistant.state_changed` (only to subscribers) and, when
  `notify.level` relaxes, asks Hermes to release held notifications as one digest; when `chat.reply` goes back to
  `live` (Oracle online again) it calls every Hub service declaring `capabilities.chat_queue_drain` (its path, via Hub
  route) so each chat client answers its queued messages, then runs the **catch-up** «Mentre non c'ero»
  (`app/services/catchup.py`, v3 D): agenda items whose last run failed during the outage are re-run
  (`run_now(by="catchup")`) when younger than `chronos.catchup.max_age_hours` (6), older ones are only listed; one
  Hermes message (`service.action_required`, entity `assistant.catchup`) says what was done.
- **Settings** (group Presenza): `enabled`, `idle_after` 5, `nap_after` 45, `sleep_after` 180 (0 = night only),
  `use_sleep_window`, `dnd_default_duration` 120, `tired_quota` 25 %, `tired_degraded` 2, `count_ui_actions`,
  `oracle_context_line`, `states` (advanced).
- **MCP**: `stato`, `nondisturbare`, `disturbami` (Telegram group sistema).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/presence` | Current state: base, overlays, label, `help` (plain explanation of the base state), effects, last interaction, activities, `dnd_minutes` |
| `POST` | `/api/presence/ping` | User interaction `{client, kind}` |
| `POST` | `/api/presence/activity` | Start an activity `{key, label, load, resource, kind, module, ttl_seconds}` |
| `DELETE` | `/api/presence/activity/{key}` | Stop an activity |
| `PUT`/`DELETE` | `/api/presence/signals/{key}` | Set/clear a fact `{value, meta, ttl_seconds}` |
| `POST`/`DELETE` | `/api/presence/dnd` | Do not disturb on (`minutes`, default setting) / off |
| `GET` | `/api/presence/states` | Effective state definitions (settings + module-declared) |
| `POST` | `/api/presence/states/register` | Module-declared states `{owner, states}` |
| `GET` | `/api/presence/history` | Last state changes |



## Weekly plan — coaches (dossier `docs/work/2026-10-20-coach-di-ogni-tipo`)

Chronos builds **one week** from what every coach module needs, in the free time around the user's calendar.
It never reads domain words: only the generic need fields of `hestia_common.coach` (kind block/slot/target, count,
minutes/min_minutes, days, time_of_day, gaps, `not_same_day`, `with`, priority).

- **Coaches** = services with Hub tag `coach` (`GET {HUB}/registry/services`), read through Hub
  (`GET /api/coach/needs`, optional `POST /api/coach/fit` for a shorter variant, `POST /api/coach/placed`,
  `GET /api/coach/review`). A module that does not answer keeps its last plan (`[🔄] event=coach_needs_failed`).
- **Planner** `app/services/coach_planner.py` (deterministic, pure): free intervals per day = day window minus
  user calendar events (Archive, non all-day) and user busy blocks, with the buffer; places must → should → could,
  full length first, else the module's shorter variant; respects the daily limits. Unplaced needs come back with a
  reason («non entra»). **Orchestration** `app/services/coach.py`.
- **Outdoor rule** (weather dossier `docs/work/2026-10-20-meteo-hecate`): needs tagged `outdoor` (e.g. a run) are
  not placed in hours with rain (≥50 % or ≥0.5 mm) or dark at Casa — Hecate forecast read only when such a need
  exists (`plan_week(wet=…)`, `wet_hours`); no forecast = no filter (`[🔄] event=coach_weather_failed`).
- **Plan items** = assistant agenda `event` items, owner = the module, key
  `coach.<week>.<module>.<need_id>.<date>`, parent `coach.week.<week>` (week = ISO date of its first day; the parent's
  params hold targets, unplaced, states, the weekly text). `params.coach_status` planned/done/skipped/replanned.
  Items the user moved (`user_modified`) are kept and never moved back; a skipped need is not re-placed that day.
- **Re-plan** of the rest of the week only (never the past), pushed and debounced 5 s: module reports
  (`POST /api/agenda/coach/report` done/skipped/changed via `hestia_common.coach.CoachClient`), a calendar sync that
  now overlaps a planned block (`sync_worker` → `on_calendar_synced`), chat/page («Rifai il piano», busy block).
  A change to today/tomorrow sends one notice through Hermes (`reminder_event`, domain `system`, key `coach.change`).
- **Weekly job** `chronos.coach_week` (agenda, the day before the week starts, 18:00; pausing it stops the weekly
  plan — no switch) → plan + Oracle use case `chronos.coach` writes the message (fixed-text fallback) → Hermes
  (`coach.week`, link to the page).

Endpoints (plugin prefix): `GET /api/agenda/coach/week?date=`, `GET /api/agenda/coach/today`,
`GET /api/agenda/coach/review?date=`, `POST /api/agenda/coach/replan {date?, busy?}`, `POST /api/agenda/coach/week/run`,
`POST /api/agenda/coach/report {module, event, need_id?, at?}`, `POST /api/agenda/coach/items/{key}/move {start_at, end_at?}`,
`POST /api/agenda/coach/items/{key}/skip`, `POST /api/agenda/coach/busy {start_at, end_at, title}`,
`DELETE /api/agenda/coach/busy/{key}`. MCP tools: `coach_week`, `coach_replan`, `coach_move`, `coach_skip`,
`coach_add_busy`, `coach_review` (domain `coach`).

WebUI: page **«La tua settimana»** (`settimana`, element `chronos-week`): seven columns (one day at a time on a
phone), blocks with the area icon, slots as chips, targets with a bar, «Non entra», last week's review; drag a
block to another day or «Sposta» (= user move), «Salta», «Rifai il piano», «Aggiungi impegno». Widget
**«Oggi nel piano»** (`chronos-today-widget`). Icons from the kit, never emoji, no module names in texts.


## Weather on the calendar page (dossier `docs/work/2026-10-20-meteo-hecate` §3.7)

`POST /api/agenda/weather {start, end, located: [{id, place, at}]}` (`app/services/agenda_weather.py`) → `{days,
events, external, horizon: 14}`: Casa's weather per day (chip next to the day number: icon, min–max, rain hours),
weather at located agenda items (`params.place`, e.g. a planned run) and at Marko's own provider events that have a
location (Hecate, cached 10 minutes; only shown, never modified). Only the next 14 days; one Hecate `weather/at`
call; failures answer empty parts. The calendar views (month, week/day grid, list) show the chips with kit icons.

## Telegram card (`display`)
`GET /api/calendar/agenda` returns a `display` card (time · title · place, grouped by day when more than one day; Nuovo evento, Prossimi giorni / Solo oggi). `GET /api/calendar/agenda/today` = the same for today only (tool `agenda_today`, which used to show 7 days). Built with `hestia_common.display`; Hestia-MCP keeps it only for Telegram (docs/work/2026-10-23-telegram-da-zero §6).

## Routines, special events, smart calendar (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy` W2)

Code: `app/life_api.py` (endpoints, MCP tools, agenda rules), `app/services/routines.py`, `special.py`,
`smart_calendar.py`, `app/core/life_store.py` (rows in Archive `/api/chronos-store`).

**Routines in words** (Cindy 7 + 27 + 28). A routine is an assistant-agenda rule (owner `chronos`, key
`routine.<slug>-<id>`) with `params.routine = {instruction, precheck?, deliver, on?, template?}`:
- by time → a `job` (RRULE) whose action is `POST /api/routines/{key}/run`; by event → an `event` with `on`
  `{"mail": {senders, subject_contains}}` (Chronos subscribes to Iris, push, domain `routine_mail`) or
  `{"signal": "<name>"}` (a module calls `POST /api/routines/signal`; Chronos itself sends `special_moment`).
- run: optional pre-check tool first (an empty answer stops the run, no model call), then one assistant turn with
  origin `routine:<key>` (writes allowed, no deletes), then the answer goes to Hermes (`routine.result`) or is kept
  for the evening recap (`deliver: recap`, also stored in `chronos-store` kind `routine_result`). The assistant
  answers `NIENTE` when there is nothing to say: nothing is sent. Pause, move, «Esegui adesso» = the agenda.
- gallery: `GET /api/routines/templates` (radar notizie, case nuove, spese da rivedere, la settimana, mail da un
  mittente) → `POST /api/routines/from-template/{id}` with the template's fields.

**Special events** (B6). Agenda `event`s `special.<…>` with `params.special = {kind birthday|anniversary|custom,
lead_days, person, person_id, note, source}`; birthdays/anniversaries are yearly. Sources: the personal setting
`themis.personal.birth_date` (followed, synced at boot and on change; the owner's edits win), the owner (tool
`special_add`), modules with a stable key (`by` = module: idempotent, the owner's edits win), the assistant only by
proposal (`special_propose` → Hermes card «Aggiungi» / «No»). Daily job `chronos.special.daily` (08:00):
«Tra N giorni» `lead_days` before, and on the day the greeting plus `special_moment` to every Hub service declaring
`capabilities.special_moment_endpoint` and to routines waiting for that signal. The recap shows tomorrow's ones.

**Smart calendar** (B8). Daily job `chronos.smart_calendar` (07:00) or tool `calendar_check`: overlapping timed
events of the next days (the owner's, not the assistant's) → Hermes card «Sposta alle HH:MM» (first free slot of
the same day between 08 and 21 with the `chronos.flex.gap_minutes` margin, through `PATCH /api/calendar/events/{id}`)
/ «Lascia così» (`POST /api/calendar/smart/kept`, remembered in `chronos-store` kind `smart_kept`). Never moves
anything by itself.

**Manual presence** (Telegram parity). `POST /api/presence/manual {state, minutes?}` sets the signal `manual.state`
(any defined state: a base state wins over the rules, an overlay is added); `DELETE` gives control back.

**WebUI pages** (W7, plugin `api_prefix` `/api/agenda/`): **Routine** (`routine`, `chronos-routines`, order 153: new
routine in words by time or by mail, the ready-made gallery, «Esegui adesso» / Pausa / Elimina through the agenda item
routes; Hermes `_link` of `routine.result`) and **Eventi speciali** (`eventi`, `chronos-special`, order 154: list with
days left and lead time, add, remove; the birthday from the personal settings is not removable there; `_link` of
`special.today` / `special.soon`). The proxy only allows the plugin prefix, so the owner-facing routes are also served
as `/api/agenda/routines` (GET/POST), `/api/agenda/routines/templates`, `/api/agenda/routines/from-template/{id}`,
`/api/agenda/special` (GET/POST), `/api/agenda/special/{key}` (DELETE) — same handlers as `/api/routines…` and
`/api/special…`, which stay for modules and the tools.

| Method | Path | |
|---|---|---|
| `GET` / `POST` | `/api/routines` | list · create `{title, instruction, recurrence?, on?, precheck?, deliver}` |
| `GET` | `/api/routines/templates` | gallery |
| `POST` | `/api/routines/from-template/{id}` | `{values, recurrence?, title?}` |
| `POST` | `/api/routines/{key}/run` | agenda action / run now |
| `POST` | `/api/routines/signal` · `/api/routines/mail` | event triggers (module signal · Iris doorbell) |
| `GET` / `POST` | `/api/special` | list (with `next`, `in_days`) · add |
| `DELETE` | `/api/special/{key}` | remove |
| `POST` | `/api/special/propose` · `/api/special/proposal/declined` · `/api/special/run` | proposal card · «No» · daily pass |
| `POST` | `/api/calendar/smart/check?days=3` · `/api/calendar/smart/kept` | check · keep as is |
| `POST` / `DELETE` | `/api/presence/manual` | manual state on / off |

MCP tools (all on Telegram through the dynamic menus): `routine_list`, `routine_templates`, `routine_create`,
`routine_from_template`, `routine_run`, `special_list`, `special_add`, `special_remove`, `special_propose`,
`calendar_check`, `presence_set`, `presence_clear`, `presence_history`.
