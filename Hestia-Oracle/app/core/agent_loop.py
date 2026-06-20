"""AgentLoop — ReAct-style multi-turn tool execution loop.

Implements the structured agentic loop with visible thinking emission.

Pattern:
  User message + tool manifest
    → LLM: reason + optionally emit tool_call JSON
    → [emit thinking: reasoning]
    → [emit thinking: tool_call]
    → Tool execution (via Hub/module-tools)
    → [emit thinking: tool_result]
    → LLM: continue reasoning with tool result
    → … (up to max_turns, with early exit)
    → LLM: final answer

Each iteration is a separate LLM call. Tool results are injected as ephemeral
scratchpad messages — they are NOT persisted to Archive chat history.

A compact tool-call log is returned so the caller can emit a post-answer
summary card for the user.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterator

import requests

from core.services import prompt_config
from core.services import stream_emitter as _stream_emitter

logger = logging.getLogger(f"hestia_oracle.{__name__}")

MAX_AGENT_TURNS: int = int(os.getenv("ORACLE_MAX_AGENT_TURNS", "25"))
MAX_AGENT_TOKENS: int = int(os.getenv("ORACLE_MAX_AGENT_TOKENS", "0"))  # 0 = unlimited
TOOL_RESULT_MAX_CHARS: int = int(
    os.getenv("ORACLE_TOOL_RESULT_MAX_CHARS", "2000")
)
# Early exit: if the LLM hasn't called a tool in this many consecutive turns
# and we have already made progress, exit the loop.
_EARLY_EXIT_NO_TOOL_TURNS: int = int(
    os.getenv("ORACLE_AGENT_EARLY_EXIT_NO_TOOL_TURNS", "2")
)

# ── Token counting ───────────────────────────────────────────────────────────────
# Realistic default: 8 K fits comfortably in 16 GB VRAM (RTX 4080 Ti).
# Set ORACLE_CONTEXT_LENGTH higher (16 K, 32 K) if you're OK with RAM spill.
_CONTEXT_WINDOW: int = int(os.getenv("ORACLE_CONTEXT_LENGTH", "8192"))
# Compaction triggers when estimated tokens exceed this fraction of the window.
_COMPACT_THRESHOLD: float = float(os.getenv("ORACLE_COMPACT_THRESHOLD", "0.80"))
_MAX_PARALLEL_TOOLS: int = int(os.getenv("ORACLE_MAX_PARALLEL_TOOLS", "8"))

# Cached chars-per-token ratio per model name.  Populated lazily via
# Ollama /api/tokenize on first use; falls back to 3.0 if unreachable.
_token_ratio_cache: dict[str, float] = {}
_BENCHMARK_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "La volpe marrone veloce salta sopra il cane pigro. "
    "1234567890 " * 10
)


class TokenCounter:
    """Accurate token estimator backed by Ollama /api/tokenize with fallback."""

    def __init__(self, model: str = ""):
        self._model = model
        self._ratio = self._resolve_ratio(model)

    @staticmethod
    def _resolve_ratio(model: str) -> float:
        if model in _token_ratio_cache:
            return _token_ratio_cache[model]
        ollama_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434").rstrip("/")
        try:
            resp = requests.post(
                f"{ollama_url}/api/tokenize",
                json={"model": model, "prompt": _BENCHMARK_TEXT},
                timeout=5,
            )
            resp.raise_for_status()
            tokens = len((resp.json() or {}).get("tokens") or [])
            if tokens > 0:
                ratio = len(_BENCHMARK_TEXT) / tokens
                _token_ratio_cache[model] = ratio
                logger.debug(
                    "event=token_counter_calibrated model=%s chars=%d tokens=%d ratio=%.2f",
                    model, len(_BENCHMARK_TEXT), tokens, ratio,
                )
                return ratio
        except Exception as exc:
            logger.debug(
                "event=token_counter_calibration_failed model=%s error=%s — using heuristic",
                model, exc,
            )
        _token_ratio_cache[model] = 3.0
        return 3.0

    def estimate(self, text: str | None) -> int:
        if not text:
            return 0
        return max(1, int(len(text) / self._ratio))

    @property
    def context_window(self) -> int:
        return _CONTEXT_WINDOW

    @property
    def compact_threshold(self) -> float:
        return _COMPACT_THRESHOLD

    def context_pct(self, token_count: int) -> float:
        if _CONTEXT_WINDOW <= 0:
            return 0.0
        return (token_count / _CONTEXT_WINDOW) * 100

    @property
    def model(self) -> str:
        return self._model


# ── Tool definition ────────────────────────────────────────────────────────────


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict        # JSON Schema for LLM to fill
    # async-friendly: called with **params, returns (ok, result)
    handler: Callable


# ── Scratchpad message ─────────────────────────────────────────────────────────

@dataclass
class ScratchMessage:
    role: str   # "assistant" | "tool"
    content: str


# ── Agent loop ─────────────────────────────────────────────────────────────────

_TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>', re.DOTALL
)
_JSON_BLOCK_PATTERN = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL)


def _extract_tool_call(text: str) -> dict | None:
    """Parse the first <tool_call>...</tool_call> block from the LLM output.

    Returns a dict with 'name' and 'params', or None if no tool call found.
    """
    if not text:
        return None

    def _normalize_tool_call(candidate: dict) -> dict | None:
        if not isinstance(candidate, dict):
            return None

        # Native shape already normalized
        if isinstance(candidate.get("name"), str):
            return {
                "name": str(candidate.get("name") or "").strip(),
                "params": candidate.get("params") if isinstance(candidate.get("params"), dict) else {},
            }

        # OpenAI/Ollama-like function wrapper
        fn = candidate.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            raw_args = fn.get("arguments")
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {}
            return {
                "name": str(fn["name"]).strip(),
                "params": raw_args if isinstance(raw_args, dict) else {},
            }

        return None

    # 1. Try XML wrapping
    for match in _TOOL_CALL_PATTERN.finditer(text):
        block = match.group(1).strip()
        try:
            candidate = json.loads(block)
            normalized = _normalize_tool_call(candidate)
            if normalized:
                logger.trace("event=agent_loop_parsed_tool_call format=xml tool=%s", normalized["name"])
                return normalized
        except Exception:
            continue

    # 2. Try fenced JSON block
    for match in _JSON_BLOCK_PATTERN.finditer(text):
        block = match.group(1).strip()
        try:
            candidate = json.loads(block)
            normalized = _normalize_tool_call(candidate)
            if normalized:
                logger.trace("event=agent_loop_parsed_tool_call format=fenced_json tool=%s", normalized["name"])
                return normalized
        except Exception:
            continue

    # 3. Try plain JSON (first JSON object in text)
    plain_pattern = re.compile(r'\{[^{}]*"name"\s*:\s*"[^"]+"[^{}]*\}', re.DOTALL)
    for match in plain_pattern.finditer(text):
        try:
            candidate = json.loads(match.group())
            normalized = _normalize_tool_call(candidate)
            if normalized:
                logger.trace("event=agent_loop_parsed_tool_call format=plain_json tool=%s", normalized["name"])
                return normalized
        except Exception:
            continue

    return None


def _truncate_tool_result(result: str, max_chars: int = TOOL_RESULT_MAX_CHARS) -> str:
    if len(result) <= max_chars:
        return result
    return result[:max_chars] + f"\n[…result truncated at {max_chars} chars. Ask for more details if needed.]"


def run_agent_loop(
    user_message: str,
    history_text: str,
    preference_facts: list[str],
    tools: list[ToolDefinition],
    ask_fn: Callable[[str], str],
    ask_tools_fn: Callable[[str, list[dict]], dict] | None = None,
    stream_fn: Callable[[str], Iterator[str]] | None = None,
    client_instructions: str | None = None,
    conversation_style: str = "",
    max_turns: int | None = None,
    on_thinking: Callable[[str], None] | None = None,
    action_intent: bool = False,
    compact_fn: Callable[[], str | None] | None = None,
) -> tuple[str, list[str], list[dict]]:
    """Run the ReAct agent loop.

    OpenClaw pattern: *compact_fn* is called before each turn when the
    estimated token count exceeds the compaction threshold.  It should
    return the new compacted history text, or None if no change.
    """
    resolved_max_turns = max_turns if max_turns is not None else MAX_AGENT_TURNS
    tool_map = {t.name: t for t in tools}
    tool_names = sorted(tool_map.keys())

    # ── Token counter (model-aware, Ollama-calibrated) ───────────────────────
    _counter = TokenCounter()

    # ── TRACE: entry ──────────────────────────────────────────────────────────
    _est_tokens = _counter.estimate
    logger.trace("event=agent_loop_entry user_msg_len=%d history_len=%d pref_count=%d "
                 "tool_count=%d tools=%s action_intent=%s max_turns=%d has_stream=%s "
                 "has_native_tools=%s context_window=%d",
                 len(user_message or ""), len(history_text or ""), len(preference_facts),
                 len(tools), tool_names, action_intent, resolved_max_turns,
                 stream_fn is not None, ask_tools_fn is not None,
                 _counter.context_window)

    # Build tool manifest JSON for LLM
    tools_manifest = [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in tools
    ]
    tools_json = json.dumps(tools_manifest, ensure_ascii=False, indent=2)
    logger.trace("event=agent_loop_tools_manifest_json_len=%d", len(tools_json))

    # When native tool calling is available, the full JSON schemas are sent via
    # the Ollama `tools` parameter.  Including them again in the text prompt
    # bloats it to 40KB+ and buries the user's message.  Use a compact name-only
    # list in the text prompt — the LLM gets full schemas from native tools.
    _has_native = ask_tools_fn is not None
    if _has_native:
        _compact_tools = "\n".join(
            f"- {t.name}: {t.description[:120]}" for t in tools
        )
        system_prompt = prompt_config.prompt(
            "agent_loop_system_preamble_compact",
            tools_list=_compact_tools,
        )
    else:
        system_prompt = prompt_config.prompt(
            "agent_loop_system_preamble",
            tools_json=tools_json,
        )
    logger.trace("event=agent_loop_system_preamble_len=%d native_tools=%s",
                 len(system_prompt), _has_native)

    if preference_facts:
        # Cap at 10 most recent — 50 preferences drown the user's message
        _capped = preference_facts[:10]
        pref_block = "\n".join(f"- {fact}" for fact in _capped)
        if len(preference_facts) > 10:
            pref_block += f"\n- … and {len(preference_facts) - 10} more saved preferences"
        system_prompt += prompt_config.optional_section(
            "ACTIVE USER PREFERENCES", pref_block)
        logger.trace("event=agent_loop_preferences_injected count=%d capped=%d",
                     len(preference_facts), len(_capped))

    if conversation_style:
        system_prompt += f"\n\n{conversation_style}"
        logger.trace("event=agent_loop_conversation_style_injected len=%d", len(conversation_style))

    if action_intent:
        system_prompt += prompt_config.optional_section(
            "ACTION INTENT",
            "The user appears to want a state-changing action. Prioritise calling the "
            "appropriate tool over giving a text-only answer. If no matching tool "
            "exists, explain clearly that the action cannot be performed.",
        )
        logger.trace("event=agent_loop_action_intent_injected")

    if client_instructions:
        system_prompt += prompt_config.optional_section(
            "CLIENT INSTRUCTIONS", client_instructions)
        logger.trace("event=agent_loop_client_instructions_injected len=%d", len(client_instructions or ""))

    # Scratchpad: ephemeral tool-call/result messages for this session turn only
    scratchpad: list[ScratchMessage] = []
    # Tool-call log for post-answer summary
    tool_log: list[dict] = []
    # Track consecutive turns without tool calls for early exit
    _consecutive_no_tool: int = 0

    def _build_prompt(is_final: bool = False) -> str:
        dynamic_parts: list[str] = []
        if history_text:
            dynamic_parts.append(f"CONVERSATION HISTORY:\n{history_text}")
        dynamic_parts.append(f"USER: {user_message}")
        for msg in scratchpad:
            dynamic_parts.append(f"[{msg.role.upper()}]: {msg.content}")
        if is_final:
            dynamic_parts.append(
                "Now provide your final answer to the user (no tool_call blocks):")
        result = prompt_config.compose_with_dynamic_boundary(
            static_sections=[system_prompt],
            dynamic_sections=dynamic_parts,
        )
        return result

    final_answer = ""
    final_tokens: list[str] = []
    _cumulative_tokens: int = 0  # Claude Agent SDK pattern: budget tracking

    for turn in range(resolved_max_turns):
        is_last_turn = (turn == resolved_max_turns - 1)

        # ── OpenClaw pattern: auto-trigger compaction when threshold exceeded
        if compact_fn is not None and turn > 0:
            _est_prompt = _counter.estimate(
                system_prompt + (history_text or "") + (user_message or ""))
            if _counter.context_pct(_est_prompt) >= (_counter.compact_threshold * 100):
                logger.debug(
                    "event=compaction_auto_trigger turn=%d est_tokens=%d threshold_pct=%.0f",
                    turn, _est_prompt, _counter.compact_threshold * 100,
                )
                _compacted = compact_fn()
                if _compacted is not None:
                    history_text = _compacted

        prompt = _build_prompt(is_final=is_last_turn)

        _prompt_chars = len(prompt)
        _prompt_tokens_est = _est_tokens(prompt)
        _cumulative_tokens += _prompt_tokens_est

        # ── Claude Agent SDK pattern: budget check ─────────────────────────
        if MAX_AGENT_TOKENS > 0 and _cumulative_tokens > MAX_AGENT_TOKENS:
            logger.warning(
                "event=agent_loop_budget_exceeded turn=%d cumulative_tokens=%d "
                "budget=%d — exiting loop",
                turn, _cumulative_tokens, MAX_AGENT_TOKENS,
            )
            final_answer = (
                "⚠️ Ho raggiunto il limite di contesto per questa richiesta. "
                "Prova a riformulare la domanda in modo più specifico."
            )
            break
        _ctx_pct = _counter.context_pct(_prompt_tokens_est)
        _ctx_window = _counter.context_window

        # ── TRACE: prompt breakdown (Plan 4d) ──────────────────────────────
        _sys_chars = len(system_prompt)
        _hist_chars = len(history_text or "")
        _user_chars = len(user_message or "")
        _scratch_chars = sum(len(msg.content) for msg in scratchpad)
        _tools_chars = len(tools_json)
        logger.trace(
            "event=prompt_breakdown turn=%d "
            "system_preamble=%d history_chars=%d user_chars=%d "
            "scratchpad_chars=%d tools_chars=%d "
            "total_chars=%d total_tokens=%d context_pct=%.1f%%",
            turn,
            _sys_chars, _hist_chars, _user_chars,
            _scratch_chars, _tools_chars,
            _prompt_chars, _prompt_tokens_est, _ctx_pct,
        )
        logger.trace("event=agent_loop_turn_start turn=%d is_last=%s prompt_chars=%d "
                     "prompt_tokens_est=%d context_pct=%.1f%% ctx_remaining_est=%d "
                     "scratchpad_msgs=%d tools_avail=%d",
                     turn, is_last_turn, _prompt_chars, _prompt_tokens_est, _ctx_pct,
                     _ctx_window - _prompt_tokens_est, len(scratchpad), len(tools_manifest))

        t_turn_start = time.perf_counter()

        raw_response = ""
        tool_call = None
        tool_calls_list: list[dict] = []
        try:
            if ask_tools_fn is not None and not is_last_turn:
                logger.trace("event=agent_loop_calling_native_tools turn=%d tools_count=%d",
                            turn, len(tools_manifest))
                decision = ask_tools_fn(prompt, tools_manifest) or {}
                logger.trace("event=agent_loop_native_tools_response turn=%d "
                            "has_tool_call=%s text_len=%d reasoning_len=%d",
                            turn,
                            bool((decision or {}).get("tool_call")),
                            len(str((decision or {}).get("text") or "")),
                            len(str((decision or {}).get("reasoning_content") or "")))

                # ── Emit reasoning_content as thinking event ───────────────
                _reasoning = str(
                    (decision or {}).get("reasoning_content") or "").strip()
                if _reasoning and on_thinking:
                    on_thinking(_stream_emitter.emit_thinking(
                        action="reasoning",
                        content=_reasoning,
                        turn=turn,
                    ))

                # ── Multi-tool support: check tool_calls list first ──────────
                tool_calls_list: list[dict] = []
                if isinstance(decision, dict):
                    _tcl = decision.get("tool_calls")
                    if isinstance(_tcl, list) and _tcl:
                        tool_calls_list = [
                            {"name": str(t.get("name", "")).strip(),
                             "params": t.get("params") or {}}
                            for t in _tcl
                            if isinstance(t, dict) and t.get("name")
                        ]
                        if tool_calls_list:
                            logger.trace(
                                "event=agent_loop_multi_tool_calls turn=%d count=%d tools=%s",
                                turn, len(tool_calls_list),
                                [t["name"] for t in tool_calls_list])

                # Single-tool fallback (backward compat)
                if not tool_calls_list:
                    maybe_tool = decision.get("tool_call") if isinstance(
                        decision, dict) else None
                    if isinstance(maybe_tool, dict) and maybe_tool.get("name"):
                        tool_calls_list = [{
                            "name": str(maybe_tool.get("name") or "").strip(),
                            "params": maybe_tool.get("params") or {},
                        }]

                if tool_calls_list:
                    tool_call = tool_calls_list[0]  # for logging compat
                    raw_response = ""
                    logger.trace("event=agent_loop_native_tool_call turn=%d tool=%s params=%s",
                                turn, tool_call["name"],
                                json.dumps(tool_call["params"], ensure_ascii=False)[:200])
                else:
                    raw_response = str(
                        (decision or {}).get("text") or "").strip()
                    logger.trace("event=agent_loop_native_text_response turn=%d text=%s",
                                turn, json.dumps(raw_response[:200], ensure_ascii=False))
                    # Some providers return tool intents as plain text blocks.
                    # Parse XML fallback here before falling through to final answer.
                    if raw_response:
                        _fallback_tc = _extract_tool_call(raw_response)
                        if _fallback_tc:
                            tool_calls_list = [_fallback_tc]
                            tool_call = _fallback_tc
                            logger.trace("event=agent_loop_fallback_parse_tool turn=%d tool=%s",
                                        turn, _fallback_tc["name"])

                if tool_call is None:
                    logger.info(
                        "event=agent_loop_tool_decision_none turn=%s tools=%s response_len=%s",
                        turn, len(tools_manifest), len(raw_response or ""),
                    )
                    logger.trace(
                        "event=agent_loop_raw_response turn=%s response=%s",
                        turn,
                        (raw_response if len(raw_response or "") <= 2000
                         else (raw_response or "")[:2000] + "..."),
                    )

            if not raw_response and tool_call is None:
                logger.trace("event=agent_loop_fallback_ask turn=%d (no native tool call, using plain ask)",
                            turn)
                raw_response = ask_fn(prompt)
                logger.trace("event=agent_loop_fallback_ask_response turn=%d len=%d",
                            turn, len(raw_response or ""))
                _fallback_tc = _extract_tool_call(
                    raw_response) if not is_last_turn else None
                if _fallback_tc:
                    tool_call = _fallback_tc
                    tool_calls_list = [_fallback_tc]
                    logger.trace("event=agent_loop_fallback_parse_tool turn=%d tool=%s",
                                turn, tool_call["name"])
                else:
                    logger.trace("event=agent_loop_fallback_no_tool turn=%d text_preview=%s",
                                turn, (raw_response or "")[:200])
        except Exception as exc:
            logger.error(
                "event=agent_loop_llm_call_failed Agent loop LLM call failed at turn %d: %s",
                turn, exc, exc_info=True)
            final_answer = "⚠️ Il modello non è disponibile. Riprova tra poco."
            break

        if tool_calls_list:
            # ── Parallel tool execution ─────────────────────────────────────
            # LangChain RunnableParallel pattern: each branch receives the same
            # input, errors are isolated per-branch, results collected in a
            # dict keyed by tool name for clear LLM association.
            import concurrent.futures

            def _exec_one(tc: dict) -> dict:
                _tn = tc.get("name", "")
                _tp = tc.get("params") or {}
                _td = tool_map.get(_tn)
                if _td is None:
                    return {"name": _tn, "ok": False,
                            "result": f"Unknown tool: {_tn}",
                            "duration_ms": 0, "error": True}
                _t0 = time.perf_counter()
                try:
                    _ok, _result = _td.handler(**_tp)
                except Exception as _exc:
                    _ok, _result = False, str(_exc)
                _dur = int((time.perf_counter() - _t0) * 1000)
                return {"name": _tn, "ok": _ok, "result": _result,
                        "duration_ms": _dur}

            # Emit thinking: tool_call for each tool about to execute
            if on_thinking:
                for tc in tool_calls_list:
                    on_thinking(_stream_emitter.emit_thinking(
                        action="tool_call",
                        content=f"Calling {tc.get('name', '?')}...",
                        turn=turn,
                        tool_name=tc.get("name", ""),
                    ))

            if len(tool_calls_list) == 1:
                _results_list = [_exec_one(tool_calls_list[0])]
            else:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(len(tool_calls_list), _MAX_PARALLEL_TOOLS)
                ) as executor:
                    _futures = {
                        executor.submit(_exec_one, tc): tc["name"]
                        for tc in tool_calls_list
                    }
                    _results_list = []
                    for f in concurrent.futures.as_completed(_futures):
                        _results_list.append(f.result())

            # ── LangChain pattern: collect results in dict keyed by tool name
            _results_dict: dict[str, dict] = {}
            for r in _results_list:
                _results_dict[r["name"]] = r

            # Emit thinking + scratchpad for each result
            for r in _results_list:
                tn = r["name"]
                ok = r["ok"]
                result_raw = r["result"]
                dur = r.get("duration_ms", 0)
                result_str = str(result_raw) if result_raw is not None else ""
                chars = len(result_str)

                # Truncate for scratchpad
                result_trunc = _truncate_tool_result(result_str)
                result_count = 1
                if isinstance(result_raw, list):
                    result_count = len(result_raw)

                logger.info(
                    "event=agent_loop_turn_tool_ok turn=%d tool=%s ok=%s "
                    "duration_ms=%d result_chars=%d result_count=%d",
                    turn, tn, ok, dur, chars, result_count,
                )

                # ── Emit thinking: tool result ────────────────────────────
                if on_thinking:
                    result_preview = result_trunc if len(
                        result_trunc) <= 300 else result_trunc[:300] + "..."
                    on_thinking(_stream_emitter.emit_thinking(
                        action="tool_result",
                        content=result_preview,
                        turn=turn,
                        tool_name=tn,
                        metadata={
                            "ok": ok,
                            "duration_ms": dur,
                            "result_count": result_count,
                        },
                    ))

                # Format scratchpad entry
                _tool_scratch = f"[{tn}] → {'✅' if ok else '❌'} {result_trunc}"
                scratchpad.append(ScratchMessage("tool", _tool_scratch))

                # Log for post-answer summary
                tool_log.append({
                    "tool": tn,
                    "ok": ok,
                    "result_preview": result_trunc[:300],
                    "turn": turn,
                })

            # ── LangChain pattern: also inject results as dict for LLM ─────
            # The scratchpad has individual [tool] lines.  Add a compact
            # dict summary so the LLM can reference results by tool name.
            if len(_results_dict) > 1:
                _compact_dict = json.dumps(
                    {name: f"{'✅' if d['ok'] else '❌'} {_truncate_tool_result(str(d['result']))[:200]}"
                     for name, d in _results_dict.items()},
                    ensure_ascii=False, indent=2,
                )
                scratchpad.append(ScratchMessage(
                    "tool", f"[RESULTS_DICT]\n{_compact_dict}"))

            _consecutive_no_tool = 0
            logger.trace("event=agent_loop_tool_done_continuing turn=%d "
                         "parallel_count=%d scratchpad_size=%d",
                         turn, len(_results_list), len(scratchpad))
            continue

        else:
            # ── Text response (no tool call) ─────────────────────────────
            _consecutive_no_tool += 1
            clean = _TOOL_CALL_PATTERN.sub("", raw_response).strip()

            logger.trace("event=agent_loop_text_response turn=%d consecutive_no_tool=%d "
                        "has_tool_log=%s raw_len=%d clean_len=%d content=%s",
                        turn, _consecutive_no_tool, bool(tool_log),
                        len(raw_response or ""), len(clean or ""),
                        json.dumps(clean[:120], ensure_ascii=False))

            # After tools have been called, the next text response means the
            # model is done reasoning.  Fall through to streaming final-prompt
            # path so the model formats tool results into a user-facing answer.
            if tool_log:
                logger.info(
                    "event=agent_loop_final_answer_after_tools turn=%s tool_calls=%s "
                    "text_preview=%s",
                    turn, len(tool_log), clean[:100],
                )
                # fall through to streaming path below (don't break yet)

            # Early exit when NO tools called yet: require consecutive
            # no-tool turns before giving up.
            elif _consecutive_no_tool >= _EARLY_EXIT_NO_TOOL_TURNS and turn > 0:
                logger.info(
                    "event=agent_loop_early_exit_no_tools turn=%s consecutive_no_tool=%s",
                    turn, _consecutive_no_tool,
                )
                final_answer = clean
                logger.trace("event=agent_loop_final_answer early_exit_no_tools=%s",
                            json.dumps(final_answer[:120], ensure_ascii=False))
                break

            if turn == 0 and tools_manifest:
                logger.info(
                    "event=agent_loop_no_tool_call_first_turn tools=%s response_preview=%s",
                    len(tools_manifest), clean[:200],
                )

            # ── Streaming final answer ────────────────────────────────────
            # Only regenerate via streaming when tools were called (the LLM
            # needs to format tool results) or when multiple turns happened.
            # On turn 0 with no tools, the text response IS the final answer.
            if stream_fn is not None and turn < resolved_max_turns - 1:
                if tool_log:
                    final_prompt = _build_prompt(is_final=True)
                    logger.trace("event=agent_loop_streaming_final turn=%d final_prompt_len=%d "
                                "scratchpad_msgs=%d tool_log_count=%d",
                                turn, len(final_prompt), len(scratchpad), len(tool_log))
                    try:
                        for token in stream_fn(final_prompt):
                            final_tokens.append(token)
                        final_answer = "".join(final_tokens)
                        logger.trace("event=agent_loop_streaming_done turn=%d token_count=%d "
                                    "final_len=%d answer_preview=%s",
                                    turn, len(final_tokens), len(final_answer),
                                    json.dumps(final_answer[:120], ensure_ascii=False))
                    except Exception as exc:
                        logger.error("event=agent_loop_streaming_failed turn=%d error=%s",
                                    turn, exc, exc_info=True)
                        final_answer = clean
                else:
                    final_answer = clean
                    logger.trace("event=agent_loop_final_answer_no_stream turn=%d len=%d",
                                turn, len(final_answer or ""))
                break

            final_answer = clean
            logger.trace("event=agent_loop_final_answer no_stream=%s",
                        json.dumps(final_answer[:120], ensure_ascii=False))
            break

    # ── Per-tool call count summary ─────────────────────────────────────────
    _tool_counts = Counter(t["tool"] for t in tool_log)
    _tool_breakdown = ", ".join(
        f"{name}={count}" for name, count in _tool_counts.items()
    ) if _tool_counts else "(none)"

    logger.info(
        "event=agent_loop_completed_turns_final_len Agent loop completed | "
        "turns=%s final_len=%s tools_called=%s tool_breakdown=[%s]",
        len(tool_log) + (1 if final_answer else 0),
        len(final_answer),
        len(tool_log),
        _tool_breakdown,
    )
    logger.trace("event=agent_loop_exit final_answer=%s tool_log_count=%d token_count=%d",
                json.dumps(final_answer[:300], ensure_ascii=False),
                len(tool_log), len(final_tokens))
    return final_answer, final_tokens, tool_log
