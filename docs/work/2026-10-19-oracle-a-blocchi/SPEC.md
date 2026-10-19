# SPEC — Oracle a blocchi: named providers, reusable model chains, external agent mode, usage panel

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User via external chat (brainstorm 2026-10-19, item 1 of the final list in `/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md`) → project thread «Oracle a blocchi» |
| **Status** | Draft — waiting for Marko's approval before any code |

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

1. **Providers** — *where* models live: a name, a type, an address and a key (env, infrastructure only).
2. **Chains** — *which* models, in order, like CSS `font-family`: a named, reusable list of provider+model steps;
   a step out of quota is skipped until its quota resets, the next one answers.
3. **Use cases** — *what for*: each use case (and each module's own use case) points to one chain.

Plus two things that only make sense once the blocks exist:

4. **External agent mode** — a chain step can be an *agent* (Claude Code `claude -p`, Codex `codex exec`…) that
   takes the whole turn and works with Hestia's MCP tools; Oracle stays the only door, Archive stays the source of
   truth of conversations.
5. **Usage panel** — like Claude Projects' usage view: per module, per session, per use case and per chain step:
   calls, frequency, tokens, context fill, cache hits, cost, model actually used.

## Scope

### A. Named providers (env = address + key only)
- Env scheme, one block per provider, any number: `ORACLE_PROVIDER_<NAME>_TYPE`, `_URL`, `_KEY`
  (e.g. `ORACLE_PROVIDER_DEEPSEEK_TYPE=openai`, `ORACLE_PROVIDER_DEEPSEEK_URL=https://api.deepseek.com/v1`,
  `ORACLE_PROVIDER_DEEPSEEK_KEY=…`). `<NAME>` is what chains refer to (lower-cased: `deepseek`).
- Types (existing code, generalised): `ollama`, `gemini`, `openai` (any OpenAI-compatible server: DeepSeek, Groq,
  OpenRouter, LM Studio, llama-server, vLLM), `anthropic` (API key), `claude_cli` (subscription, as model),
  and the new agent types of §D: `claude_code`, `codex`.
- Built-in providers with no config: `ollama` (from the existing `OLLAMA_URL`, the infra address it already has) and
  `claude` (`claude_cli`, present when the CLI is installed and logged in). Every other provider is declared.
- **Removed, no compatibility layer** (rule: env keeps only secrets/infra, no legacy env): `GEMINI_API_KEY`
  → `ORACLE_PROVIDER_GEMINI_KEY` (type `gemini` implied by the name `gemini` when `_TYPE` is absent, same for
  `ollama`, `claude`, `anthropic`); `ORACLE_OPENAI_BASE_URL/_API_KEY` → a named `openai`-type provider;
  `ORACLE_ANTHROPIC_API_KEY` → `ORACLE_PROVIDER_ANTHROPIC_KEY`; all `ORACLE_LLM_PROFILE_*` gone.
  `.env.example`, compose comments, `tools/cloud_test.py` and the docs are updated in the same change; the cloud
  bench secret becomes `ORACLE_PROVIDER_GEMINI_KEY`.
- Safety kept: no provider key ever reaches a `claude`/`codex` subprocess (`cli_env()` strips every
  `ORACLE_PROVIDER_*_KEY` and `ANTHROPIC_API_KEY`), so Forge's Claude Code never switches to paid API billing.
- `GET /api/llm/providers`: name, type, address (no key), reachable, models (`list_models()`), per-model quota state.

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

### C. Use cases point to chains
- Setting `oracle.usecases` (object, live): `{use_case: {chain, thinking}}` with the 7 known use cases and defaults:
  generale → `veloce`, ragionamento → `potente`, codice → `codice`, embedding → `embedding`,
  `scout_extraction` → `veloce`, `athena_strategist` → `potente`, `athena_auditor` → `veloce`; plus `forge` → `codice`.
- **Any** module can send a new `use_case` to `/api/llm/generate` (future coaches, Spese…): unknown use cases run on
  the `generale` chain and appear in the panel and in the editor, so Marko can point them to another chain without
  touching Oracle code.
- The 32 `oracle.models.*` settings and `oracle.models.claude_code.model` disappear; one-time migration on first
  start: if Marko changed any old value, Oracle writes the equivalent chain (`<use case>-personale`) and points the
  use case to it, then deletes the old keys (log `event=oracle_models_migrated`).
- Forge: `/api/llm/chat` takes `use_case` (default `forge`) instead of `profile`; the Forge engines `local` and
  `cloud` become one engine `oracle` (the in-process loop on the `forge` chain); engine `claude` stays (Claude
  Code in the worktree, model = the chain's `claude_code` step if any, else Claude Code's default).
  `GET /api/llm/profiles` is removed; callers updated (Hephaestus, swagger, WebUI).
- Settings panel: **Modelli** shows only use case → chain (7 rows) and the chain list; everything else in Oracle's
  settings (agent loop, context, timeouts, memory, approvals, documents, A/B) moves under *avanzate*. Every remaining
  setting keeps its key (Athena/Themis proposals unaffected).

### D. External agent mode
- New step kind **agent** (`claude_code`, `codex`): when the chain of a chat turn (`/api/chat`, proactive turns from
  Chronos/Athena/Argus/modules) reaches an agent step, Oracle hands the **whole turn** to the agent instead of running
  its own agent loop. On a plain `/api/llm/generate` call an agent step runs as a plain model call (no tools).
  So "internal vs external" is not a switch: it is which step of the chain answers, and a chain can mix them
  (`claude_code sonnet → gemini 2.5-flash → ollama`), so when the subscription limit is hit Hestia keeps answering.
- Tools: the agent gets Hestia's tools through a **stdio MCP bridge started by Oracle** (`--mcp-config` for
  Claude Code, `-c mcp_servers…` for Codex). The bridge only forwards `tools/list` / `tools/call` to Oracle's own
  tool executor, so the agent sees the same domain-filtered tools, the same high-impact **approval gate**
  (confirmation through Hermes), the same logs and Hub routing as the internal loop. No new service URL, no direct
  module access, Claude Code's own file/shell tools stay disabled.
- Sessions: **Archive stays the source of truth** (messages saved as today). The agent's session id
  (`--resume <id>`, `codex exec resume <id>`) is only a cache keyed by (Archive session, agent, model), kept in
  Oracle memory. Missing, expired, different agent, or older than the last Archive message written by another step →
  Oracle starts a new agent session primed with the same context it builds for the internal loop (summary + recent
  messages + memory). Result: switching steps mid-conversation never loses history.
- Prompt: the agent gets Oracle's system prompt (fixed prefix first, unchanged → provider-side cache works) and the
  conversation style contract, so answers look the same whichever step answered.
- Codex: implemented behind the same interface; usable only where its CLI is installed and logged in
  (`ORACLE_INSTALL_CODEX=1` build arg, like Claude Code). Not testable in the cloud bench without a login → covered by
  tests with a fake CLI.

### E. Usage panel
- Every LLM call (internal steps and agent runs) produces one usage row: time, **caller module**, client and session
  (chat), use case, chain, step index, provider, model, input/output/cached tokens, context window and fill, duration,
  cost (provider-reported, or computed from `oracle.pricing` — object setting `{provider/model: $ per Mtok in, out,
  cached}`; subscription steps show "abbonamento" with the CLI's own equivalent cost), outcome (ok / quota / error /
  skipped).
- Caller identity: `hestia_common` Hub route helper adds header `X-Hestia-Caller: <service>` (Hub forwards headers in
  the envelope already); missing → `sconosciuto`.
- Storage: rows are **pushed** by Oracle to Archive (new store `llm-usage`, fire-and-forget through Hub, retention
  `oracle.usage.retention_days` default 90); aggregates are queried from Archive. The in-memory `llm_stats` stays
  for the live chat gauge.
- `GET /api/llm/usage?group=module|session|usecase|model&days=N` + per-session detail.
- WebUI: Oracle's plugin page **Cervello** gains a tab **Uso** (cards per module: calls today, calls/hour, tokens,
  cache hit %, cost; table of sessions; daily chart; which chain step answered and how often a fallback was used) and
  a tab **Modelli** with the chain editor (drag to reorder steps, provider/model pickers from
  `/api/llm/providers`, quota state per step) and use case → chain picker. It writes through Themis like every
  setting.

### Out of scope
- Local KV save per session with llama-server (thread «Contesto salvato e alternative a Ollama»).
- What clients show/queue when every step fails (thread «Cervello offline»).
- Voice / Whisper move (item 4 of the list).
- `memory_note` for direct MCP chats (item 10).

## Acceptance criteria
1. A provider is added by three env lines and appears in `/api/llm/providers` and in the chain editor.
2. A chain `gemini-2.5-flash → gemini-2.5-flash-lite → gemini-2.0-flash`: a 429 on the first step answers with the
   second, and the first is skipped by all chains until its reset; the panel shows it as exhausted until then.
3. Changing the chain of «Uso generale» in one place changes chat, classifier and memory; changing chain `veloce`
   changes every use case that points to it.
4. Forge `oracle` engine runs on the `forge` chain; no `ORACLE_LLM_PROFILE_*` or `/api/llm/profiles` left anywhere.
5. Oracle's settings in *Modelli* (non-advanced) ≤ 10; old `oracle.models.*` values migrated once.
6. With chain `claude_code → gemini`, a chat turn is answered by Claude Code using Hestia tools through the bridge
   (approval gate still asks via Hermes for high-impact tools); with the CLI failing/limited the same turn is answered
   by Gemini with full history; Archive holds every message either way.
7. Usage panel shows per module (Scout, Athena, Forge, chat…) and per session: calls, frequency, tokens, context, cache,
   cost, model used; data survives an Oracle restart.
8. Tests (unit/api) for chain resolution, quota skip/reset, migration, provider env parsing, bridge, session cache
   rebuild, usage rows; cloud bench `python tools/cloud_test.py all` green with the fake LLM (and Gemini if a key is
   set as environment secret).
9. Docs follow code: `hestia-oracle.md`, `hestia-hephaestus.md`, `hestia-archive.md`, swagger, `.env.example`,
   compose comments, `docs/ARCHITECTURE.md`, `docs/AI-GUIDE.md`, README, TESTING.md, root CHANGELOG.

## Design decisions (defaults chosen; Marko can change them before approval)
1. **Env names** `ORACLE_PROVIDER_<NAME>_{TYPE,URL,KEY}` and the old ones removed with no compatibility (rule:
   no legacy env). One `.env` edit for Marko at upgrade (`GEMINI_API_KEY` → `ORACLE_PROVIDER_GEMINI_KEY`).
2. **Embedding chain has one step.** Vectors from different models are not comparable: falling back to another model
   would silently break memory and document search. If it fails the call fails (retried as today).
3. **External mode is a step kind, not a switch** (rule: no on/off settings; and it gives fallback across modes).
4. **Chains and use cases are two object settings** edited by a dedicated editor, instead of ~40 flat keys.
5. **Usage rows in Archive** (only DB owner), pushed per call; no flush job.
6. **Quota state in memory**, not persisted.

## Phases
- P1 Providers + chains + quota skip in Oracle core (dispatch through chain; `universal_agent` keeps provider code).
- P2 Use cases → chains, settings migration, Modelli simplified, the rest under *avanzate*; Forge on `forge` chain,
  profiles removed (Hephaestus + swagger).
- P3 Usage: caller header, Archive `llm-usage`, `/api/llm/usage`.
- P4 WebUI: *Cervello* tabs Uso and Modelli (chain editor).
- P5 External agent mode: MCP bridge, `claude_code` step, session cache + rebuild from Archive; `codex` adapter.
- P6 Docs everywhere, cloud bench run with screenshots, root CHANGELOG, PR merged when CI green.

## Coordination
- «Cervello offline» thread: touches Argus/Hermes and the chat queue; this work only guarantees a clear
  `llm_chain_exhausted` error from Oracle. Shared files (`Hestia-Oracle/app/main.py`, `hestia-oracle.md`) are edited
  in small hunks and merged from main before each push.
- «Email in push e modulo Spese»: Spese will just send its own `use_case` (§C) — nothing to wait for.
