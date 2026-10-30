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
  - changes  : what the answer changed, each item with its «Annulla» (Cindy 13)
  - notice   : STANDARD system packet for every client (memory saved, action done,
               errors…): {type, kind, level, icon, emoji, title, detail, data}.
               Clients render it distinctly from chat text (see NOTICE_KINDS and
               Hestia-Shared/hestia-shared.md § Response packets).
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


def emit_final(reply: str, domain: str = "none", origin: dict | None = None, trace_id: str = "") -> str:
    """Return the terminal final-type NDJSON line. ``origin`` (Cindy 6) is set when the turn was not typed by the
    owner: clients show its ``label`` as a small tag («Da una tua routine»). ``trace_id`` names the turn: clients
    send it back with a 👍/👎 so the vote lands on this turn (docs/work/2026-10-30-dataset-allenamento)."""
    payload = {"type": "final", "reply": reply, "domain": domain}
    if trace_id:
        payload["trace_id"] = trace_id
    if origin:
        payload["origin"] = {k: origin.get(k, "") for k in ("kind", "level", "label")}
    return json.dumps(payload) + "\n"


def changes_from_log(tool_log: list[dict]) -> list[dict]:
    """«Cosa ho cambiato» (Cindy 13): one item per successful write of the turn; ``undo`` when the module declared
    how to undo it in its result (``{"tool", "args", "label"}``, or a tool name + the call's ``id``)."""
    out = []
    for entry in tool_log or []:
        if not entry.get("ok") or not entry.get("writes") or entry.get("confirm") or entry.get("unchanged"):
            continue   # a proposal waiting for the user's confirmation (or a write that changed nothing)
        undo = entry.get("undo")
        if isinstance(undo, str) and undo.strip():
            params = entry.get("params") or {}
            undo = {"tool": undo.strip(), "args": {"id": params["id"]} if params.get("id") else {}}
        if isinstance(undo, dict) and undo.get("tool"):
            undo = {"tool": str(undo["tool"]), "args": dict(undo.get("args") or {}),
                    "label": str(undo.get("label") or "Annulla")}
        else:
            undo = None
        out.append({"tool": str(entry.get("tool") or ""), "title": str(entry.get("title") or entry.get("tool") or ""),
                    "detail": str(entry.get("result_preview") or "")[:160], "undo": undo})
    return out


def emit_changes(items: list[dict], session_id: str = "") -> str:
    """Return the ``changes`` frame: what this answer changed, each with its Annulla (clients may ignore it)."""
    return json.dumps({"type": "changes", "items": items, "session_id": session_id}, ensure_ascii=False) + "\n"


def emit_question(
    question_id: str,
    header: str,
    prompt: str,
    kind: str = "free_text",
    options: list | None = None,
    timeout_sec: int | None = None,
    required: bool = True,
    allow_other: bool = False,
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
    if allow_other:
        payload["allow_other"] = True  # choice kinds also accept a free answer («Altro…»)
    return json.dumps(payload, ensure_ascii=False) + "\n"


def emit_needs_input(missing_fields: list[str], context: str = "") -> str:
    """Return a needs_input frame for non-interactive (service-to-service) callers."""
    return json.dumps({
        "type": "needs_input",
        "missing_fields": missing_fields,
        "context": context,
    }, ensure_ascii=False) + "\n"


# kind → (level, icon name, emoji, default title). Clients may restyle by kind/level/icon.
NOTICE_KINDS: dict[str, tuple[str, str, str, str]] = {
    "memory.saved": ("success", "memory", "💾", "Ricordato"),
    "memory.removed": ("info", "trash", "🗑️", "Dimenticato"),
    "memory.updated": ("info", "memory", "💾", "Memoria aggiornata"),
    "mood.saved": ("info", "smile", "🙂", "Umore segnato"),
    "mood.removed": ("info", "trash", "🗑️", "Umore tolto"),
    "subscription.added": ("success", "bell", "🔔", "Avviso attivato"),
    "subscription.changed": ("info", "bell", "🔔", "Avviso modificato"),
    "subscription.removed": ("info", "bell-off", "🔕", "Avviso disattivato"),
    "action.done": ("success", "check", "✅", "Fatto"),
    "action.failed": ("error", "alert", "❌", "Non riuscito"),
    "action.needs_approval": ("warning", "alert", "✋", "Serve la tua conferma"),
    "agenda.planned": ("info", "calendar", "📅", "In agenda"),
    "forge.task": ("info", "terminal", "🔨", "Sviluppo"),
    "document.saved": ("success", "file", "📄", "Documento salvato"),
    "goal.progress": ("info", "target", "🎯", "Obiettivo"),
    "info": ("info", "info", "ℹ️", "Info"),
    "warning": ("warning", "alert", "⚠️", "Attenzione"),
    "error": ("error", "alert", "❌", "Errore"),
}

# Legacy signal events → standard notice kinds (tool.summary is reasoning, not a notice).
_SIGNAL_TO_NOTICE: dict[str, str] = {
    "memory.preference.added": "memory.saved",
    "memory.preference.removed": "memory.removed",
    "memory.updated": "memory.updated",
    "mood.logged": "mood.saved",
    "mood.removed": "mood.removed",
    "subscription.added": "subscription.added",
    "subscription.changed": "subscription.changed",
    "subscription.removed": "subscription.removed",
    "action.executed": "action.done",
    "action.failed": "action.failed",
    "action.approval.required": "action.needs_approval",
    "document.saved": "document.saved",
    "document_saved": "document.saved",
}


def emit_notice(kind: str, title: str = "", detail: str = "", data: dict | None = None,
                level: str | None = None) -> str:
    """Return a standard notice packet (one NDJSON line)."""
    lvl, icon, emoji, default_title = NOTICE_KINDS.get(kind, NOTICE_KINDS["info"])
    return json.dumps({
        "type": "notice", "kind": kind, "level": level or lvl, "icon": icon, "emoji": emoji,
        "title": title or default_title, "detail": detail, "data": data or {},
    }, ensure_ascii=False) + "\n"


def notice_from_signal(event: str, message: str, data: dict | None = None) -> str:
    """Notice line for a legacy signal event, or '' when the event is not user-facing."""
    kind = _SIGNAL_TO_NOTICE.get(str(event or "").lower())
    if not kind:
        return ""
    d = data or {}
    detail = str(d.get("fact") or d.get("filename") or d.get("summary") or d.get("detail") or "").strip()
    if not detail:
        detail = str(message or "").split(":", 1)[-1].strip() if ":" in str(message or "") else str(message or "")
    return emit_notice(kind, detail=detail[:300], data=d)


def emit_signal(event: str, message: str, data: dict | None = None) -> str:
    """Return a signal-type NDJSON line (+ its standard notice line when user-facing)."""
    line = json.dumps(
        {"type": "signal", "event": event, "content": message, "data": data or {}},
        ensure_ascii=False,
    ) + "\n"
    return line + notice_from_signal(event, message, data)


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
        data={"calls": [{k: v for k, v in e.items() if k != "result_text"} for e in tool_log]},
    )
