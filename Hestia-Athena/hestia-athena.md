# Hestia-Athena

Role: Proactive cognition and advisory strategy engine.

Athena is the "thinking brain" of Hestia. It runs a periodic observation-and-reasoning
loop: gathers system state, generates action candidates via Oracle LLM, scores them
through a relevance gate, and emits accepted actions to Hermes. Every thinking cycle
is archived for audit and client display.

## Two tracks (docs/work/2026-10-20-riflessione-a-livelli)

| Track | Reads | Produces | When |
|---|---|---|---|
| **Sistema** | Hub, Argus health/errors, Metis weak spots, settings, presence (no life data) | Hermes briefs, Forge hand-offs, setting proposals | idle cycles in window `athena.thinking` |
| **Vita** | only module **signals** + weekly metrics (Archive `signals-store`), details via `/api/module/context?topic=` | **observations** stored for the evening recap (never sent to Hermes), at most one setting proposal via Themis | once a day in window `athena.reflection` (default 18–20, before the recap) |

### Life reflection («Vita», `app/core/reflection.py`)
1. Read active signals (`hestia_common.signals_client.SignalReader`) and weekly series (26 weeks).
2. **Link** series of different areas: Pearson at lag 0 (same week) and lag 1 (the week after), closed weeks only,
   ≥ `athena.reflection.min_weeks` paired weeks and |r| ≥ `athena.reflection.min_correlation`. Numbers, not the model.
3. **Topics**: `alta` signals, then links (strongest), then `attenzione` signals; at most `max_topics`; anything told
   within `repeat_days` is skipped (dedup on `topic_key`).
4. **Details**: `GET route/<module>/api/module/context?topic=<key>&budget=<detail_budget>` per signal topic; the
   normal context line of both modules for a link.
5. **Think**: one Oracle call, use case `athena.riflessione` (chain `potente`), caveman prompt, same `AZIONE/TIPO/…`
   format plus `TEMA: T<n>`; kinds `observation` | `setting`.
6. **Gate** (same score and threshold). Accepted observations → Archive `signals-store` (`kind=observation`,
   `ref_id=athena`, `day`, `title`, `text`, `domains`, `topic_key`, `link`, `page`, `score`), outcome `observed`,
   at most `max_per_day` per day. Settings → Themis proposal (`setting_proposed`).
7. **Record**: thinking record with `track: "vita"` and `life{signals, links, topics, details, series}`.
Oracle down → record with `error`, nothing stored, no static fallback.

### Recap piece
Athena advertises `recap_endpoint` like any module: `GET /api/module/recap?day=` → `{module: athena, title: «Da tenere
d'occhio», icon: eye, order: 900, done: [{text, tone}]}` with that day's observations, or `{empty: true}`. The daily
recap (`app/core/recap.py`, dossier `2026-10-20-recap-giornaliero`) collects it like the other pieces.

## Event contract
- Event type: `athena.focus_brief`
- Destination: Hermes `/api/events/ingest`
- Domain: cognition (or candidate-specific domain)
- Payload: brief + gate decision and component signals

## Gate factors
- urgency
- usefulness
- novelty
- interruption_cost
- confidence

Weighted score:
- 0.30 × urgency
- 0.25 × usefulness
- 0.20 × novelty
- 0.15 × confidence
- 0.10 × (1 − interruption_cost)

## Architecture (Phase 3)

```
┌─────────────────────────────────────────────────────┐
│                  Athena Runtime Loop                  │
│                                                       │
│  1. OBSERVE ──► Observer queries Hub, Archive, Argus │
│  2. THINK   ──► Strategist calls Oracle LLM          │
│  3. SCORE   ──► Relevance gate with retrospective    │
│  4. ACT     ──► Emit to Hermes, hint to Oracle       │
│  5. ARCHIVE ──► Store thinking record                 │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### Modules

| Module | File | Responsibility |
|--------|------|---------------|
| Observer | `app/core/observer.py` | Gather system state via Hub-routed calls to Archive, Argus, and self |
| Strategist | `app/core/strategist.py` | Call Oracle LLM for reasoning, parse structured action candidates |
| Runtime | `app/core/runtime.py` | Main loop: observe → think → score → act → archive |
| Schemas | `app/core/schemas.py` | Data models: RelevanceSignals, ObservationSnapshot, ActionCandidate, ThinkingRecord |

### Observation sources
- **Hub registry**: registered services, base URLs, types, tags, topology tags
- **Argus health**: per-service health status (up/down/degraded)
- **Archive entities**: domain summaries (counts, recent activity, pending steps)
  - Domains are **discovered dynamically** from Hub: services with `layer:domain` tag
    (e.g. Scout with `domain:real_estate`) map to Archive domains
  - No hardcoded domain list — if Hub is unreachable, domains are simply empty (logged)
- **Self-state**: active commitments, unresolved commitments, failure streaks
- **Settings (Themis)**: up to 12 proposable system settings as `key=value [scelte]` (not advanced, not personal)

### Strategist (LLM reasoning)
- Single Oracle round-trip per cycle via Hub routing (`POST /route/oracle/api/llm/generate`)
- Compact prompt format optimized for local models
- Structured `AZIONE:/TIPO:/PRIORITA:/DOMINIO:/MOTIVO:/RIASSUNTO:` output format
- Graceful responses: `NESSUNA_AZIONE` when nothing actionable, empty list on Oracle failure
- Oracle is a **core dependency** — if it is unreachable, Athena returns no candidates
  (the observation cycle still runs and is archived, but no static rules are substituted)

### Idle retrospective (autonomous mode)
- Cycles run **only when the user is idle**: Athena reads Oracle `GET /api/activity` and defers the cycle while the
  last real chat is younger than `athena.loop.idle_seconds` (default 300; `0` = always run). The local model is never
  contended with the user.
- Retrospective inputs on top of health/domains: **Argus errors of the last hour** (`/api/argus/logs?level=ERROR&since=1h`)
  and **Metis weak spots** (`/api/metis/insights`).
- Candidate kind `improvement` (code/prompt change) is handed to **Hephaestus Forge** via Hub. Forge's permission
  mode decides (`ask` waits for you, `auto` codes on a branch, `full_auto` may also merge). Defaults: local=auto, cloud=ask.
  Max `athena.forge.max_per_day` (2) hand-offs/day, deduplicated by title. Disable: `athena.forge.enabled`.
- Strategist prompt is caveman-style (short lines, exact output format) to save context on local models.

### Action candidate kinds
- `advisory` — suggestion for user consideration
- `remediation` — fix action for Hephaestus
- `notification` — user-facing alert
- `maintenance` — routine housekeeping
- `improvement` — change to Hestia code/prompts → Hephaestus Forge
- `setting` — change one listed setting (`CHIAVE:` + `VALORE:` lines) → `POST /route/themis/api/settings/proposals`
  with `proposer: athena`. Themis validates and dedupes, Hermes asks you on every client, nothing changes until you
  approve. Max `athena.settings.proposals_per_day` (setting, default 2; 0 = off) per day, one per key.

### Central settings
All tunables live in Themis, declared in `app/core/athena_settings.py` (`SettingsClient("athena")`), editable
from every client. All `live` (read at use time) except `athena.tasks.store_max` (`restart`).

| Key | Type | Default | Notes |
|---|---|---|---|
| `athena.settings.proposals_per_day` | int | 2 | setting proposals/day (0 = off) |
| `athena.loop.enabled` | bool | true | thinking loop on/off (thread always runs, checks every cycle) |
| `athena.loop.interval` | int s | 300 | seconds between cycles |
| `athena.loop.idle_seconds` | int s | 300 | idle gate (0 = always) |
| `athena.gate.threshold` | float | 0.55 | minimum relevance score to emit |
| `athena.retro.window` | int | 24 | outcome history for boosts (advanced) |
| `athena.retro.failure_urgency_boost` | float | 0.07 | per consecutive failure (advanced) |
| `athena.retro.unresolved_urgency_boost` | float | 0.04 | per unresolved commitment (advanced) |
| `athena.retro.unresolved_usefulness_boost` | float | 0.03 | per unresolved commitment (advanced) |
| `athena.commitments.ttl` | int s | 86400 | commitment / hint expiry (advanced) |
| `athena.hints.enabled` | bool | true | publish hints to Oracle (also skill-curator hints) |
| `athena.hints.timeout` | int s | 8 | Oracle hint call timeout (advanced) |
| `athena.thinking.archive_enabled` | bool | true | push thinking records to Archive |
| `athena.thinking.store_max` | int | 100 | in-memory thinking records (advanced) |
| `athena.tasks.store_max` | int | 500 | task lifecycle records, `restart` (advanced) |
| `athena.observe.timeout` | float s | 8 | observation call timeout (advanced) |
| `athena.observe.entity_window_hours` | int h | 24 | "recent" entity window |
| `athena.strategist.enabled` | bool | true | LLM reasoning via Oracle |
| `athena.strategist.timeout` | float s | 20 | strategist Oracle timeout (advanced) |
| `athena.strategist.max_candidates` | int | 3 | candidates per cycle |
| `athena.forge.enabled` | bool | true | hand-off to Forge (`oracle=read`) |
| `athena.forge.max_per_day` | int | 2 | Forge hand-offs/day (`oracle=read`) |
| `athena.memory.active_days` | int giorni | 7 | sessions active in last N days are consolidated |
| `athena.memory.lookback_hours` | int h | 24 | min time between consolidations of one session |
| `athena.memory.oracle_timeout` | int s | 30 | consolidation LLM timeout |
| `athena.memory.preference_decay_days` | int giorni | 90 | preference decay |
| `athena.memory.reinforce_threshold` | int | 3 | occurrences to reinforce a pattern |
| `athena.skills.min_sessions` | int | 3 | sessions per cluster to create a skill |
| `athena.skills.sim_threshold` | float | 0.90 | clustering similarity |
| `athena.skills.dedup_threshold` | float | 0.95 | duplicate-skill merge similarity |
| `athena.skills.stale_days` | int giorni | 30 | deprecate unused skills |
| `athena.skills.hard_delete_days` | int giorni | 90 | hard-delete dead skills (<3 uses) |
| `athena.skills.core_use_count` | int | 50 | uses to promote to core |
| `athena.audit.timeout` | float s | 40 | auditor LLM timeout |
| `athena.audit.max_turns` | int | 20 | default turns per audit |
| `athena.recap.style` | enum | amichevole | recap tone (amichevole / asciutto) |
| `athena.recap.max_chars` | int | 900 | recap length cap |
| `athena.recap.piece_timeout_seconds` | float s | 5 | wait for each area's piece |
| `athena.reflection.max_per_day` | int | 2 | life observations per day (all in the evening recap) |
| `athena.reflection.max_topics` | int | 4 | topics per life cycle |
| `athena.reflection.min_weeks` | int settimane | 6 | paired weeks before a link counts |
| `athena.reflection.min_correlation` | float | 0.6 | minimum |r| (advanced) |
| `athena.reflection.repeat_days` | int giorni | 14 | same topic not repeated before (advanced) |
| `athena.reflection.detail_budget` | int caratteri | 600 | detail asked to a module (advanced) |
| `athena.log.level` | enum | `LOG_LEVEL` env | log verbosity |

### Thinking archive
- Every cycle is stored in-memory (ring buffer, `athena.thinking.store_max`) and pushed to Archive
- Archive entity type: `athena_thinking` under domain `cognition`
- Clients can query `/api/athena/thinking` (full records) or `/api/athena/thinking/summary` (compact) to see
  "what Athena is thinking"
- A record keeps **every** candidate the strategist proposed, accepted or discarded: `score`, the 5 `signals` (after
  the retrospective boost), `accepted`, `gate_reason` (Italian: «punteggio 0.48 < soglia 0.55 (urgenza bassa, utilità
  bassa)» — the factors that cost the most points, or the strongest ones when accepted) and `outcome`
  (`emitted` · `forge` · `forge_skipped` · `setting_proposed` · `setting_skipped` · `failed` · `discarded`). The record
  also has `threshold` and `duration_ms`. Log: `event=thinking_cycle_done trigger= candidates= accepted= emitted= ms=`.

### «Pensa ora» (one cycle now)
`POST /api/athena/think` runs one full cycle (observe → think → gate → act → archive, `trigger=manual`) in the
background, past the idle gate and the `athena.thinking` agenda window (the user asked for it). One cycle at a time:
a lock is shared with the loop (`busy` if one is running; the periodic cycle skips with
`event=thinking_cycle_skipped reason=cycle_running`). `POST /api/athena/trigger` stays the "reflect on a theme" action
(agenda template `reflect`, custom title/summary/signals).

### WebUI plugin: Pensieri (core module, Sistema section)
Declared in `app/main.py` (`hestia_common.plugin_client`, `kind="core"`, `api_prefix=/api/athena/`; SPEC
`docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2). Bundle `ui/` (Lit, SDK kit) built in the Docker image (Node stage
→ `/ui/dist/webui/athena.js`, outside `/code/app` because of the dev mount; infra env `ATHENA_UI_DIST`).

| Kind | Id | What |
|---|---|---|
| page (order 130) | `pensieri` → `<athena-thoughts>` | status (loop on/off, strategist, threshold), open commitments (Fatto / Ignora → `/commitments/{id}/resolve`), each cycle: 1 Osserva (services, down, errors, domains, weak spots, presence) · 2 Pensa · 3 Filtra (threshold) · 4 Agisce, and every candidate with score vs threshold, the 5 factor bars, the gate reason and the outcome. *Pensa ora* → `POST /think`, then polls until the cycle ends and opens it. Athena down → «Athena non raggiungibile» |
| page (order 131) | `segnali` → `<athena-signals>` | active signals per area (severity icon + tone, «Apri» opens the module page), links between areas, recent observations, weekly series charts; area filter |
| widget (auto) | `ultimo` → `<athena-last-widget>` (m/l) | «Ultimo pensiero»: last cycle, best candidate, accepted/total |
| quick action | `pensa` «Fai pensare Athena» | `POST /api/athena/think` |

Pensieri has a **Vita / Sistema** switch (default Vita): a life cycle shows 1 Legge i segnali · 2 Collega · 3
Approfondisce · 4 Pensa e filtra · 5 Per il recap; «Pensa ora» runs the selected track.

### MCP tool `athena_signals(domain?, limit?)`
Read only (GET `/api/athena/signals`), clients `ui` + `external`, not in the Telegram menu.

### Daily recap (dossier `docs/work/2026-10-20-recap-giornaliero`)
One message a day, «com'è andata e cosa c'è domani». `app/core/recap.py` `RecapComposer`:
1. **Collect**: every module with capability `recap_endpoint` (Hub registry) is asked `GET /api/module/recap?day=&next=`
   in parallel (`athena.recap.piece_timeout_seconds`); a module down or slow is just left out. Athena's own piece
   «Da tenere d'occhio» (reflection thread) comes the same way.
2. **Write**: Oracle use case `athena.recap` (chain veloce, caveman prompt, `athena.recap.style`, `athena.recap.max_chars`);
   Oracle failing → deterministic list per area (`fallback: true`, `[🔄] event=recap_fallback`).
3. **Quiet day** (every piece empty) → nothing is sent (`event=recap_empty`); proposals belong to other moments.
4. **Deliver**: Hermes `service.action_required` (domain system, level info, `replaces: athena.recap`, target `owner`,
   `_link {module: athena, page: recap}`); stored in Archive entities, domain `recap`.

When: agenda job `athena.recap.evening`, daily 21:30, `flex 20:00–23:30` (Chronos moves it around the user's
events). Morning recap (previous day + today) = agenda template `recap` with `momento: mattina`, added by the user.
If the user deletes the evening job, «Attività standard» in the agenda puts it back in one click.
WebUI: page **Recap** (order 132, text + facts per area), quick action «Recap adesso». Chat: tool `recap_today`.

### MCP tool `athena_thinking(limit?)`
Read only (GET `/api/athena/thinking/summary`), clients `ui` + `external` (external AIs with an MCP access may read
it), not in the Telegram menu. Returns the compact cycles (default 10, max 50).

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/logs` | Service logs (filterable) |
| GET | `/api/athena/status` | Runtime status (ticks, emissions, strategist state) |
| POST | `/api/athena/trigger` | Manual trigger with custom signals |
| GET | `/api/athena/tasks` | Task lifecycle records |
| GET | `/api/athena/tasks/{task_id}` | Single task detail |
| GET | `/api/athena/commitments` | Active commitments (action items tracked) |
| POST | `/api/athena/commitments/{brief_id}/resolve` | Resolve a commitment |
| GET | `/api/athena/thinking` | Recent thinking records, full (observation payload included) |
| GET | `/api/athena/thinking/summary?limit=&track=` | Compact cycles + `running`, `threshold`, `weights`, `loop_enabled`, `strategist_enabled` (page Pensieri, MCP `athena_thinking`) |
| POST | `/api/athena/think?track=` | «Pensa ora»: one full cycle now in background (`sistema` default, or `vita`) → `{status: started, trace_id, track}` or `{status: busy}` |
| GET | `/api/athena/signals?domain=&limit=&weeks=` | signals, weekly series, links, recent observations (page Segnali, MCP `athena_signals`) |
| GET | `/api/module/recap?day=` | Athena's recap piece «Da tenere d'occhio» (capability `recap_endpoint`) |
| GET | `/api/ui/manifest` · `/ui/webui/athena.js` | WebUI plugin manifest and bundle |
| GET | `/api/athena/observation` | Most recent observation snapshot (new in Phase 3) |
| POST | `/api/athena/recap` | Compose the daily recap `{momento: sera\|mattina, day?, deliver?, trigger?}` (agenda job `athena.recap.evening`, template `recap`) |
| POST | `/api/athena/recap/now` | Quick action «Recap adesso» (evening, delivered) |
| GET | `/api/athena/recaps?limit=` | Recap history (page Recap) |
| POST | `/api/athena/recap/today` | MCP tool `recap_today` (chat: text only, not delivered nor stored) |

### When Athena works = assistant agenda windows

Registered at boot in Hestia's agenda (Chronos), editable by you (move, skip a day, pause). The default
hours are constants in code (`runtime.py`, `consolidator.py`), not env vars nor settings: the agenda already
makes them user-editable and Chronos keeps your edits over the registered defaults.

| Window | Default | Effect |
|---|---|---|
| `athena.consolidation` | daily 03–05 | memory consolidation, once per day inside the window |
| `athena.skill_curation` | daily 05–07 | skill curation, once per day inside the window |
| `athena.thinking` | all day | idle thinking cycles (observe → think → propose); skip/pause = Athena silent |
| `athena.reflection` | daily 18–20 | life reflection, once per day inside the window; skip/pause = no observations |

Missing window or Chronos down → default hours (consolidation 03–05) / always (skills, thinking). Skipped or paused
window = closed (your decision). Thinking still requires the idle gate (`athena.loop.idle_seconds`).

## Environment

Only infrastructure and model routing stay in env (tunables are central settings, see above).

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_NAME` / `SERVICE_BASE_URL` / `SERVICE_VERSION` / `SERVICE_TYPE` / `SERVICE_TAGS` / `SERVICE_TOPOLOGY_TAGS` | see `.env.example` | Hub registration |
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub base URL |
| `HUB_KEEPALIVE_SECONDS` | `60` | Hub re-registration period |
| `ATHENA_ORACLE_HINT_ROUTE` | `api/athena/hints` | Oracle path for hints (route) |
| `LOG_LEVEL` | `INFO` | Boot log level only (live: `athena.log.level`) |
| `ATHENA_UI_DIST` | `/ui/dist` | WebUI bundle folder (set in the Dockerfile, infrastructure) |

Models are not Athena settings: Athena calls Oracle `/api/llm/generate` with `use_case` `athena.strategia`
(strategist + memory consolidation), `athena.riflessione` (life reflection) or `athena.revisione` (answer audit), both declared in its Hub registration
(`capabilities.llm_usecases`); their chain and mode are chosen in Oracle → Cervello → Modelli (suggested `potente`).

## Resource-conscious design
- Single Oracle LLM call per cycle (no multi-step chain-of-thought)
- Compact prompts — never stuff full entity payloads
- Observation timeout prevents hanging on unavailable services
- Source-level failure isolation — one down service never blocks the full cycle
- Strategist can be disabled (setting `athena.strategist.enabled`) for debugging; returns empty
- Domains discovered dynamically from Hub topology tags, no hardcoded list

## Scope (Phase 3)
- [x] Real system observation (Hub, Archive, Argus)
- [x] LLM-powered reasoning via Oracle
- [x] Structured action candidate generation
- [x] Thinking cycle archiving
- [x] Client-visible thinking history endpoint
- [x] Resource-conscious prompt design

## Out of scope (future phases)
- Multi-cycle planning (today: single cycle, single Oracle call)
- Cross-domain prioritization ranking
- Persistent working memory across restarts
- Static rule-based fallbacks (by design — Oracle is core, no hardcoded substitutes)

## Skill Curator (Plan P3b-10)

Athena now manages the procedural memory lifecycle — creating, evaluating,
and curating skills from Oracle session summaries.

**Daily cycle addition (alongside memory consolidation):**
1. Read session summaries from Archive (`entity_type=session_summary`, last 24h)
2. Cluster by domain + embedding similarity
3. For clusters with ≥3 similar sessions: extract most common tool_sequence, create/update skill in Archive
4. Lifecycle management: deprecate stale (30d unused), hard-delete dead (90d, <3 uses), merge near-duplicates (sim >0.95), promote core (50+ uses, >95% success)

**Configuration:** central settings `athena.skills.*` (see "Central settings"). Embeddings go through
Oracle `/api/embed` via Hub (no Athena embedding config).

**Files:** `app/core/skill_curator.py` (new), `app/core/runtime.py` (wired into daily cycle)

## Oracle alignment
- Athena remains a separate service with its own runtime loop.
- Athena outputs are advisory cognition events, not direct Oracle action execution.
- Oracle can ingest Athena hints as context while preserving execution truth contracts.
- Skills are created by Athena (not Oracle) — the app improves day by day without user prompts.
- Oracle writes session summaries; Athena reads them, creates skills, and manages lifecycle.
- Oracle discovers skills at session start via Archive similarity search and injects them into the agent loop prompt.
- Shared priorities with Oracle:
    - trace propagation across Oracle/Hub/Hermes/Athena
    - typed task lifecycle for background jobs
    - explicit relevance gate observability for focus_brief decisions

## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.

## Assistant presence

Light work (thinking cycles) waits while presence `work.light=defer`; consolidation and skill curation run only with `work.heavy` allow/local (still inside their agenda windows). Thinking runs as activity `athena.thinking` (light, gpu); the observation includes the presence context line. Chronos down → old Oracle-idle check.
