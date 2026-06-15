"""NDJSON streaming event helpers.

Single responsibility: format Oracle's streaming protocol events.
Each public function returns a newline-terminated JSON string ready
to be yielded from a FastAPI StreamingResponse generator.

Event types:
  - status   : intermediate progress message shown in the UI
  - token    : incremental LLM token (web clients can render progressively;
                clients that don't support this type safely ignore it)
  - thinking : agent loop reasoning / tool-call visibility events
  - final    : terminal event carrying the assistant's full reply
  - signal   : side-channel event (e.g. memory update, tool summary, document saved)
  - question : interactive question frame for cross-client approval flows
"""
import json


def emit_status(message: str) -> str:
    """Return a status-type NDJSON line."""
    return json.dumps({"type": "status", "content": message}) + "\n"


def emit_token(token: str) -> str:
    """Return a token-type NDJSON line for incremental LLM output."""
    return json.dumps({"type": "token", "text": token}) + "\n"


def emit_thinking(
    action: str,
    content: str,
    turn: int = 0,
    tool_name: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Return a thinking-type NDJSON line for agent loop visibility.

    action values:
      - "reasoning"   : LLM is thinking before a tool call or final answer
      - "tool_call"   : about to execute a tool
      - "tool_result" : tool execution completed

    Clients can render these as subtle progress indicators or ignore them.
    """
    payload: dict = {
        "type": "thinking",
        "action": action,
        "content": content,
        "turn": turn,
    }
    if tool_name:
        payload["tool"] = tool_name
    if metadata:
        payload["metadata"] = metadata
    return json.dumps(payload, ensure_ascii=False) + "\n"


def emit_final(reply: str, domain: str = "none") -> str:
    """Return the terminal final-type NDJSON line."""
    return json.dumps({"type": "final", "reply": reply, "domain": domain}) + "\n"


def emit_question(
    question_id: str,
    header: str,
    prompt: str,
    kind: str = "free_text",
    options: list | None = None,
    timeout_sec: int | None = None,
    required: bool = True,
) -> str:
    """Return a question-type NDJSON frame for the cross-client question protocol.

    Clients that understand the protocol present this as an interactive prompt.
    Clients that don't understand it will ignore the frame (handled on their end).
    """
    payload: dict = {
        "type": "question",
        "question_id": question_id,
        "header": header,
        "prompt": prompt,
        "kind": kind,          # free_text | single_choice | multi_choice | confirm
        "required": required,
    }
    if options:
        payload["options"] = options
    if timeout_sec is not None:
        payload["timeout_sec"] = timeout_sec
    return json.dumps(payload, ensure_ascii=False) + "\n"


def emit_needs_input(missing_fields: list[str], context: str = "") -> str:
    """Return a needs_input frame for non-interactive (service-to-service) callers."""
    return json.dumps({
        "type": "needs_input",
        "missing_fields": missing_fields,
        "context": context,
    }, ensure_ascii=False) + "\n"


def emit_signal(event: str, message: str, data: dict | None = None) -> str:
    """Return a signal-type NDJSON line for side-channel events."""
    return json.dumps(
        {"type": "signal", "event": event, "content": message, "data": data or {}},
        ensure_ascii=False,
    ) + "\n"


def emit_tool_summary(tool_log: list[dict]) -> str:
    """Return a signal-type NDJSON line carrying the agent loop tool-call summary.

    The tool_log is a list of dicts, each describing one tool invocation:
        {"tool": str, "params": dict, "ok": bool, "result_count": int | None,
         "result_preview": str, "duration_ms": int}

    Clients render this as a compact post-answer summary card.
    """
    return emit_signal(
        event="tool.summary",
        message="Riepilogo strumenti utilizzati",
        data={"calls": tool_log},
    )
