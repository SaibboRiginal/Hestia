# SPEC — Core modules as WebUI plugins (see inside Hestia) · External AIs on Hestia via MCP

| | |
|---|---|
| **Version** | 2.1 |
| **Source** | User request · channel: project thread (Claude Code cloud session) · 2026-10-18 |
| **Status** | Approved 2026-10-18 (Marko, card) — in progress, see PROGRESS.md |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): add the **system / core modules** too (Athena, the ones that
run the assistant itself like Hermes, the monitoring ones) so you can **see and show what happens inside and how they
work**. Example: the development list (Forge) — give **external AIs (like Claude) a way to see it via MCP** and fix
items, so Marko is not forced to use only local models or Forge with Claude; or is an **exported list** simpler?
Follow-up: can these MCPs be connected to Claude and other AI tools? Keep every project `.md` up to date.

v2.0 (Marko, after reading v1.0): the built-in pages become plugins too; the sidebar scrolls only on the module part
and on a short screen the rest hides under the fixed top → one scroll area, and a sidebar you arrange like VS Code
(pin = built dynamically, never duplicates); MCP **and** the export; **Oracle must use MCP like every other client**,
one single way to maintain; a way to manage MCP authentication for external sources; core modules get pages (and
widgets) — honest opinion asked.

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

### A4. Built-in pages become plugins too (v2.0)

The WebUI becomes a **shell**: it keeps only what is the client itself — **Home** (dashboards + quick actions),
**Chat** (+ "Crea con Hestia"), **Impostazioni** (generic renderer of every module's Themis settings + the WebUI's own
configuration) and login. Every other page moves to the module that owns it:

| Today (built-in) | Becomes plugin of | Notes |
|---|---|---|
| Sviluppo | Hephaestus (Forge) | biggest page; first to move, together with the MCP work (it gains *Copia per AI*) |
| Notifiche | Hermes | inbox + the new *Consegne* view as sub-pages; the sidebar badge comes from a plugin `badge` source |
| Agenda di Hestia | Chronos | calendar + *Esecuzioni* as sub-pages; ICS feed stays Chronos |
| Comandi & MCP | Hestia-MCP | catalog browser + *Accessi* (B6) |
| Documenti | Oracle | documents search/ingest is Oracle's today |

How: the Angular components are ported to the SDK kit (Lit) one page per change; the old route redirects to the new
`/p/<module>/…` so links in old notifications keep working. Until a page is ported it stays built-in (no gap).
Contract addition needed: a page/nav item may declare `badge: {source: "/api/…/counts", field: "unread"}` (polled by the
WebUI, same rule as quick-action `source`).

My honest view: it is the right end state (one rule for everything, a module change never needs a WebUI rebuild),
but it is the most expensive part of this SPEC and gives no new function by itself, so it goes **after** the inside
views and the MCP work, one page at a time, Sviluppo first.

### A5. Sidebar: one scroll area, arranged by you (v2.0)

Bug today: only the *Moduli* list scrolls (`.mods`); the top block is not shrink-proof, so on a short window the
items slide under the fixed top part. New layout:
- fixed **top**: logo, *Crea con Hestia*; fixed **bottom**: Impostazioni, Esci, assistant state;
- **one scroll area** in between with every entry.

Arrangement like VS Code: entries come from the catalog (built-in shell pages + plugin pages + dashboards), grouped in
**sections** (*Fissati*, *Dashboard*, *Moduli*, *Sistema*). Each section collapses; any entry can be **fissato** (pin)
from its ⋯ menu or by drag: it moves into *Fissati* (in your order) and **disappears from its own section** — the list
is computed, never stored twice, so duplicates are impossible. Hidden entries stay in Impostazioni → Moduli e Home.
Storage: WebUI client settings (Themis, `scope=user`): `webui.sidebar.pinned` (list, ordered),
`webui.sidebar.collapsed` (list of sections); the existing `webui.plugins.order` keeps the order inside a section and
`webui.plugins.hidden` the hidden ones. Collapsed sidebar (icons only) shows *Fissati* first. Phone: same list in the
drawer.

### A6. Core modules: pages **and** widgets (v2.0, honest view)

Yes, pages: they are where you understand a module (history, reasons, logs). Widgets alone would only say "ok / not
ok". Each core module ships **both**: one or more pages (A2) and 1–2 small widgets for a *Sistema* dashboard, plus quick
actions where there is an obvious one-tap action (*Pensa ora*, *Ricontrolla*, *Riprova job*). A ready-made dashboard
**Sistema** is built from the core `auto` widgets (like Home is built from the domain ones).

## Part B — External AIs on Hestia: MCP (recommended) vs an exported list

### B1. Options

| | **Export** (file / "Copia per AI") | **MCP server for external clients** |
|---|---|---|
| Effort | very small (one button on Sviluppo, markdown/JSON) | medium (endpoint, auth, tunnel, audit) |
| Freshness | snapshot, stale at once | live |
| Direction | one-way: AI reads, you copy back by hand | two-way: AI reads tasks, logs, dossiers, and **submits** work |
| Works with | any AI, even without connectors | every MCP client (B3) |
| Safety | nothing exposed | must be guarded: token/OAuth, read-mostly, writes go through Forge + Marko's approval |

**Decision (v2.0): both** — MCP as the real path, the export as a small extra. MCP because most of it already exists (Hephaestus already declares `forge_*` tools, Hestia-MCP
already aggregates every module's tools and proxies calls through Hub) and only MCP lets an external AI actually fix
items. The export is kept as a tiny extra (B5) because it costs almost nothing and works with any chat.

### B2. Design — one MCP for everyone (v2.0)

Today there are **three ways** to get tools: Oracle reads Hub `/discovery/module-tools` and calls services itself,
Telegram reads Hestia-MCP `/tools/all`, Hestia-MCP proxies `/tools/call` with its own REST shape. v2.0 makes **one**:

- **Hestia-MCP is the only MCP server of Hestia**: standard **MCP Streamable HTTP** `POST /mcp` (JSON-RPC
  `initialize`, `tools/list`, `tools/call`, `ping`; later `resources/*` for dossiers). It still aggregates every
  module's own `/mcp` (they stay as they are) and proxies calls through Hub.
- **Every client uses it the same way**: Oracle (agent loop, and the `claude -p` provider via `--mcp-config` pointing to
  the same endpoint), Telegram (command menu), WebUI (Comandi page, assistant tools), external AIs. Oracle's domain
  filter becomes a standard-compatible extra on `tools/list` (`params._meta.domains`), so Oracle stays an ordinary MCP
  client. The old `/tools`, `/tools/all`, `/tools/call` and Hub `/discovery/module-tools` stay only until every caller
  moved, then are removed (one change per caller).
- **Who sees what = the client's access** (B6): internal clients (Oracle, Telegram, WebUI) see every tool as today;
  an external client sees only the tools its access allows, and only among the tools a module marked `"external"` in
  `MCPTool.clients` (the module decides what may leave the house; nothing is exposed by default).
- **Public door = WebUI** (the only service behind the Cloudflare tunnel): WebUI `/mcp` forwards to Hestia-MCP through
  Hub (`/route/mcp/mcp`). No new port is published. Internal clients call Hestia-MCP through Hub as today.
- **Audit**: every external call logged `event=mcp_external_call access=<name> tool=<tool> ok=<bool>`; every write tool
  also leaves a silent Hermes inbox entry ("Claude esterno ha creato il task …"), no push.
- **Settings (Themis)**: `mcp.external.max_calls_per_min` (int, default 60). No on/off switch: no access = no door.
- **Stable URL**: `cloudflare-tunnel.bat` today opens a *quick* tunnel (random `trycloudflare.com` URL each start). A
  connector needs a fixed URL → named tunnel with a hostname (Marko's Cloudflare account; hostname in `.env`, not in
  the repo). Clients on the same PC can use `http://localhost:19015/mcp` without the tunnel.

### B3. Can it be connected to Claude and other AI tools? Yes — MCP is an open standard

| Client | How | Needs |
|---|---|---|
| Claude Code (CLI/IDE/desktop) | `claude mcp add --transport http hestia <url>/mcp --header "Authorization: Bearer …"` | token |
| Claude Desktop | `claude_desktop_config.json` entry (or Connectors) | token / OAuth |
| claude.ai web + mobile, Claude projects (like this thread) | Settings → Connectors → custom connector URL | public HTTPS + OAuth (B6) |
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

### B6. Managing access (who may use Hestia's MCP) — v2.0

Owner: **Hestia-MCP** (it is the door for tools). Page **Accessi** in its plugin (sub-page of Comandi & MCP):

- **Accesso** = `{name ("Claude Code PC", "claude.ai"), kind: token | oauth, scope: read | read+write, tools: all
  external | chosen list, expires, created, last used, calls today}`. Stored in Archive (`mcp-access` store); tokens
  only as a hash, shown once at creation (copy button + the ready `claude mcp add …` line).
- **Nuovo token** → for Claude Code, Claude Desktop, Cursor, VS Code, Gemini/Codex CLI (header `Authorization:
  Bearer`). **Revoca** / **Rinnova** in one tap; expired or revoked → 401 at once.
- **OAuth** for claude.ai web/mobile and ChatGPT (they only speak OAuth): Hestia-MCP is the OAuth 2.1 authorization
  server (metadata, dynamic client registration, PKCE); the authorize step opens a WebUI consent page behind the
  normal WebUI login, where Marko picks scope and tools → an access of kind `oauth` appears in the list. Nothing is
  granted without that page.
- **Outbound** (third-party MCP servers Hestia itself uses, already supported by Hestia-MCP registration): their
  credentials are Hecate's job (it owns external providers and OAuth): API keys stay secrets in `.env` referenced by
  name, OAuth ones go through Hecate's existing OAuth flow. Same Accessi page shows them in a second list
  (connected / to re-authorize). No credential in the repo or in Themis.
- No env token (`HESTIA_MCP_EXTERNAL_TOKEN` of v1.0 dropped): accesses are data, managed from the page.

## 3. Who does what

| Module | Job |
|---|---|
| Each core module | its plugin bundle (pages, widgets, quick actions), its read endpoints, `"external"` on the tools it lets out; the modules that own today's built-in pages take them over (A4) |
| Hub | catalog carries `kind` and `badge`; `/discovery/module-tools` retired once Oracle uses MCP |
| WebUI | shell only (Home, Chat, Impostazioni); sidebar sections + pins (A5); public `/mcp` door; OAuth consent page |
| Hestia-MCP | the one MCP server for every client; accesses (tokens, OAuth server), rate limit, audit; Comandi & Accessi pages |
| Hephaestus (Forge) | Sviluppo page as its plugin (+ *Copia per AI*), `forge_task_note`, `forge_submit_branch`, external tools flagged |
| Hermes | Notifiche page as its plugin; silent inbox entries for external writes; approvals as today |
| Chronos | Agenda page as its plugin |
| Oracle | MCP client of Hestia-MCP like everyone (agent loop + `claude -p`) |
| Hecate | credentials of third-party MCP servers Hestia uses |
| Themis | `mcp.external.max_calls_per_min` |

## 4. Acceptance criteria

1. With the core images rebuilt, the WebUI sidebar shows **Sistema** with Hub, Argus, Oracle, Athena, Hermes, Chronos,
   Themis, Hephaestus, Metis pages; their widgets can be put on a dashboard; a stopped module shows "non raggiungibile".
2. Athena *Pensieri* shows the last cycles with gate scores; *Pensa ora* runs a cycle and the list refreshes.
3. Argus *Salute* shows a stopped service as down within one poll; *Ricontrolla* works.
4. Accessi → Nuovo token → the shown `claude mcp add … /mcp` line works → Claude Code lists only `external` tools; `forge_tasks` returns the list.
5. Wrong, revoked or expired token → 401; over the limit → 429; a read-only access calling a write tool → 403.
6. `forge_submit_branch` on a test task → Forge tests it, Marko gets the usual approval, merge + health check.
7. *Copia per AI* produces a readable markdown of the chosen tasks.
8. claude.ai custom connector: OAuth → consent page → connected, lists the tools allowed on that page.
9. Oracle, Telegram and the WebUI get their tools only from Hestia-MCP `/mcp`; chat and Telegram commands work as before.
10. Short window (e.g. 500 px high): the whole sidebar list scrolls, top/bottom stay; pin an entry → it moves to *Fissati*, not shown twice; reload keeps it.
11. Each ported page (Sviluppo, Notifiche, Agenda, Comandi, Documenti) works as before from `/p/…`; old links redirect.
12. Phone 360 px and both themes for every core page.

## 5. Phases

- **P1 Sidebar + contract**: one scroll area, sections, pins (A5); `kind`, `badge`, order decades in plugin_client /
  manifest / catalog; docs (client-plugins SPEC §4 note, DESIGN-SYSTEM, ARCHITECTURE).
- **P2 One MCP**: Hestia-MCP Streamable HTTP `/mcp` (+ `_meta.domains`); Oracle agent loop and `claude -p`, Telegram,
  WebUI move to it; old endpoints removed after the last caller; docs.
- **P3 Accesses + external door**: Archive `mcp-access`, tokens, scopes, rate limit, audit, WebUI `/mcp` door, Forge
  `forge_task_note` / `forge_submit_branch`, tools flagged `external`; README "Collegare un'AI esterna".
- **P4 Inside views**: plugins for Hub, Argus, Oracle, Athena, then Hermes, Chronos, Themis, Hephaestus, Metis (+ the
  *new* reads found missing), dashboard *Sistema*.
- **P5 OAuth + Accessi page**: OAuth 2.1 server in Hestia-MCP, WebUI consent page, Accessi page (in/out), Hecate for
  outbound credentials, named tunnel guide.
- **P6 Built-in pages → plugins**: Sviluppo (+ *Copia per AI*), Notifiche, Agenda, Comandi & MCP, Documenti — one per
  change, old routes redirect.

Each phase updates the module `.md`, swagger, README/ARCHITECTURE where touched, this dossier and the root CHANGELOG.
Tests written per phase, not run here (user rule).

## 6. Decisions

v1.0 defaults, revised by Marko (2026-10-18):
1. Built-in pages → **plugins too** (A4), after the inside views and MCP, Sviluppo first.
2. MCP **and** export (B1).
3. **One MCP for everyone**, Oracle included (B2).
4. Access management with tokens + OAuth from a page (B6).
5. Core modules: pages + widgets + quick actions (A6).

Confirmed 2026-10-18: external write tools limited to create task, note, submit branch, propose setting (B4); phase order §5.
