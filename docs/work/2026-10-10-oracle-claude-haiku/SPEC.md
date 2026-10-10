# SPEC — Claude Haiku in Oracle (API key + subscription) and the provider layer

| Version | Source | Status |
|---|---|---|
| 1.2 | user via project thread "Usare Claude Haiku per la chat di Oracle" (2026-10-10) | waiting: user finishes central settings first |

## 1. Goal
Let Oracle's normal chat run on Claude Haiku, alongside Gemini and Ollama (not replacing them), in two ways:
- **`anthropic`** — Anthropic API key (`ORACLE_ANTHROPIC_API_KEY`, pay per use, ~$0.001 per chat turn on
  Haiku 5.5). Clean, fast, explicitly allowed for an own app.
- **`claude_cli`** — the user's Claude subscription through the official `claude` CLI (same
  `CLAUDE_CODE_OAUTH_TOKEN` Forge uses). No extra cost, but slower (one CLI start per call), shares the
  subscription usage limits with Forge, and it is a grey area of Anthropic's terms (subscription login is meant
  for "ordinary use of Claude Code"; https://code.claude.com/docs/en/legal-and-compliance). The user chose to
  have it as an option knowing this.

Both are provider types of the central-settings provider layer (§3.9 of
`docs/work/2026-10-10-central-settings/SPEC.md`); this task owns that layer's `UniversalAgent` dispatch
refactor and `load_llm_config()`.

## 2. Scope
- `agents/providers/`: base class `LLMProvider` (`TYPE`, `CONFIG_FIELDS` in §3.1 format, `CAPABILITIES`,
  `list_models()`, config dict in, never `os.getenv`) + types `ollama`, `gemini` (moved as-is from
  `UniversalAgent`), `openai` (basic OpenAI-compatible: chat, tools, stream, `/v1/models`; the
  local-context thread extends it), `anthropic`, `claude_cli`.
- `agents/llm_config.py`: `load_llm_config()` = the only env reader → `{providers: {type: config}, usecases: {...}}`; provider configs from env (infra), mappings from Themis later.
- `UniversalAgent` keeps its public API (`provider`, `model_name`, `thinking`, `ask`, `ask_with_tools`,
  `ask_stream`, `ask_with_attachment`, `embed`, `complete`) and dispatches to the provider type named by `provider`. Existing Gemini→Ollama auto-fallback kept.
- Thinking per mode: `thinking` becomes a level, `False` | `True`/`"normal"` | `"deep"` (Oracle mode quick |
  auto | thinking). Ollama keeps the bool `think`. `anthropic` maps it with config `thinking_by_mode`
  (`{"fast":"off","normal":"low","deep":"high"}` → off = thinking disabled + effort low, else adaptive thinking
  with that effort, summarized reasoning returned as `reasoning_content`). No extra CoT prompt for Claude.
- Oracle orchestration unchanged: classifier → domains → only those tools (`_build_domain_tools`), skills,
  Athena hints. `anthropic` gets the filtered tools natively (`input_schema`), `claude_cli` gets them as text
  with the `<tool_call>{json}</tool_call>` format that `agent_loop._extract_tool_call` already parses; Claude
  Code's own tools are disabled (`--tools ""`) and no MCP is loaded (`--strict-mcp-config`).
- Prompt caching (`anthropic`): system prompt and tool list marked `cache_control`; the agent-loop prompt is
  split at `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` so its static part is a cached block.
- Forge safety: `claude_code_runner` strips `ANTHROPIC_API_KEY` / `ORACLE_ANTHROPIC_API_KEY` from the CLI env
  so Forge always stays on the subscription.

Out of scope: settings UI / Themis (central-settings thread), Ollama num_ctx/keep_alive and llama-server
specifics (local-context thread), assistant presence (own thread), embeddings on Anthropic (no such API).

## 3. Configuration
Aligned with central-settings SPEC v2.0: there is no provider-instance list. Endpoints and key names are
infrastructure and stay in `.env` permanently (`OLLAMA_URL`, `ORACLE_OPENAI_BASE_URL`, `GEMINI_API_KEY`,
`ORACLE_ANTHROPIC_API_KEY`; `claude_cli` uses the existing `CLAUDE_CODE_OAUTH_TOKEN`). A provider type is
available when it is implemented and its endpoint/key is set. `load_llm_config()` is the single env reader:
it builds one config per available type and the use-case mapping `{provider type, model, fallback, options}`
(from Themis settings once they exist). Non-address tunables (e.g. `thinking_by_mode`, `prompt_cache`) are
type `CONFIG_FIELDS` defaults, later settings `oracle.provider.<type>.*`. No new tunable env vars.
Oracle contains no settings or approval logic (settings tools live in Themis via Hestia-MCP).

## 4. Acceptance criteria
- With no new env, Oracle behaves exactly as before (ollama/gemini paths moved, not changed).
- Use case `generic` mapped to provider `anthropic` + key → chat quick/auto/thinking work, tools called natively,
  reasoning shown, cache read tokens logged (`event=anthropic_usage`).
- Use case `generic` mapped to provider `claude_cli` → chat works through the CLI, tools via text tool calls.
- Forge's `claude` never sees an Anthropic API key.
- Provider classes never call `os.getenv`; `load_llm_config()` is the single env reader for LLM providers.
- Docs: `hestia-oracle.md`, `.env.example`, compose comments.

## 5. Design decisions
- Official `anthropic` Python SDK (no OpenAI shim). Default model `claude-haiku-5-5`.
- `claude_cli` reuses Oracle's own agent loop (text tool calls) instead of an MCP bridge: keeps the
  domain tool filtering identical for every provider and needs no new server. (Thread reply mentioned MCP;
  changed because the loop already parses text tool calls.)
- Tests: not run by Claude (user rule); syntax/import checks only.
