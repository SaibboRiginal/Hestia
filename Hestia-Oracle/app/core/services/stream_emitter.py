"""NDJSON streaming event helpers.

Single responsibility: format Oracle's streaming protocol events.
Each public function returns a newline-terminated JSON string ready
to be yielded from a FastAPI StreamingResponse generator.

Event types:
  - status  : intermediate progress message shown in the UI
  - final   : terminal event carrying the assistant's reply
  - signal  : side-channel event (e.g. memory update, document saved)
"""
import json


def emit_status(message: str) -> str:
    """Return a status-type NDJSON line."""
    return json.dumps({"type": "status", "content": message}) + "\n"


def emit_final(reply: str, domain: str = "none") -> str:
    """Return the terminal final-type NDJSON line."""
    return json.dumps({"type": "final", "reply": reply, "domain": domain}) + "\n"


def emit_signal(event: str, message: str, data: dict | None = None) -> str:
    """Return a signal-type NDJSON line for side-channel events."""
    return json.dumps(
        {"type": "signal", "event": event, "content": message, "data": data or {}},
        ensure_ascii=False,
    ) + "\n"
