# SPEC — Claude Haiku in Oracle (API key + subscription) and the provider layer

| Version | Source | Status |
|---|---|---|
| 1.4 | user via project thread "Usare Claude Haiku per la chat di Oracle" (2026-10-10) | done (user test pending) |

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

## 3. Configuration (rebased on settings P1-P5 on main)
- Model choice per use case = existing live Themis keys `oracle.models.<uc>.{provider,model,fallback_provider,
  fallback_model,thinking}` (`core/services/oracle_settings.py`). New provider types only add values to
  `oracle_settings.PROVIDERS`: `anthropic` "Claude (chiave API)", `claude_cli` "Claude (abbonamento)", plus
  their `list_models()` behind `GET /api/llm/models?provider=`.
- Secrets/infra stay in env: `ORACLE_ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`. A type is offered only when
  its key is set. `load_llm_config()` (new, `agents/llm_config.py`) is the single place reading these
  infra env vars and hands each provider its config dict.
- Use-case `thinking` setting keeps its meaning: `false` = never think; `auto`/`true` = level from the chat mode
  (quick/auto/thinking → off/low/high effort for Claude). No new env vars; any new tunable goes through
  `settings_client.setting(...)` as `oracle.provider.<type>.*` (none planned in v1).
- Optional preset "Claude" (all chat use cases on Haiku) — only if the user wants it.

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

## 6. Implementation notes (v1.4)
- `ollama`/`gemini` stay inline in `UniversalAgent` for now and the basic `openai` type is not built here: the
  local-context thread is rewriting the Ollama calls and adds `openai`; both plug into `agents/providers`
  (`PROVIDER_TYPES` registry, `LLMProvider` base) the same way `anthropic`/`claude_cli` do.
- Forge's runner strips only `ORACLE_ANTHROPIC_API_KEY` (an explicit `ANTHROPIC_API_KEY` stays a valid Forge
  auth choice); the chat `claude_cli` provider strips both.
- No preset added (user choice). Claude types are offered in the provider enum only when configured (at startup).
