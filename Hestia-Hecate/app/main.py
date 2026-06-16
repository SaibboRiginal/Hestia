import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from providers.registry import CalendarProviderRegistry
from schemas.calendar_events import CalendarEvent

from core.registry import get_fetcher_class, FETCHER_REGISTRY
from core.archive_client import ArchiveClient
from core.state_manager import StateManager

load_dotenv()

try:
    from hestia_common.logging_utils import setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging

logger, log_buffer = setup_service_logging("hestia_hecate")

app = FastAPI(title="Hestia-Hecate Gateway", version="3.1")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────────────────────────────
#  MCP tools
# ─────────────────────────────────────────────────────────────────────

try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    _hecate_mcp_tools = [
        MCPTool(
            name="sync_calendar",
            description="Sincronizza gli eventi del calendario da Google e Outlook in Hestia",
            parameters={
                "type": "object",
                "properties": {
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "Calendar fetcher sources: gcal, outlook_calendar"},
                    "calendar_id": {"type": "string", "description": "Calendar ID to fetch from each provider"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "sync_calendar", "params": kw},
            title="\U0001f504 Sincronizza calendario", method="POST", path="/api/ingest/calendar/trigger",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Conferma la sincronizzazione del calendario. Indica quanti eventi "
                "sono stati trovati per ogni provider (Google, Outlook). "
                "Sii conciso e usa un tono da assistente."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
        MCPTool(
            name="gateway_auth_status",
            description="Verifica quali provider (Google, Outlook) sono autenticati e attivi",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "gateway_auth_status", "params": kw},
            title="\U0001f510 Stato autenticazione provider", method="GET", path="/api/gateway/auth/status",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Elenca i provider configurati e il loro stato di autenticazione. "
                "Sii diretto e usa un tono da assistente."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
        MCPTool(
            name="gateway_auth_initiate_google",
            description="Avvia il flusso OAuth per Google Calendar",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "gateway_auth_initiate_google", "params": kw},
            title="\U0001f511 Connetti Google Calendar", method="POST", path="/api/gateway/auth/initiate/google",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Presenta il link di autorizzazione Google all'utente. "
                "Invita l'utente ad aprire il link, concedere l'accesso e poi "
                "inviare il codice via POST /api/gateway/auth/complete/google."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
        MCPTool(
            name="gateway_auth_initiate_microsoft",
            description="Avvia il flusso device-code OAuth per Outlook/Microsoft",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "gateway_auth_initiate_microsoft", "params": kw},
            title="\U0001f511 Connetti Outlook Calendar", method="POST", path="/api/gateway/auth/initiate/microsoft",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Presenta il codice device e l'URL di verifica Microsoft all'utente. "
                "Invita l'utente ad aprire l'URL e inserire il codice. "
                "Poi usa GET /api/gateway/auth/poll/microsoft per verificare il completamento."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
        MCPTool(
            name="gateway_auth_poll",
            description="Controlla se l'utente ha completato il flusso OAuth",
            parameters={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "Provider da verificare (google, microsoft)"},
                },
                "required": ["provider"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "gateway_auth_poll", "params": kw},
            title="⏳ Verifica completamento autenticazione", method="GET", path="/api/gateway/auth/poll/{provider}",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Comunica all'utente se l'autenticazione è stata completata con successo "
                "o se è ancora in attesa. Sii diretto."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
    ]
    app.include_router(create_mcp_router(_hecate_mcp_tools, service_name="hecate"))
    logger.info("event=mcp_router_mounted service=hecate")
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=hecate reason=hestia_common_not_available")

vault = ArchiveClient(api_url="")
memory = StateManager("data/state.json")  # Move this to a mounted volume!
_calendar_registry = CalendarProviderRegistry()

_CALENDAR_SOURCES = {"gcal", "outlook_calendar"}


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _provider_env_is_configured(provider: str) -> bool:
    if provider == "google":
        return bool(
            os.getenv("GOOGLE_TOKEN_JSON")
            or os.getenv("GOOGLE_CREDENTIALS_JSON")
            or (
                os.getenv("GOOGLE_CLIENT_ID")
                and os.getenv("GOOGLE_CLIENT_SECRET")
                and os.getenv("GOOGLE_REFRESH_TOKEN")
            )
        )
    if provider == "microsoft":
        return bool(
            os.getenv("OUTLOOK_CLIENT_ID")
            and os.getenv("OUTLOOK_CLIENT_SECRET")
            and os.getenv("OUTLOOK_TENANT_ID")
            and os.getenv("OUTLOOK_REFRESH_TOKEN")
        )
    return False


def detect_gateway_providers() -> list[dict[str, object]]:
    providers: list[dict[str, object]] = []
    for provider in ("google", "microsoft"):
        force_enabled = _parse_bool(
            os.getenv(f"HECATE_ENABLE_PROVIDER_{provider.upper()}"),
            default=False,
        )
        configured = _provider_env_is_configured(provider)
        enabled = force_enabled or configured
        if not enabled:
            continue
        providers.append(
            {
                "provider": provider,
                "configured": configured,
                "enabled": enabled,
                "auth_status": "configured" if configured else "enabled_without_credentials",
            }
        )
    return providers


def _normalize_provider_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = str(name).strip().lower()
    if normalized == "microsoft":
        return "outlook"
    return normalized


def _resolve_target_providers(targets: list[str] | None) -> list[str]:
    if not targets:
        return []
    resolved: list[str] = []
    for item in targets:
        normalized = _normalize_provider_name(item)
        if normalized:
            resolved.append(normalized)
    return resolved


def _refresh_calendar_registry() -> dict:
    """Refresh credentials for all active providers in-place.

    Calling ``provider.refresh()`` re-acquires the access token without
    tearing down and re-creating the full registry.  If all active providers
    fail to refresh we fall back to a full registry re-initialisation so the
    caller always gets a usable status report.
    """
    global _calendar_registry  # must be declared before first use of the name

    refreshed_any = False
    for provider in _calendar_registry.active_providers:
        try:
            ok = provider.refresh()
            logger.info(
                "event=provider_refreshed provider=%s available=%s", provider.name, ok
            )
            refreshed_any = ok or refreshed_any
        except Exception as exc:
            logger.warning(
                "event=provider_refresh_error provider=%s error=%s", provider.name, exc
            )

    if not refreshed_any:
        # Fallback: full registry reinit (covers the case where no providers
        # were active and a new token may have been injected via env)
        _calendar_registry = CalendarProviderRegistry()
        logger.info(
            "event=calendar_registry_reinitialized No active providers; reinitialised registry")

    return _calendar_registry.status_report()


def _route_via_hub(
    service: str,
    path: str,
    *,
    method: str,
    query: dict | None = None,
    body: dict | None = None,
    timeout_seconds: float = 12.0,
    auth_refresh_provider: str | None = None,
) -> tuple[int, dict]:
    import requests

    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    envelope = {
        "method": method,
        "headers": {},
        "query": query or {},
        "body": body,
        "timeout_seconds": timeout_seconds,
    }
    response = requests.post(
        f"{hub_api_url}/route/{service}/{path.lstrip('/')}",
        json=envelope,
        timeout=max(5.0, timeout_seconds + 2.0),
    )
    response.raise_for_status()
    routed = response.json() if response.content else {}
    status_code = int((routed or {}).get("status_code", 500))
    payload = (routed or {}).get("payload") or {}

    # If an upstream provider token expired, refresh once and retry the call.
    if status_code == 401 and auth_refresh_provider:
        try:
            gateway_auth_refresh(auth_refresh_provider)
        except Exception as exc:
            logger.warning(
                "event=gateway_auth_refresh_failed Provider auth refresh failed | provider=%s error=%s",
                auth_refresh_provider,
                exc,
            )
            return status_code, payload

        retry_response = requests.post(
            f"{hub_api_url}/route/{service}/{path.lstrip('/')}",
            json=envelope,
            timeout=max(5.0, timeout_seconds + 2.0),
        )
        retry_response.raise_for_status()
        retry_routed = retry_response.json() if retry_response.content else {}
        return int((retry_routed or {}).get("status_code", 500)), (retry_routed or {}).get("payload") or {}

    return status_code, payload


@app.on_event("startup")
def register_on_hub_startup():
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    service_base_url = os.getenv(
        "HECATE_SERVICE_BASE_URL", "http://hestia_hecate:19003"
    )
    payload = {
        "name": "hecate",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "core",
        "service_version": os.getenv("HECATE_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "connector"],
        "topology_tags": ["layer:gateway", "domain:auth_api", "status:stable"],
        "capabilities": {
            "ingest_trigger": "/api/ingest/trigger",
            "calendar_sync": "/api/ingest/calendar/trigger",
            "mcp_endpoint": f"{service_base_url.rstrip('/')}/mcp",
        },
    }
    try:
        import requests
        resp = requests.post(
            f"{hub_api_url}/registry/register", json=payload, timeout=4)
        if resp.status_code < 400:
            logger.info("event=registered_hub_hub_base_url Registered on Hub | hub=%s base_url=%s",
                        hub_api_url, service_base_url)
        else:
            logger.warning("event=hub_registration_non_success_status Hub registration non-success | status=%s body=%s",
                           resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s", exc)

    # Periodically re-register with Hub so a Hub restart doesn't lose this service.
    def _hub_keepalive():
        import time
        while True:
            time.sleep(60)
            try:
                import requests as _req
                _req.post(f"{hub_api_url}/registry/register",
                          json=payload, timeout=4)
            except Exception as exc:
                logger.warning(
                    "event=hub_keepalive_registration_failed Hub keepalive registration failed: %s", exc)
    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hecate"}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_hecate",
        "count": len(rows),
        "logs": rows,
    }


class FetchCommand(BaseModel):
    domain: str = Field(..., description="The context, e.g., 'real_estate'")
    source: str = Field(...,
                        description="The fetcher to use, e.g., 'gmail_imap'")
    filter_query: str = Field(
        ..., description="The targeted query, e.g., 'FROM \"alerts@casa.it\"'")


@app.post("/api/ingest/trigger")
def trigger_fetch(command: FetchCommand):
    logger.info("event=ingest_trigger_domain_source Ingest trigger | domain=%s source=%s",
                command.domain, command.source)

    try:
        FetcherClass = get_fetcher_class(command.source)
        fetcher_instance = FetcherClass()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_name = f"{command.source}_{command.domain}"
    last_run = memory.get_last_run_date(task_name)

    if not fetcher_instance.connect():
        raise HTTPException(
            status_code=500, detail="Fetcher connection failed.")

    # THE CLEANUP: Use try/finally to ensure disconnect is ALWAYS called
    try:
        logger.info("event=fetching_since_task Fetching since %s | task=%s",
                    last_run.strftime("%Y-%m-%d"), task_name)
        raw_data = fetcher_instance.fetch_new_data(
            since_date=last_run, custom_filter=command.filter_query)
        logger.info("event=fetched_items_task Fetched %d items | task=%s", len(
            raw_data), task_name)

        for item in raw_data:
            vault.ship_record(
                payload=item,
                domain=command.domain,
                source=command.source,
                reference_id=item.get("reference_id")
            )

        # Only update memory if the whole batch shipped successfully
        memory.mark_as_run(task_name)
        return {"status": "success", "fetched": len(raw_data)}

    except Exception as e:
        logger.error(
            "event=critical_error_during_extraction_shipping Critical error during extraction/shipping | task=%s error=%s", task_name, e)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # This will ALWAYS run, closing the connection safely.
        fetcher_instance.disconnect()


class CalendarSyncCommand(BaseModel):
    """Request body for the calendar sync trigger.

    Leave ``sources`` empty to sync all configured calendar providers.
    ``calendar_id`` is the calendar identifier within each provider
    (e.g. "primary", or a specific Google Calendar email address).
    """
    sources: list[str] = Field(
        default_factory=list,
        description="Calendar fetcher sources to sync: 'gcal', 'outlook_calendar'. "
                    "Empty means all calendar sources.",
    )
    calendar_id: str = Field(
        "primary",
        description="Calendar id to fetch from each provider.",
    )


@app.post("/api/ingest/calendar/trigger")
def trigger_calendar_sync(command: CalendarSyncCommand):
    """Fetch calendar events from Google and/or Outlook and archive them as CalendarItems.

    Unlike the generic /api/ingest/trigger, this endpoint writes to
    Archive's /api/calendar/items (CalendarItem table) rather than the raw
    archive store, enabling the Chronos notification worker and Oracle to
    access a unified calendar view without querying each provider directly.
    """
    from datetime import datetime, timedelta, timezone as _tz

    sources = command.sources or list(_CALENDAR_SOURCES)
    # Keep only valid calendar sources
    sources = [s for s in sources if s in _CALENDAR_SOURCES]
    if not sources:
        raise HTTPException(
            status_code=400,
            detail=f"No valid calendar sources specified. Available: {sorted(_CALENDAR_SOURCES)}",
        )

    results: dict[str, dict] = {}
    # HECATE_CALENDAR_BACKFILL_DAYS: how many days back to include recent past events (default 7)
    backfill_days = int(os.getenv("HECATE_CALENDAR_BACKFILL_DAYS", "7"))
    since = datetime.now(_tz.utc) - timedelta(days=backfill_days)
    logger.info("event=calendar_sync_sources_backfill_days_since Calendar sync | sources=%s backfill_days=%d since=%s",
                sources, backfill_days, since.date())

    for source in sources:
        try:
            FetcherClass = get_fetcher_class(source)
            fetcher = FetcherClass()
        except ValueError as exc:
            results[source] = {"error": str(exc), "fetched": 0, "archived": 0}
            continue

        if not fetcher.connect():
            logger.warning(
                "event=calendar_connection_failed_source Calendar connection failed | source=%s", source)
            results[source] = {"error": "Connection failed",
                               "fetched": 0, "archived": 0}
            continue

        try:
            items = fetcher.fetch_new_data(
                since_date=since,
                custom_filter=command.calendar_id,
            )
            archived = 0
            for item in items:
                if vault.ship_calendar_item(item):
                    archived += 1
            logger.info("event=calendar_sync_done_source_fetched Calendar sync done | source=%s fetched=%d archived=%d", source, len(
                items), archived)
            results[source] = {"fetched": len(items), "archived": archived}
        except Exception as exc:
            logger.error(
                "event=calendar_sync_error_source_error Calendar sync error | source=%s error=%s", source, exc)
            results[source] = {"error": str(exc), "fetched": 0, "archived": 0}
        finally:
            fetcher.disconnect()

    total_archived = sum(r.get("archived", 0) for r in results.values())
    logger.info("event=calendar_sync_complete_total_archived_sources Calendar sync complete | total_archived=%d sources=%s",
                total_archived, list(results.keys()))
    return {"status": "success", "sources": results, "total_archived": total_archived}


@app.get("/api/gateway/providers")
def gateway_providers():
    providers = detect_gateway_providers()
    return {
        "status": "ok",
        "count": len(providers),
        "providers": providers,
        "runtime": _calendar_registry.status_report(),
    }


@app.get("/api/gateway/auth/status")
def gateway_auth_status():
    providers = detect_gateway_providers()
    return {
        "status": "ok",
        "providers": providers,
        "runtime": _calendar_registry.status_report(),
    }


@app.post("/api/gateway/auth/refresh/{provider}")
def gateway_auth_refresh(provider: str):
    normalized = provider.strip().lower()
    available = {row["provider"] for row in detect_gateway_providers()}
    if normalized not in {"google", "microsoft"}:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    if normalized not in available:
        return {"status": "ok", "provider": normalized, "refreshed": False, "reason": "provider_not_configured"}
    runtime = _refresh_calendar_registry()
    target_runtime = "outlook" if normalized == "microsoft" else normalized
    return {
        "status": "ok",
        "provider": normalized,
        "refreshed": target_runtime in runtime.get("active", []),
        "details": runtime,
    }


@app.get("/api/gateway/calendar/events")
def gateway_calendar_events(
    start_datetime: str | None = None,
    end_datetime: str | None = None,
    provider: str | None = None,
    calendar_id: str = "primary",
    max_results: int = 50,
):
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(start_datetime) if start_datetime else now
    end = datetime.fromisoformat(
        end_datetime) if end_datetime else (now + timedelta(days=30))
    requested = [_normalize_provider_name(provider)] if provider else []
    providers = _calendar_registry.resolve([p for p in requested if p])
    if not providers and requested:
        raise HTTPException(
            status_code=404, detail=f"Provider '{provider}' not available")
    if not providers:
        providers = _calendar_registry.active_providers

    events: list[dict] = []
    errors: dict[str, str] = {}
    for row in providers:
        try:
            listed = row.list_events(
                start=start,
                end=end,
                calendar_id=calendar_id,
                max_results=max(1, min(max_results, 250)),
            )
            events.extend([item.model_dump() for item in listed])
        except Exception as exc:
            errors[row.name] = str(exc)

    events.sort(key=lambda item: str(item.get("start_datetime") or ""))
    return {"events": events, "provider_errors": errors}


@app.post("/api/gateway/calendar/events")
def gateway_calendar_create(body: dict):
    event_data = body.get("event") if isinstance(body, dict) else None
    if not isinstance(event_data, dict):
        raise HTTPException(status_code=400, detail="Missing 'event' payload")
    event = CalendarEvent.model_validate(event_data)
    requested = _resolve_target_providers(
        body.get("target_providers") if isinstance(body, dict) else [])
    providers = _calendar_registry.resolve(requested)
    if not providers:
        providers = _calendar_registry.active_providers
    if not providers:
        raise HTTPException(
            status_code=503, detail="No calendar providers available")

    calendar_id = str(body.get("calendar_id", "primary")
                      ) if isinstance(body, dict) else "primary"
    results: list[dict] = []
    for row in providers:
        try:
            event_id = row.create_event(event, calendar_id=calendar_id)
            results.append({"provider": row.name, "success": True,
                           "event_id": event_id, "error": None})
            vault.ship_calendar_item(
                {
                    "external_id": event_id,
                    "source": row.name,
                    "kind": "event",
                    "title": event.title,
                    "description": event.description,
                    "start_at": event.start_datetime.isoformat(),
                    "end_at": event.end_datetime.isoformat(),
                    "all_day": event.all_day,
                    "location": event.location,
                    "nag_enabled": True,
                }
            )
        except Exception as exc:
            results.append({"provider": row.name, "success": False,
                           "event_id": None, "error": str(exc)})

    total_created = sum(1 for result in results if result.get("success"))
    return {
        "results": results,
        "total_created": total_created,
        "total_failed": len(results) - total_created,
    }


@app.put("/api/gateway/calendar/events/{event_id}")
def gateway_calendar_update(event_id: str, body: dict):
    provider_name = _normalize_provider_name(
        body.get("provider") if isinstance(body, dict) else None)
    if not provider_name:
        raise HTTPException(status_code=400, detail="Missing provider")
    target = _calendar_registry.get(provider_name)
    if target is None:
        raise HTTPException(
            status_code=404, detail=f"Provider '{provider_name}' not available")
    updates = body.get("updates") if isinstance(body, dict) else None
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="Missing updates payload")
    ok = target.update_event(
        event_id,
        updates,
        calendar_id=str(body.get("calendar_id", "primary")),
    )
    return {"success": bool(ok)}


@app.delete("/api/gateway/calendar/events/{event_id}")
def gateway_calendar_delete(event_id: str, provider: str, calendar_id: str = "primary"):
    normalized = _normalize_provider_name(provider)
    target = _calendar_registry.get(normalized or "")
    if target is None:
        raise HTTPException(
            status_code=404, detail=f"Provider '{provider}' not available")
    deleted = target.delete_event(event_id, calendar_id=calendar_id)
    return {"success": bool(deleted)}


@app.get("/api/gateway/email/messages")
def gateway_email_messages(q: str = "", limit: int = 20):
    status_code, payload = _route_via_hub(
        "iris",
        "/api/email/messages",
        method="GET",
        query={"q": q, "limit": max(1, min(limit, 200))},
        timeout_seconds=15,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return payload


@app.get("/api/gateway/email/messages/{message_id}")
def gateway_email_message(message_id: str):
    status_code, payload = _route_via_hub(
        "iris",
        "/api/email/messages",
        method="GET",
        query={"q": message_id, "limit": 50},
        timeout_seconds=15,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)

    rows = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(
            status_code=502, detail="Invalid iris response payload")
    for row in rows:
        if str((row or {}).get("id", "")) == message_id:
            return {"status": "ok", "message": row}
    raise HTTPException(
        status_code=404, detail=f"message '{message_id}' not found")


@app.post("/api/gateway/email/send")
def gateway_email_send(body: dict):
    status_code, payload = _route_via_hub(
        "iris",
        "/api/email/send",
        method="POST",
        body=body,
        timeout_seconds=15,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return payload


# ---------------------------------------------------------------------------
# OAuth Initiation Flow
# ---------------------------------------------------------------------------
# In-memory store for pending device-code auth sessions.  Each entry is keyed
# by provider name and holds the data needed to poll for completion.
_pending_auth: dict[str, dict] = {}


@app.post("/api/gateway/auth/initiate/{provider}")
def gateway_auth_initiate(provider: str):
    """Start an OAuth flow for the given provider.

    • Google  → returns an ``auth_url`` the user must open in a browser.
      After granting access, the browser shows a code; pass it to
      ``POST /api/gateway/auth/complete/google`` with ``{"code": "<code>"}``.

    • Microsoft → uses MSAL device-code flow: returns a ``verification_url``
      and ``user_code``.  Poll ``GET /api/gateway/auth/poll/microsoft`` until
      the user finishes.
    """
    normalized = provider.strip().lower()
    if normalized not in {"google", "microsoft"}:
        raise HTTPException(
            status_code=400, detail=f"Unsupported provider: {provider}")

    if normalized == "google":
        return _initiate_google_oauth()
    return _initiate_microsoft_oauth()


@app.get("/api/gateway/auth/poll/{provider}")
def gateway_auth_poll(provider: str):
    """Poll whether the user has completed the device-code OAuth flow.

    Returns ``{"status": "authorized"}`` once the token has been acquired and
    the provider registry refreshed.  Returns ``{"status": "pending"}`` while
    still waiting.
    """
    normalized = provider.strip().lower()
    if normalized not in _pending_auth:
        return {"status": "no_pending_flow", "provider": normalized}

    if normalized == "microsoft":
        return _poll_microsoft_oauth()
    # Google uses the redirect/code path; use poll to check session presence
    session = _pending_auth.get("google", {})
    return {"status": "pending", "provider": "google", "auth_url": session.get("auth_url")}


@app.delete("/api/gateway/auth/initiate/{provider}")
def gateway_auth_cancel(provider: str):
    """Cancel a pending OAuth device-code flow."""
    normalized = provider.strip().lower()
    _pending_auth.pop(normalized, None)
    return {"status": "cancelled", "provider": normalized}


@app.post("/api/gateway/auth/complete/{provider}")
def gateway_auth_complete(provider: str, body: dict):
    """Exchange the authorization code returned by Google OAuth for a token.

    For Google: pass ``{"code": "<code-from-browser>"}`` in the request body.
    For Microsoft: pass ``{"code": "<device-code>"}`` — use poll instead.
    """
    normalized = provider.strip().lower()
    if normalized == "google":
        return _complete_google_oauth(body)
    if normalized == "microsoft":
        return _poll_microsoft_oauth()
    raise HTTPException(
        status_code=400, detail=f"Unsupported provider: {provider}")


# ---------------------------------------------------------------------------
# Import availability flags (set once at module load)
# ---------------------------------------------------------------------------
try:
    from google.oauth2 import service_account as _sa  # noqa: F401
    _GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    _GOOGLE_LIBS_AVAILABLE = False

try:
    import msal as _msal_check  # noqa: F401
    _OUTLOOK_LIBS_AVAILABLE = True
except ImportError:
    _OUTLOOK_LIBS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Google OAuth helpers
# ---------------------------------------------------------------------------

def _initiate_google_oauth() -> dict:
    if not _GOOGLE_LIBS_AVAILABLE:
        raise HTTPException(
            status_code=501, detail="Google auth libraries not installed")

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set to start OAuth flow",
        )

    try:
        from google_auth_oauthlib.flow import Flow  # type: ignore

        flow = Flow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        auth_url, _ = flow.authorization_url(
            access_type="offline", prompt="consent", include_granted_scopes="true"
        )
        _pending_auth["google"] = {"flow": flow,
                                   "auth_url": auth_url, "mode": "redirect"}
        logger.info("event=google_oauth_initiated auth_url=%s", auth_url)
        return {
            "status": "initiated",
            "provider": "google",
            "mode": "redirect",
            "auth_url": auth_url,
            "instructions": (
                "Open the auth_url in a browser, grant access, then call "
                "POST /api/gateway/auth/complete/google with {\"code\": \"<code>\"}"
            ),
        }
    except ImportError:
        raise HTTPException(
            status_code=501, detail="google-auth-oauthlib not installed")
    except Exception as exc:
        logger.error("event=google_oauth_initiate_error error=%s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _complete_google_oauth(body: dict) -> dict:
    if "google" not in _pending_auth:
        raise HTTPException(
            status_code=404, detail="No pending Google OAuth flow. Call initiate first.")
    code = (body or {}).get("code", "").strip()
    if not code:
        raise HTTPException(
            status_code=400, detail="Missing 'code' in request body")

    session = _pending_auth["google"]
    flow = session.get("flow")
    if flow is None:
        raise HTTPException(
            status_code=500, detail="Corrupt auth session — please re-initiate")

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        import json as _json

        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or []),
        }
        os.environ["GOOGLE_TOKEN_JSON"] = _json.dumps(token_data)
        _pending_auth.pop("google", None)
        refreshed = _refresh_calendar_registry()
        logger.info("event=google_oauth_complete active_providers=%s",
                    refreshed.get("active"))
        return {
            "status": "authorized",
            "provider": "google",
            "active_providers": refreshed.get("active", []),
            "note": (
                "Token stored in GOOGLE_TOKEN_JSON for this process lifetime. "
                "Persist it to your env/secrets store to survive restarts."
            ),
        }
    except Exception as exc:
        logger.error("event=google_oauth_complete_error error=%s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Microsoft device-code helpers
# ---------------------------------------------------------------------------

def _initiate_microsoft_oauth() -> dict:
    if not _OUTLOOK_LIBS_AVAILABLE:
        raise HTTPException(status_code=501, detail="msal not installed")

    client_id = os.getenv("OUTLOOK_CLIENT_ID", "").strip()
    tenant_id = os.getenv("OUTLOOK_TENANT_ID", "").strip()
    if not client_id or not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="OUTLOOK_CLIENT_ID and OUTLOOK_TENANT_ID must be set to start OAuth flow",
        )

    try:
        import msal as _msal

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        msal_app = _msal.PublicClientApplication(
            client_id, authority=authority)
        flow = msal_app.initiate_device_flow(
            scopes=["https://graph.microsoft.com/Calendars.ReadWrite"])
        if "error" in flow:
            raise HTTPException(
                status_code=500, detail=f"Device flow error: {flow.get('error_description')}")

        _pending_auth["microsoft"] = {"app": msal_app, "flow": flow}
        logger.info(
            "event=microsoft_oauth_initiated user_code=%s verification_url=%s",
            flow.get("user_code"),
            flow.get("verification_uri"),
        )
        return {
            "status": "initiated",
            "provider": "microsoft",
            "mode": "device_code",
            "user_code": flow.get("user_code"),
            "verification_url": flow.get("verification_uri"),
            "expires_in": flow.get("expires_in"),
            "instructions": (
                f"Go to {flow.get('verification_uri')} and enter the code {flow.get('user_code')}. "
                "Then call GET /api/gateway/auth/poll/microsoft to check completion."
            ),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("event=microsoft_oauth_initiate_error error=%s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _poll_microsoft_oauth() -> dict:
    session = _pending_auth.get("microsoft")
    if not session:
        return {"status": "no_pending_flow", "provider": "microsoft"}

    try:
        import msal as _msal

        msal_app: _msal.PublicClientApplication = session["app"]
        flow = session["flow"]
        # Non-blocking single poll: pass exit_condition that exits immediately after one attempt
        result = msal_app.acquire_token_by_device_flow(
            flow, exit_condition=lambda: True)

        if "access_token" in result:
            refresh_token = result.get("refresh_token", "")
            os.environ["OUTLOOK_REFRESH_TOKEN"] = refresh_token
            _pending_auth.pop("microsoft", None)
            refreshed = _refresh_calendar_registry()
            logger.info(
                "event=microsoft_oauth_complete active_providers=%s", refreshed.get("active"))
            return {
                "status": "authorized",
                "provider": "microsoft",
                "active_providers": refreshed.get("active", []),
                "note": (
                    "Refresh token stored in OUTLOOK_REFRESH_TOKEN for this process lifetime. "
                    "Persist it to your env/secrets store to survive restarts."
                ),
            }
        error = result.get("error", "")
        if error in ("authorization_pending", "slow_down"):
            return {"status": "pending", "provider": "microsoft", "error": error}
        # Token declined, expired, or other terminal error
        _pending_auth.pop("microsoft", None)
        return {"status": "error", "provider": "microsoft", "error": result.get("error_description", error)}
    except Exception as exc:
        logger.error("event=microsoft_oauth_poll_error error=%s", exc)
        return {"status": "error", "provider": "microsoft", "error": str(exc)}
