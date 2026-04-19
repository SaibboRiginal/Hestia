import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from core.registry import get_fetcher_class, FETCHER_REGISTRY
from core.archive_client import ArchiveClient
from core.state_manager import StateManager

load_dotenv()

app = FastAPI(title="Hestia-Ingest Factory", version="3.0")
vault = ArchiveClient(api_url="")
memory = StateManager("data/state.json")  # Move this to a mounted volume!

_CALENDAR_SOURCES = {"gcal", "outlook_calendar"}


@app.on_event("startup")
def register_on_hub_startup():
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    service_base_url = os.getenv(
        "INGEST_SERVICE_BASE_URL", "http://hestia_ingest:19003")
    payload = {
        "name": "ingest",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "core",
        "service_version": os.getenv("INGEST_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "connector"],
        "capabilities": {
            "ingest_trigger": "/api/ingest/trigger",
            "calendar_sync": "/api/ingest/calendar/trigger",
            "commands": [
                {
                    "command": "sync_calendar",
                    "title": "🔄 Sincronizza calendario",
                    "description": "Sincronizza gli eventi del calendario da Google e Outlook in Hestia",
                    "method": "POST",
                    "path": "/api/ingest/calendar/trigger",
                    "body_template": {},
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": (
                        "Conferma la sincronizzazione del calendario. Indica quanti eventi "
                        "sono stati trovati per ogni provider (Google, Outlook). "
                        "Sii conciso e usa un tono da assistente."
                    ),
                },
            ],
        },
    }
    try:
        import requests
        requests.post(f"{hub_api_url}/registry/register",
                      json=payload, timeout=4)
    except Exception:
        pass


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_ingest"}


class FetchCommand(BaseModel):
    domain: str = Field(..., description="The context, e.g., 'real_estate'")
    source: str = Field(...,
                        description="The fetcher to use, e.g., 'gmail_imap'")
    filter_query: str = Field(
        ..., description="The targeted query, e.g., 'FROM \"alerts@casa.it\"'")


@app.post("/api/ingest/trigger")
def trigger_fetch(command: FetchCommand):
    print(f"\n[⚡] COMMAND: Fetch {command.domain} via {command.source}")

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
        print(
            f"[*] Executing target search since {last_run.strftime('%Y-%m-%d')}...")
        raw_data = fetcher_instance.fetch_new_data(
            since_date=last_run, custom_filter=command.filter_query)
        print(f"[*] Fetched {len(raw_data)} matching items.")

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
        print(f"[!] Critical error during extraction/shipping: {e}")
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
    # include recent past events
    since = datetime.now(_tz.utc) - timedelta(days=7)

    for source in sources:
        try:
            FetcherClass = get_fetcher_class(source)
            fetcher = FetcherClass()
        except ValueError as exc:
            results[source] = {"error": str(exc), "fetched": 0, "archived": 0}
            continue

        if not fetcher.connect():
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
            results[source] = {"fetched": len(items), "archived": archived}
        except Exception as exc:
            results[source] = {"error": str(exc), "fetched": 0, "archived": 0}
        finally:
            fetcher.disconnect()

    total_archived = sum(r.get("archived", 0) for r in results.values())
    return {"status": "success", "sources": results, "total_archived": total_archived}
