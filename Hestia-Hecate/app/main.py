import logging
import os
import requests
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from providers.registry import CalendarProviderRegistry
from providers.mail import mail_gateway, MailUnavailable
from schemas.calendar_events import CalendarEvent

from core.registry import get_fetcher_class, FETCHER_REGISTRY
from core.archive_client import ArchiveClient
from core.state_manager import StateManager
from core import google_oauth

load_dotenv()

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import wait_for_hub_services
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import wait_for_hub_services

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
            name="gateway_auth_verify",
            description=(
                "Verifica lo stato di autenticazione di tutti i provider "
                "(Google, Outlook) e INVIA notifiche Telegram per quelli "
                "che richiedono riautenticazione. Usa questo comando quando "
                "l'utente chiede di controllare se i provider funzionano."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "gateway_auth_verify", "params": kw},
            title="🩺 Verifica autenticazione provider",
            method="POST",
            path="/api/gateway/auth/verify",
            clients=["telegram", "ui"],
            response_mode="oracle_natural",
            response_prompt=(
                "Elenca lo stato di ogni provider e indica chiaramente "
                "se sono state inviate notifiche per quelli non funzionanti. "
                "Se il provider Google non è autenticato, ricorda all'utente "
                "di usare il pulsante 'Riautentica Google' nel messaggio "
                "di notifica che ha ricevuto."
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
                "Mostra il link auth_url (cliccabile). Se mode=device_code mostra invece "
                "verification_url e user_code. Se public_redirect=true: basta aprire il link da "
                "qualsiasi dispositivo e concedere Calendar+Gmail, si completa da solo. "
                "Se public_redirect=false: dal PC di Hestia si completa da solo; da telefono la "
                "pagina finale localhost non si carica (normale): copiare l'URL intero dalla "
                "barra e incollarlo qui in chat."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
        MCPTool(
            name="gateway_auth_complete_google",
            description=(
                "Completa il collegamento Google Calendar. Usa quando l'utente incolla un URL "
                "che contiene 'code=' (es. http://localhost.../callback/google?code=...) o un codice OAuth."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "URL completo incollato dall'utente, oppure il solo codice"},
                },
                "required": ["code"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "gateway_auth_complete_google", "params": kw},
            title="\u2705 Completa collegamento Google", method="POST", path="/api/gateway/auth/complete/google",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Se status=authorized conferma che Google Calendar è collegato. "
                "Altrimenti riporta errore e hint in breve."
            ),
            telegram_visible=False, telegram_group="pianificazione",
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
            name="gateway_auth_complete",
            description=(
                "Completa l'autenticazione Google inviando il codice "
                "di autorizzazione copiato dal browser. "
                "Usa questo comando DOPO aver aperto il link di auth "
                "SUL TELEFONO e aver copiato il codice 'code=' "
                "dalla barra degli indirizzi del browser."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "Provider: google"},
                    "code": {"type": "string", "description": "Codice di autorizzazione dalla barra degli indirizzi del browser"},
                },
                "required": ["provider", "code"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "gateway_auth_complete", "params": kw},
            title="✅ Completa autenticazione Google",
            method="POST",
            path="/api/gateway/auth/complete/{provider}",
            clients=["telegram", "ui"],
            response_mode="oracle_natural",
            response_prompt=(
                "Conferma se l'autenticazione è riuscita o se il codice "
                "non è valido. Se riuscita, indica che Calendar e Gmail "
                "sono ora operativi."
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
                "Comunica all'utente se l'autenticazione Google/Microsoft "
                "è stata completata con successo o se è ancora in attesa. "
                "Se completata, informa che Calendar e Gmail sono ora operativi."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
    ]
    app.include_router(create_mcp_router(_hecate_mcp_tools, service_name="hecate"))
    logger.info("event=mcp_router_mounted service=hecate")
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=hecate reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_hecate"))

vault = ArchiveClient()
memory = StateManager("data/state.json")  # Move this to a mounted volume!
_calendar_registry = CalendarProviderRegistry()

_CALENDAR_SOURCES = {"gcal", "outlook_calendar"}

HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")


# Cooldown tracker for action notifications — prevents spamming duplicate
# events when multiple code paths detect the same auth failure.
_action_notify_cooldown: dict[str, float] = {}
_ACTION_NOTIFY_COOLDOWN_SECONDS = float(
    os.getenv("HECATE_ACTION_NOTIFY_COOLDOWN", "300"))


def _notify_action_required(
    action: str,
    message: str,
    actions: list[dict[str, str]] | None = None,
) -> None:
    """Push a service action-required notification via Hermes.

    ``actions`` is an optional list of button definitions, each with:
        text: str    — button label
        command: str — Telegram command name (routed via ``run:`` callback)

    Notifications for the same ``action`` are throttled to once every
    ``HECATE_ACTION_NOTIFY_COOLDOWN`` seconds (default 300).
    """
    now = time.monotonic()
    last = _action_notify_cooldown.get(action)
    if last is not None and (now - last) < _ACTION_NOTIFY_COOLDOWN_SECONDS:
        logger.debug(
            "event=action_notify_cooldown_skipped action=%s age=%.1fs",
            action,
            now - last,
        )
        return
    _action_notify_cooldown[action] = now

    # Scope entity_id by hour so the notification fires on each restart
    # instead of being permanently deduped against a past delivery.
    # The process-level cooldown (above) still prevents intra-run spam.
    _ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H")
    _payload: dict = {
        "action": action,
        "_message": message,
        "service": "hecate",
    }
    if actions:
        _payload["_actions"] = actions
    try:
        requests.post(
            f"{HUB_API_URL}/route/hermes/api/events/ingest",
            json={
                "method": "POST",
                "headers": {},
                "query": {},
                "body": {
                    "event_type": "service.action_required",
                    "domain": "system",
                    "entity_id": f"hecate-{action}-{_ts}",
                    "payload": _payload,
                },
                "timeout_seconds": 8,
            },
            timeout=10,
        )
        logger.info(
            "event=action_required_notified action=%s actions=%d",
            action,
            len(actions) if actions else 0,
        )
    except Exception as exc:
        logger.warning(
            "event=action_required_notify_failed action=%s error=%s", action, exc)


def _check_auth_and_notify() -> None:
    """Check configured providers for auth failures and notify the user.

    Called once at startup after Hub registration succeeds.  Idempotent —
    Hermes deduplicates duplicate notifications.
    """
    _reauth_actions = [
        {"text": "🔑 Riautentica Google", "command": "gateway_auth_initiate_google"},
    ]

    # 1) Calendar provider check
    registry_status = _calendar_registry.status_report()
    unavailable = registry_status.get("unavailable", {})
    if "google" in unavailable and _provider_env_is_configured("google"):
        reason = unavailable["google"]
        _notify_action_required(
            "reauth_google_calendar",
            (
                f"⚠️ <b>Google Calendar</b> non è autenticato.\n\n"
                f"{reason}\n\n"
                "Usa il pulsante qui sotto per riautenticarti."
            ),
            actions=_reauth_actions,
        )

    # 2) Mail provider check (lazy-init — force init to detect auth state)
    mail = _get_mail_provider()
    if not mail.is_available() and _provider_env_is_configured("google"):
        mail_error = mail._init_error or "Gmail provider not available"
        _notify_action_required(
            "reauth_google_gmail",
            (
                f"⚠️ <b>Gmail</b> non è accessibile.\n\n"
                f"{mail_error}\n\n"
                "Usa il pulsante qui sotto per riautenticarti con lo scope gmail.readonly."
            ),
            actions=_reauth_actions,
        )


def _get_mail_provider():
    """Gmail API provider (lazy, rebuilt after re-auth)."""
    return mail_gateway.gmail()


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _provider_env_is_configured(provider: str) -> bool:
    if provider == "google":
        from providers.google import has_stored_token
        return bool(
            has_stored_token()
            or os.getenv("GOOGLE_TOKEN_JSON")
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

    if not refreshed_any or _calendar_registry.unavailable:
        # Full reinit: no provider survived the refresh, or a provider that was
        # unavailable at boot may now have credentials (OAuth just completed,
        # token file written by the host helper, env injected).
        _calendar_registry = CalendarProviderRegistry()
        logger.info(
            "event=calendar_registry_reinitialized active=%s unavailable=%s",
            _calendar_registry.active_names, list(_calendar_registry.unavailable))

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
            "module_tool_domains": ["calendar"],
        },
    }
    try:
        import requests
        resp = requests.post(
            f"{hub_api_url}/registry/register", json=payload, timeout=4)
        if resp.status_code < 400:
            logger.info("event=registered_hub_hub_base_url Registered on Hub | hub=%s base_url=%s",
                        hub_api_url, service_base_url)
            # Wait for required dispatch-path services to appear in Hub registry
            # before sending notifications.  Uses Hub service discovery — no sleeps.
            def _deferred_auth_check():
                ready = wait_for_hub_services(
                    hub_api_url,
                    ["telegram", "hermes"],
                    timeout_seconds=30,
                    interval_seconds=1.5,
                    logger=logger,
                )
                if ready:
                    _check_auth_and_notify()
                else:
                    logger.warning(
                        "event=auth_check_skipped "
                        "reason=required_services_not_registered "
                        "required=telegram,hermes")

                # ── Periodic auth re-check ──────────────────────────────────
                # Re-check provider auth every N seconds and re-notify about
                # persistent failures.  Hermes dedup uses time-based expiry
                # for service.action_required events, so repeated failures
                # result in a fresh notification after the expiry window.
                _reauth_check_interval = float(
                    os.getenv("HECATE_AUTH_RECHECK_INTERVAL_SECONDS", "3600"))
                if _reauth_check_interval > 0:
                    while True:
                        time.sleep(_reauth_check_interval)
                        try:
                            _check_auth_and_notify()
                        except Exception as _exc:
                            logger.warning(
                                "event=auth_recheck_error error=%s", _exc)
            threading.Thread(target=_deferred_auth_check, daemon=True,
                             name="auth-check").start()
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

        failed = 0
        for item in raw_data:
            if not vault.ship_record(
                payload=item,
                domain=command.domain,
                source=command.source,
                reference_id=item.get("reference_id")
            ):
                failed += 1

        # Only advance the cursor if the whole batch shipped (Archive dedupes by
        # reference_id, so the next run safely re-ships). The cursor used to
        # advance even when ships failed: those mails were lost forever.
        if failed:
            logger.warning("[🔄] event=ingest_partial_ship task=%s failed=%d total=%d (cursor not advanced)",
                           task_name, failed, len(raw_data))
            return {"status": "partial", "fetched": len(raw_data), "failed": failed}
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


_REAUTH_ACTIONS = [{"text": "🔑 Riautentica Google", "command": "gateway_auth_initiate_google"}]


class MailSendRequest(BaseModel):
    to: str
    subject: str
    body: str


def _parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    try:
        return datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="since must be ISO date/datetime")


def _mail_unavailable(exc: MailUnavailable, q: str = "") -> dict:
    if exc.auth_required:
        _notify_action_required(
            "reauth_google_gmail", f"⚠️ <b>Gmail</b> non accessibile: {exc}.", actions=_REAUTH_ACTIONS)
    return {"status": "error", "query": q, "count": 0, "messages": [], "error": str(exc),
            "action_required": "reauth_google" if exc.auth_required else None}


@app.get("/api/gateway/mail/status")
def gateway_mail_status():
    """Gmail state for Iris/Scout (authorized, can_send, error)."""
    return {"status": "ok", **mail_gateway.status()}


@app.get("/api/gateway/email/messages")
@app.get("/api/gateway/mail/messages")
def gateway_email_messages(q: str = "", since: str | None = None, limit: int = 20):
    """Search mail. ``q``: Gmail syntax, raw IMAP criteria ('FROM "x"') or free text.

    Gmail API (OAuth token); an auth failure notifies the user with a re-auth button.
    """
    since_dt = _parse_since(since)
    try:
        rows, backend = mail_gateway.search(q=q, since=since_dt, limit=max(1, min(limit, 200)))
    except MailUnavailable as exc:
        logger.warning("[🔄] event=gateway_email_unavailable error=%s", exc)
        return _mail_unavailable(exc, q)
    return {"status": "ok", "query": q, "backend": backend, "count": len(rows), "messages": rows}


@app.get("/api/gateway/email/messages/{message_id}")
def gateway_email_message(message_id: str):
    try:
        row = mail_gateway.get(message_id)
    except MailUnavailable as exc:
        raise HTTPException(status_code=503, detail=_mail_unavailable(exc))
    if not row:
        raise HTTPException(status_code=404, detail=f"message '{message_id}' not found")
    return {"status": "ok", "message": row}


@app.post("/api/gateway/email/send")
@app.post("/api/gateway/mail/send")
def gateway_email_send(req: MailSendRequest):
    """Send mail via Gmail API (scope gmail.send)."""
    try:
        sent, backend = mail_gateway.send(req.to, req.subject, req.body)
    except MailUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"status": "ok", "backend": backend, "sent": sent}


# ---------------------------------------------------------------------------
# OAuth Initiation Flow
# ---------------------------------------------------------------------------
# In-memory store for pending device-code auth sessions.  Each entry is keyed
# by provider name and holds the data needed to poll for completion.
_pending_auth: dict[str, dict] = {}


@app.post("/api/gateway/auth/initiate/{provider}")
def gateway_auth_initiate(provider: str):
    """Start an OAuth flow for the given provider.

    • Google  → device_code flow (default): returns ``user_code`` +
      ``verification_url``.  Open the URL on ANY device (phone, tablet, PC),
      enter the code, then poll ``GET /api/gateway/auth/poll/google``.
      Set ``GOOGLE_OAUTH_FLOW_MODE=redirect`` for the legacy localhost flow.

    • Microsoft → MSAL device-code flow: returns ``verification_url``
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


@app.post("/api/gateway/auth/verify")
def gateway_auth_verify() -> dict:
    """Check all provider auth status and notify for broken ones.

    Returns the same status report as ``/api/gateway/auth/status`` but also
    triggers ``_check_auth_and_notify()`` so the user receives a Telegram
    message with the re-auth button for any broken provider.
    """
    _check_auth_and_notify()
    providers = detect_gateway_providers()
    runtime = _calendar_registry.status_report()
    # Include mail provider status
    mail = _get_mail_provider()
    mail_ok = mail.is_available()
    return {
        "status": "ok",
        "providers": providers,
        "runtime": runtime,
        "mail_available": mail_ok,
        "mail_error": mail._init_error if not mail_ok else None,
        "notifications_sent": True,
    }


@app.get("/api/gateway/auth/callback/google", response_class=HTMLResponse)
def gateway_auth_callback_google(code: str = "", state: str = "", error: str = ""):
    """Google OAuth redirect target — completes the flow automatically.

    Reached directly from the Docker host (localhost) or from any device via the
    Cloudflare tunnel.  Verifies ``state``, exchanges the code with the PKCE
    verifier, persists the token and reloads Calendar + Gmail.
    """
    import html as _html

    raw = f"?error={error}" if error else f"?code={code}&state={state}"
    try:
        result = _finish_google_oauth(raw, state=state or None)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        msg = _html.escape(str(detail.get("error", "")))
        hint = _html.escape(str(detail.get("hint", "")))
        return HTMLResponse(
            _OAUTH_CALLBACK_HTML.format(icon="❌", title="Autorizzazione non riuscita",
                                        detail=f"{msg}<br><br>{hint}"),
            status_code=exc.status_code)
    if result["status"] == "authorized":
        scopes = ", ".join(s.rsplit("/", 1)[-1] for s in result.get("granted_scopes", [])) or "nessuno"
        return HTMLResponse(_OAUTH_CALLBACK_HTML.format(
            icon="✅", title="Autorizzazione completata!",
            detail=f"Google è connesso a Hestia (scope: {_html.escape(scopes)}). "
                   "Puoi chiudere questa pagina e tornare su Telegram."))
    return HTMLResponse(_OAUTH_CALLBACK_HTML.format(
        icon="⚠️", title="Token salvato, provider non attivo",
        detail=_html.escape(str(result.get("unavailable")))))


# ── HTML template for the OAuth callback page ──────────────────────────
_OAUTH_CALLBACK_HTML = """\
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hestia — {title}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh; margin: 0; background: #0f0f0f; color: #e0e0e0;
  }}
  .card {{
    background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px;
    padding: 40px 48px; max-width: 480px; text-align: center; box-shadow: 0 4px 24px rgba(0,0,0,0.4);
  }}
  .icon {{ font-size: 48px; margin-bottom: 16px; }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 12px 0; color: #fff; }}
  p {{ font-size: 14px; line-height: 1.6; color: #999; margin: 0; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">{icon}</div>
  <h1>{title}</h1>
  <p>{detail}</p>
</div>
</body>
</html>"""


@app.get("/api/gateway/auth/poll/{provider}")
def gateway_auth_poll(provider: str):
    """Poll whether the user has completed the device-code / redirect OAuth flow.

    Returns ``{"status": "authorized"}`` once the token has been acquired and
    the provider registry refreshed.  Returns ``{"status": "pending"}`` while
    still waiting.
    """
    normalized = provider.strip().lower()
    if normalized == "google":
        if (_pending_auth.get("google") or {}).get("mode") == "device_code":
            return _poll_google_device_flow()
        if "google" in _calendar_registry.active_names:
            return {"status": "authorized", "provider": "google"}
        session = google_oauth.pending()
        if session:
            return {"status": "pending", "provider": "google", "auth_url": session.get("auth_url")}
        return {"status": "no_pending_flow", "provider": "google",
                "error": _calendar_registry.unavailable.get("google")}

    if normalized not in _pending_auth:
        return {"status": "no_pending_flow", "provider": normalized}
    if normalized == "microsoft":
        return _poll_microsoft_oauth()
    return {"status": "unknown_provider", "provider": normalized}


@app.delete("/api/gateway/auth/initiate/{provider}")
def gateway_auth_cancel(provider: str):
    """Cancel a pending OAuth device-code flow."""
    normalized = provider.strip().lower()
    _pending_auth.pop(normalized, None)
    if normalized == "google":
        google_oauth.cancel()
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
# Two flow modes, controlled by GOOGLE_OAUTH_FLOW_MODE:
#
#   "redirect" (default) — authorization code + PKCE (core/google_oauth.py).
#       Redirect URI: GOOGLE_OAUTH_REDIRECT_URI → Cloudflare tunnel URL
#       (/code/data/tunnel-url.txt, written by cloudflare-tunnel.bat) →
#       localhost.  With the tunnel the callback completes from ANY device;
#       with localhost it completes only from the Docker host, elsewhere the
#       user pastes the final URL (or the code) in chat →
#       POST /api/gateway/auth/complete/google.  The pending session (state +
#       PKCE verifier) is persisted on disk, so a restart in between is safe.
#
#   "device_code" — RFC 8628 device authorization.  ONLY works if the Google
#       Cloud OAuth client is "Desktop" or "TV / Limited Input".  Web
#       application clients receive "invalid_client".

_GOOGLE_OAUTH_FLOW_MODE = os.getenv(
    "GOOGLE_OAUTH_FLOW_MODE", "redirect").strip().lower()
_GOOGLE_DEVICE_CODE_ENDPOINT = "https://oauth2.googleapis.com/device/code"
_GOOGLE_TOKEN_ENDPOINT = google_oauth.TOKEN_ENDPOINT


def _build_google_redirect_uri() -> str:
    """Redirect URI for the redirect flow (env → tunnel → localhost)."""
    return google_oauth.redirect_uri()


def _initiate_google_oauth() -> dict:
    """Start a Google OAuth flow (redirect by default, device_code on request)."""
    if _GOOGLE_OAUTH_FLOW_MODE == "device_code":
        result = _initiate_google_device_flow()
        _start_google_device_auto_poll()
        return result
    return _initiate_google_redirect_flow()


def _initiate_google_redirect_flow() -> dict:
    try:
        started = google_oauth.start()
    except google_oauth.GoogleOAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail())
    redirect = started["redirect_uri"]
    public = google_oauth.is_public_redirect(redirect)
    _pending_auth["google"] = {"auth_url": started["auth_url"], "mode": "redirect",
                               "redirect_uri": redirect}
    if public:
        instructions = (
            "Apri il link da qualsiasi dispositivo (telefono, PC) e concedi l'accesso a "
            "Calendar e Gmail: il ritorno passa dal tunnel pubblico e l'autenticazione "
            "si completa da sola (riceverai conferma su Telegram).")
    else:
        instructions = (
            "DA PC (dove gira Hestia): apri il link, concedi l'accesso — si completa da solo.\n"
            "DA TELEFONO: apri il link, concedi l'accesso; la pagina finale (localhost) NON "
            "si carica: è normale. Copia l'URL intero dalla barra degli indirizzi (o solo il "
            "valore di code=) e incollalo qui in chat.\n"
            "Per completare da telefono senza copia-incolla avvia cloudflare-tunnel.bat.")
    logger.info("event=google_oauth_redirect_initiated redirect_uri=%s public=%s", redirect, public)
    return {
        "status": "initiated",
        "provider": "google",
        "mode": "redirect",
        "auth_url": started["auth_url"],
        "redirect_uri": redirect,
        "public_redirect": public,
        "expires_in": started["expires_in"],
        "instructions": instructions,
    }


def _initiate_google_device_flow() -> dict:
    """Start Google's OAuth 2.0 Device Authorization Grant (RFC 8628).

    No redirect URI is needed — the user visits a standard URL on any
    device and enters a short code.  Hecate polls until completion.
    """
    client_id, client_secret = google_oauth.client_credentials()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set to start OAuth flow",
        )
    try:
        resp = requests.post(
            _GOOGLE_DEVICE_CODE_ENDPOINT,
            data={"client_id": client_id, "scope": " ".join(google_oauth.scopes())},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Google device endpoint unreachable: {exc}")
    if resp.status_code != 200:
        detail = resp.text[:400]
        logger.error("event=google_device_code_error status=%s detail=%s", resp.status_code, detail)
        raise HTTPException(
            status_code=502,
            detail=f"Google device code endpoint returned {resp.status_code}: {detail}",
        )

    data = resp.json()
    user_code = data.get("user_code", "")
    verification_url = data.get("verification_url", "https://www.google.com/device")
    expires_in = int(data.get("expires_in", 1800))
    interval = int(data.get("interval", 5))
    _pending_auth["google"] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "device_code": data.get("device_code", ""),
        "user_code": user_code,
        "verification_url": verification_url,
        "expires_in": expires_in,
        "interval": interval,
        "mode": "device_code",
        "started_at": time.monotonic(),
    }
    logger.info("event=google_device_flow_initiated verification_url=%s expires_in=%s",
                verification_url, expires_in)
    return {
        "status": "initiated",
        "provider": "google",
        "mode": "device_code",
        "user_code": user_code,
        "verification_url": verification_url,
        "expires_in": expires_in,
        "instructions": (
            f"1. Apri {verification_url} sul tuo telefono o computer\n"
            f"2. Inserisci questo codice: {user_code}\n"
            "3. Concedi l'accesso a Calendar e Gmail\n"
            "4. Hestia completa da sola (o usa 'Verifica completamento')."
        ),
    }


def _poll_google_device_flow() -> dict:
    """Poll Google's token endpoint for a pending device-code flow."""
    session = _pending_auth.get("google")
    if not session or session.get("mode") != "device_code":
        return {"status": "no_pending_flow", "provider": "google"}
    device_code = session.get("device_code", "")
    if not device_code:
        _pending_auth.pop("google", None)
        return {"status": "error", "provider": "google", "error": "No device_code in session"}
    try:
        resp = requests.post(
            _GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": session.get("client_id", ""),
                "client_secret": session.get("client_secret", ""),
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=15,
        )
        data = resp.json() if resp.content else {}
    except Exception as exc:
        logger.error("event=google_device_flow_poll_error error=%s", exc)
        return {"status": "pending", "provider": "google", "mode": "device_code", "error": str(exc)}

    if resp.status_code == 200 and "access_token" in data:
        expires_in = int(data.get("expires_in") or 3600)
        expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=expires_in - 60)
        _pending_auth.pop("google", None)
        return _apply_google_token({
            "token": data.get("access_token", ""),
            "refresh_token": data.get("refresh_token", ""),
            "token_uri": _GOOGLE_TOKEN_ENDPOINT,
            "client_id": session.get("client_id", ""),
            "client_secret": session.get("client_secret", ""),
            "scopes": (data.get("scope", "") or "").split() or google_oauth.scopes(),
            "expiry": expiry.isoformat() + "Z",
        })

    error = data.get("error", "")
    if error == "authorization_pending":
        return {"status": "pending", "provider": "google", "mode": "device_code"}
    if error == "slow_down":
        return {"status": "pending", "provider": "google", "mode": "device_code", "error": "slow_down"}
    _pending_auth.pop("google", None)
    logger.warning("event=google_device_flow_terminal_error error=%s", error)
    return {"status": "error", "provider": "google", "error": data.get("error_description", error)}


def _start_google_device_auto_poll() -> None:
    """Background poller for the device flow; notifies the outcome via Hermes."""
    def _auto_poller():
        deadline = time.monotonic() + 1200  # 20 min max (Google default is 30 min)
        poll_interval = 5.0
        while time.monotonic() < deadline:
            session = _pending_auth.get("google")
            if not session or session.get("mode") != "device_code":
                return  # cancelled or completed elsewhere
            time.sleep(poll_interval)
            result = _poll_google_device_flow()
            status = result.get("status", "")
            if status == "authorized":
                return  # _apply_google_token already notified
            if status == "error":
                _notify_action_required(
                    "google_reauth_failed",
                    f"❌ <b>Autenticazione Google fallita:</b> {result.get('error', 'unknown')}\n\n"
                    "Riprova con il pulsante qui sotto.",
                    actions=[{"text": "🔑 Riautentica Google", "command": "gateway_auth_initiate_google"}],
                )
                return
            if result.get("error") == "slow_down":
                poll_interval = min(poll_interval + 5, 60)
            else:
                poll_interval = float(session.get("interval") or 5)
        _pending_auth.pop("google", None)
        logger.warning("event=google_auto_poll_timeout")
        _notify_action_required(
            "google_reauth_timeout",
            "⏰ <b>Autenticazione Google scaduta.</b>\n\nRiavviala con il pulsante qui sotto.",
            actions=[{"text": "🔑 Riautentica Google", "command": "gateway_auth_initiate_google"}],
        )

    threading.Thread(target=_auto_poller, daemon=True, name="google-auto-poll").start()


def _apply_google_token(token_data: dict) -> dict:
    """Persist a Google token (any flow), reload calendar + mail providers, notify."""
    from providers.google import GoogleCalendarProvider

    GoogleCalendarProvider.persist_token(token_data)
    _pending_auth.pop("google", None)
    refreshed = _refresh_calendar_registry()
    mail_gateway.reset()  # rebuild Gmail with the new scopes
    active = refreshed.get("active", [])
    granted = list(token_data.get("scopes") or [])
    ok = "google" in active
    logger.info("event=google_oauth_complete active_providers=%s granted_scopes=%s", active, granted)
    if ok:
        gmail_ok = "https://www.googleapis.com/auth/gmail.readonly" in granted
        _notify_action_required(
            "google_reauth_complete",
            "✅ <b>Google</b> è connesso a Hestia.\n\n"
            + ("Calendar e Gmail operativi." if gmail_ok
               else "Calendar operativo. Gmail NON autorizzato: riautentica concedendo la lettura email."),
        )
    return {
        "status": "authorized" if ok else "token_saved_provider_unavailable",
        "provider": "google",
        "granted_scopes": granted,
        "active_providers": active,
        "unavailable": refreshed.get("unavailable", {}),
        "note": "Token salvato in data/google_token.json: sopravvive ai riavvii del container.",
    }


def _finish_google_oauth(raw_code: str, state: str | None = None) -> dict:
    """Exchange the code (redirect flow), persist the token, reload providers."""
    try:
        token_data = google_oauth.complete(raw_code, state=state)
    except google_oauth.GoogleOAuthError as exc:
        logger.warning("event=google_oauth_complete_error error=%s", exc)
        raise HTTPException(status_code=exc.status_code, detail=exc.to_detail())
    return _apply_google_token(token_data)


def _complete_google_oauth(body: dict) -> dict:
    """Manual completion: accepts the bare code, the full redirect URL or the query string."""
    body = body or {}
    session = _pending_auth.get("google") or {}
    if session.get("mode") == "device_code":
        return _poll_google_device_flow()
    raw = str(body.get("code") or body.get("redirect_url") or body.get("url") or "").strip()
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="Missing 'code' in request body (authorization code or full redirect URL)")
    return _finish_google_oauth(raw, state=body.get("state"))

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
