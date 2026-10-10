# SPEC — Oracle on local models: real context window, cache reuse, faster runtimes

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User request · channel: external chat (Claude Code cloud session, project thread) · 2026-10-10 |
| **Status** | Draft — waiting for user approval; no code yet |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the thread): when working with local Ollama, can Oracle be
improved? Are there better runtimes/services that use context better or are faster — not to replace Ollama,
but as an extra option to try? Claude and Codex use caching and compaction to reduce context use: can we do
something similar for Oracle, following what the big providers publicly do? Oracle should already measure
context and compact it. The user chose "dossier only" for now: plan first, code later.

---

## 1. Current state (read on 2026-10-10, `Hestia-Oracle/app`)

- **Context size is only estimated, never sent.** `ORACLE_CONTEXT_LENGTH` (default 8192,
  `core/agent_loop.py:54`) drives `TokenCounter`, `/api/chat/context` and auto-compaction at
  `ORACLE_COMPACT_THRESHOLD` (0.80). But the Ollama payloads in `agents/universal_agent.py`
  (`_ask_once` ~l.128, `_ask_with_tools_ollama_native` ~l.237, stream, vision) pass **no `options.num_ctx`**.
  Ollama then uses its server default (version/VRAM dependent, often 4096) and **silently truncates the
  start of the prompt** (= the system prompt) when it overflows. Our 8K budget is fiction unless the host
  sets `OLLAMA_CONTEXT_LENGTH`.
- **No `keep_alive`.** The model unloads after Ollama's default 5 min idle → cold load (seconds to tens of
  seconds) on the first message after a pause.
- **Prompt shape.** Every call is stateless: `/api/generate` with `role_prompt + "User: …"`, or `/api/chat`
  with a short fixed system + the whole composed prompt as one user message. `prompt_config.compose_with_dynamic_boundary`
  already splits static (system) and dynamic (history, user, scratchpad) — good base for prefix reuse.
- **Several agents share one model.** Per turn: classifier → agent loop (N turns) → background memory
  extraction, control extraction, compaction check. Each uses a different system prompt; with one Ollama
  slot (`OLLAMA_NUM_PARALLEL=1`) each call evicts the KV cache of the previous one.
- **History** = last `ORACLE_HISTORY_LIMIT` (6) messages, rolling; compaction = LLM summary with protected
  prefixes (`[PREFERENCE]`, `[SUBSCRIPTION]`, …) kept verbatim (`core/services/context_builder.py`),
  triggered at `ORACLE_COMPACT_TRIGGER_MSGS` (20) or by the 80 % threshold inside the agent loop.
- **Tool results** in the agent-loop scratchpad are capped at `ORACLE_TOOL_RESULT_MAX_CHARS` (2000) each
  but stay in full for every later loop turn.
- **No cache telemetry.** Ollama returns `prompt_eval_count` (tokens actually evaluated, i.e. NOT served
  from cache), `prompt_eval_duration`, `load_duration`, `eval_count/eval_duration`; we discard them.
- `llm_gateway.py` already has OpenAI-compatible **profiles** (`local`, `cloud`, `ORACLE_LLM_PROFILE_<NAME>_*`)
  for Forge's "local/cloud model" engine — but the chat path (`UniversalAgent`) only knows `ollama` and `gemini`.

## 2. What the big providers do (public docs) → our local equivalent

| Technique | Who | Local translation |
|---|---|---|
| Prompt/prefix caching: stable prefix first, volatile last; cache hits are cheap & fast | Anthropic `cache_control`, OpenAI automatic ≥1024 tok, Gemini implicit/explicit cache | Ollama/llama.cpp reuse the KV cache of the **byte-identical prefix** of the previous request in the same slot. Same rule: static first, append-only after |
| Auto-compaction near the limit (summary + recent turns) | Claude Code, Codex | Already have it; make it block-wise so the prefix stays stable between compactions |
| Context editing: clear old tool results, keep a stub | Anthropic API context management | Stub old scratchpad tool results in the agent loop — no LLM call |
| Memory outside the window, loaded on demand | Claude memory tool / CLAUDE.md, ChatGPT memory | Already have Archive memory + RAG; keep injecting only on demand |
| Sub-agents with isolated context | Claude Code, Codex | Classifier/extractors already separate; give them their own slot or smaller model |
| Speculative decoding, paged/radix KV cache | serving stacks (vLLM, SGLang, llama.cpp) | Optional alternative runtime (§3 D) |

## 3. Scope — four phases, each shippable alone

**A. Real context + warm model (bug fix, small)**
- Every Ollama call sends `options.num_ctx = ORACLE_CONTEXT_LENGTH` and `keep_alive = ORACLE_OLLAMA_KEEP_ALIVE`
  (default `30m`). **Same `num_ctx` on every call** — a different value forces Ollama to reload the model.
- Startup log `event=ollama_context_config num_ctx=… keep_alive=…`; warn if Ollama `/api/ps` reports a
  smaller loaded context.
- Docs/`.env.example`: recommend host env `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`
  (≈ half KV memory → more context in the same VRAM), optional `OLLAMA_NUM_PARALLEL=2`.

**B. Measure (small)**
- Read `prompt_eval_count`, `prompt_eval_duration`, `load_duration`, `eval_count`, `eval_duration` from
  every Ollama response → log `event=ollama_call_stats agent=<classifier|chat|tools|memory|compact> prompt_tokens=…
  evaluated_tokens=… cache_hit_pct=… load_ms=… tok_per_s=…`.
- Keep a small rolling aggregate per agent; expose it in `/api/chat/context` (and `oracle.context_stats` MCP tool)
  so the WebUI context gauge can show real numbers instead of estimates. Real `prompt_eval_count` also
  replaces the chars/token heuristic when available.

**C. Cache-friendly prompts + context editing (medium)**
- Audit every prompt builder: nothing volatile (date/time, ids, counters, random order of tools/domains)
  in the static part; tools manifest sorted deterministically.
- History block append-only between compactions (no rolling 6-message window that shifts every turn):
  keep `summary + messages since last compaction`, compact in one block when the threshold is hit.
- Agent loop: after K loop turns (default 2), replace older tool results with a one-line stub
  (`[tool X → 14 rows, shown earlier]`) — Anthropic-style context editing, no LLM.
- Classifier/extractors: option to run on a dedicated small model (`MODEL_USECASE_*` already exists) so
  they stop evicting the chat model's cache; document `OLLAMA_NUM_PARALLEL` trade-off (VRAM × slots).

**D. Optional alternative runtime (larger, coordinated)**
- New `UniversalAgent` provider **`openai`** (OpenAI-compatible `/v1/chat/completions` with tools +
  streaming), configured per use-case like Ollama/Gemini. One implementation serves:
  - **llama.cpp `llama-server`** (recommended first try): same GGUF files as Ollama, `--cache-reuse`,
    `-fa`, KV-cache quantisation, speculative decoding with a small draft model (often 1.5–2× faster),
    `/slots` save/restore of a warm prefix.
  - **vLLM** (Linux/WSL, model fully in VRAM): automatic prefix caching, paged attention, best with parallel calls.
  - **LM Studio**, and cloud OpenAI-compatible endpoints.
- Ollama stays the default; the new runtime is an extra option selectable per use-case.
- **Shared with the "Claude Haiku in Oracle" thread**: Haiku needs a new chat provider too. Build one
  provider layer, not two. Owner of `universal_agent.py` changes to be agreed between the two threads.

## 4. Settings (consistency with `docs/work/2026-10-10-central-settings/`)

All new knobs are declared as Oracle settings in the central registry once it exists (until then: env):
`ORACLE_CONTEXT_LENGTH`, `ORACLE_OLLAMA_KEEP_ALIVE`, `ORACLE_TOOL_RESULT_STUB_AFTER_TURNS`, per-use-case
provider/model/base_url. Changing `num_ctx` is a "reload model" setting (state visible to all clients).
Host-side Ollama env (`OLLAMA_*`) is infrastructure → documented, not managed.

## 5. Acceptance criteria

- A: Ollama logs/`/api/ps` show the loaded context = `ORACLE_CONTEXT_LENGTH`; no reload between calls;
  first message after 10 min idle has `load_duration` ≈ 0.
- B: every Ollama call logs `ollama_call_stats`; `/api/chat/context` returns real per-agent averages.
- C: on a multi-turn chat, `cache_hit_pct` of the chat agent rises measurably vs. the B baseline
  (target: > 70 % of prompt tokens served from cache from turn 2 on); answers unchanged in the format tests.
- D: setting one use-case to provider `openai` + a `llama-server` URL works for chat, tools and streaming;
  Ollama path unchanged.
- Tests (unit/format, mocked HTTP) for payload options, stats parsing, stub logic, provider; docs updated
  (`Hestia-Oracle/hestia-oracle.md`, `.env.example`, swagger for `/api/chat/context`).

## 6. Design decisions

- Fix A before anything else: every later optimisation is meaningless if the real window is smaller than we think.
- Measure (B) before optimising (C) or adding runtimes (D): numbers decide whether D is worth it.
- No new LLM client outside Oracle; the new provider lives in `UniversalAgent` (CLAUDE.md rule).
- No new service/container in compose for llama.cpp/vLLM: the user runs it on the host like Ollama; Oracle only needs a URL.

## 7. Open points for the user

1. Approve the phase order A → B → C → D (or pick a subset).
2. Default `keep_alive`: `30m` (frees VRAM when idle) or `-1` (always loaded)?
3. Host GPU/OS for D: is WSL/Linux available (vLLM) or only Windows (llama-server)?
