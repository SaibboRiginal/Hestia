import time
import uuid
import os
import threading
import requests
import logging
from pathlib import Path
import sys
from fastapi import Body, FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Literal, Optional
from core.oracle_engine import OracleEngine
from core.services import chat_sessions

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router
    from hestia_common.plugin_client import PluginClient, page, widget
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router
    from hestia_common.plugin_client import PluginClient, page, widget

logger, log_buffer = setup_service_logging("hestia_oracle")

app = FastAPI(title="Hestia Oracle Microservice", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])
engine = OracleEngine()

# ── MCP tools — Oracle's own agent tools exposed via MCP standard ─────────

_oracle_mcp_tools = [
    MCPTool(
        name="memory.save",
        description="Save a durable fact or preference about the user for future reference. Use when the user expresses a preference, constraint, or personal detail.",
        parameters={
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The fact or preference to remember"},
                "domain": {"type": "string", "description": "Domain category (default 'general')"},
            },
            "required": ["fact"],
        },
        handler=lambda **kw: engine._memory_service.save_memory(
            fact=str(kw.get("fact", "")),
            domain=str(kw.get("domain", "general")),
        ),
        title="Salva preferenza", method="POST", path="/api/memory",
        clients=["telegram", "ui"], response_mode="oracle_natural",
        telegram_visible=False, telegram_group="memoria",
                telegram={"section": "Note e preferenze"}),
    MCPTool(
        name="memory.search",
        description="Search saved memories and preferences about the user.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords to search for in memories"},
            },
        },
        handler=lambda **kw: engine._memory_service.search_memories(
            query=str(kw.get("query", "")),
        ),
        title="Cerca ricordi", method="GET", path="/api/memory",
        clients=["telegram", "ui"], response_mode="oracle_natural",
        telegram_visible=False, telegram_group="memoria",
                telegram={"section": "Note e preferenze"}),
    # ── Memory from external AIs (docs/work/2026-10-20-memory-note) ────────
    MCPTool(
        name="memory_note",
        description=("Save in Hestia's long-term memory the durable facts about the user that came out of this "
                     "conversation: preferences, constraints, decisions, personal details, plans. Send them already "
                     "distilled, one short sentence per line, max 10 lines; never a transcript or temporary chatter. "
                     "Facts Hestia already knows are skipped. Hestia uses them from then on in every client."),
        parameters={
            "type": "object",
            "properties": {
                "facts": {"type": "string", "description": "One durable fact per line (max 10, 300 chars each)"},
                "topic": {"type": "string", "description": "A few words on what the conversation was about"},
            },
            "required": ["facts"],
        },
        handler=lambda **kw: engine._memory_service.save_note(
            facts=kw.get("facts", ""), topic=str(kw.get("topic", "") or "")),
        title="Ricorda questo", method="POST", path="/api/memory/note",
        clients=["ui", "telegram", "external"], response_mode="oracle_natural",
        telegram_visible=False, telegram_group="memoria",
                telegram={"section": "Note e preferenze", "primary": 1}),
    MCPTool(
        name="memory_recall",
        description=("What Hestia already knows about the user on a topic (keywords), so your answer and Hestia's "
                     "memory agree. Empty query = the most recent memories. Max 20 rows."),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords, e.g. 'palestra' or 'cibo allergie'"},
            },
        },
        handler=lambda **kw: engine._memory_service.recall(query=str(kw.get("query", "") or "")),
        title="Cosa ricordi", method="GET", path="/api/memory/recall",
        clients=["ui", "telegram", "external"], response_mode="oracle_natural",
        telegram_visible=False, telegram_group="memoria",
                telegram={"section": "Note e preferenze", "primary": 2}),
    MCPTool(
        name="documents.search",
        description="Search through uploaded documents and files for relevant content.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
        handler=lambda **kw: (True, engine._doc_rag.search_relevant_chunks(
            str(kw.get("query", "")), None, None)),
        title="Cerca nei documenti", method="GET", path="/api/documents/search",
        clients=["telegram", "ui"], response_mode="oracle_natural",
        telegram_visible=False, telegram_group="memoria",
                telegram={"section": "Documenti", "primary": 3}),
    # ── Conversations: tags and list (Cindy 26, dossier 2026-10-24-tutto-brainstorm-cindy W7) ─────────
    MCPTool(
        name="chat_tag", description=chat_sessions.TAG_DESCRIPTION, parameters=chat_sessions.TAG_PARAMETERS,
        handler=lambda **kw: _chat_tool(chat_sessions.tool_tag, **kw),
        title="Etichetta la conversazione", method="POST", path="/api/chats/tag",
        clients=["ui", "telegram"], response_mode="oracle_natural",
        telegram_visible=False, telegram_group="sistema",
                telegram={"section": "Chat"}),
    MCPTool(
        name="chat_list", description=chat_sessions.LIST_DESCRIPTION, parameters=chat_sessions.LIST_PARAMETERS,
        handler=lambda **kw: _chat_tool(chat_sessions.tool_list, **kw),
        title="Le tue conversazioni", method="GET", path="/api/chats",
        clients=["ui", "telegram"], response_mode="direct",
        telegram_visible=False, telegram_group="sistema",
                telegram={"section": "Chat"}),
    # ── Oracle self-tools (Plan P3c) ───────────────────────────────────────
    MCPTool(
        name="oracle.context_stats",
        description="Return token breakdown and context-window usage for a session.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
        handler=lambda **kw: engine.estimate_context_stats(
            session_id=str(kw.get("session_id", ""))),
        title="Contesto della chat", method="GET", path="/api/chat/context",
        clients=["telegram", "ui"], response_mode="raw_json",
        telegram_visible=False, telegram_group="sistema",
                telegram={"section": "Chat"}),
    MCPTool(
        name="oracle.compact",
        description="Force-compact conversation history for a session via LLM summarisation.",
        parameters={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
        handler=lambda **kw: engine.compact_context(
            session_id=str(kw.get("session_id", ""))),
        title="Compatta la chat", method="POST", path="/api/chat/compact",
        clients=["telegram", "ui"], response_mode="raw_json",
        telegram_visible=False, telegram_group="sistema",
                telegram={"section": "Chat"}),
    MCPTool(
        name="oracle.session_info",
        description="Return global Oracle state: active sessions, uptime, model in use, Hub connection.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=lambda **kw: engine.get_session_info(),
        title="Stato dei modelli", method="GET", path="/api/sessions",
        clients=["telegram", "ui"], response_mode="raw_json",
        telegram_visible=False, telegram_group="sistema",
                telegram={"section": "Salute e log"}),
    MCPTool(
        name="oracle.logs_query",
        description="Query Oracle's in-memory log buffer by level and text filter.",
        parameters={
            "type": "object",
            "properties": {
                "level": {"type": "string", "description": "Log level filter (DEBUG, INFO, WARNING, ERROR, TRACE)"},
                "contains": {"type": "string", "description": "Text to search for in log messages"},
                "limit": {"type": "integer", "description": "Max log lines (default 50, max 500)"},
            },
        },
        handler=lambda **kw: engine.query_logs(
            level=str(kw.get("level", "") or "").strip() or None,
            contains=str(kw.get("contains", "") or "").strip() or None,
            limit=int(kw.get("limit", 50)),
        ),
        title="Log dei modelli", method="GET", path="/api/logs",
        clients=["telegram", "ui"], response_mode="raw_json",
        telegram_visible=False, telegram_group="sistema",
                telegram={"section": "Salute e log"}),
]
try:
    app.include_router(create_mcp_router(_oracle_mcp_tools, service_name="oracle"))
    logger.info("event=mcp_router_mounted service=oracle tools=%d", len(_oracle_mcp_tools))
except Exception as exc:
    logger.warning("event=mcp_router_mount_failed service=oracle error=%s", exc)


from core.services import oracle_settings as _oracle_settings  # noqa: E402
from core.services import llm_stats  # noqa: E402
from core.services import activity_log  # noqa: E402
from core.services import queued_chat  # noqa: E402
from core.services import quoted_context  # noqa: E402

app.include_router(_oracle_settings.settings.router())

# ── WebUI plugin (core module, Sistema section): Cervello ────────────────────
# Inside view of Oracle (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2): recent turns, LLM use per
# use case/model, tokens/cost per day, Claude Code. Reads under /api/ui/ (Oracle's routes are spread over prefixes).
UI_DIST = os.getenv("ORACLE_UI_DIST", "/ui/dist")   # outside /code: the compose dev mount of app/ must not hide it
ui = PluginClient("oracle", title="Assistente", icon="brain", color="purple", kind="core", dist=UI_DIST,
                  description="Come lavora l'assistente: richieste, modelli usati, token e costi, documenti, memoria.",
                  version=os.getenv("ORACLE_SERVICE_VERSION", "1.0.0"))
ui.webui(entry="oracle.js", api_prefix="/api/ui/",
         pages=[page("cervello", "Richieste e modelli", element="oracle-brain", icon="brain", order=120,
                     help="Cosa fa Oracle: ultime richieste (dominio, strumenti, modello, tempi), stato di Claude "
                          "Code; scheda Uso (chiamate, token, cache e costi per modulo e conversazione) e scheda "
                          "Modelli (fornitori, catene di modelli, uso scelto da ogni modulo)."),
                page("documenti", "Documenti", element="oracle-documents", icon="file", order=121,
                     help="I file che hai condiviso con Hestia (in chat o da qui): cercali come fa la chat, "
                          "aggiungine di nuovi, tienili per sempre o eliminali."),
                page("memoria", "Memoria", element="oracle-memory", icon="bookmark", order=122,
                     help="Quello che Hestia ricorda di te: imparato in chat o annotato da un'AI esterna "
                          "(Claude, ChatGPT) collegata a Hestia. Cerca, filtra per origine, dimentica.")],
         widgets=[widget("uso-oggi", "Uso modelli oggi", element="oracle-usage-widget", sizes=["s", "m", "l"],
                         size="m", open_page="cervello", icon="chart",
                         help="Chiamate, token e costo di oggi, per modello.")])
app.include_router(ui.router())

# ── export / import (hestia_common.transfer): long-term memory only, never chats ─────────────────────────
from hestia_common.transfer import Transfer
from core.services.memory_transfer import MemorySection

transfer = Transfer("oracle", sections=[MemorySection(lambda *a, **kw: engine._memory_service._route_archive(*a, **kw))])
app.include_router(transfer.router())


@app.get("/api/ui/activity")
def ui_activity(limit: int = 30):
    """Recent chat turns (newest first) + last real user interaction (page Cervello)."""
    ts = _LAST_USER_ACTIVITY["ts"]
    rows = activity_log.recent(limit)
    return {"status": "ok", "count": len(rows), "turns": rows, "last_user_activity_ts": ts or None,
            "idle_seconds": int(time.time() - ts) if ts else None}


@app.get("/api/ui/stats")
def ui_stats(days: int = 14):
    """LLM use from the in-memory llm_stats: per day (tokens, cost), today per use case/model, and the
    rolling averages per use case (prompt size, cache hit, speed). Counted since Oracle started."""
    out = llm_stats.daily(days)
    for row in out["today_by_model"]:
        row["label"] = _use_case_label(row["use_case"])
    use_cases = [{"use_case": uc, "label": _use_case_label(uc), **row}
                 for uc, row in sorted(llm_stats.summary().items())]
    return {"status": "ok", **out, "use_cases": use_cases}


def _use_case_label(use_case: str) -> str:
    """Italian name of a use case (declared by Oracle or by its module) or of an agent slot."""
    from core.services import llm_chains
    if use_case == "claude_code":
        return "Claude Code (Forge)"
    use_case = llm_chains.SLOTS.get(use_case, use_case)
    entry = llm_chains.declared_usecases().get(use_case)
    return entry["label"] if entry else use_case


@app.get("/api/ui/code")
def ui_code():
    """Claude Code ("code" use case): ready or why not, plus the recent Forge runs."""
    from core.services.claude_code_runner import runs, status
    return {"status": "ok", **status(), **runs()}


# ── Cervello → Modelli and Uso tabs (dossier docs/work/2026-10-19-oracle-a-blocchi §D-E) ──────────────────
_MODEL_PARTS = {"providers": _oracle_settings.PROVIDERS_KEY, "chains": _oracle_settings.CHAINS_KEY,
                "usecases": _oracle_settings.USECASES_KEY}


class UiModelsWrite(BaseModel):
    value: dict


@app.get("/api/ui/models")
def ui_models():
    """Providers (no keys), standards, chains with each step's state, use cases by module, modes."""
    from core.services import llm_chains, llm_providers
    return {"status": "ok", "providers": llm_providers.public_view(),
            "types": [{"value": k, "label": v} for k, v in llm_providers.TYPES.items()],
            "chains": llm_chains.chains_view(), "usecases": llm_chains.usecases_view(),
            "overrides": _oracle_settings.settings.get(_oracle_settings.USECASES_KEY, {}) or {},
            "modes": [{"value": m, "label": label} for m, label in llm_chains.MODES]}


@app.get("/api/ui/models/list")
def ui_models_list(provider: str):
    """Model names a provider offers (picker of the chain editor)."""
    from core.services import llm_providers
    if not llm_providers.get(provider):
        raise HTTPException(status_code=404, detail="unknown provider")
    return {"status": "ok", "provider": provider, "models": llm_providers.list_models(provider)}


@app.put("/api/ui/models/{part}")
def ui_models_write(part: str, req: UiModelsWrite):
    """Marko's edit from the page Modelli (providers | chains | usecases): stored through Themis."""
    from core.services import llm_providers
    key = _MODEL_PARTS.get(part)
    if not key:
        raise HTTPException(status_code=404, detail="part must be providers | chains | usecases")
    value = req.value
    if part == "providers":
        bad = [n for n, p in value.items() if not isinstance(p, dict) or p.get("type") not in llm_providers.TYPES]
        if bad or not value:
            raise HTTPException(status_code=400, detail=f"unknown standard for: {', '.join(bad) or 'empty'}")
    elif part == "chains":
        if not value or any(not isinstance(c, dict) or not isinstance(c.get("steps"), list) for c in value.values()):
            raise HTTPException(status_code=400, detail="every chain needs a list of steps")
    elif part == "usecases":
        if any(not isinstance(v, dict) for v in value.values()):
            raise HTTPException(status_code=400, detail="every use case needs an object")
    if not _oracle_settings.settings.put(key, value, actor="user", reason="WebUI Cervello → Modelli"):
        raise HTTPException(status_code=502, detail="Themis did not accept the change")
    return {"status": "ok", "key": key}


@app.post("/api/ui/models/quota/reset")
def ui_models_quota_reset(provider: str = "", model: str = ""):
    """«Riprova adesso»: forget a model's quota state (all when no provider)."""
    from core.services import llm_chains
    llm_chains.clear_exhausted(provider, model)
    return {"status": "ok"}


@app.get("/api/ui/usage")
def ui_usage(group: str = "module", days: int = 7, module: str = "", session_id: str = "", use_case: str = ""):
    """Tab Uso: same as ``GET /api/llm/usage``."""
    return llm_usage_endpoint(group=group, days=days, module=module, session_id=session_id, use_case=use_case)


@app.get("/api/ui/usage/calls")
def ui_usage_calls(days: int = 7, module: str = "", session_id: str = "", use_case: str = "", limit: int = 100):
    return llm_usage_calls_endpoint(days=days, module=module, session_id=session_id, use_case=use_case, limit=limit)


# ── Documenti page (SPEC §A4): documents in Archive, same search and archiving pipeline as the chat ─────────
from core.services import ui_documents  # noqa: E402
from core.document.transcription import capabilities as _voice_capabilities  # noqa: E402


class UiDocumentUpload(BaseModel):
    name: str = ""
    mime: str = "application/octet-stream"
    data_b64: str


class UiDocumentPermanent(BaseModel):
    is_permanent: bool


def _ui_doc(fn, *args, **kwargs):
    try:
        return fn(engine, *args, **kwargs)
    except ui_documents.DocumentError as exc:
        if exc.status >= 500:
            logger.warning("[🔄] event=ui_documents_archive_failed detail=%s", exc.detail)
        raise HTTPException(status_code=exc.status, detail=exc.detail)


@app.get("/api/ui/memory")
def ui_memory():
    """Memoria page: what Hestia remembers about the user and where each memory came from."""
    return {"memories": engine._memory_service.list_memories()}


@app.delete("/api/ui/memory/{memory_id}")
def ui_memory_forget(memory_id: int):
    if not engine._memory_service.forget(memory_id):
        raise HTTPException(status_code=502, detail="memory not removed")
    return {"status": "forgotten", "id": memory_id}


def _chat_route(*args, **kwargs):
    return engine._memory_service._route_archive(*args, **kwargs)


def _chat_tool(fn, **kwargs):
    try:
        return fn(_chat_route, **kwargs)
    except chat_sessions.ChatSessionsError as exc:
        return {"error": exc.detail, "status": exc.status}


def _chats(fn, *args, **kwargs):
    try:
        return fn(_chat_route, *args, **kwargs)
    except chat_sessions.ChatSessionsError as exc:
        if exc.status >= 500:
            logger.warning("[🔄] event=ui_chats_archive_failed detail=%s", exc.detail)
        raise HTTPException(status_code=exc.status, detail=exc.detail)


@app.post("/api/chats/tag")
def chats_tag(body: dict = Body(...)):
    """``chat_tag`` over REST (same handler)."""
    return _chats(chat_sessions.tool_tag, **{k: v for k, v in body.items() if k in (
        "tags", "remove", "title", "pinned", "color", "session_id", "replace")})


@app.get("/api/chats")
def chats_list(tag: str = "", query: str = "", limit: int = 10):
    """``chat_list`` over REST (same handler)."""
    return _chats(chat_sessions.tool_list, tag=tag, query=query, limit=limit)


@app.get("/api/ui/chats")
def ui_chats(q: str = "", tag: str = "", since: str = "", until: str = "", pinned: Optional[bool] = None,
             limit: int = 30, offset: int = 0):
    """WebUI history sidebar: conversations newest first (pinned on top), search, tag and date filter."""
    return _chats(chat_sessions.list_chats, q=q, tag=tag, since=since, until=until, pinned=pinned,
                  limit=limit, offset=offset)


@app.get("/api/ui/chats/tags")
def ui_chats_tags():
    return _chats(chat_sessions.tags)


@app.get("/api/ui/chats/{session_id}/messages")
def ui_chats_messages(session_id: str, limit: int = 200):
    """Messages of one conversation (oldest first) to open it again in the chat."""
    return _chats(chat_sessions.messages, session_id, limit=limit)


@app.put("/api/ui/chats/{session_id}")
def ui_chats_meta(session_id: str, body: dict = Body(...)):
    """Title, tags (`tags` replace, `add_tags`, `remove_tags`), pinned; returns the previous meta as `before`."""
    return _chats(chat_sessions.set_meta, session_id, {**body, "client": "webui"})


@app.get("/api/ui/documents")
def ui_documents_list(limit: int = 100, domain: str = "", permanent: Optional[bool] = None):
    """Documents Hestia keeps (newest first), with domain / permanent filters."""
    return _ui_doc(ui_documents.list_documents, limit=limit, domain=domain, permanent=permanent)


@app.get("/api/ui/documents/search")
def ui_documents_search(query: str = "", limit: int = 8):
    """Semantic search over document passages (the one the chat uses)."""
    return _ui_doc(ui_documents.search, query, limit=limit)


@app.post("/api/ui/documents")
def ui_documents_add(req: UiDocumentUpload):
    """Add a file (base64, from the SDK upload helper): archived in the background like a chat attachment."""
    max_bytes = _oracle_settings.get_int(_oracle_settings.DOC_MAX_ARCHIVE_MB, 1) * 1024 * 1024
    return _ui_doc(ui_documents.ingest, req.name, req.mime, req.data_b64, max_bytes)


@app.patch("/api/ui/documents/{document_id}/permanent")
def ui_documents_permanent(document_id: str, req: UiDocumentPermanent):
    """Keep a document for good (never pruned) or make it temporary again."""
    return _ui_doc(ui_documents.set_permanent, document_id, req.is_permanent)


@app.delete("/api/ui/documents/{document_id}")
def ui_documents_delete(document_id: str):
    return _ui_doc(ui_documents.delete, document_id)



@app.get("/api/llm/models")
def llm_models_endpoint(provider: str = "ollama"):
    """Model choices of a named provider (chain editor in Modelli)."""
    from core.services import llm_providers
    return {"provider": provider, "options": [{"value": m, "label": m} for m in llm_providers.list_models(provider)]}


@app.get("/api/llm/providers")
def llm_providers_endpoint(check: bool = False):
    """Named providers (setting oracle.providers): type, address, key set (never the key), availability,
    models out of quota; ``check`` also lists each available provider's models."""
    from core.services import llm_providers
    from agents.providers import PROVIDER_TYPES
    types = [{"value": t, "label": label} for t, label in llm_providers.TYPES.items()]
    return {"status": "ok", "providers": llm_providers.public_view(check=check), "types": types,
            "class_types": sorted(PROVIDER_TYPES)}


@app.get("/api/llm/chains")
def llm_chains_endpoint():
    """Chains (setting oracle.chains) with each step's state (available, out of quota until)."""
    from core.services import llm_chains
    return {"status": "ok", "chains": llm_chains.chains_view()}


@app.get("/api/llm/usecases")
def llm_usecases_endpoint():
    """Every use case — Oracle's, the ones modules declare in their Hub registration, undeclared ones seen —
    with its effective chain, mode and thinking (overrides: setting oracle.usecases)."""
    from core.services import llm_chains
    return {"status": "ok", "usecases": llm_chains.usecases_view(), "modes": [
        {"value": v, "label": label} for v, label in llm_chains.MODES]}


@app.get("/api/llm/usecases/{use_case}")
def llm_usecase_status_endpoint(use_case: str):
    """What an OpenAI-compatible chat on *use_case* uses now (Forge engine ``oracle``): first usable step,
    context window, whether any usable step is billed."""
    from core.services.llm_gateway import usecase_status
    return {"status": "ok", **usecase_status(use_case)}


# ── External agent MCP bridge (dossier 2026-10-19-oracle-a-blocchi §D): loopback only, one token per turn ─────
def _bridge_guard(request: Request) -> None:
    host = (request.client.host if request.client else "") or ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(status_code=403, detail="bridge is loopback only")


@app.get("/api/agent-bridge/{token}/tools")
def agent_bridge_tools(token: str, request: Request):
    """Tools of the external agent's running turn (the stdio MCP bridge's tools/list)."""
    from core.services import external_agent
    _bridge_guard(request)
    try:
        return {"tools": external_agent.list_tools(token)}
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown or finished turn")


@app.post("/api/agent-bridge/{token}/call")
def agent_bridge_call(token: str, body: dict, request: Request):
    """Run one tool for the external agent (same handler, approval gate and logs as the internal loop)."""
    from core.services import external_agent
    _bridge_guard(request)
    try:
        return external_agent.call_tool(token, str(body.get("name") or ""), body.get("params") or {})
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown or finished turn")


@app.get("/api/llm/usage")
def llm_usage_endpoint(group: str = "module", days: int = 7, module: str = "", session_id: str = "",
                       use_case: str = ""):
    """Usage of the models (panel Cervello → Uso): sums of the calls of the last *days* grouped by
    module | session | usecase | model | step | day (rows kept in Archive, store ``llm-usage``)."""
    from core.services import llm_usage
    try:
        data = llm_usage.query("summary", {"group": group, "days": days, "module": module,
                                           "session_id": session_id, "use_case": use_case})
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"usage not readable: {exc}")
    return {"status": "ok", **(data if isinstance(data, dict) else {"rows": []})}


@app.get("/api/llm/usage/calls")
def llm_usage_calls_endpoint(days: int = 7, module: str = "", session_id: str = "", use_case: str = "",
                             limit: int = 100):
    """Latest single calls (newest first), e.g. the detail of one session."""
    from core.services import llm_usage
    try:
        data = llm_usage.query("rows", {"days": days, "module": module, "session_id": session_id,
                                        "use_case": use_case, "limit": limit})
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"usage not readable: {exc}")
    return {"status": "ok", **(data if isinstance(data, dict) else {"rows": []})}


@app.on_event("startup")
def register_on_hub_startup():
    """Register on Hub now and keep re-registering (Hub restarts lose the registry)."""
    _oracle_settings.settings.start()
    threading.Thread(target=_log_ollama_context, daemon=True, name="ollama-context-check").start()
    _register_on_hub()
    try:
        from hestia_common.startup_utils import start_hub_keepalive
        start_hub_keepalive(_register_on_hub, logger=logger)
    except ImportError:
        logger.warning("[🔄] event=hub_keepalive_unavailable reason=hestia_common_missing")


def _log_ollama_context():
    """Log the context/keep-alive Oracle sends and warn when a loaded model runs smaller."""
    opts = _oracle_settings.ollama_request_options()
    num_ctx = opts["options"]["num_ctx"]
    logger.info("event=ollama_context_config num_ctx=%s keep_alive=%s", num_ctx, opts["keep_alive"])
    base = (os.getenv("OLLAMA_API_URL") or os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
            ).split("/api/")[0].rstrip("/")
    try:
        models = (requests.get(f"{base}/api/ps", timeout=5).json() or {}).get("models") or []
    except Exception as exc:
        logger.debug("event=ollama_ps_unavailable error=%s", exc)
        return
    for m in models:
        loaded = m.get("context_length")
        if loaded and int(loaded) < int(num_ctx):
            logger.warning("[🔄] event=ollama_context_smaller model=%s loaded_ctx=%s wanted=%s "
                           "— reloads with the right size on the next Oracle call", m.get("name"), loaded, num_ctx)


def _register_on_hub():
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    service_base_url = os.getenv(
        "ORACLE_SERVICE_BASE_URL", "http://hestia_oracle:19004")
    payload = {
        "name": "oracle",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "core",
        "service_version": os.getenv("ORACLE_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "chat"],
        "topology_tags": ["layer:cognition", "domain:llm", "status:stable"],
        "capabilities": {
            "chat_endpoint": "/api/chat",
            "mcp_endpoint": f"{service_base_url.rstrip('/')}/mcp",
            **ui.capabilities(service_base_url),
            **_voice_capabilities(),
            **transfer.capabilities(),
        },
    }
    try:
        resp = requests.post(
            f"{hub_api_url}/registry/register", json=payload, timeout=4)
        if resp.status_code < 400:
            logger.debug("event=registered_hub_hub_base_url Registered on Hub | hub=%s base_url=%s",
                         hub_api_url, service_base_url)
        else:
            logger.warning("event=hub_registration_non_success_status Hub registration non-success | status=%s body=%s",
                           resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s", exc)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    notify_target: Optional[str] = None
    force_notification_compiler: Optional[bool] = False
    client_instructions: Optional[str] = None
    # Client name (telegram, webui…): personal chat settings resolve session → client → profile (Themis)
    client: Optional[str] = None
    save_history: bool = True
    # Mode: quick (1 call, no tools) · auto (classify+loop) · thinking (always loop, reasoning) ·
    # cot (deep reasoning, step by step). Empty = the user's setting oracle.chat.mode (Themis).
    mode: str = ""
    # Which use-case model: generic (daily), reasoning (deep), code (coding)
    model: str = "generic"
    # Messages written while the assistant could not answer ([{text, written_at}], oldest first): answered in one
    # turn where the model decides how (oracle-offline v3 C). `message` is ignored when this is set.
    queued: Optional[list[dict]] = None
    # The earlier message the user replied to or quoted ({text, from: assistant|user|notification, at, ref}):
    # context for this turn only, never saved as the user's text (docs/work/2026-10-23-telegram-da-zero §5.10).
    quoted: Optional[dict] = None


class ChatResponse(BaseModel):
    reply: str
    domain_used: str
    session_id: str  # 🆕 We return it so the frontend can remember it


class FormatRequest(BaseModel):
    command: str
    payload: object
    response_prompt: Optional[str] = None
    client_instructions: Optional[str] = None
    client: Optional[str] = None          # personal chat settings (tone…) of this client
    thinking: bool = False
    max_length: Optional[int] = None
    locale: str = "it"


class FormatResponse(BaseModel):
    text: str


class NotificationCompileRequest(BaseModel):
    message: str
    session_id: str
    notify_target: Optional[str] = None


class NotificationCompileResponse(BaseModel):
    ok: bool
    message: str
    signals: list[dict]


class QuestionAnswerRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str
    client: Optional[str] = None  # e.g. "telegram", "web", "voice"


class UserControlsPatch(BaseModel):
    proactive_enabled: Optional[bool] = None
    allowed_categories: Optional[list[str]] = None
    quiet_hours: Optional[dict] = None
    reminder_aggressiveness: Optional[str] = None
    dont_ask_again: Optional[list[str]] = None
    reset_scope: Optional[str] = None


QualityLabel = Literal["excellent", "good", "mixed", "poor", "rejected"]


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    interaction_id: Optional[str] = None
    source_client: Optional[str] = None
    quality_label: Optional[str] = None
    quality_score: Optional[int] = Field(default=None, ge=1, le=5)
    outcome_label: Optional[str] = None
    feedback_text: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class FeedbackResponse(BaseModel):
    ok: bool
    feedback: dict[str, Any]


class ActionApprovalResponseRequest(BaseModel):
    approval_token: str
    approve: bool
    actor: Optional[str] = None
    client_instructions: Optional[str] = None


class AthenaHintIngestRequest(BaseModel):
    hint_id: Optional[str] = None
    source: str = "athena"
    hint_type: str = "focus_brief"
    session_id: Optional[str] = None
    domain: Optional[str] = None
    domains: list[str] = Field(default_factory=list)
    priority: str = "normal"
    summary: str
    brief: dict[str, Any] = Field(default_factory=dict)
    gate: dict[str, Any] = Field(default_factory=dict)
    retrospective: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: Optional[int] = None
    trace_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _models_state() -> str:
    try:
        from core.services import llm_chains
        return llm_chains.models_state()["state"]
    except Exception:
        return "ok"


def _no_usable_model() -> bool:
    """Every step of the general chain is out of quota or not configured. A chain that only failed recently is
    still tried (a success clears it), so the chat refuses only what cannot work."""
    try:
        from core.services import llm_chains
        return llm_chains.models_state()["usable_steps"] == 0
    except Exception:
        return False


@app.get("/health")
def health_endpoint():
    # `models`: ok | limited | none — Argus turns it into «Limitato» / «Non disponibile» (oracle-offline v3 E).
    return {"status": "ok", "service": "hestia_oracle", "models": _models_state()}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_oracle",
        "count": len(rows),
        "logs": rows,
    }

app.include_router(create_log_control_router("hestia_oracle"))

@app.get("/api/tasks")
def list_background_tasks(
    limit: int = 100,
    task_type: str | None = None,
    lifecycle_state: str | None = None,
):
    rows = engine.list_background_tasks(
        limit=limit,
        task_type=task_type,
        lifecycle_state=lifecycle_state,
    )
    return {
        "count": len(rows),
        "tasks": rows,
    }


@app.get("/api/tasks/{task_id}")
def get_background_task(task_id: str):
    row = engine.get_background_task(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"task '{task_id}' not found")
    return {"task": row}


@app.post("/api/athena/hints")
def ingest_athena_hint_endpoint(req: AthenaHintIngestRequest, request: Request):
    """Ingest advisory hints produced by Athena through Hub-routed calls."""
    try:
        trace_id = str(
            request.headers.get("X-Trace-Id") or req.trace_id or "").strip() or None
        result = engine.ingest_athena_hint(
            hint_payload=req.model_dump(exclude_none=True),
            trace_id=trace_id,
        )
        return result
    except Exception as e:
        logger.exception(
            "event=unhandled_error_ingest_athena_hint_endpoint Unhandled error in Athena hint ingest endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/athena/hints")
def list_athena_hints_endpoint(session_id: str | None = None, limit: int = 20):
    try:
        rows = engine.list_athena_hints(session_id=session_id, limit=limit)
        return {
            "count": len(rows),
            "hints": rows,
        }
    except Exception as e:
        logger.exception(
            "event=unhandled_error_list_athena_hints_endpoint Unhandled error in Athena hints list endpoint")
        raise HTTPException(status_code=500, detail=str(e))


# Last real user interaction (Telegram/UI chats carry notify_target; internal
# callers like Argus narration do not). The shared state lives in Chronos (assistant
# presence): each user chat pings it; /api/activity stays as a thin local alias.
_LAST_USER_ACTIVITY = {"ts": 0.0}
from core.services.oracle_presence import presence as _presence, presence_instructions  # noqa: E402


def _mark_user_activity(notify_target: Optional[str], client: Optional[str] = None) -> dict | None:
    """Mark a real user chat (Telegram sends notify_target, the WebUI only its client name). Returns the presence
    state read BEFORE the ping (so the assistant sees how long the user was away, e.g. to say "bentornato")."""
    if not notify_target and not client:
        return None
    _LAST_USER_ACTIVITY["ts"] = time.time()
    state = _presence.get()
    _presence.ping(client or "chat", "chat", force=True)
    return state


@app.get("/api/activity")
def user_activity():
    ts = _LAST_USER_ACTIVITY["ts"]
    return {"last_user_activity_ts": ts or None,
            "idle_seconds": int(time.time() - ts) if ts else None}


def _with_personal_settings(client_instructions: Optional[str], client: Optional[str], session: str,
                            presence_state: dict | None = None) -> str:
    """Client presentation contract + the user's tone/instructions (oracle.chat.*, Themis)
    + one line of assistant presence (state, last interaction, style/notice effects)."""
    parts = [str(client_instructions or "").strip(),
             *_oracle_settings.chat_instructions(client=client or "", session=session),
             *presence_instructions(presence_state)]
    return "\n".join(p for p in parts if p)


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest, request: Request):
    # Who started this turn comes from the routed headers, never from the body (Cindy 6, hestia_common.origin).
    from hestia_common import origin as _origin
    turn_origin = _origin.parse(dict(request.headers), req.client or "")
    presence_state = (_mark_user_activity(req.notify_target, req.client)
                      if turn_origin["level"] == "utente" else None)
    try:
        current_session = req.session_id if req.session_id else str(
            uuid.uuid4())

        # No model can answer (every step out of quota or not configured): refuse like an unreachable Oracle, so
        # the client queues the message and it is answered when a model is back (oracle-offline v3 E).
        if _no_usable_model():
            logger.warning("[🔄] event=chat_refused_no_models session_id=%s", current_session)
            return JSONResponse(status_code=503, content={"detail": "no model available", "models": "none"})
        if turn_origin["level"] == "utente" and not req.queued:
            # A written or spoken message answers the assistant's open question (it is in the history).
            engine.close_open_questions(current_session)
        mode = _oracle_settings.chat_mode(req.mode, client=req.client or "", session=current_session)
        message, instructions = req.message, quoted_context.with_instructions(req.client_instructions, req.quoted)
        queued = [q for q in (req.queued or []) if isinstance(q, dict) and str(q.get("text") or "").strip()]
        if queued:
            message = queued_chat.compose(queued)
            instructions = queued_chat.instructions(queued, instructions)
            mode = "thinking" if len(queued) > 1 else mode  # the agent loop: ask_user may be needed
            logger.info("event=chat_queued_batch session_id=%s items=%d", current_session, len(queued))
        # Return the Engine's output as a continuous stream (LLM usage counted for this session)
        return StreamingResponse(
            llm_stats.bind_session(current_session, engine.chat(
                message, current_session,
                notify_target=req.notify_target,
                force_notification_compiler=bool(req.force_notification_compiler),
                client_instructions=_with_personal_settings(
                    instructions, req.client, current_session, presence_state),
                save_history=req.save_history,
                mode=mode,
                model=req.model,
                client=req.client or "",
                origin=turn_origin), client=req.client or ""),
            media_type="application/x-ndjson"
        )
    except Exception as e:
        logger.exception(
            "event=unhandled_error_chat_endpoint_session Unhandled error in chat endpoint | session=%s", req.session_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/document")
async def chat_document_endpoint(
    message: str = Form(default=""),
    session_id: Optional[str] = Form(default=None),
    notify_target: Optional[str] = Form(default=None),
    client_instructions: Optional[str] = Form(default=None),
    filename: Optional[str] = Form(default=None),
    file: UploadFile = File(...),
    client: Optional[str] = Form(default=None),
):
    """Accept any file type and stream an NDJSON analysis back to the caller.

    Accepts: images, PDFs, audio, video, office docs, text/code files.
    Capability-aware: uses model vision/audio features when available,
    falls back to local extraction (WhisperX, CLIP, YOLO, python-docx, etc.)
    otherwise.
    """
    presence_state = _mark_user_activity(notify_target, client)
    ACCEPTED_MIMES = {
        # Images
        "image/jpeg", "image/jpg", "image/png", "image/webp",
        "image/gif", "image/heic", "image/heif", "image/bmp",
        "image/tiff", "image/svg+xml",
        # PDFs
        "application/pdf",
        # Audio
        "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
        "audio/ogg", "audio/vorbis", "audio/flac", "audio/aac",
        "audio/x-aac", "audio/m4a", "audio/mp4",
        # Video
        "video/mp4", "video/mpeg", "video/webm", "video/ogg",
        "video/quicktime", "video/x-msvideo",
        # Office docs
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        # Text / code / data
        "text/plain", "text/csv", "text/markdown", "text/html",
        "text/xml", "application/xml",
        "application/json",
        "application/x-yaml", "application/yaml",
    }
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    # Accept unknown subtypes of text/ and application/ gracefully
    is_text_like = content_type.startswith("text/") or content_type in (
        "application/json", "application/xml", "application/yaml", "application/x-yaml"
    )
    if content_type not in ACCEPTED_MIMES and not is_text_like:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: '{content_type}'. Send images, PDFs, audio, video, or office/text documents.",
        )
    try:
        file_bytes = await file.read()
        current_session = session_id if session_id else str(uuid.uuid4())
        resolved_filename = filename or file.filename or None

        # Infer a sensible default message per file category
        default_message = "Analizza questo file."
        if content_type.startswith("audio/") or content_type.startswith("video/"):
            default_message = "Trascrivi e riassumi questo file audio/video."
        elif content_type.startswith("image/"):
            default_message = "Descrivi questa immagine."
        elif content_type == "application/pdf":
            default_message = "Riassumi e analizza questo documento."

        return StreamingResponse(
            engine.analyze_document(
                file_bytes=file_bytes,
                mime_type=content_type,
                user_message=message.strip() or default_message,
                session_id=current_session,
                notify_target=notify_target,
                client_instructions=_with_personal_settings(client_instructions, client, current_session,
                                                            presence_state),
                filename=resolved_filename,
            ),
            media_type="application/x-ndjson",
        )
    except Exception as exc:
        logger.exception(
            "event=unhandled_error_document_endpoint Unhandled error in document endpoint")
        raise HTTPException(status_code=500, detail=str(exc))


class DocumentJsonRequest(BaseModel):
    """Same as /api/chat/document but JSON (base64): the Hub envelope cannot carry
    multipart, so Hub clients (WebUI) use this one."""
    message: str = ""
    session_id: Optional[str] = None
    notify_target: Optional[str] = None
    client_instructions: Optional[str] = None
    client: Optional[str] = None
    filename: Optional[str] = None
    mime_type: str = "application/octet-stream"
    content_base64: Optional[str] = None
    data_uri: Optional[str] = None


@app.post("/api/chat/document/json")
async def chat_document_json_endpoint(req: DocumentJsonRequest):
    import base64
    import binascii

    raw = req.content_base64 or ""
    mime = (req.mime_type or "").split(";")[0].strip().lower()
    if not raw and req.data_uri and "," in req.data_uri:
        header, raw = req.data_uri.split(",", 1)
        if header.startswith("data:") and not req.mime_type:
            mime = header[5:].split(";")[0].lower()
    try:
        file_bytes = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="content_base64/data_uri is not valid base64")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="empty document")

    class _Upload:  # minimal UploadFile stand-in for the multipart endpoint
        def __init__(self):
            self.content_type = mime
            self.filename = req.filename

        async def read(self):
            return file_bytes

    return await chat_document_endpoint(
        message=req.message, session_id=req.session_id, notify_target=req.notify_target,
        client_instructions=req.client_instructions, filename=req.filename, file=_Upload(), client=req.client)


@app.post("/api/format", response_model=FormatResponse)
def format_endpoint(req: FormatRequest, request: Request):
    trace_id = str(request.headers.get("X-Trace-Id") or "").strip()
    if trace_id:
        logger.info(
            "event=format_request_received trace_id=%s command=%s payload_type=%s",
            trace_id,
            req.command,
            type(req.payload).__name__,
        )
    try:
        text = engine.format_payload(
            command=req.command,
            payload=req.payload,
            response_prompt=req.response_prompt,
            client_instructions=_with_personal_settings(req.client_instructions, req.client, "")
            if req.client else req.client_instructions,
            thinking=req.thinking,
            max_length=req.max_length,
            locale=req.locale,
            variant_seed=trace_id or None,
        )
        if trace_id:
            logger.info(
                "event=format_request_completed trace_id=%s command=%s output_chars=%s",
                trace_id,
                req.command,
                len(text or ""),
            )
        return {"text": text}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_format_endpoint trace_id=%s Unhandled error in format endpoint",
            trace_id,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/subscriptions/compile", response_model=NotificationCompileResponse)
def compile_subscription_endpoint(req: NotificationCompileRequest):
    try:
        result = engine.compile_notification_shortcut(
            user_message=req.message,
            session_id=req.session_id,
            notify_target=req.notify_target,
        )
        return result
    except Exception as e:
        logger.exception(
            "event=unhandled_error_compile_endpoint Unhandled error in compile endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/question-answer")
def question_answer_endpoint(req: QuestionAnswerRequest):
    """Receive a user's answer to a previously emitted question frame.

    Used by any client (Telegram, web, voice) to close out a pending question.
    Returns 200 with {resolved: true} or 404 if question_id is unknown.
    """
    try:
        resolved = engine.answer_question(req.question_id, req.answer)
        if not resolved:
            raise HTTPException(
                status_code=404,
                detail=f"Question '{req.question_id}' not found or already resolved.",
            )
        action = engine.run_question_action(req.question_id, req.answer, client=req.client or "")
        # A question the model asked (ask_user): the client sends `resume.message` as the next chat turn.
        resume = engine.question_resume_message(req.question_id, req.answer)
        return {"resolved": True, "question_id": req.question_id, **({"action": action} if action else {}),
                **({"resume": {"message": resume}} if resume else {})}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "event=unhandled_error_question_answer_endpoint Unhandled error in question-answer endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/questions")
def open_questions_endpoint(session_id: str):
    """Questions the assistant asked in this session still waiting for an answer (clients redraw them after a reload)."""
    return {"session_id": session_id, "questions": engine.open_questions(session_id)}


@app.post("/api/actions/approval/respond")
def action_approval_response_endpoint(req: ActionApprovalResponseRequest):
    """Resolve a pending high-impact action approval token."""
    try:
        result = engine.respond_high_impact_action_approval(
            approval_token=req.approval_token,
            approve=req.approve,
            actor=req.actor,
            client_instructions=req.client_instructions,
        )
        status = str(result.get("status") or "")
        if status == "not_found":
            raise HTTPException(
                status_code=404, detail="approval token not found or expired")
        if status == "invalid":
            raise HTTPException(status_code=400, detail=str(
                result.get("error") or "invalid approval payload"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "event=unhandled_error_action_approval_response_endpoint Unhandled error in action approval response endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/user/controls")
def get_user_controls_endpoint():
    """Read durable user controllability settings."""
    try:
        return {"controls": engine.get_user_controls()}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_get_user_controls Unhandled error in get user controls endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/user/controls")
def update_user_controls_endpoint(req: UserControlsPatch):
    """Apply partial updates to durable user controllability settings."""
    try:
        controls, saved = engine.update_user_controls(
            req.model_dump(exclude_none=True),
            source="api",
        )
        return {"updated": bool(saved), "controls": controls}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_update_user_controls Unhandled error in update user controls endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/feedback", response_model=FeedbackResponse)
def create_feedback_endpoint(req: FeedbackRequest):
    """Capture explicit quality feedback and store it in Archive via Hub route."""
    try:
        record = engine.submit_feedback(
            quality_label=req.quality_label or "mixed",
            quality_score=req.quality_score,
            session_id=req.session_id,
            interaction_id=req.interaction_id,
            source_client=req.source_client,
            outcome_label=req.outcome_label,
            feedback_text=req.feedback_text,
            tags=req.tags,
            payload=req.payload,
        )
        if not record:
            raise HTTPException(
                status_code=502,
                detail="feedback persistence unavailable",
            )
        return {"ok": True, "feedback": record}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "event=unhandled_error_feedback_endpoint Unhandled error in feedback endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/feedback")
def list_feedback_endpoint(
    session_id: Optional[str] = None,
    quality_label: Optional[QualityLabel] = None,
    source_client: Optional[str] = None,
    limit: int = 200,
):
    """List feedback records for dashboarding or audits."""
    try:
        rows = engine.list_feedback(
            session_id=session_id,
            quality_label=quality_label,
            source_client=source_client,
            limit=limit,
        )
        return {"count": len(rows), "feedback": rows}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_list_feedback_endpoint Unhandled error in list feedback endpoint")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/feedback/export/jsonl")
def export_feedback_jsonl_endpoint(
    session_id: Optional[str] = None,
    quality_label: Optional[QualityLabel] = None,
    source_client: Optional[str] = None,
    limit: int = 1000,
):
    """Export feedback as JSONL for offline quality analysis/training."""
    try:
        jsonl_payload = engine.export_feedback_jsonl(
            session_id=session_id,
            quality_label=quality_label,
            source_client=source_client,
            limit=limit,
        )
        return Response(content=jsonl_payload, media_type="application/x-ndjson")
    except Exception as e:
        logger.exception(
            "event=unhandled_error_feedback_export_endpoint Unhandled error in feedback export endpoint")
        raise HTTPException(status_code=500, detail=str(e))


# ── REST mirrors of Oracle MCP tools (declared paths must exist: Hub
#    discovery, Telegram and the MCP gateway call them via method/path) ──

class MemorySaveRequest(BaseModel):
    fact: str
    domain: str = "general"


@app.post("/api/memory")
def memory_save_endpoint(req: MemorySaveRequest):
    ok, detail = engine._memory_service.save_memory(fact=req.fact, domain=req.domain)
    if not ok:
        raise HTTPException(status_code=502, detail=str(detail))
    return {"status": "saved", "detail": detail}


@app.get("/api/memory")
def memory_search_endpoint(query: str = ""):
    ok, rows = engine._memory_service.search_memories(query=query)
    if not ok:
        raise HTTPException(status_code=502, detail="memory search failed")
    return {"count": len(rows), "memories": rows}


class MemoryNoteRequest(BaseModel):
    facts: Any = ""
    topic: str = ""


@app.post("/api/memory/note")
def memory_note_endpoint(req: MemoryNoteRequest, request: Request):
    """``memory_note``: durable facts from an external AI's conversation. ``X-Hestia-Access`` names the AI."""
    access = request.headers.get("x-hestia-access") or ""
    ok, detail = engine._memory_service.save_note(facts=req.facts, topic=req.topic, access=access)
    if not ok:
        raise HTTPException(status_code=422 if "Archive" not in str(detail) else 502, detail=str(detail))
    return {"status": "saved", **detail}


@app.get("/api/memory/recall")
def memory_recall_endpoint(query: str = ""):
    ok, rows = engine._memory_service.recall(query=query)
    if not ok:
        raise HTTPException(status_code=502, detail="memory recall failed")
    return {"count": len(rows), "memories": rows}


@app.get("/api/documents/search")
def documents_search_endpoint(query: str):
    chunks = engine._doc_rag.search_relevant_chunks(query, None, None) or []
    return {"count": len(chunks), "chunks": chunks}


@app.post("/api/llm/chat")
def llm_chat_endpoint(req: dict):
    """OpenAI-compatible chat (messages + tools) along a use case's chain (Forge engine ``oracle``).
    Body: {use_case?: forge.codice, messages, tools?, temperature?, max_tokens?}"""
    from core.services.llm_gateway import LLMGatewayError, chat
    try:
        return chat(req or {})
    except LLMGatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


class CodeTaskRequest(BaseModel):
    workdir: str
    prompt: str
    append_system_prompt: str = ""
    max_turns: int = 40
    timeout_seconds: int = 1800


@app.get("/api/llm/code/status")
def llm_code_status_endpoint():
    """Is the Claude Code "code" use case ready (installed, token, worktrees mounted)?"""
    from core.services.claude_code_runner import status
    return {"status": "ok", **status()}


@app.post("/api/llm/code")
def llm_code_endpoint(req: CodeTaskRequest):
    """Run a coding task with Claude Code (Pro/Max subscription) inside a Forge
    worktree. Used by Hephaestus Forge engine `claude`."""
    from core.services.claude_code_runner import ClaudeCodeError, run
    try:
        return run(req.workdir, req.prompt, req.append_system_prompt, req.max_turns, req.timeout_seconds)
    except ClaudeCodeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.post("/api/llm/generate")
def llm_generate_endpoint(req: dict):
    """
    Plain generation for services: {"prompt": "...", "use_case": "scout.annunci"}.
    ``use_case`` (declared by the module in its Hub registration) picks the chain (setting oracle.usecases,
    default «Uso generale»); the chain tries its steps in order and skips the ones out of quota.
    Returns: {"response": "...", "model": "...", "provider": "...", "use_case": "...", "chain": "..."}
    """
    from core.services import llm_chains
    prompt = str(req.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    use_case = str(req.get("use_case") or llm_chains.GENERAL).strip().lower()
    from core.services import external_agent
    if external_agent.mode_for(use_case) == "esterna":
        try:   # external agent, one shot without tools
            text = external_agent.ask(prompt, use_case=use_case)
            cfg = external_agent.brain()
            return {"response": text, "model": cfg["model"], "provider": cfg["agent"], "use_case": use_case,
                    "chain": f"agente:{cfg['agent']}"}
        except external_agent.AgentError as exc:
            if external_agent.brain()["fallback"] != "interna":
                raise HTTPException(status_code=503, detail=f"external agent: {exc}")
            logger.warning("[🔄] event=llm_generate_external_failed use_case=%s fallback=interna error=%s",
                           use_case, str(exc)[:200])
    agent = llm_chains.agent_for(use_case)
    try:
        text = agent.ask(prompt)
    except llm_chains.ChainExhausted as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("event=unhandled_error_llm_generate_endpoint use_case=%s", use_case)
        raise HTTPException(status_code=500, detail=str(exc))
    step = llm_chains.last_answered() or {}
    return {"response": text, "model": step.get("model", ""), "provider": step.get("provider", ""),
            "use_case": use_case, "chain": step.get("chain", "")}


@app.delete("/api/chat/{session_id}")
def clear_chat_endpoint(session_id: str):
    try:
        engine.delete_chat_history(session_id)
        return {"status": "cleared", "session_id": session_id}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_clearing_chat_history Unhandled error clearing chat history | session_id=%s", session_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/context")
def get_context_stats(session_id: str):
    """Return context-window usage stats for *session_id*.

    Token counts via Ollama /api/tokenize (cached) with heuristic fallback.
    Context window = setting oracle.provider.ollama.num_ctx (sent to Ollama on every call);
    ``runtime`` = measured per-agent stats of the last calls (prompt size, cache reuse, speed).
    """
    try:
        stats = engine.estimate_context_stats(session_id)
        return {"session_id": session_id, **stats}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_context_stats Unhandled error in context stats | session_id=%s", session_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/compact")
def compact_chat_context(session_id: str):
    """Force-compact conversation history for *session_id*.

    Summarises older messages via the generic model, preserves recent messages
    and protected content ([PREFERENCE], [SUBSCRIPTION], etc.), writes compacted
    history back to Archive.
    """
    try:
        result = engine.compact_context(session_id)
        return {"session_id": session_id, **result}
    except Exception as e:
        logger.exception(
            "event=unhandled_error_context_compact Unhandled error in context compaction | session_id=%s", session_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions")
def get_session_info():
    """Return global Oracle state — active models, uptime, Hub connection."""
    try:
        info = engine.get_session_info()
        return info
    except Exception as e:
        logger.exception(
            "event=unhandled_error_session_info Unhandled error in session info")
        raise HTTPException(status_code=500, detail=str(e))


class EmbedRequest(BaseModel):
    text: str


@app.post("/api/embed")
def embed_endpoint(req: EmbedRequest):
    """Return embedding vector for *text* via Oracle's embedding model.

    The ONLY embedding endpoint in Hestia. All services route through here.
    """
    try:
        vector = engine._embed(req.text)
        return {"embedding": vector, "dimensions": len(vector)}
    except Exception as e:
        logger.exception("event=unhandled_error_embed")
        raise HTTPException(status_code=500, detail=str(e))
