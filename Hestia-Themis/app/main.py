"""Hestia-Themis — central settings.

Modules declare their settings (``hestia_common.settings_client``); every client and the
assistant read/change them here; Archive stores them; Hermes delivers proposals to the user.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _shared = Path(__file__).resolve().parents[2] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

from hestia_common.plugin_client import PluginClient, page
from hestia_common.settings_client import PERSONAL

from .core.hub import Hub, HubError
from .core.registry import Registry
from .core.service import SELF_OWNER, Themis, ThemisError
from .core.transfer import settings_sections
from hestia_common.transfer import FORMAT as TRANSFER_FORMAT, Transfer

logger, log_buffer = setup_service_logging("hestia_themis")

SERVICE_NAME = os.getenv("SERVICE_NAME", "themis")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_themis:19016")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "core")
SERVICE_TAGS = [t.strip().lower() for t in os.getenv("SERVICE_TAGS", "core,settings").split(",") if t.strip()]
SERVICE_TOPOLOGY_TAGS = [t.strip().lower() for t in os.getenv(
    "SERVICE_TOPOLOGY_TAGS", "layer:foundation,domain:settings,status:alpha").split(",") if t.strip()]
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
DATA_DIR = Path(os.getenv("THEMIS_DATA_DIR", "/code/data"))

hub = Hub(HUB_API_URL)
registry = Registry(DATA_DIR / "schema_cache.json")
themis = Themis(hub, registry)
# export / import: every module's settings, one section per module (hestia_common.transfer)
transfer = Transfer("themis", hub, sections=lambda: settings_sections(themis))
# Personal settings shared by every module (week start, currency): Themis owns them, modules follow them.
registry.register(SELF_OWNER, list(PERSONAL.values()))

app = FastAPI(title="Hestia-Themis", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── WebUI plugin (core module, Sistema section): Registro ────────────────────
UI_DIST = os.getenv("THEMIS_UI_DIST", "/ui/dist")   # outside /code: the compose dev mount of app/ must not hide it
ui = PluginClient("themis", title="Themis", icon="settings", color="gray", kind="core", dist=UI_DIST,
                  description="Chi ha cambiato quale impostazione, quando e come: modifiche, proposte, annulla.",
                  version=SERVICE_VERSION)
ui.webui(entry="themis.js", api_prefix="/api/settings/",
         pages=[page("registro", "Registro", element="themis-log", icon="settings", order=160,
                     help="Ogni modifica e proposta di impostazione: chi (tu, Athena, Oracle, un client, un'AI "
                          "esterna), quando, da cosa a cosa. Annulla l'ultima modifica; le proposte aspettano te.")])
app.include_router(ui.router())
app.include_router(transfer.router())   # /api/transfer/* (settings of every module)


@app.exception_handler(ThemisError)
async def _themis_error(_: Request, exc: ThemisError):
    body: dict[str, Any] = {"detail": str(exc)}
    if isinstance(exc.detail, dict):
        body.update(exc.detail)
    return JSONResponse(status_code=exc.status, content=body)


@app.exception_handler(HubError)
async def _hub_error(_: Request, exc: HubError):
    logger.warning("[🔄] event=themis_archive_error status=%s payload=%s", exc.status, str(exc.payload)[:200])
    return JSONResponse(status_code=502, content={"detail": "archivio non disponibile", "upstream": exc.status})


@app.exception_handler(requests.RequestException)
async def _transport_error(_: Request, exc: requests.RequestException):
    logger.warning("[🔄] event=themis_hub_unreachable error=%s", exc)
    return JSONResponse(status_code=503, content={"detail": "hub non raggiungibile"})


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_themis", "version": SERVICE_VERSION,
            "modules": len(registry.modules()), "revision": themis.revision}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    logs = log_buffer.query(limit=limit, level=level, contains=contains)
    return {"service": "hestia_themis", "count": len(logs), "logs": logs}


# ── modules ──────────────────────────────────────────────────────────────────

@app.post("/api/settings/register")
def settings_register(body: dict):
    """A module declares its settings; the answer carries its stored system values."""
    return themis.register(str(body.get("owner") or ""), body.get("definitions") or [],
                           body.get("presets") or [], body.get("effective") or {}, body.get("follows") or [])


@app.get("/api/settings/effective")
def settings_effective():
    """Themis' own settings (the personal ones every module follows): no runtime copy, stored = effective."""
    return {"owner": SELF_OWNER, "loaded": True, "values": {**{k: d["default"] for k, d in PERSONAL.items()},
                                                            **themis.system_values(SELF_OWNER)},
            "pending_restart": []}


@app.get("/api/settings/revision")
def settings_revision():
    """Cheap change marker: clients refetch when it differs from the last one they saw."""
    return {"revision": themis.revision}


@app.get("/api/settings/modules")
def settings_modules():
    """Modules with settings + their live state (from Hub) for the panel's module list/cards."""
    health = {s.get("name"): s for s in hub.status()}
    pending = themis.proposals(status="pending")
    out = []
    for owner in registry.modules():
        entry = registry.module(owner) or {}
        svc = health.get(owner) or {}
        out.append({
            "module": owner, "definitions": len(entry.get("definitions", [])),
            "groups": sorted({d.get("group", "") for d in entry.get("definitions", [])}),
            "registered_at": entry.get("registered_at"),
            "health": svc.get("health") or ("unknown" if svc else "unregistered"),
            "version": svc.get("service_version"), "service_type": svc.get("service_type"),
            "topology_tags": svc.get("topology_tags") or [],
            "pending_proposals": sum(1 for p in pending if str(p.get("key", "")).startswith(f"{owner}.")),
        })
    others = [{"module": name, "definitions": 0, "health": s.get("health"), "version": s.get("service_version"),
               "service_type": s.get("service_type"), "topology_tags": s.get("topology_tags") or []}
              for name, s in health.items() if name and name not in registry.modules()]
    return {"revision": themis.revision, "modules": out, "other_services": others}


# ── settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def settings_list(module: str | None = None, q: str = "", client: str = "", session: str = "",
                  status: bool = True):
    return themis.list(module=module, q=q, client=client, session=session, include_status=status)


@app.get("/api/settings/search")
def settings_search(query: str = "", module: str | None = None, limit: int = 15):
    """Compact search (assistant tool): what a setting is, its current value and where it lives."""
    items = themis.list(module=module, q=query, include_status=False)["items"][: max(1, min(limit, 50))]
    return {"count": len(items), "settings": [
        {"key": i["key"], "label": i.get("label"), "module": i.get("module"), "group": i.get("group"),
         "value": i.get("value"), "default": i.get("default"), "help": (i.get("help") or "")[:200],
         "assistant": i.get("oracle", "propose")} for i in items]}


@app.get("/api/settings/key/{key}")
def settings_get(key: str, client: str = "", session: str = ""):
    return themis.get(key, client=client, session=session)


@app.get("/api/settings/key/{key}/options")
def settings_options(key: str, client: str = "", session: str = ""):
    """Choices for a setting (static, or fetched from the owning module's options_source)."""
    return themis.options(key, client=client, session=session)


@app.put("/api/settings/key/{key}")
def settings_set(key: str, body: dict):
    return themis.set(key, body.get("value"), scope=body.get("scope"), scope_id=body.get("scope_id"),
                      actor=str(body.get("actor") or "user"), reason=str(body.get("reason") or ""))


@app.delete("/api/settings/key/{key}")
def settings_reset(key: str, scope: str | None = None, scope_id: str | None = None, actor: str = "user"):
    return themis.reset(key, scope=scope, scope_id=scope_id, actor=actor)


@app.get("/api/settings/key/{key}/history")
def settings_history(key: str, scope: str = "system", scope_id: str = "", limit: int = 10):
    return {"key": key, "history": themis.history(key, scope=scope, scope_id=scope_id, limit=limit)}


@app.get("/api/settings/history")
def settings_history_all(limit: int = 50, offset: int = 0, module: str = "", actor: str = "", key: str = "",
                         sessions: bool = False):
    """Every setting change (all keys, newest first, paged): who, when, old → new, ``undoable``
    (WebUI plugin page «Registro»). ``actor`` = comma list of user | oracle | athena | external (any external:<name>) | <client>…"""
    return themis.history_all(limit=limit, offset=offset, module=module, actor=actor, key=key, sessions=sessions)


@app.post("/api/settings/key/{key}/undo")
def settings_undo(key: str, body: dict | None = None):
    body = body or {}
    return themis.undo(key, scope=body.get("scope") or "system", scope_id=body.get("scope_id") or "",
                       actor=str(body.get("actor") or "user"))


@app.post("/api/settings/presets/{module}/{preset_id}/apply")
def settings_apply_preset(module: str, preset_id: str, body: dict | None = None):
    return themis.apply_preset(module, preset_id, actor=str((body or {}).get("actor") or "user"))


@app.post("/api/settings/sessions/{session}/init")
def settings_init_session(session: str, body: dict | None = None):
    """New chat session: start from the profile defaults (like Claude/Codex)."""
    return themis.init_session(session, str((body or {}).get("client") or ""))


# ── proposals ────────────────────────────────────────────────────────────────

@app.get("/api/settings/proposals")
def settings_proposals(status: str | None = "pending"):
    """``status`` pending (default) | approved | rejected | expired | all (or empty)."""
    return {"proposals": themis.proposals(status=None if status in (None, "", "all") else status)}


@app.post("/api/settings/proposals")
def settings_propose(body: dict, x_session_id: str = Header(default=""), x_hestia_client: str = Header(default=""),
                     x_hestia_access: str = Header(default="")):
    """The assistant (Oracle on request, Athena in autonomy) proposes; the user decides.
    Born in a chat (Oracle sends ``X-Session-Id`` + ``X-Hestia-Client``) → confirmation card in that chat
    (``confirm`` in the answer); otherwise via Hermes. An external AI (``X-Hestia-Access`` from the Hestia-MCP
    door) proposes under its access name and never picks the confirmation chat."""
    origin = body.get("origin") if isinstance(body.get("origin"), dict) else None
    if x_hestia_access:
        origin, proposer = None, f"external:{x_hestia_access}"
    else:
        proposer = str(body.get("proposer") or "oracle")
        if not origin and x_session_id and x_hestia_client:
            origin = {"client": x_hestia_client, "session_id": x_session_id}
    return themis.propose(str(body.get("key") or ""), body.get("value"),
                          proposer=proposer, reason=str(body.get("reason") or ""),
                          scope=body.get("scope"), scope_id=body.get("scope_id"), origin=origin)


@app.post("/api/settings/proposals/{proposal_id}/approve")
def settings_approve(proposal_id: str, body: dict | None = None):
    return themis.decide(proposal_id, True, by=str((body or {}).get("by") or "user"))


@app.post("/api/settings/proposals/{proposal_id}/reject")
def settings_reject(proposal_id: str, body: dict | None = None):
    return themis.decide(proposal_id, False, by=str((body or {}).get("by") or "user"))


@app.post("/api/settings/key/{key}/undo-propose")
def settings_undo_propose(key: str, body: dict | None = None):
    """Assistant undo: proposes the value before the last change (still confirmed by the user)."""
    rows = themis.history(key, limit=1)
    if not rows:
        raise ThemisError("niente da annullare", 404)
    d = registry.definition(key) or {}
    old = rows[0].get("old_value")
    return themis.propose(key, d.get("default") if old is None else old,
                          proposer=str((body or {}).get("proposer") or "oracle"),
                          reason=str((body or {}).get("reason") or "annulla l'ultima modifica"))


# ── MCP tools (aggregated by Hestia-MCP; the assistant uses them on demand) ──
try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    def _tool_search(query: str = "", module: str = "", limit: int = 10) -> dict:
        return settings_search(query=query, module=module or None, limit=limit)

    def _tool_get(key: str = "") -> dict:
        item = themis.get(key)
        keep = ("key", "label", "module", "group", "help", "type", "value", "default", "options", "min", "max",
                "unit", "apply", "status", "source", "oracle")
        return {k: item.get(k) for k in keep if k in item}

    def _tool_propose(key: str = "", value: Any = None, reason: str = "") -> dict:
        return themis.propose(key, value, proposer="oracle", reason=reason)

    def _tool_undo(key: str = "", reason: str = "") -> dict:
        return settings_undo_propose(key, {"proposer": "oracle", "reason": reason or "annulla l'ultima modifica"})

    _themis_mcp_tools = [
        MCPTool(name="settings_search",
                description="Cerca impostazioni di Hestia (tutti i moduli) per parole: cosa fanno, valore attuale.",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string", "description": "parole da cercare (es. modello codice)"},
                    "module": {"type": "string", "description": "modulo opzionale (oracle, argus…)"},
                    "limit": {"type": "integer"}}},
                handler=_tool_search, title="Cerca impostazioni", method="GET",
                path="/api/settings/search", clients=["ui", "external"], response_mode="oracle_natural",
                telegram_visible=False, telegram_group="sistema",
                telegram={"section": "Impostazioni", "primary": 5, "label": "Impostazioni"}),
        MCPTool(name="settings_get",
                description="Dettaglio di un'impostazione: descrizione, valori ammessi, valore attuale, stato.",
                parameters={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
                handler=_tool_get, title="Dettaglio impostazione", method="GET",
                path="/api/settings/key/{key}", clients=["ui", "external"], telegram_visible=False,
                telegram_group="sistema",
                telegram={"section": "Impostazioni"}),
        MCPTool(name="settings_propose",
                description="Proponi all'utente di cambiare un'impostazione. NON la applica: l'utente "
                            "conferma o rifiuta dalla notifica. Dopo, di' all'utente che la proposta è inviata.",
                parameters={"type": "object", "properties": {
                    "key": {"type": "string"}, "value": {"description": "nuovo valore (tipo dell'impostazione)"},
                    "reason": {"type": "string", "description": "perché, in una frase"}},
                    "required": ["key", "value"]},
                handler=_tool_propose, title="Cambia un'impostazione", method="POST",
                path="/api/settings/proposals", clients=["ui", "external"], telegram_visible=False,
                telegram_group="sistema",
                telegram={"section": "Impostazioni"}),
        MCPTool(name="settings_undo",
                description="Proponi di annullare l'ultima modifica di un'impostazione (conferma dell'utente).",
                parameters={"type": "object", "properties": {
                    "key": {"type": "string"}, "reason": {"type": "string"}}, "required": ["key"]},
                handler=_tool_undo, title="Annulla una modifica", method="POST",
                path="/api/settings/key/{key}/undo-propose", clients=["ui"], telegram_visible=False,
                telegram_group="sistema",
                telegram={"section": "Impostazioni"}),
    ]
    app.include_router(create_mcp_router(_themis_mcp_tools, service_name="themis"))
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=themis reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_themis"))


# ── Hub registration ─────────────────────────────────────────────────────────
_REGISTRATION = {
    "name": SERVICE_NAME, "base_url": SERVICE_BASE_URL, "health_endpoint": "/health",
    "service_type": SERVICE_TYPE, "service_version": SERVICE_VERSION, "tags": SERVICE_TAGS,
    "topology_tags": SERVICE_TOPOLOGY_TAGS,
    "capabilities": {"mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp",
                     # Assistant tools appear when the chat is about Hestia itself / its settings.
                     "module_tool_domains": ["system", "settings"],
                     "settings": "/api/settings", "settings_register": "/api/settings/register",
                     "settings_revision": "/api/settings/revision"},
}


def _register() -> None:
    payload = {**_REGISTRATION, "capabilities": {**_REGISTRATION["capabilities"], **ui.capabilities(SERVICE_BASE_URL),
                                                 "transfer": {"endpoint": "/api/transfer", "format": TRANSFER_FORMAT,
                                                              "settings": True}}}
    resp = requests.post(f"{HUB_API_URL}/registry/register", json=payload, timeout=4)
    if resp.status_code >= 400:
        logger.warning("event=hub_registration_non_success status=%s body=%s", resp.status_code, resp.text[:200])
    else:
        logger.info("event=registered_on_hub hub=%s base_url=%s", HUB_API_URL, SERVICE_BASE_URL)


@app.on_event("startup")
def register_on_hub_startup():
    try:
        _register()
    except Exception as exc:
        logger.warning("[🔄] event=hub_registration_failed_non_fatal error=%s", exc)
    from hestia_common.startup_utils import start_hub_keepalive
    start_hub_keepalive(_register, logger=logger, name="themis-hub-keepalive")
