# Hestia Architecture and Flow Map

A quick, single-page reference for service roles, dependencies, and runtime data flow.

## Role Matrix

| Service | Role Type | Owns Business Logic | Owns Provider Runtime/Auth | Main Dependency Pattern |
|---|---|---|---|---|
| Hub | Core | No | No | Registry + routing for all services |
| Archive | Core | No | No | Persistent storage gateway |
| Oracle | Core | No | No | Uses Hub discovery and routes commands |
| Hermes | Core | No | No | Dispatches events/notifications (audio from Echo when the module wants voice) |
| Echo | Core | No | Speech engines only (keys `ECHO_KEY_<NAME>`) | The only caller of speech-to-text/text-to-speech; providers → chains → uses like Oracle; audio kept in Archive |
| Telegram | Interface | No | No | User-facing chat/file relay to Oracle |
| WebUI | Interface | No | No | Web-based chat/file relay to Oracle, SignalR streaming |
| Hecate | Core Gateway | No domain logic | Yes (Google/Outlook provider runtime) | Provider-facing gateway; the one Gmail watcher (pushes new mails to Iris) |
| Chronos | Domain (Calendar) | Yes (calendar workflows + assistant agenda) | No | Routes provider calendar calls to Hecate; owns the assistant agenda |
| Iris | Domain (Email) | Yes (email workflows) | No (gateway-mediated when needed) | Email-domain APIs and commands; dispatches incoming mail to module subscriptions |
| Scout | Domain (Real Estate) | Yes (listing extraction/ranking) | No | Gets listing mails by push (Iris subscription) |
| Hercules | Domain (Fitness) | Yes (gym coach) | No | Archive store, agenda job + Hermes for reminders, WebUI plugin |
| Hygieia | Domain (Self care) | Yes (products, routines) | No | Archive store, agenda job + Hermes for reminders, WebUI plugin |
| Wardrobe | Domain (Wardrobe) | Yes (pieces, outfits, suggestions) | No | Archive store + blobs, agenda + Hermes, WebUI plugin |
| Plutus | Domain (Finance) | Yes (expenses, budgets, statements) | No | PayPal mails by push (Iris), statement PDF via plugin or chat (Oracle hand-off), Archive `finance-store`, agenda + Hermes, WebUI plugin «Spese» |
| Themis | Core | No | No | Settings registry; pushes values (and followed personal values) to modules |
| Argus | Core Organ | Yes (monitoring/remediation intent policy) | No | Reads health/logs and emits remediation intents |
| Hephaestus | Core Organ | Yes (remediation + Forge self-development) | No | Policy-gated remediation; Forge codes/tests/merges Hestia itself |
| Athena | Core Organ | Yes (proactive advisory cognition, idle retrospective) | No | Advisory hints for Oracle; improvement hand-off to Forge |
| Atlas | Shared Integration | No domain logic | No | Host-side fetch helper routed via Hub |
| Metis | Core Organ | Yes (dataset curation, benchmark, training orchestration) | No | Builds datasets from feedback, runs benchmarks, orchestrates LoRA training |
| Dummy | Test Module | Generic integration testing behavior | No | Deterministic target for routing/policy/execution tests |
| MCP | Core Gateway | No tool-ownership (aggregates) | No | Hestia's one MCP server: every client (Oracle, Telegram, WebUI, external AIs with an access) lists and runs tools here; owns external accesses |
| Swagger | Documentation Aggregator | No | No | Canonical API contract surface (`swagger.yml`) |
| Shared | Shared Library | No | No | Common runtime/logging/startup helpers for services |

## Single Entry Point Rule (Provider Access)

1. Google and Outlook provider runtime/auth lifecycle are centralized in Hecate.
2. Domain services do not own direct provider SDK/OAuth runtime in their service boundary.
3. Domain APIs remain domain-owned:
   - Chronos owns calendar business operations.
   - Iris owns email business operations.
4. Modules get mail only by push: they subscribe at Iris (`hestia_common.mail_client`); nobody polls Gmail or logs in by IMAP.

## High-Level Dependency Graph

```mermaid
flowchart LR
    TG[Telegram UI] --> OR[Oracle]
    WU[WebUI] --> OR[Oracle]
    WU --> HUB[Hub]
    OR --> HUB[Hub]

    HUB --> HE[Hecate Gateway]
    HUB --> CH[Chronos Calendar Domain]
    HUB --> IR[Iris Email Domain]
    HUB --> SC[Scout Real Estate Domain]
    HUB --> PL[Plutus Expenses Domain]
    HUB --> EC[Echo Voice]
    HUB --> AT[Athena Advisory Engine]
    HUB --> AG[Argus Monitoring]
    HUB --> HP[Hephaestus Remediation]
    HUB --> MT[Metis Improvement]
    HUB --> MCP[MCP Tool Gateway]
    HUB --> DU[Dummy Test Module]
    HUB --> AL[Atlas Fetch Gateway]
    HUB --> AR[Archive]
    HUB --> HM[Hermes]

    CH -->|provider calendar ops via Hub route| HE
    IR -->|provider mediation when needed| HE
    HE -->|new mails push| IR
    IR -->|doorbell for subscribed mail| SC
    IR -->|doorbell for subscribed mail| PL
    OR -->|chat attachment hand-off| PL

    HE --> GP[Google Provider Runtime]
    HE --> OP[Outlook Provider Runtime]

    OR -->|advisory context| AT
    AT -->|bounded hints| OR

    AG -->|remediation intent| HP
    HP -->|maintenance execution policy gated| DU

    SC -->|optional page retrieval| AL

    CH --> AR
    IR --> AR
    SC --> AR
    PL --> AR
    OR --> AR

    MT[Metis Improvement] --> AR
    MT --> OR
    AT -->|improvement hand-off| HP
    AG -->|recurring error fix| HP
    HP -->|LLM turns /api/llm/chat| OR
    AT -->|weak spots| MT

    SC --> HM
    PL --> HM
    CH --> HM
    OR --> HM
    AG --> HM
    MT --> HM
```

## Runtime Placement

| Node | Services |
|---|---|
| Raspberry Pi (always-on) | Hub, Archive, Oracle, Telegram, WebUI, Hecate, Hermes, Chronos, Iris, MCP |
| Main PC (best-effort) | Scout and other domain modules, Echo (voice engines), Metis, local LLM/runtime helpers |
| Host utility (outside Docker) | Atlas |

## Coverage Checklist

- Core: Hub, Archive, Oracle, Echo, Hermes, Telegram, WebUI, Hecate
- Domain: Chronos, Iris, Scout, Hercules, Hygieia, Wardrobe, Plutus
- Organ services: Argus, Hephaestus, Athena, Metis
- Utility/support: Atlas, Dummy, Swagger, Shared, MCP

## Practical Flows

### Calendar flow
1. Oracle/Telegram triggers calendar action.
2. Chronos handles calendar domain logic.
3. Chronos routes provider-facing calls to Hecate.
4. Hecate executes against Google/Outlook runtime.
5. Chronos persists normalized state in Archive and emits via Hermes when applicable.

### Email flow (search/send)
1. Oracle/Telegram triggers email-domain action.
2. Iris handles email domain API semantics.
3. If provider mediation/runtime is needed, flow is routed through Hecate.

### Incoming mail flow (push, no module polls)
1. Hecate watches Gmail: Chronos job `hecate.mail_watch` (default 15 min, history API) or, when configured, Gmail
   Pub/Sub streaming pull (`HECATE_GMAIL_PUBSUB_*`; the job then stays as a safety net, `hecate.mail_watch_renew` daily).
2. Hecate → Iris `POST /api/email/incoming` with the new mails' headers.
3. Iris matches them against module subscriptions (`hestia_common.mail_client`, `/api/email/subscriptions`).
4. For each match Iris stores the full mail in Archive as a raw record under the subscriber's domain (deduped), then
   rings the module `POST route/<module>/<path> {owner, key, domain, count, reference_ids}`.
5. The module processes its unevaluated records (also once at startup, so nothing is lost while it was down).
   Subscribers: Scout (listings), Plutus (PayPal receipts).

### Chat attachment hand-off
1. A file sent in chat (Telegram/WebUI) → Oracle `/api/chat/document`.
2. Oracle checks modules' `attachment_handlers` (Hub capabilities: mime + words). Match → file stored as Archive blob
   (`owner_module=chat`) → `POST route/<module>/<path>` with the blob id → the module's `{handled, text}` is the reply.
3. No match or failure → normal document analysis. Example: Hype statement PDF → Plutus preview → user confirms.

### Self-development flow (Forge)
1. User on Telegram: "aggiungi X" → Oracle (classifier: domain `system`) → tool `forge_develop` → Hub → Hephaestus.
2. Athena (idle retrospective) and Argus (recurring errors) also submit via Hub; the permission mode
   (`ask | auto | full_auto`, per group local/cloud) decides if coding starts alone.
3. Forge creates a git worktree + branch, runs the engine:
   - `local` / `cloud` → LLM turns through **Oracle `/api/llm/chat`** (Oracle owns providers and keys);
   - `claude` → Claude Code CLI inside Hephaestus.
4. Forge commits, runs the touched services' tests, notifies the user via Hub → Hermes → Telegram.
5. "approva sviluppo <id>" → merge (+ optional deploy, health check via Hub, auto rollback).

### Tool flow (one MCP for every client)
1. Each module declares its tools (`/mcp` or inline commands); Hub's discovery is read only by Hestia-MCP.
2. Oracle, Telegram and the WebUI call Hestia-MCP `/mcp` through Hub (`tools/list`, `tools/call`); Hestia-MCP builds
   the request with `hestia_common.tool_call` and routes it through Hub to the module.
3. External AI (Claude Code, Cursor…): WebUI `POST /mcp` with `Authorization: Bearer <token>` → Hub → Hestia-MCP
   `/mcp/external` → access check (Archive `mcp-access-store`, hashed token), scope, rate limit → only tools marked
   `"external"` → module with `X-Hestia-Access`; writes leave a silent Hermes inbox entry.
4. A fix made by an external AI: `forge_submit_branch` → Forge fetches the branch, tests it, asks the owner; merge
   and deploy only after the owner's approval.
5. OAuth AI (claude.ai, ChatGPT): `/mcp` 401 with `resource_metadata` → WebUI `/.well-known/oauth-*` →
   `/oauth/register` → `/oauth/authorize` (WebUI → Hub → Hestia-MCP parks the request) → browser to
   `/p/mcp/accessi?oauth=<id>` (WebUI login) → **Consenti** → code to the AI's redirect → `/oauth/token` (PKCE) →
   `hso_…` bearer on `/mcp` exactly like a token access; `refresh_token` rotates, a replay revokes the access.

### Plugin flow (module pages and widgets)
1. A module with a UI declares its pages, widgets and quick actions (`hestia_common.plugin_client`) in its Hub
   registration capabilities; Hub merges them into `/api/discovery/catalog` (core modules `kind=core`).
2. Hub never registers with itself: it folds its own manifest into the catalog and answers
   `/api/route/hub/{api/ui/*, ui/*}` locally.
3. The WebUI loads each bundle through Hub and proxies the plugin's calls only under its `api_prefix`; core modules
   go under *Sistema* and their `auto` widgets build the *Sistema* dashboard.

### Assistant agenda flow (rules as data)
1. Modules register default rules in Chronos (`POST /api/agenda/register`, idempotent by key) at startup.
2. Windows: modules ask Chronos `GET /api/agenda/windows/{key}` before doing scheduled work (fallback if down).
3. Jobs/tasks: the Chronos agenda worker fires their action via Hub at the due time.
4. The user reads and edits the agenda from Telegram (move, pause, skip, cancel, run now); edits win over defaults.
5. The agenda (`source=hestia`) is separate from the user's calendars and never sent as user reminders.
6. Registered today: `hecate.mail_watch`, `hecate.mail_watch_renew`, `chronos.calendar_sync` (jobs); `athena.consolidation`,
   `athena.skill_curation`, `athena.thinking`, `metis.training`, `forge.claude_nights`, `forge.claude_final`
   (windows); `metis.train.<job>`, `hephaestus.repair.<id>`, `argus.repair.<service>` (tasks); `forge.task.<id>`
   (events). Jobs keep a module-side fallback (Chronos down / job missing / stale) that never overrides a pause.
7. A rule a module no longer declares is retired by the module itself: `POST /api/agenda/retire {owner, keys}`
   (only rules it created; user items stay). Example: Scout retired `scout.email_cycle`.

### LLM access rule
Only Oracle talks to LLM providers. Athena/Scout/Argus/Chronos use `/api/llm/generate`, Forge and Wardrobe use
`/api/llm/chat` — always via Hub. Callers name a `use_case` `<module>.<task>` (e.g. `scout.annunci`, `athena.strategia`,
`forge.codice`) and declare it in their Hub registration (`capabilities.llm_usecases`, `hestia_common.oracle_usecases`);
Oracle maps each use case to a named chain of provider/model steps (quota skip) and a brain mode (interna / esterna =
Claude Code or Codex with Hestia's tools over MCP), all chosen in Oracle → Cervello → Modelli, never env in the caller.
Every call becomes a usage row in Archive (`llm-usage`, panel Cervello → Uso).

### Module reminder flow
1. Agenda job (Chronos) calls the module's reminder check; the module decides (enabled, goal behind, once a day,
   weekly cap).
2. Module → Hermes `api/events/ingest` with `hestia_common.reminders.reminder_event` (domain `system`, `replaces`,
   `_link`); Hermes delivers to every client of the owner; an answer is routed back to the module.

### Oracle offline flow (Oracle down)
1. Argus' monitor cycle sees Oracle down past `argus.oracle.grace` (60 s) → presence signal `oracle.offline` (Chronos
   overlay «⏳ Non disponibile», effect `chat.reply = queued`) + one Hermes notice to every client.
2. Telegram/WebUI: a chat message Oracle does not accept → Archive `/api/chat-queue` + fixed «in coda» reply.
3. Oracle healthy → Argus clears the signal and closes the notice; Chronos sees `chat.reply` back to `live` and calls each
   client's `capabilities.chat_queue_drain` via Hub; each client replays its queue to Oracle, oldest first.
SPEC `docs/work/2026-10-19-oracle-offline`.

### Google OAuth flow
1. "collega Google Calendar" → Oracle → Hecate `POST /api/gateway/auth/initiate/google` → link (loopback + PKCE).
2. Phone: the final `localhost` page fails (expected); user pastes the URL in Telegram → Telegram forwards it
   to Hecate `complete/google` via Hub (no LLM). Host browser: Hecate's callback completes it directly.
3. Token saved to `Hestia-Hecate/data/google_token.json`, provider registry reloaded.

### Voice flows (Echo)
1. Voice note (Telegram) or voice message (WebUI) → client → Echo `/api/voice/transcribe` (use `telegram.vocale` /
   `webui.vocale`, recording kept in Archive with the message) → the text goes to Oracle like a typed message.
2. «Ascolta» under a reply → Echo `/api/voice/speak` (kept with the reply; asked again → the kept audio).
3. Live («Parla», Telegram `/live`): mic chunks → Echo `listen` stream (partial text, silence ends the turn) → Oracle
   chat as usual → answer text → Echo `say` stream → sentences played in order. No external live service.
4. Notification in voice: module setting `<module>.notifiche.voce` → event `_voice` → Hermes publishes the text, then
   Echo `speak` (use `hermes.notifica`, kept with the notification) → `update` with `voice` to the clients.
5. Audio inside a document → Oracle → Echo (use `oracle.documenti`); Oracle has no speech engine.

### Real-estate extraction flow
1. Iris rings Scout (`/api/scout/mail`) for listing mails already stored in Archive (`real_estate`).
2. Scout runs pre-parse, dedupe, extraction, enrichment.
3. Scout writes entities to Archive and emits events to Hermes.

## Notes

- This file is a quick architecture map. Detailed endpoint contracts remain in each service `hestia-*.md` and in `Hestia-Swagger/swagger.yml`.
