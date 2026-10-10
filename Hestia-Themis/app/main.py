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
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _shared = Path(__file__).resolve().parents[2] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

from .core.hub import Hub, HubError
from .core.registry import Registry
from .core.service import Themis, ThemisError

logger, log_buffer = setup_service_logging("hestia_themis")

SERVICE_NAME = os.getenv("SERVICE_NAME", "themis")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_themis:19016")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "core")
SERVICE_TAGS = [t.strip().lower() for t in os.getenv("SERVICE_TAGS", "core,settings").split(",") if t.strip()]
SERVICE_TOPOLOGY_TAGS = [t.strip().lower() for t in os.getenv(
    "SERVICE_TOPOLOGY_TAGS", "layer:core,domain:settings,status:alpha").split(",") if t.strip()]
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
DATA_DIR = Path(os.getenv("THEMIS_DATA_DIR", "/code/data"))

hub = Hub(HUB_API_URL)
registry = Registry(DATA_DIR / "schema_cache.json")
themis = Themis(hub, registry)

app = FastAPI(title="Hestia-Themis", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
                           body.get("presets") or [], body.get("effective") or {})


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
    return {"proposals": themis.proposals(status=status or None)}


@app.post("/api/settings/proposals")
def settings_propose(body: dict):
    """The assistant (Oracle on request, Athena in autonomy) proposes; the user decides via Hermes."""
    return themis.propose(str(body.get("key") or ""), body.get("value"),
                          proposer=str(body.get("proposer") or "oracle"), reason=str(body.get("reason") or ""),
                          scope=body.get("scope"), scope_id=body.get("scope_id"))


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
                handler=_tool_search, title="⚙️ Cerca impostazioni", method="GET",
                path="/api/settings/search", clients=["ui"], response_mode="oracle_natural",
                telegram_visible=False, telegram_group="impostazioni"),
        MCPTool(name="settings_get",
                description="Dettaglio di un'impostazione: descrizione, valori ammessi, valore attuale, stato.",
                parameters={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
                handler=_tool_get, title="⚙️ Dettaglio impostazione", method="GET",
                path="/api/settings/key/{key}", clients=["ui"], telegram_visible=False,
                telegram_group="impostazioni"),
        MCPTool(name="settings_propose",
                description="Proponi all'utente di cambiare un'impostazione. NON la applica: l'utente "
                            "conferma o rifiuta dalla notifica. Dopo, di' all'utente che la proposta è inviata.",
                parameters={"type": "object", "properties": {
                    "key": {"type": "string"}, "value": {"description": "nuovo valore (tipo dell'impostazione)"},
                    "reason": {"type": "string", "description": "perché, in una frase"}},
                    "required": ["key", "value"]},
                handler=_tool_propose, title="⚙️ Proponi modifica impostazione", method="POST",
                path="/api/settings/proposals", clients=["ui"], telegram_visible=False,
                telegram_group="impostazioni"),
        MCPTool(name="settings_undo",
                description="Proponi di annullare l'ultima modifica di un'impostazione (conferma dell'utente).",
                parameters={"type": "object", "properties": {
                    "key": {"type": "string"}, "reason": {"type": "string"}}, "required": ["key"]},
                handler=_tool_undo, title="⚙️ Annulla modifica impostazione", method="POST",
                path="/api/settings/key/{key}/undo-propose", clients=["ui"], telegram_visible=False,
                telegram_group="impostazioni"),
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
    resp = requests.post(f"{HUB_API_URL}/registry/register", json=_REGISTRATION, timeout=4)
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
