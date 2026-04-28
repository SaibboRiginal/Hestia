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

logger = logging.getLogger(__name__)

MAX_AGENT_TURNS: int = int(os.getenv("ORACLE_MAX_AGENT_TURNS", "6"))

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

_SYSTEM_PREAMBLE = """\
You are Hestia's reasoning engine. You have access to the following tools.

To call a tool, output EXACTLY this XML block (nothing before or after on the same line):
<tool_call>
{{"name": "<tool_name>", "params": {{...}}}}
</tool_call>

After receiving a tool result, continue reasoning and either call another tool or produce your final answer.
When you are ready to give your final answer, output it directly without any tool_call block.

Available tools:
{tools_json}
"""


def _extract_tool_call(text: str) -> dict | None:
    """Parse the first <tool_call>...</tool_call> block from the LLM output.

    Returns a dict with 'name' and 'params', or None if no tool call found.
    """
    m = _TOOL_CALL_PATTERN.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (ValueError, KeyError):
        return None


def _truncate_tool_result(result: str, max_chars: int = 2000) -> str:
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

    system_prompt = _SYSTEM_PREAMBLE.format(tools_json=tools_json)
    if preference_facts:
        system_prompt += "\n\nACTIVE USER PREFERENCES:\n" + \
            "\n".join(f"- {f}" for f in preference_facts)
    if conversation_style:
        system_prompt += f"\n\n{conversation_style}"
    if client_instructions:
        system_prompt += f"\n\nCLIENT_INSTRUCTIONS:\n{client_instructions}"

    # Scratchpad: ephemeral tool-call/result messages for this session turn only
    scratchpad: list[ScratchMessage] = []

    def _build_prompt(is_final: bool = False) -> str:
        parts = [system_prompt]
        if history_text:
            parts.append(f"\nCONVERSATION HISTORY:\n{history_text}")
        parts.append(f"\nUSER: {user_message}")
        for msg in scratchpad:
            parts.append(f"\n[{msg.role.upper()}]: {msg.content}")
        if is_final:
            parts.append(
                "\nNow provide your final answer to the user (no tool_call blocks):")
        return "\n".join(parts)

    final_answer = ""
    final_tokens: list[str] = []

    for turn in range(MAX_AGENT_TURNS):
        is_last_turn = (turn == MAX_AGENT_TURNS - 1)
        prompt = _build_prompt(is_final=is_last_turn)

        try:
            raw_response = ask_fn(prompt)
        except Exception as exc:
            logger.error(
                "Agent loop LLM call failed at turn %d: %s", turn, exc)
            final_answer = "⚠️ Il modello non è disponibile. Riprova tra poco."
            break

        tool_call = _extract_tool_call(
            raw_response) if not is_last_turn else None

        if tool_call:
            # ── Tool call turn ─────────────────────────────────────────────
            tool_name = tool_call.get("name", "")
            tool_params = tool_call.get("params") or {}
            scratchpad.append(ScratchMessage("assistant", raw_response))

            tool_def = tool_map.get(tool_name)
            if not tool_def:
                tool_result = f"ERROR: Tool '{tool_name}' not found in manifest."
                logger.warning(
                    "Agent loop: LLM called unknown tool '%s'", tool_name)
            else:
                try:
                    ok, result = tool_def.handler(**tool_params)
                    raw_result = json.dumps(result, ensure_ascii=False) if not isinstance(
                        result, str) else result
                    tool_result = _truncate_tool_result(
                        raw_result) if ok else f"TOOL_ERROR: {result}"
                    logger.info("Agent loop | turn=%d tool=%s ok=%s",
                                turn, tool_name, ok)
                except Exception as exc:
                    tool_result = f"TOOL_ERROR: {exc}"
                    logger.warning(
                        "Agent loop tool execution failed | tool=%s error=%s", tool_name, exc)

            scratchpad.append(ScratchMessage(
                "tool", f"[{tool_name}] {tool_result}"))
            continue

        else:
            # ── Final answer turn ──────────────────────────────────────────
            # Strip any residual tool_call blocks from final answer
            clean = _TOOL_CALL_PATTERN.sub("", raw_response).strip()

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
                        "Agent loop final stream failed, using non-streamed answer: %s", exc)
                    final_answer = clean
            else:
                final_answer = clean

            logger.info("Agent loop completed | turns=%d final_len=%d",
                        turn + 1, len(final_answer))
            break

    return final_answer, final_tokens
