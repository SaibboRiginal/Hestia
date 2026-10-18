# SPEC — Core modules as WebUI plugins (see inside Hestia) · External AIs on Hestia via MCP

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User request · channel: project thread (Claude Code cloud session) · 2026-10-18 |
| **Status** | Draft — waiting for Marko's ok before implementing |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): add the **system / core modules** too (Athena, the ones that
run the assistant itself like Hermes, the monitoring ones) so you can **see and show what happens inside and how they
work**. Example: the development list (Forge) — give **external AIs (like Claude) a way to see it via MCP** and fix
items, so Marko is not forced to use only local models or Forge with Claude; or is an **exported list** simpler?
Follow-up: can these MCPs be connected to Claude and other AI tools? Keep every project `.md` up to date.

---

## Part A — Core modules ship their own "inside view" as WebUI plugins

### A1. Goal

Every core module that has something worth seeing ships a small plugin (pages + widgets) on the **existing client
plugin contract** (`docs/work/2026-10-17-client-plugins/SPEC.md` §4): same `hestia_common.plugin_client`, same Hub
catalog, same SDK kit. The WebUI groups them in a **Sistema** section of the sidebar. Nothing new in the WebUI except
that grouping: a core module appears/disappears exactly like Scout does.

Why plugins and not more built-in Angular pages: the rule is "each module does only its own job"; who knows what is
inside Athena is Athena. A module that changes its internals updates its own page in the same change.

### A2. What each module shows (first set)

| Module | Page(s) | Widget(s) | Reads (existing endpoints unless marked *new*) |
|---|---|---|---|
| **Hub** | *Mappa* — every service: online, node, version, last heartbeat, topology tags, registry revision | *Servizi online* (auto) | `/api/registry/services`, `/api/status` |
| **Argus** | *Salute* — health per service over time, open incidents and what Argus did, log viewer with filters, *Ricontrolla* | *Stato sistema* (auto) | `/api/argus/status`, `/api/argus/logs`, `POST /api/argus/recheck/{svc}` |
| **Oracle** | *Cervello* — recent activity (requests, chosen domain/tools, provider, ms), use per use case/model, tokens/cost per day, Claude Code status | *Uso modelli oggi* | `/api/activity`, `/api/llm/code/status`, *new* `/api/ui/stats` (from `llm_stats`) |
| **Athena** | *Pensieri* — each cycle: observe → think → gate score (5 factors) → act, accepted/discarded with reasons; commitments; *Pensa ora* | *Ultimo pensiero* | `/api/athena/thinking`, `/api/athena/commitments`, `POST /api/athena/trigger` |
| **Hermes** | *Consegne* — what was sent to which client, held/quiet/retracted, answers, subscriptions (the Notifiche page stays the inbox) | *Consegne oggi* | `/api/notifications`, `/api/notifications/clients`, *new* `/api/ui/deliveries` if the delivery log is not already exposed |
| **Chronos** | *Esecuzioni* — job runs of the assistant agenda: ok/failed/skipped, duration, rules registered per owner (the Agenda page stays the calendar) | *Job falliti* | `/api/agenda/items`, *new* `/api/ui/runs` if runs are not already listable |
| **Themis** | *Registro* — every setting change and proposal: who (Marko, Athena, Oracle, client), when, old → new, undo | — | `/api/settings/proposals`, `/api/settings/key/{k}/history`, *new* `/api/ui/history` (all keys, paged) |
| **Hephaestus** | *Riparazioni* — remediation tasks (runbook, consent, dry-run, outcome, rollback) | *Forge* (state, queue, budget) | `/api/hephaestus/tasks`, Forge `/status`, `/claude-budget` |
| **Metis** | *Miglioramento* — insights, LoRA jobs | — | `/api/metis/insights`, `/api/metis/lora/jobs` |

Hestia-MCP is already covered by the *Comandi & MCP* page; Hecate/Iris/Atlas/Archive come later if wanted.
Exact fields are fixed per module during its phase (endpoint reading first, *new* endpoints only where data is missing).

### A3. Contract additions (small)

- Manifest gains `kind: "core" | "domain"` (default `domain`); `PluginClient(..., kind="core")`. The WebUI puts
  `core` modules under a collapsible **Sistema** sidebar section, below the domain modules.
- Plugin order for core modules: hundreds, one decade each — Hub 100, Argus 110, Oracle 120, Athena 130, Hermes 140,
  Chronos 150, Themis 160, Hephaestus 170, Metis 180 (domain modules keep 20–50).
- Core plugins call their **existing** API: `api_prefix` is the module's own prefix (e.g. `/api/athena/`), so the WebUI
  call proxy (only paths under `api_prefix`, 403 otherwise) needs no change and no duplicate endpoints are written.
  Modules whose routes are spread over several prefixes (Hub, Hermes) add the few `/api/ui/` reads instead.
- Bundles: `Hestia-<Name>/ui/` built in the module Docker image (Node stage), like Scout. Pi-hosted modules (Hub,
  Hermes, Chronos, Themis, Argus) build for arm the same way (the stage output is plain JS).
- Visibility uses the existing WebUI settings (`webui.plugins.hidden`); no new setting, no switch.
- Actions that change something (Ricontrolla, Pensa ora, Annulla impostazione) are the module's existing actions;
  anything that needs Marko's consent keeps going through Hermes / Themis proposals as today.

### A4. Built-in pages stay (default)

*Sviluppo* (Forge), *Notifiche*, *Agenda di Hestia*, *Impostazioni* are large built-in pages and keep working as they
are. Core plugins add the *inside view* next to them. Moving them into plugins is possible later, one per change.

## Part B — External AIs on Hestia: MCP (recommended) vs an exported list

### B1. Options

| | **Export** (file / "Copia per AI") | **MCP server for external clients** |
|---|---|---|
| Effort | very small (one button on Sviluppo, markdown/JSON) | medium (endpoint, auth, tunnel, audit) |
| Freshness | snapshot, stale at once | live |
| Direction | one-way: AI reads, you copy back by hand | two-way: AI reads tasks, logs, dossiers, and **submits** work |
| Works with | any AI, even without connectors | every MCP client (B3) |
| Safety | nothing exposed | must be guarded: token/OAuth, read-mostly, writes go through Forge + Marko's approval |

**Recommendation: MCP**, because most of it already exists (Hephaestus already declares `forge_*` tools, Hestia-MCP
already aggregates every module's tools and proxies calls through Hub) and only MCP lets an external AI actually fix
items. The export is kept as a tiny extra (B5) because it costs almost nothing and works with any chat.

### B2. Design

- **Owner = Hestia-MCP** (its job is "single tool source"). It gains a standard **MCP Streamable HTTP** endpoint
  `POST /mcp` (JSON-RPC: `initialize`, `tools/list`, `tools/call`, `ping`) for external clients, next to the internal
  `/tools` API Oracle uses. Calls are still proxied through Hub like today.
- **Which tools**: only tools whose module declares `"external"` in `MCPTool.clients` (the same client list the catalog
  already uses for `telegram`/`ui`). The module decides what may leave the house; nothing is exposed by default.
- **Public door = WebUI** (the only service already behind the Cloudflare tunnel): WebUI `/mcp` forwards to Hestia-MCP
  through Hub (`/route/mcp/mcp`). No new port is published.
- **Auth**:
  - B-phase 1: bearer token `HESTIA_MCP_EXTERNAL_TOKEN` in `.env` (secret → env is right; empty = endpoint answers 404).
    Works with Claude Code, Claude Desktop (config file), Cursor, VS Code, Gemini/Codex CLI.
  - B-phase 2: OAuth 2.1 in the WebUI (metadata, dynamic client registration, authorize = existing WebUI login + a
    consent page) for clients that only speak OAuth: **claude.ai web/mobile custom connectors, ChatGPT connectors**.
- **Audit**: every external call logged `event=mcp_external_call client=<name> tool=<tool> ok=<bool>`; every write
  tool also leaves a silent Hermes inbox entry ("Claude esterno ha creato il task …"), no push.
- **Settings (Themis)**: `mcp.external.max_calls_per_min` (int, default 60). No on/off switch: the token is the door.
- **Stable URL**: `cloudflare-tunnel.bat` today opens a *quick* tunnel (random `trycloudflare.com` URL each start). A
  connector needs a fixed URL → named tunnel with a hostname (Marko's Cloudflare account; the hostname lives in `.env`,
  not in the repo). Local clients on the same PC can use `http://localhost:19015/mcp` without the tunnel.

### B3. Can it be connected to Claude and other AI tools? Yes — MCP is an open standard

| Client | How | Needs |
|---|---|---|
| Claude Code (CLI/IDE/desktop) | `claude mcp add --transport http hestia <url>/mcp --header "Authorization: Bearer …"` | token |
| Claude Desktop | `claude_desktop_config.json` entry (or Connectors) | token / OAuth |
| claude.ai web + mobile, Claude projects (like this thread) | Settings → Connectors → custom connector URL | public HTTPS + OAuth (B-phase 2) |
| ChatGPT (connectors / developer mode) | connector URL | public HTTPS + OAuth |
| Cursor, VS Code Copilot, Windsurf, Gemini CLI, Codex CLI, LM Studio… | their MCP config (URL + header) | token |

### B4. Tools exposed to external clients (first set)

Read (no side effects):
- `forge_tasks(status?, q?, limit?)` — the development list (id, title, status, engine, created, last event).
- `forge_task(task_id)` — request text, status, engine, error, test results, WORKDOC name, branch, events.
- `forge_task_diff(task_id)` · `forge_dossier(name)` (SPEC/PROGRESS/CHANGELOG of a dossier) · `forge_status()`.
- `system_status()` (Hub registry + Argus) · `service_logs(service, level?, since?, q?)` (Argus/Hub logs, capped).
- `athena_thinking(limit?)` · `settings_get(key|module)`.

Write (guarded, nothing irreversible):
- `forge_develop(request)` — creates a normal Forge task (same queue, same approval).
- `forge_task_note(task_id, text)` — adds an analysis/hint to a task (shown on Sviluppo, used by Forge on retry).
- `forge_submit_branch(task_id, branch, summary)` — "I fixed it on this branch": Forge fetches the branch from the
  repo remote, runs its tests, asks Marko through Hermes as usual, then merges, restarts, health-checks, rolls back on
  failure. So the external AI codes wherever it likes (GitHub, its own checkout), Forge stays the only deploy gate.
- `settings_propose(key, value, reason)` — proposal only, Marko confirms via Hermes.

Never exposed: approve/reject/merge/rollback, direct setting writes, Hecate/Gmail, anything that sends messages.

### B5. Export (small extra)

Sviluppo page → **Copia per AI**: markdown of the selected tasks (request, status, error, dossier path, how to
submit a fix) to the clipboard or a `.md` download. Built from `forge_tasks`/`forge_task` output, so both paths say
the same thing. Nothing is written to the repo (task text can contain personal data; the repo is public).

## 3. Who does what

| Module | Job |
|---|---|
| Each core module | its plugin bundle, its read endpoints, `"external"` on the tools it lets out |
| Hub | unchanged (catalog already carries `kind` through the manifest) |
| WebUI | Sistema sidebar section; public `/mcp` door + auth (token, then OAuth); *Copia per AI* |
| Hestia-MCP | external MCP protocol endpoint, `external` filter, rate limit, audit log |
| Hephaestus (Forge) | `forge_task_note`, `forge_submit_branch`, external tools flagged |
| Hermes | silent inbox entries for external writes; approvals as today |
| Themis | `mcp.external.max_calls_per_min` |

## 4. Acceptance criteria

1. With the core images rebuilt, the WebUI sidebar shows **Sistema** with Hub, Argus, Oracle, Athena, Hermes, Chronos,
   Themis, Hephaestus, Metis pages; their widgets can be put on a dashboard; a stopped module shows "non raggiungibile".
2. Athena *Pensieri* shows the last cycles with gate scores; *Pensa ora* runs a cycle and the list refreshes.
3. Argus *Salute* shows a stopped service as down within one poll; *Ricontrolla* works.
4. `claude mcp add … /mcp` with the token → Claude Code lists only `external` tools; `forge_tasks` returns the list.
5. Wrong/missing token → 401; token empty in `.env` → 404; >limit/min → 429.
6. `forge_submit_branch` on a test task → Forge tests it, Marko gets the usual approval, merge + health check.
7. *Copia per AI* produces a readable markdown of the chosen tasks.
8. B-phase 2: claude.ai custom connector connects through OAuth and lists the same tools.
9. Phone 360 px and both themes for every core page.

## 5. Phases

- **P1 Contract + Sistema section**: `kind` in plugin_client/manifest/catalog, WebUI sidebar section, order decades,
  docs (client-plugins SPEC §4 note, DESIGN-SYSTEM, ARCHITECTURE).
- **P2 Monitoring plugins**: Hub, Argus, Oracle (+ `/api/ui/stats`), Athena.
- **P3 Assistant plugins**: Hermes, Chronos, Themis, Hephaestus, Metis (+ the *new* reads found missing).
- **P4 External MCP (token)**: Hestia-MCP `/mcp` + `external` filter + rate limit + audit; WebUI `/mcp` door;
  Forge `forge_task_note`, `forge_submit_branch`; tools flagged; *Copia per AI*; `.env.example`, swagger,
  `hestia-mcp.md`, README "Collegare un'AI esterna".
- **P5 OAuth for claude.ai / ChatGPT**: WebUI OAuth 2.1 (DCR + consent), named tunnel guide.

Each phase updates the module `.md`, swagger, README/ARCHITECTURE where touched, this dossier and the root CHANGELOG.
Tests written per phase, not run here (user rule).

## 6. Open choices (defaults in bold — Marko confirms)

1. Built-in Sviluppo/Notifiche/Agenda/Impostazioni pages: **stay built-in**, core plugins add the inside view.
2. External write tools: **only create task, note, submit branch, propose setting** (no approve/merge from outside).
3. OAuth (claude.ai web/mobile, ChatGPT): **included as P5** after the token version works.
