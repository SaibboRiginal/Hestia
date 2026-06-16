# Oracle Improvement Plan

> Last updated 2026-06-16. Phases 1-6 complete. Phase 7-10 ready.

---

## ✅ Completed

### Phase 1 — Unify Tool Calling
Single `_build_domain_tools()` path. Removed `_try_action_call()`, `_try_query_command_call()`, `_detect_action_intent()`. All Hub commands + domain tools + memory tools flow through one agent loop.

### Phase 2 — Visible Thinking
New `thinking` NDJSON event type (`reasoning`, `tool_call`, `tool_result`). Tool-call summary signal (`tool.summary`) after answer. Telegram renders thinking as live status updates + post-answer summary card.

### Phase 3 — Single Classify Call
`chat_classifier.py` returns `action_intent` (10th field). Mode + domain + action_intent in one LLM call instead of two.

### Phase 4 — Memory as First-Class Tools
`memory.save` and `memory.search` as agent loop tools. LLM decides when to persist/recall. Background extraction remains.

### Phase 5 — Fallback Chains
Every LLM call site: primary → fallback. Cloud/local auto-fallback at runtime. No restart.

### Phase 6 — Agent Loop Flexibility
Max turns configurable (default 25). Early exit. Tool log for post-answer summary.

### Test Infrastructure
264 fast unit/integration tests. 34 live LLM tool-calling tests (`run_live_tests.bat -s`). 8 domain-scoped manifests. Anti-hallucination validation.

---

## Remaining Phases — In Dependency Order

```
Phase 7 ──▶ Phase 8 ──▶ Phase 9 ──▶ Phase 10 ──▶ Phase 11 ──▶ Phase 12
(cleanup)   (MCP gw)    (migrate)   (modes)      (Athena)     (context)

7.  Agent Factory Cleanup (Oracle internal, no deps)
8.  Hestia-MCP Gateway (new service — template-based, foundation for everything)
9.  Service MCP Migration (every service gets MCP, old commands removed)
10. Chat Modes + Domain Filtering (Oracle switches to MCP as sole tool source)
11. Athena Daily Memory Consolidation (per-user retrospective analysis)
12. Enriched Temporal Context (calendar-aware, time-of-day, seasonal)
```

---

## Phase 7 — Agent Factory Cleanup

**No dependencies. Oracle-internal only.**

### Problem
Three competing env-var naming schemes. Ten agents with role names that don't reflect what they do. Six of ten point to the same model.

### Design: Use-Case Model Config

Mode and model are orthogonal dimensions:

```
MODE (how to orchestrate)          USE CASE (which brain)

quick    → 1 ask(), no tools       generic   → gemma4:e4b (daily driver)
auto     → classify + loop         reasoning → 26B (deep thinking, on demand)
thinking → full agent loop         code      → gemma4:e4b (coding tasks)
                                   embedding → nomic-embed-text (vectors)

ChatRequest.mode  = "auto"        ChatRequest.model = "generic"
```

**New `.env` — 4 use cases, each with primary + fallback:**
```env
MODEL_USECASE_GENERIC_PROVIDER=ollama
MODEL_USECASE_GENERIC_MODEL=gemma4:e4b
MODEL_USECASE_GENERIC_FALLBACK_PROVIDER=gemini
MODEL_USECASE_GENERIC_FALLBACK_MODEL=gemini-2.0-flash-lite

MODEL_USECASE_REASONING_PROVIDER=ollama
MODEL_USECASE_REASONING_MODEL=gemma-4-26B-A4B-it-UD-IQ4_NL:latest
MODEL_USECASE_REASONING_FALLBACK_PROVIDER=gemini
MODEL_USECASE_REASONING_FALLBACK_MODEL=gemini-2.5-flash

MODEL_USECASE_CODE_PROVIDER=ollama
MODEL_USECASE_CODE_MODEL=gemma4:e4b
MODEL_USECASE_CODE_FALLBACK_PROVIDER=gemini
MODEL_USECASE_CODE_FALLBACK_MODEL=gemini-2.0-flash

MODEL_USECASE_EMBEDDING_PROVIDER=ollama
MODEL_USECASE_EMBEDDING_MODEL=nomic-embed-text
MODEL_USECASE_EMBEDDING_FALLBACK_PROVIDER=gemini
MODEL_USECASE_EMBEDDING_FALLBACK_MODEL=gemini-embedding-001
```

**Old keys removed (no deprecation — just removed):**
`ROUTER_PROVIDER`, `ROUTER_MODEL`, `SCRIBE_PROVIDER`, `SCRIBE_MODEL`, `ANALYST_PROVIDER`, `ANALYST_MODEL`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `CODER_PROVIDER`, `CODER_MODEL`, all `FALLBACK_*` variants, all `MODEL_CLASS_*` variants.

**New `AgentBundle`:**
```python
@dataclass
class AgentBundle:
    generic: UniversalAgent
    generic_fallback: UniversalAgent
    reasoning: UniversalAgent
    reasoning_fallback: UniversalAgent
    code: UniversalAgent
    code_fallback: UniversalAgent
    embedding: UniversalAgent
    embedding_fallback: UniversalAgent
```

**VRAM:** Only one text model loaded at a time. `generic` always loaded. `reasoning` triggers unload+load (~5-10s) only when `ChatRequest.model="reasoning"`. `embedding` is tiny (<1GB), stays loaded.

**Files:** `agent_factory.py` (rewrite), `oracle_engine.py` (~20 refs), `memory_service.py`, `user_control_service.py`, `chat_classifier.py`, `.env`, tests.

---

## Phase 8 — Hestia-MCP Gateway (New Service)

### Problem
Tools are discovered via Hub's custom `/discovery/commands` format. Each service registers differently (some have `commands` list, some have `tool_endpoints`, some have `module_tool_domains`). Oracle manually builds tool schemas from this mess. Third-party tools have no integration path at all.

### Design: Single MCP Gateway

```
                    ┌──────────────────┐
                    │   Hestia-MCP     │
                    │   (Gateway)      │
                    │                  │
 Telegram ──▶ Hub   │  Tool registry   │────▶ Scout MCP server
 (direct /commands) │  Domain filter   │────▶ Chronos MCP server
                    │  Auth/proxy      │────▶ Iris MCP server
 Oracle ───────────▶│  Manifest cache  │────▶ Hecate MCP server
 (tools for LLM)    │                  │────▶ Argus MCP server
                    │                  │────▶ Hephaestus MCP server
                    │                  │────▶ 3rd-party MCP servers
                    └──────────────────┘
```

**Hestia-MCP is the ONLY tool source.** After Phase 9, Hub's `/discovery/commands` is removed. Every consumer that needs tools goes through Hestia-MCP.

**Responsibilities:**
1. Aggregates MCP tools from all internal services + third-party servers
2. Pre-filters by domain — Oracle asks for `["scout", "chronos"]`, gets only those tools
3. Translates MCP tool schemas to Oracle's `ToolDefinition` format
4. Handles third-party auth (API keys, OAuth)
5. Caches tool manifests with TTL, refreshes on registry change
6. Proxies tool calls from Oracle to target MCP servers

**Endpoints (for Oracle):**
```
GET  /tools?domains=scout,chronos    → returns ToolDefinition[] for those domains
POST /tools/call                     → proxy a tool call to the target MCP server
GET  /tools/health                   → health check all registered MCP servers
```

**Endpoints (for Telegram after Phase 9):**
```
GET  /commands?client=telegram       → returns command catalog (replaces Hub /discovery/commands)
```

**Registration flow:**
1. Each service starts its MCP server (alongside existing HTTP API during migration)
2. Service registers MCP endpoint in Hub: `capabilities.mcp_endpoint: "http://scout:19006/mcp"`
3. Hestia-MCP watches Hub registry for services with `mcp_endpoint`
4. Hestia-MCP calls `tools/list` on each MCP server, caches the manifest

**Files:** New service at `Hestia-MCP/`, created from `templates/python-service-template/`. Follows `HestiaServiceBase` pattern (same as Atlas, Hephaestus). Hub adds `mcp_endpoint` to registration schema. Oracle adds `HestiaMCPClient`.

---

## Phase 9 — Service MCP Migration

### Problem
Each service currently exposes tools via `capabilities.commands` in Hub registration. After Phase 8, Hestia-MCP is ready to consume MCP tools. Services must expose MCP servers.

### Per-Service Work

Each service gets a lightweight MCP server using the `mcp` Python SDK. The server runs on the same FastAPI app, at `/mcp` endpoint. The existing HTTP API stays in place — MCP runs alongside, not instead of.

**Migration per service:**
1. Add `mcp` SDK dependency
2. Define MCP tools from existing command handlers
3. Expose `/mcp` endpoint on the FastAPI app
4. Register `mcp_endpoint` in Hub registration payload
5. Remove `commands` list from Hub registration (MCP is now the source)

**Priority order:**
| # | Service | Tools | Complexity |
|---|---------|-------|------------|
| 1 | Scout | scout.search, scout_listings, scout_reconcile | Low — 3 tools |
| 2 | Chronos | 8 calendar tools | Medium — complex params |
| 3 | Iris | 4 email tools | Low — simple CRUD |
| 4 | Hecate | 5 gateway/auth tools | Medium — OAuth flow |
| 5 | Argus | 4 monitoring tools | Low — read-only |
| 6 | Hephaestus | 5 remediation tools | Medium — approval flow |

**After all services migrated:** Hub's `/discovery/commands` endpoint is removed. `capabilities.commands` is removed from Hub registration schema. Telegram switches to Hestia-MCP for command discovery.

---

## Phase 10 — Chat Modes + Domain Filtering

### 10a — Chat Modes (auto / quick / thinking)

Mode controls PROCESS. Model controls BRAIN. They're independent.

| Mode | Classify? | Agent Loop? | Max Turns |
|------|-----------|-------------|-----------|
| `auto` | Yes | If domain_query | 25 |
| `quick` | No | Never | 0 |
| `thinking` | Yes | Always | 25+ |

```python
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    mode: Literal["auto", "quick", "thinking"] = "auto"
    model: Literal["generic", "reasoning", "code"] = "generic"
```

**Flow:**
- `quick` → `agent.ask(user_message)`, done. <2s latency.
- `auto` → current behavior. Classify → agent loop if needed.
- `thinking` → force agent loop, emit all thinking events, higher max_turns.
- Telegram always sends `mode=auto`, `model=generic`.

### 10b — Domain Pre-Filtering

After MCP migration, Oracle gets tools from Hestia-MCP with domain filtering built in:

```python
# Before: Oracle gets ALL 34 tools from Hub
all_commands = self._hub.get_commands()
tools = [build_tool(cmd) for cmd in all_commands]  # 34 tools

# After: Hestia-MCP returns only domain-relevant tools
tools = self._mcp.get_tools_for_domains(intent.valid_domains)  # 5-12 tools
```

Hestia-MCP handles the filtering internally — Oracle just asks for what it needs.

**Result:** A scout query gets 6 tools. A calendar query gets 10. A greeting gets 3. The 4B model never sees more than ~12 tools at once.

---

## Phase 11 — Athena Daily Memory Consolidation

### Problem
Memory extraction runs per-turn in a background thread. No cross-session consolidation. Preferences never decay, conflicts never surface, patterns never emerge. The assistant forgets everything between sessions except what the scribe happens to catch.

### Design: Daily Cron-Style User Model Builder

Athena already runs a periodic observe→think→score→act loop (every 300s for system state). Phase 11 adds a **daily per-user memory consolidation pass**.

**New Athena phase: CONSOLIDATE**
1. **Read all sessions since last consolidation** — chat history from Archive for each active user
2. **Extract durable facts** — call Oracle's `/api/llm/generate` with a structured extraction prompt
3. **Cross-session consolidation:**
   - Detect conflicting preferences (old: "prefers Milano", new: "prefers Roma") → flag or resolve
   - Reinforce repeated patterns (mentioned "budget 300k" 5 times across 3 sessions → weight up)
   - Decay old unused preferences (last mentioned 90 days ago → weight down → eventually deprecate)
4. **Build user model:** structured profile per user — explicit prefs, implicit patterns, frequent domains, behavioral notes
5. **Publish hints to Oracle** — consolidated insights as Athena hints (already implemented endpoint)
6. **Archive the thinking record** — audit trail of what changed

**Schedule:** Once per day per active user. Configurable time window (default: 03:00-05:00 local). Only processes users with activity in the last 7 days.

**Integration:**
- Calls Oracle `/api/llm/generate` for LLM analysis
- Reads chat history + active memories from Archive via Hub
- Writes consolidated memories back to Archive
- Publishes hints to Oracle `POST /api/athena/hints`
- All through MCP (Phase 9) — Athena discovers Oracle's LLM endpoint via Hestia-MCP

**Files:** `Hestia-Athena/app/core/consolidator.py` (new module), `runtime.py` (add CONSOLIDATE phase).

---

---

## Phase 12 — Enriched Temporal Context

### Problem
Oracle currently injects only basic datetime (today, tomorrow, weekday). The assistant doesn't know about the user's calendar, time of day, season, or upcoming deadlines. This limits its ability to make contextual suggestions and affects greeting style, priority awareness, and proactive behavior.

### Current State
`_current_datetime_context()` returns:
```
timezone=Europe/Rome
now_iso=2026-06-16T14:30:00+02:00
today_date=2026-06-16
today_weekday=Tuesday
tomorrow_date=2026-06-17
tomorrow_weekday=Wednesday
```

### What to Add

**1. Calendar Integration (via Chronos MCP)**
Before each turn, query Chronos for today's events:
```
CALENDAR_CONTEXT:
- 15:00-16:00: Call con cliente
- 18:00-19:00: Dentista
```

**2. Time-of-Day Awareness**
```
TIME_CONTEXT: afternoon (14:00-18:00 window)
```
Affects greeting style, suggestion relevance, availability assumptions.

**3. Day-of-Week + Season**
```
WEEKDAY: Tuesday (workday)
SEASON: Summer (June)
```
Workday vs weekend affects what's reasonable to suggest. Season affects contextual recommendations.

**4. Upcoming Deadlines / Reminders**
```
UPCOMING:
- Task "Inviare proposta" due Thursday
- Reminder "Pagare bolletta" tomorrow
```

### Enriched Context Block
```
TEMPORAL_CONTEXT:
timezone=Europe/Rome | now=2026-06-16T14:30:00 | weekday=Tuesday | season=Summer
TODAY_AGENDA:
  15:00-16:00: Call con cliente
  18:00-19:00: Dentista
UPCOMING_DEADLINES:
  Thu: Inviare proposta
  Tomorrow: Pagare bolletta
```

### Implementation
- New method `_build_enriched_temporal_context()` in `context_builder.py`
- Queries Chronos via Hestia-MCP for calendar items (depends on Phase 9)
- Queries Archive for upcoming reminders/tasks
- Injected into agent loop `client_instructions` (same path as current temporal context)
- Configurable via env: `ORACLE_TEMPORAL_CALENDAR_ENABLED`, `ORACLE_TEMPORAL_REMINDERS_ENABLED`
- Falls back gracefully when Chronos/Archive unreachable — just the basic datetime

**Files:** `oracle_engine.py` (new method + injection), `context_builder.py` (formatting).

---

## Future Phases

### F.1 Multi-Model Concurrency
When VRAM allows: `generic` always loaded, `reasoning` + `code` loaded on demand without unloading `generic`.

---

## Principles
- No deprecation — remove old code, don't maintain two systems
- One tool protocol — MCP is the only interface between services
- No hardcoded values — everything is env vars
- Mode ≠ Model — orthogonal dimensions, both optional, sensible defaults
- Every change includes tests + doc sync (hestia-oracle.md, swagger.yml, readme.md, TESTING.md)
- Fallback chain on every LLM call site
- Scalable: nothing hardcoded to current hardware
