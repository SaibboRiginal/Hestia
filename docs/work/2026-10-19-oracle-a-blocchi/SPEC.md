# SPEC — Oracle a blocchi: named providers, reusable model chains, external agent mode, usage panel

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | User via external chat (brainstorm 2026-10-19, item 1 of the final list in `/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md`) → project thread «Oracle a blocchi» |
| **Status** | Approved v1.1 (Marko, card, 2026-10-19 11:55); v1.2 = implementation refinements (below) — implemented, Marko real run pending |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## Why (Marko's words, summarised)
Hestia must become a personal "Jarvis": open, easy to configure in any way, environment and client; it works with a
local LLM, on top of Claude/Codex/Gemini, or with an external brain, and accepts further layers on top. Every kind of
coach (life, training, nutrition, finance, study…) will lean on Marko's personal dataset and on Oracle.
Today Oracle is hard to configure: **94 settings (32 about models)**, ~15 env vars, one primary + one fallback per use
case, a single `openai` endpoint, and Forge has its own parallel profiles (`ORACLE_LLM_PROFILE_*`, built-in
`local`/`cloud`). Gemini's free quota is **per model**, so one fallback is not enough.

## Goal
Oracle built from three simple blocks, configured in one place:

1. **Providers** — *where* models live: a name, a standard (type) and an address in Themis; the key alone in env.
2. **Chains** — *which* models, in order, like CSS `font-family`: a named, reusable list of provider+model steps;
   a step out of quota is skipped until its quota resets, the next one answers.
3. **Use cases** — *what for*: every module that needs Oracle declares its own use cases (one per kind of task);
   each points to a chain, all edited in one place (Oracle → Modelli, grouped by module).

Plus two things that only make sense once the blocks exist:

4. **External mode** — a mode of its own (not a chain step): Oracle's internal machine (classifier, modes, tool
   selection, agent loop) is replaced by an agent (Claude Code `claude -p`, Codex `codex exec`…) that works with
   Hestia's MCP tools; Oracle stays the only door, Archive stays the source of truth of conversations.
5. **Usage panel** — like Claude Projects' usage view: per module, per session, per use case and per chain step:
   calls, frequency, tokens, context fill, cache hits, cost, model actually used.

## Scope

### A. Named providers (Themis = name, standard, address · env = key only)
- Provider **types are standards**, providers are named instances (as LiteLLM/OpenRouter-style tools do):
  | Type (standard) | Example providers |
  |---|---|
  | `ollama` | `ollama` (local) |
  | `openai` (compatible) | `llamacpp` (llama-server, local), `lmstudio`, `deepseek`, `openrouter`, `groq` |
  | `anthropic` | `claude-api` (API key), `deepseek-anthropic` |
  | `gemini` | `gemini` (API key) |
  | `claude_cli` | `claude` (subscription through the `claude` CLI, as a model in a chain) |
  | agent (§D) | `claude-code` (subscription), `codex` |
- Setting `oracle.providers` (Themis, object, live): `{name: {type, label, url}}`; added/edited from the WebUI.
  Defaults: `ollama` (url from the existing infra `OLLAMA_URL`), `gemini`, `claude` / `claude-code` (shown only when
  the CLI is installed and logged in).
- **Keys stay in env** (repo is public): `ORACLE_KEY_<NAME>` (name upper-cased, `-` → `_`, e.g.
  `ORACLE_KEY_DEEPSEEK`, `ORACLE_KEY_CLAUDE_API`). The panel shows only "key ✓ / missing".
- **Removed, no compatibility layer** (rule: no legacy env): `GEMINI_API_KEY` → `ORACLE_KEY_GEMINI`;
  `ORACLE_OPENAI_BASE_URL/_API_KEY` → an `openai` provider + `ORACLE_KEY_<NAME>`; `ORACLE_ANTHROPIC_API_KEY` →
  `ORACLE_KEY_CLAUDE_API`; all `ORACLE_LLM_PROFILE_*` gone. `.env.example`, compose comments, `tools/cloud_test.py`
  and docs updated in the same change; the cloud bench secret becomes `ORACLE_KEY_GEMINI`.
- Safety kept: no key ever reaches a `claude`/`codex` subprocess (`cli_env()` strips every `ORACLE_KEY_*` and
  `ANTHROPIC_API_KEY`), so Forge's Claude Code never switches to paid API billing.
- `GET /api/llm/providers`: name, type, address, key present, reachable, models (`list_models()`), per-model quota
  state.

### B. Named reusable chains
- Setting `oracle.chains` (Themis, type object, live): `{name: {label, steps: [{provider, model, thinking?}]}}`.
  Defaults (editable, more can be added):
  | Chain | Default steps (only steps whose provider exists are used) |
  |---|---|
  | `veloce` | ollama gemma4:e4b → gemini gemini-2.5-flash-lite → gemini gemini-2.0-flash-lite |
  | `potente` | ollama gemma4:e4b → gemini gemini-2.5-flash → gemini gemini-2.5-flash-lite |
  | `codice` | ollama gemma4:e4b → gemini gemini-2.5-flash → gemini gemini-2.0-flash |
  | `embedding` | ollama qwen3-embedding:0.6b (one step only, see decisions) |
  | `visione` | first vision-capable model among the above |
- A step is tried; on **quota/rate-limit** (429, Gemini `RESOURCE_EXHAUSTED`, Anthropic 429/529, CLI usage-limit
  message) the provider+model pair is marked *exhausted until* the reset time the provider gives (`Retry-After`,
  Gemini `RetryInfo`), else for `oracle.chains.cooldown` (default 60 min; Gemini daily quotas: until next
  midnight Pacific time); exhausted pairs are skipped by **every** chain until then. On other errors (timeout,
  5xx, unreachable) the existing retries run, then the next step for this call only (no long skip).
- A step whose provider is not declared or not available is skipped silently with one
  `event=llm_chain_step_unavailable` log line per change (not per call).
- All steps exhausted → the use case's call fails with a clear error (`event=llm_chain_exhausted`), exactly where
  today the fallback fails. (The "Cervello offline" thread decides what clients show then.)
- Quota state lives in Oracle memory (lost on restart = at most one extra 429 per pair).

### C. Use cases: declared by each module, configured in one place
- Every module that calls Oracle **declares its use cases** (one per kind of task, as many as it needs) with
  `hestia_common` (`oracle_usecases([...])` next to its settings declaration): id `<module>.<task>`, label,
  suggested chain (`veloce`/`potente`/`codice`/…), optional suggested mode. Examples: `scout.annunci` → veloce,
  `athena.strategia` → potente, `athena.revisione` → veloce, `hercules.pianifica` → potente (future coaches).
  Oracle's own: `oracle.generale` → veloce, `oracle.ragionamento` → potente, `oracle.codice` → codice,
  `oracle.embedding` → embedding; Forge: `forge.codice` → codice.
- Setting `oracle.usecases` (object, live): `{use_case: {chain, mode, thinking}}` holds only Marko's overrides;
  missing = the module's suggestion. `mode` = `segui` (global mode, default) | `interna` | `esterna`.
- Modules call `/api/llm/generate` with their `use_case` (existing field; current ids renamed: `scout_extraction`
  → `scout.annunci`, `athena_strategist` → `athena.strategia`, `athena_auditor` → `athena.revisione`). An
  undeclared use case runs on `oracle.generale` and is listed too, so nothing breaks.
- The 32 `oracle.models.*` settings and `oracle.models.claude_code.model` disappear; one-time migration on first
  start: if Marko changed any old value, Oracle writes the equivalent chain (`<use case>-personale`) and points the
  use case to it, then deletes the old keys (log `event=oracle_models_migrated`).
- Forge: `/api/llm/chat` takes `use_case` (default `forge.codice`) instead of `profile`; the Forge engines `local`
  and `cloud` become one engine `oracle` (the in-process loop on that use case's chain); engine `claude` stays
  (Claude Code in the worktree). `GET /api/llm/profiles` is removed; callers updated (Hephaestus, swagger, WebUI).
- Settings panel **Oracle → Modelli** = Fornitori, Catene, Usi grouped by module (chain + mode per row), Cervello
  (global mode). Everything else in Oracle's settings (agent loop, context, timeouts, memory, approvals, documents,
  A/B) moves under *avanzate*. Remaining settings keep their keys (Athena/Themis proposals unaffected).

### D. External mode (a mode of its own)
- Setting `oracle.brain.mode` = `interna` (default) | `esterna`, plus `oracle.brain.agent` (provider of kind
  agent + model, e.g. `claude-code` / `sonnet`) and `oracle.brain.fallback` (`interna`, default, or none).
  A use case can override the mode (§C). This is a real tunable, not a feature switch.
- **Interna** = today's machine: classifier, Rapida/Pensata/CoT, context builder, domain tool selection, agent loop,
  model from the use case's chain.
- **Esterna** = the agent runs the loop. Oracle keeps the door work only: receives every turn (chat and proactive
  turns from Chronos/Athena/Argus/modules), builds the context, saves messages to Archive, gives the agent Hestia's
  tools, extracts memory after the turn, records usage. If the agent fails or hits its limit, the turn is redone in
  `interna` with the chains (when `fallback = interna`), with full history.
- Tools: the agent gets Hestia's tools through a **stdio MCP bridge started by Oracle** (`--mcp-config` for
  Claude Code, `-c mcp_servers…` for Codex). The bridge only forwards `tools/list` / `tools/call` to Oracle's own
  tool executor, so the agent sees the same domain-filtered tools, the same high-impact **approval gate**
  (confirmation through Hermes), the same logs and Hub routing as the internal loop. No new service URL, no direct
  module access; Claude Code's own file/shell tools stay disabled.
- Sessions: **Archive stays the source of truth** (messages saved as today). The agent's session id
  (`--resume <id>`, `codex exec resume <id>`) is only a cache keyed by (Archive session, agent, model), kept in
  Oracle memory. Missing, expired, different agent, or older than the last Archive message written in `interna` →
  Oracle starts a new agent session primed with the same context it builds for the internal loop (summary + recent
  messages + memory). Switching mode mid-conversation never loses history.
- Prompt: the agent gets Oracle's system prompt (fixed prefix first → provider-side cache works) and the
  conversation style contract, so answers look the same in both modes.
- On a plain `/api/llm/generate` call of a use case in `esterna`, the agent answers without tools (one shot).
- Codex: same interface; usable only where its CLI is installed and logged in (`ORACLE_INSTALL_CODEX=1` build arg,
  like Claude Code). Not testable in the cloud bench without a login → covered by tests with a fake CLI.

### E. Usage panel
- Every LLM call (internal steps and agent runs) produces one usage row: time, **caller module**, client and session
  (chat), use case, chain, step index, provider, model, input/output/cached tokens, context window and fill, duration,
  cost (provider-reported, or computed from `oracle.pricing` — object setting `{provider/model: $ per Mtok in, out,
  cached}`; subscription steps show "abbonamento" with the CLI's own equivalent cost), outcome (ok / quota / error /
  skipped).
- Caller identity (v1.2): the module is the prefix of the use case (`scout.annunci` → `scout`), which every module
  already declares and sends — no header needed; Oracle's own calls are `oracle.*`, Forge's `forge.codice`.
- Storage: rows are **pushed** by Oracle to Archive (new store `llm-usage`, fire-and-forget through Hub, retention
  `oracle.usage.retention_days` default 90); aggregates are queried from Archive. The in-memory `llm_stats` stays
  for the live chat gauge.
- `GET /api/llm/usage?group=module|session|usecase|model&days=N` + per-session detail.
- WebUI: Oracle's plugin page **Cervello** gains a tab **Uso** (cards per module: calls today, calls/hour, tokens,
  cache hit %, cost; table of sessions; daily chart; which chain step answered and how often a fallback was used) and
  a tab **Modelli** with the chain editor (↑↓ buttons to reorder steps (v1.2: works on phones), provider/model pickers from
  `/api/llm/providers`, quota state per step) and use case → chain picker. It writes through Themis like every
  setting.

### Out of scope
- Local KV save per session with llama-server (thread «Contesto salvato e alternative a Ollama»).
- What clients show/queue when every step fails (thread «Cervello offline»).
- Voice / Whisper move (item 4 of the list).
- `memory_note` for direct MCP chats (item 10).

## Acceptance criteria
1. A provider is added from the WebUI (name, standard, address) + one `ORACLE_KEY_<NAME>` env line and appears in
   `/api/llm/providers` and in the chain editor.
2. A chain `gemini-2.5-flash → gemini-2.5-flash-lite → gemini-2.0-flash`: a 429 on the first step answers with the
   second, and the first is skipped by all chains until its reset; the panel shows it as exhausted until then.
3. Changing the chain of «Uso generale» in one place changes chat, classifier and memory; changing chain `veloce`
   changes every use case that points to it.
4. Forge `oracle` engine runs on the `forge.codice` chain; no `ORACLE_LLM_PROFILE_*` or `/api/llm/profiles` left anywhere.
5. Oracle's settings in *Modelli* (non-advanced) ≤ 10; old `oracle.models.*` values migrated once.
6. In `esterna` with agent `claude-code`, a chat turn is answered by Claude Code using Hestia tools through the bridge
   (approval gate still asks via Hermes for high-impact tools); with the CLI failing/limited the same turn is answered
   in `interna` with full history; Archive holds every message either way.
6b. A module declaring two use cases shows two rows under its name in Modelli; changing one changes only that task.
7. Usage panel shows per module (Scout, Athena, Forge, chat…) and per session: calls, frequency, tokens, context, cache,
   cost, model used; data survives an Oracle restart.
8. Tests (unit/api) for chain resolution, quota skip/reset, migration, provider env parsing, bridge, session cache
   rebuild, usage rows; cloud bench `python tools/cloud_test.py all` green with the fake LLM (and Gemini if a key is
   set as environment secret).
9. Docs follow code: `hestia-oracle.md`, `hestia-hephaestus.md`, `hestia-archive.md`, swagger, `.env.example`,
   compose comments, `docs/ARCHITECTURE.md`, `docs/AI-GUIDE.md`, README, TESTING.md, root CHANGELOG.

## Design decisions
1. **Providers in Themis, keys in env** (Marko 2026-10-19). Env names `ORACLE_KEY_<NAME>`; old env names removed
   with no compatibility. One `.env` edit for Marko at upgrade (`GEMINI_API_KEY` → `ORACLE_KEY_GEMINI`).
2. **Types are standards** (`openai`, `anthropic`, `gemini`, `ollama`, CLI, agent); providers are named instances
   (Marko 2026-10-19). DeepSeek recommended on the `openai` standard (native tools, automatic prefix cache).
3. **External is a mode of its own**, global with per-use-case override, falls back to internal (Marko 2026-10-19).
4. **Use cases declared by modules**, several per module, configured in one place (Marko 2026-10-19).
5. **Embedding chain has one step.** Vectors from different models are not comparable: falling back to another model
   would silently break memory and document search.
6. **Usage rows in Archive** (only DB owner), pushed per call; no flush job. **Quota state in memory**.

## Phases
- P1 Providers (Themis + `ORACLE_KEY_*`) + chains + quota skip in Oracle core (dispatch through chain; `universal_agent` keeps provider code).
- P2 Use cases declared by modules (`hestia_common`), → chains, settings migration, Modelli simplified, the rest under *avanzate*; Forge on use case `forge.codice`,
  profiles removed (Hephaestus + swagger).
- P3 Usage: module from the use case prefix, Archive `llm-usage`, `/api/llm/usage`.
- P4 WebUI: *Cervello* tab Uso; Modelli editor (providers, chains, use cases by module, mode).
- P5 External mode: `oracle.brain.*`, MCP bridge, Claude Code agent, session cache + rebuild from Archive; `codex` adapter.
- P6 Docs everywhere, cloud bench run with screenshots, root CHANGELOG, PR merged when CI green.

## Coordination
- «Cervello offline» thread: touches Argus/Hermes and the chat queue; this work only guarantees a clear
  `llm_chain_exhausted` error from Oracle. Shared files (`Hestia-Oracle/app/main.py`, `hestia-oracle.md`) are edited
  in small hunks and merged from main before each push.
- «Email in push e modulo Spese»: Spese will just send its own `use_case` (§C) — nothing to wait for.

## Implementation notes (v1.2, 2026-10-19)
- Oracle use cases: `oracle.generale`, `oracle.ragionamento`, `oracle.codice`, `oracle.documenti` (vision; documents,
  images, audio), `oracle.embedding`. Default chains `veloce`, `potente`, `codice`, `visione`, `embedding`.
- Module use cases shipped: `scout.annunci`, `athena.strategia`, `athena.revisione`, `argus.analisi`, `chronos.agenda`,
  `wardrobe.foto` (chain `visione`, replaces the setting `wardrobe.ai.profile`), `forge.codice` (Hephaestus).
  Metis reads the current model from `/api/llm/usecases/oracle.generale`.
- Forge engines: `oracle` (chain of `forge.codice`) and `claude`; old `local`/`cloud` names are aliases. Permission
  group of `oracle` = `cloud` when any usable step is billed, else `local`.
- Agent settings: `oracle.brain.agent` = `claude` | `codex` and a separate `oracle.brain.model` (instead of a provider
  of kind agent); `oracle.brain.fallback` = `interna` | `nessuno`. In esterna the classifier still runs (it gives the
  domain filter of the tools), quick shortcuts are skipped. The bridge calls Oracle on loopback
  (`/api/agent-bridge/<token>`, one token per turn) because the tool handlers live in Oracle's process.
- Usage rows are pushed by one background worker started by the first row (no timer); Archive applies retention on
  write. `oracle.pricing` keys are `provider/model` or `model`.
- Old `oracle.models.*` rows stay in Archive as orphans (Themis cannot delete undeclared keys); the migration runs only
  while neither `oracle.chains` nor `oracle.usecases` was ever stored.
