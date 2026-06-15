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
                "name": str(fn.get("name") or "").strip(),
                "params": raw_args if isinstance(raw_args, dict) else {},
            }

        return None

    m = _TOOL_CALL_PATTERN.search(text)
    if not m:
        # Fallback 1: fenced JSON object
        fm = _JSON_BLOCK_PATTERN.search(text)
        if fm:
            try:
                normalized = _normalize_tool_call(json.loads(fm.group(1)))
                if normalized and normalized.get("name"):
                    return normalized
            except (ValueError, KeyError):
                pass

        # Fallback 2: any JSON object in plain text
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                normalized = _normalize_tool_call(
                    json.loads(text[start:end + 1]))
                if normalized and normalized.get("name"):
                    return normalized
        except Exception:
            pass
        return None
    try:
        normalized = _normalize_tool_call(json.loads(m.group(1)))
        if normalized and normalized.get("name"):
            return normalized
        return None
    except (ValueError, KeyError):
        return None


def _truncate_tool_result(result: str, max_chars: int = TOOL_RESULT_MAX_CHARS) -> str:
    """Truncate a verbose tool result and add a pointer note."""
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
    """Run the ReAct agent loop and return (final_answer, tokens, tool_log).

    Args:
        user_message: The user's current input.
        history_text: Compacted conversation history (plain text).
        preference_facts: Active user preferences to inject.
        tools: Available ToolDefinitions for this session.
        ask_fn: Blocking LLM call used for intermediate turns.
        ask_tools_fn: Optional provider-native tool-calling callback.
        stream_fn: Optional streaming LLM call used for the final answer turn.
        client_instructions: Optional client-specific style instructions.
        conversation_style: Conversation style contract string.
        max_turns: Override for max agent turns (uses env default if None).
        on_thinking: Optional callback receiving NDJSON thinking lines for
                     real-time visibility into the agent loop.
        action_intent: When True, the agent is nudged to prioritize tool usage.

    Returns:
        (final_answer_text, tokens_list, tool_log)
        tokens_list contains token strings for the final streamed answer.
        tool_log is a list of compact dicts describing each tool invocation.
    """
    resolved_max_turns = max_turns if max_turns is not None else MAX_AGENT_TURNS
    tool_map = {t.name: t for t in tools}

    # Build tool manifest JSON for LLM
    tools_manifest = [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in tools
    ]
    tools_json = json.dumps(tools_manifest, ensure_ascii=False, indent=2)

    system_prompt = prompt_config.prompt(
        "agent_loop_system_preamble",
        tools_json=tools_json,
    )
    if preference_facts:
        system_prompt += prompt_config.optional_section(
            "ACTIVE USER PREFERENCES",
            "\n".join(f"- {fact}" for fact in preference_facts),
        )
    if conversation_style:
        system_prompt += f"\n\n{conversation_style}"
    if action_intent:
        system_prompt += prompt_config.optional_section(
            "ACTION INTENT",
            "The user appears to want a state-changing action. Prioritise calling the "
            "appropriate tool over giving a text-only answer. If no matching tool "
            "exists, explain clearly that the action cannot be performed.",
        )
    if client_instructions:
        system_prompt += prompt_config.optional_section(
            "CLIENT INSTRUCTIONS",
            client_instructions,
        )

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
        return prompt_config.compose_with_dynamic_boundary(
            static_sections=[system_prompt],
            dynamic_sections=dynamic_parts,
        )

    final_answer = ""
    final_tokens: list[str] = []

    for turn in range(resolved_max_turns):
        is_last_turn = (turn == resolved_max_turns - 1)
        prompt = _build_prompt(is_final=is_last_turn)
        t_turn_start = time.perf_counter()

        raw_response = ""
        tool_call = None
        try:
            if ask_tools_fn is not None and not is_last_turn:
                decision = ask_tools_fn(prompt, tools_manifest) or {}
                maybe_tool = decision.get("tool_call") if isinstance(
                    decision, dict) else None
                if isinstance(maybe_tool, dict) and maybe_tool.get("name"):
                    tool_call = {
                        "name": str(maybe_tool.get("name") or "").strip(),
                        "params": maybe_tool.get("params") or {},
                    }
                    raw_response = ""
                else:
                    raw_response = str(
                        (decision or {}).get("text") or "").strip()
                    # Some providers return tool intents as plain text blocks.
                    # Parse XML fallback here before falling through to final answer.
                    if raw_response:
                        tool_call = _extract_tool_call(raw_response)

                if tool_call is None:
                    logger.info(
                        "event=agent_loop_tool_decision_none turn=%s tools=%s response_len=%s",
                        turn,
                        len(tools_manifest),
                        len(raw_response or ""),
                    )

            if not raw_response and tool_call is None:
                raw_response = ask_fn(prompt)
                tool_call = _extract_tool_call(
                    raw_response) if not is_last_turn else None
        except Exception as exc:
            logger.error(
                "event=agent_loop_llm_call_failed Agent loop LLM call failed at turn %d: %s", turn, exc)
            final_answer = "⚠️ Il modello non è disponibile. Riprova tra poco."
            break

        if tool_call:
            # ── Tool call turn ─────────────────────────────────────────────
            tool_name = tool_call.get("name", "")
            tool_params = tool_call.get("params") or {}

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
                    "event=agent_loop_llm_called_unknown Agent loop: LLM called unknown tool '%s'", tool_name)
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
                except Exception as exc:
                    tool_result = f"TOOL_ERROR: {exc}"
                    tool_ok = False
                    tool_raw_result = str(exc)
                    logger.warning(
                        "event=agent_loop_tool_execution_failed Agent loop tool execution failed | tool=%s error=%s", tool_name, exc)

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
            continue

        else:
            # ── Text response (no tool call) ─────────────────────────────
            _consecutive_no_tool += 1

            # Early exit: if we've already made tool calls and the LLM is
            # now producing text without tools, it's likely the final answer.
            if tool_log and _consecutive_no_tool >= _EARLY_EXIT_NO_TOOL_TURNS:
                logger.info(
                    "event=agent_loop_early_exit turn=%s consecutive_no_tool=%s tool_calls=%s",
                    turn, _consecutive_no_tool, len(tool_log),
                )
                clean = _TOOL_CALL_PATTERN.sub("", raw_response).strip()
                final_answer = clean
                break

            # Strip any residual tool_call blocks from final answer
            clean = _TOOL_CALL_PATTERN.sub("", raw_response).strip()

            if turn == 0 and tools_manifest:
                logger.info(
                    "event=agent_loop_no_tool_call_first_turn tools=%s response_preview=%s",
                    len(tools_manifest),
                    clean[:200],
                )

            if stream_fn is not None and turn < resolved_max_turns - 1:
                # Re-issue the final prompt through the streaming path so the
                # client can receive tokens progressively.
                final_prompt = _build_prompt(is_final=True)
                try:
                    for token in stream_fn(final_prompt):
                        final_tokens.append(token)
                    final_answer = "".join(final_tokens)
                except Exception as exc:
                    logger.warning(
                        "event=agent_loop_final_stream_failed Agent loop final stream failed, using non-streamed answer: %s", exc)
                    final_answer = clean
            else:
                final_answer = clean

            logger.info("event=agent_loop_completed_turns_final_len Agent loop completed | turns=%d final_len=%d tools_called=%d",
                        turn + 1, len(final_answer), len(tool_log))
            break

    return final_answer, final_tokens, tool_log
