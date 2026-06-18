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
from dataclasses import dataclass, field
from typing import Callable, Iterator

from core.services import prompt_config
from core.services import stream_emitter as _stream_emitter

logger = logging.getLogger(f"hestia_oracle.{__name__}")

MAX_AGENT_TURNS: int = int(os.getenv("ORACLE_MAX_AGENT_TURNS", "25"))
TOOL_RESULT_MAX_CHARS: int = int(
    os.getenv("ORACLE_TOOL_RESULT_MAX_CHARS", "2000")
)
# Early exit: if the LLM hasn't called a tool in this many consecutive turns
# and we have already made progress, exit the loop.
_EARLY_EXIT_NO_TOOL_TURNS: int = int(
    os.getenv("ORACLE_AGENT_EARLY_EXIT_NO_TOOL_TURNS", "2")
)

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
) -> tuple[str, list[str], list[dict]]:
    resolved_max_turns = max_turns if max_turns is not None else MAX_AGENT_TURNS
    tool_map = {t.name: t for t in tools}
    tool_names = sorted(tool_map.keys())

    # ── TRACE: entry ──────────────────────────────────────────────────────────
    # Rough token estimate: ~3 chars per token for mixed IT/EN + JSON
    _est_tokens = lambda s: int(len(s or "") / 3)
    logger.trace("event=agent_loop_entry user_msg_len=%d history_len=%d pref_count=%d "
                 "tool_count=%d tools=%s action_intent=%s max_turns=%d has_stream=%s "
                 "has_native_tools=%s",
                 len(user_message or ""), len(history_text or ""), len(preference_facts),
                 len(tools), tool_names, action_intent, resolved_max_turns,
                 stream_fn is not None, ask_tools_fn is not None)

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

    for turn in range(resolved_max_turns):
        is_last_turn = (turn == resolved_max_turns - 1)
        prompt = _build_prompt(is_final=is_last_turn)

        _prompt_chars = len(prompt)
        _prompt_tokens_est = _est_tokens(prompt)
        _ctx_pct = (_prompt_tokens_est / 256000) * 100  # Gemma 4 256K context
        logger.trace("event=agent_loop_turn_start turn=%d is_last=%s prompt_chars=%d "
                     "prompt_tokens_est=%d context_pct=%.1f%% ctx_remaining_est=%d "
                     "scratchpad_msgs=%d tools_avail=%d",
                     turn, is_last_turn, _prompt_chars, _prompt_tokens_est, _ctx_pct,
                     256000 - _prompt_tokens_est, len(scratchpad), len(tools_manifest))

        t_turn_start = time.perf_counter()

        raw_response = ""
        tool_call = None
        try:
            if ask_tools_fn is not None and not is_last_turn:
                logger.trace("event=agent_loop_calling_native_tools turn=%d tools_count=%d",
                            turn, len(tools_manifest))
                decision = ask_tools_fn(prompt, tools_manifest) or {}
                logger.trace("event=agent_loop_native_tools_response turn=%d "
                            "has_tool_call=%s text_len=%d",
                            turn,
                            bool((decision or {}).get("tool_call")),
                            len(str((decision or {}).get("text") or "")))

                maybe_tool = decision.get("tool_call") if isinstance(
                    decision, dict) else None
                if isinstance(maybe_tool, dict) and maybe_tool.get("name"):
                    tool_call = {
                        "name": str(maybe_tool.get("name") or "").strip(),
                        "params": maybe_tool.get("params") or {},
                    }
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
                        tool_call = _extract_tool_call(raw_response)
                        if tool_call:
                            logger.trace("event=agent_loop_fallback_parse_tool turn=%d tool=%s",
                                        turn, tool_call["name"])

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
                tool_call = _extract_tool_call(
                    raw_response) if not is_last_turn else None
                if tool_call:
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

        if tool_call:
            # ── Tool call turn ─────────────────────────────────────────────
            tool_name = tool_call.get("name", "")
            tool_params = tool_call.get("params") or {}

            logger.trace("event=agent_loop_executing_tool turn=%d tool=%s params_keys=%s",
                        turn, tool_name, list(tool_params.keys()))

            # Emit thinking: reasoning before tool call
            if on_thinking and raw_response:
                reasoning_preview = str(raw_response).strip()[:400]
                on_thinking(_stream_emitter.emit_thinking(
                    action="reasoning",
                    content=reasoning_preview,
                    turn=turn,
                    tool_name=tool_name,
                ))

            if raw_response:
                scratchpad.append(ScratchMessage("assistant", raw_response))

            # Emit thinking: tool call about to execute
            if on_thinking:
                on_thinking(_stream_emitter.emit_thinking(
                    action="tool_call",
                    content=f"Calling {tool_name}...",
                    turn=turn,
                    tool_name=tool_name,
                    metadata={"params_keys": list(tool_params.keys())},
                ))

            t_tool_start = time.perf_counter()
            tool_def = tool_map.get(tool_name)
            if not tool_def:
                tool_result = f"ERROR: Tool '{tool_name}' not found in manifest."
                logger.warning(
                    "event=agent_loop_llm_called_unknown Agent loop: LLM called unknown tool '%s' "
                    "available=%s", tool_name, tool_names)
                tool_ok = False
                tool_raw_result = tool_result
            else:
                try:
                    ok, result = tool_def.handler(**tool_params)
                    raw_result = json.dumps(result, ensure_ascii=False) if not isinstance(
                        result, str) else result
                    tool_result = _truncate_tool_result(
                        raw_result) if ok else f"TOOL_ERROR: {result}"
                    tool_ok = ok
                    tool_raw_result = raw_result
                    logger.info("event=agent_loop_turn_tool_ok Agent loop | turn=%d tool=%s ok=%s",
                                turn, tool_name, ok)
                    logger.trace(
                        "event=agent_loop_tool_call_detail turn=%d tool=%s params=%s result=%s",
                        turn, tool_name,
                        json.dumps(tool_params, ensure_ascii=False),
                        (raw_result if len(raw_result) <= 2000 else raw_result[:2000] + "..."),
                    )
                except Exception as exc:
                    tool_result = f"TOOL_ERROR: {exc}"
                    tool_ok = False
                    tool_raw_result = str(exc)
                    logger.warning(
                        "event=agent_loop_tool_execution_failed Agent loop tool execution failed | "
                        "tool=%s error=%s", tool_name, exc, exc_info=True)

            tool_duration_ms = int((time.perf_counter() - t_tool_start) * 1000)

            # Build compact tool log entry
            result_preview = str(tool_raw_result)[:300]
            result_count = None
            if tool_ok:
                try:
                    parsed = json.loads(tool_raw_result) if isinstance(tool_raw_result, str) else tool_raw_result
                    if isinstance(parsed, list):
                        result_count = len(parsed)
                    elif isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                        result_count = len(parsed["items"])
                except Exception:
                    pass

            tool_log.append({
                "tool": tool_name,
                "params": {k: str(v)[:100] for k, v in tool_params.items()},
                "ok": tool_ok,
                "result_count": result_count,
                "result_preview": result_preview,
                "duration_ms": tool_duration_ms,
            })

            # Emit thinking: tool result
            if on_thinking:
                on_thinking(_stream_emitter.emit_thinking(
                    action="tool_result",
                    content=result_preview,
                    turn=turn,
                    tool_name=tool_name,
                    metadata={
                        "ok": tool_ok,
                        "duration_ms": tool_duration_ms,
                        "result_count": result_count,
                    },
                ))

            scratchpad.append(ScratchMessage(
                "tool", f"[{tool_name}] {tool_result}"))
            _consecutive_no_tool = 0
            logger.trace("event=agent_loop_tool_done_continuing turn=%d scratchpad_size=%d",
                        turn, len(scratchpad))
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
            if stream_fn is not None and turn < resolved_max_turns - 1:
                # Re-issue the final prompt through the streaming path so the
                # client can receive tokens progressively.
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
                break

            final_answer = clean
            logger.trace("event=agent_loop_final_answer no_stream=%s",
                        json.dumps(final_answer[:120], ensure_ascii=False))
            break

    logger.info(
        "event=agent_loop_completed_turns_final_len Agent loop completed | "
        "turns=%s final_len=%s tools_called=%s",
        len(tool_log) + (1 if final_answer else 0),
        len(final_answer),
        len(tool_log),
    )
    logger.trace("event=agent_loop_exit final_answer=%s tool_log_count=%d token_count=%d",
                json.dumps(final_answer[:300], ensure_ascii=False),
                len(tool_log), len(final_tokens))
    return final_answer, final_tokens, tool_log
