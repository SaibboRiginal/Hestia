import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from core.registry import get_fetcher_class
from core.archive_client import ArchiveClient
from core.state_manager import StateManager

load_dotenv()

app = FastAPI(title="Hestia-Ingest Factory", version="3.0")
vault = ArchiveClient(api_url="")
memory = StateManager("data/state.json")  # Move this to a mounted volume!


@app.on_event("startup")
def register_on_hub_startup():
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:8005/api").rstrip("/")
    service_base_url = os.getenv(
        "INGEST_SERVICE_BASE_URL", "http://hestia_ingest:8001")
    payload = {
        "name": "ingest",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "core",
        "service_version": os.getenv("INGEST_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "connector"],
        "capabilities": {
            "ingest_trigger": "/api/ingest/trigger",
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
