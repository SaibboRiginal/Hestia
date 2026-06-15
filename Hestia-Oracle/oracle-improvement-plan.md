# Oracle Improvement Plan — Reference for Future Sessions

> Written 2026-06-12. Covers the 6 immediate fixes (implemented this session) plus
> longer-term architectural improvements for future work.

---

## Immediate Fixes (This Session)

### 1. Unify Tool Calling
- **Before:** Three competing paths — `_try_action_call()`, `_try_query_command_call()`, `_build_domain_tools()` in agent loop
- **After:** Single `_build_domain_tools()` path. All Hub commands (read + write) become tools in the agent loop manifest. Agent loop handles everything.
- **Rationale:** Removes duplicate code, prevents LLM confusion from different tool schemas, single code path to debug.

### 2. Visible Thinking
- **Before:** Status messages are fixed strings. No visibility into what the LLM is doing.
- **After:** New `thinking` NDJSON event type. Agent loop emits reasoning text before tool calls, tool results after execution, and a compact tool-call summary as a final signal after the answer.
- **Rationale:** Users see what the assistant is doing. Telegram gets tool-call results as a separate compact message after the answer.

### 3. Single Classify Call
- **Before:** Two separate LLM calls — `classify()` (mode + domain) and `_detect_action_intent()` (action intent boolean).
- **After:** One LLM call returns `mode`, `domain`, `confidence`, `valid_domains`, `filters`, `sort_by`, `sort_order`, AND `action_intent`.
- **Rationale:** Cuts LLM calls per turn from 4-8 to 1-3. Faster response.

### 4. Memory as First-Class Tools
- **Before:** Memory extraction runs in a background daemon thread after the response is sent. The LLM cannot save or recall memories during conversation.
- **After:** `memory.save` and `memory.search` are agent loop tools. The LLM decides when to persist a fact or recall previous memories. Background extraction remains as a safety net.
- **Rationale:** The LLM can save a preference DURING the turn and use it immediately. Aligns with how Claude Code handles memory.

### 5. Strengthened Fallback Chains
- **Before:** Fallback exists for some paths but not all. Cloud/local switching requires env restart.
- **After:** Every LLM call site uses primary → fallback chain. Provider/model configured via .env. If primary (e.g. Ollama) fails, fallback (e.g. Gemini) is tried automatically at runtime.
- **Rationale:** Resilient operation — if local model crashes, cloud takes over transparently. No restart needed.

### 6. Increased Agent Flexibility
- **Before:** Max 6 turns, no early exit, scratchpad lost after loop.
- **After:** Max turns configurable (default 25 for `domain_query`, 50 for `thinking` mode). Early exit when LLM produces final answer with no tool calls. Tool-call log persisted in Archive history.
- **Rationale:** Complex multi-step tasks can use many turns. Simple tasks exit after 1-2 turns. Tool results are remembered across conversation turns.

---

## Future Work (Not This Session)

### A. MCP Standardization for All Modules
**Goal:** Every Hestia service exposes tools via the Model Context Protocol (MCP) instead of the custom `commands` list format.

**Current State:** Each service registers `capabilities.commands` with Hub in a custom JSON format. Hub aggregates them. Oracle manually builds tool schemas from this format.

**Why MCP:**
- Standard tool discovery (`tools/list`) and invocation (`tools/call`)
- Properly typed input schemas (JSON Schema)
- LLMs natively understand MCP tool formats (Claude, GPT, Gemini all support it)
- Resources and prompts as first-class concepts
- Streaming tool results

**Migration Path:**
1. Each service runs a lightweight MCP server alongside its HTTP API (can share the same FastAPI app)
2. Hub becomes an MCP registry — services register their MCP endpoint
3. Oracle connects as an MCP client, discovers tools from all services
4. Agent loop uses native MCP tool calling instead of custom `ToolDefinition` handlers

**Services to migrate (priority order):**
1. Scout (real_estate domain — most actively used)
2. Chronos (calendar — complex CRUD tools)
3. Iris (email — search/send/thread)
4. Hecate (gateway — auth flows, ingest triggers)
5. Argus (monitoring — status/logs/analysis)
6. Hephaestus (remediation — runbooks/approval flow)

### B. Athena Daily Memory Consolidation
**Goal:** Athena runs a daily cron-style job that analyzes per-user conversation history and consolidates durable memories.

**Current State:** Memory extraction runs per-turn in a background thread. Athena observes system state (services, health, entities) but does NOT analyze per-user behavior.

**What to Build:**
1. **Per-Session Analysis Pass:** Athena reads all messages since last analysis, extracts durable facts using Oracle's scribe LLM
2. **Cross-Session Consolidation:** Detect conflicting preferences, reinforce repeated patterns, decay old unused preferences
3. **User Model Evolution:** A structured user profile that evolves over time — explicit preferences, implicit preferences, behavioral patterns, frequently used domains
4. **Daily Summary:** Athena produces a morning brief: "User has been searching for X. Last week they asked about Y. Their top domains are Z."

**Integration Points:**
- Athena calls Oracle's `/api/llm/generate` for the LLM analysis (already done for system state)
- Reads chat history from Archive via Hub
- Writes consolidated memories back to Archive
- Publishes hints to Oracle (already implemented in `POST /api/athena/hints`)

**Schedule:** Once per day per active user, during quiet hours (configurable).

### C. Chat Modes (auto/quick/thinking)
**Goal:** Three explicit execution modes selectable by clients.

**Mode Definitions:**
| Mode | Classify? | Agent Loop? | Max Turns | Model | Target Latency |
|------|-----------|-------------|-----------|-------|----------------|
| `auto` | Yes | If domain_query | 25 | Primary (local) | <5s |
| `quick` | No | Never | 0 | Fastest (fallback) | <2s |
| `thinking` | Yes | Always | 50 | Strongest (analyst) | <30s |

**Implementation:**
- `ChatRequest.mode` field (default `"auto"`)
- `quick` skips straight to `_quick_answer()` with Gemini Flash (bypasses classify + agent loop entirely)
- `thinking` forces agent loop with visible reasoning, higher max turns, uses the strongest analyst model
- Telegram always uses `auto` (as requested)

### D. Richer Temporal Context
**Goal:** Make the assistant aware of more than just current date/time.

**Additional Context to Inject:**
- Calendar events from Chronos (today's agenda items)
- Time of day (morning/afternoon/evening/night — affects greeting style)
- Day of week (weekday vs weekend — affects suggestions)
- Season (affects contextual recommendations)
- Upcoming reminders and tasks

**Implementation:** Add a `_build_enriched_temporal_context()` method that queries Chronos/Archive for calendar items and builds a richer context block.

---

## Principles Followed
- No hardcoded values — all thresholds/timeouts are env vars
- Every change includes tests
- Documentation synchronized (hestia-oracle.md, swagger.yml, readme.md)
- Background threads are daemon=True
- All HTTP calls have timeouts
- Fallback chain on every LLM call site
- No silent failures — all exceptions logged at WARNING or ERROR
