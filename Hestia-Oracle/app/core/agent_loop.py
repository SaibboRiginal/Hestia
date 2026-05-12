"""AgentLoop — ReAct-style multi-turn tool execution loop.

Implements the structured agentic loop described in oracle-rewrite-groundwork.md §2.

Pattern:
  User message + tool manifest
    → LLM: reason + optionally emit tool_call JSON
    → Tool execution (via Hub/module-tools)
    → LLM: continue reasoning with tool result
    → … (up to MAX_AGENT_TURNS)
    → LLM: final answer

Each iteration is a separate LLM call. Tool results are injected as ephemeral
scratchpad messages — they are NOT persisted to Archive chat history.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Iterator

from core.services import prompt_config

logger = logging.getLogger(f"hestia_oracle.{__name__}")

MAX_AGENT_TURNS: int = int(os.getenv("ORACLE_MAX_AGENT_TURNS", "6"))
TOOL_RESULT_MAX_CHARS: int = int(
    os.getenv("ORACLE_TOOL_RESULT_MAX_CHARS", "2000")
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
) -> tuple[str, list[str]]:
    """Run the ReAct agent loop and return (final_answer, list_of_token_strings).

    Args:
        user_message: The user's current input.
        history_text: Compacted conversation history (plain text).
        preference_facts: Active user preferences to inject.
        tools: Available ToolDefinitions for this session.
        ask_fn: Blocking LLM call used for intermediate turns.
        stream_fn: Optional streaming LLM call used for the final answer turn.
        client_instructions: Optional client-specific style instructions.
        conversation_style: Conversation style contract string.

    Returns:
        (final_answer_text, tokens_list)
        tokens_list contains token strings for the final streamed answer (empty if stream_fn is None).
    """
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
    if client_instructions:
        system_prompt += prompt_config.optional_section(
            "CLIENT INSTRUCTIONS",
            client_instructions,
        )

    # Scratchpad: ephemeral tool-call/result messages for this session turn only
    scratchpad: list[ScratchMessage] = []

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

    for turn in range(MAX_AGENT_TURNS):
        is_last_turn = (turn == MAX_AGENT_TURNS - 1)
        prompt = _build_prompt(is_final=is_last_turn)

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
            if raw_response:
                scratchpad.append(ScratchMessage("assistant", raw_response))

            tool_def = tool_map.get(tool_name)
            if not tool_def:
                tool_result = f"ERROR: Tool '{tool_name}' not found in manifest."
                logger.warning(
                    "event=agent_loop_llm_called_unknown Agent loop: LLM called unknown tool '%s'", tool_name)
            else:
                try:
                    ok, result = tool_def.handler(**tool_params)
                    raw_result = json.dumps(result, ensure_ascii=False) if not isinstance(
                        result, str) else result
                    tool_result = _truncate_tool_result(
                        raw_result) if ok else f"TOOL_ERROR: {result}"
                    logger.info("event=agent_loop_turn_tool_ok Agent loop | turn=%d tool=%s ok=%s",
                                turn, tool_name, ok)
                except Exception as exc:
                    tool_result = f"TOOL_ERROR: {exc}"
                    logger.warning(
                        "event=agent_loop_tool_execution_failed Agent loop tool execution failed | tool=%s error=%s", tool_name, exc)

            scratchpad.append(ScratchMessage(
                "tool", f"[{tool_name}] {tool_result}"))
            continue

        else:
            # ── Final answer turn ──────────────────────────────────────────
            # Strip any residual tool_call blocks from final answer
            clean = _TOOL_CALL_PATTERN.sub("", raw_response).strip()

            if turn == 0 and tools_manifest:
                logger.info(
                    "event=agent_loop_no_tool_call_first_turn tools=%s response_preview=%s",
                    len(tools_manifest),
                    clean[:200],
                )

            if stream_fn is not None and turn < MAX_AGENT_TURNS - 1:
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

            logger.info("event=agent_loop_completed_turns_final_len Agent loop completed | turns=%d final_len=%d",
                        turn + 1, len(final_answer))
            break

    return final_answer, final_tokens
