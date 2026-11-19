# SPEC — Remove the tools that were doubles of another tool

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Migliorare i prompt per ogni situazione», Marko 2026-11-14: «si i doppioni controlla se effettivamente non facevano cose diverse, ma rimuovi») |
| **Status** | Implemented; PR open |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).
Part of the tool review (285 tools, 2026-11-14). Only doubles: hiding tools from the chat was dropped (Marko wants
«mostrami i log di Oracle» to keep working) and merging tools waits for a separate decision.

## Rule

A tool is removed only when another tool does the same thing. The endpoint behind it always stays: other modules,
the site and Telegram call endpoints through Hub, not tools.

## Checked one by one

| Pair | Verdict | Why |
|---|---|---|
| `create_event` / `calendar_create_event` | **removed** `calendar_create_event` | same endpoint POST /api/calendar/events; `create_event` takes `provider` and `calendar_id` now |
| `scout.search` / `scout_listings` | **removed** `scout_listings` | same endpoint and search; listings = search with fewer filters. Routine «Case nuove», Telegram alias and Scout card now use `scout.search` |
| `gateway_auth_complete` / `gateway_auth_complete_google` | **removed** `gateway_auth_complete` | only Google completes with a code; same endpoint with provider=google |
| `system_remediate` (Argus) / `hephaestus_remediate` | **removed** `system_remediate` | Argus endpoint only forwards to Hephaestus |
| Oracle MCP `memory.save` / `memory_note`, `memory.search` / `memory_recall` | **removed** the MCP `memory.save` and `memory.search` | same save/search for Telegram, site and other AIs; the chat's own `memory.save`/`memory.search`/`memory.forget` (agent loop, turn guards) stay |
| `agenda` / `agenda_today` | kept | `agenda_today` = `agenda` with one day, but it is the Telegram «Oggi» card header, which needs a tool without arguments |
| `agenda` / `calendar_list_events` | kept | different source: Hestia's stored agenda vs a live provider query in a range |
| `metis_dataset_export` / `metis_dataset_esporta` | kept | different files: LoRA formats of a built dataset vs the sft/dpo/eval zip |
| `gateway_auth_status` / `gateway_auth_verify` | kept | status reads; verify tests every token and warns |
| `nondisturbare` / `presence_set` | kept | «Non disturbare» filters notifications; the manual state is the assistant's own state |
| `special_list` / `people_upcoming` | kept | people's dates come with gift ideas; special events also hold other dates |

## Acceptance

1. The five tools are not in their module's `/mcp` list; their endpoints answer as before.
2. Nothing in code, Telegram menus, routines or tests names a removed tool.
3. Tests of Oracle, Chronos, Scout, Hecate, Argus, Telegram, MCP green; precheck 0 failed.
