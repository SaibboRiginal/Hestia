import os
import threading
import time
import requests

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from tools.geocoding import GeocodingService
from tools.retrieval import ScoutRetrievalService
from tools.schemas import ModuleToolQueryRequest, RealEstateSearchRequest
from worker.runner import ScoutWorker

TARGET_DOMAIN = "real_estate"
TARGET_SOURCE = "gmail_imap"


def _build_target_filters() -> list[str]:
    explicit_filters = [
        item.strip()
        for item in os.getenv("SCOUT_FILTER_QUERIES", "").split("||")
        if item.strip()
    ]
    if explicit_filters:
        return explicit_filters

    sender_list_raw = os.getenv(
        "SCOUT_EMAIL_SENDERS",
        "nonrispondere@idealista.it,noreply@notifiche.immobiliare.it",
    )
    senders = [
        sender.strip()
        for sender in sender_list_raw.split(",")
        if sender.strip()
    ]
    return [f'FROM "{sender}"' for sender in senders]


TARGET_FILTERS = _build_target_filters()

api_app = FastAPI(title="Hestia Scout Tools", version="2.0.0")


def _build_retrieval_service() -> ScoutRetrievalService:
    archive_api_url = os.getenv(
        "ARCHIVE_API_URL", "http://hestia_archive:8000/api/archive")
    hub_api_url = os.getenv("HUB_API_URL", "http://hestia_hub:8005/api")
    geocoder = GeocodingService(user_agent="hestia-scout-tools/1.0")
    return ScoutRetrievalService(
        archive_api_url=archive_api_url,
        target_domain=TARGET_DOMAIN,
        geocoder=geocoder,
        hub_api_url=hub_api_url,
    )


retrieval_service = _build_retrieval_service()
worker = ScoutWorker(
    target_domain=TARGET_DOMAIN,
    target_source=TARGET_SOURCE,
    target_filters=TARGET_FILTERS,
)


@api_app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_scout_tools"}


@api_app.get("/api/module-tools/domains")
def list_module_domains():
    return {"domains": [TARGET_DOMAIN]}


@api_app.post("/api/module-tools/query")
def module_query(req: ModuleToolQueryRequest):
    if req.domain != TARGET_DOMAIN:
        return {"items": []}

    specialized_request = retrieval_service.from_module_query(req)
    items = retrieval_service.search(specialized_request)
    return {"domain": req.domain, "items": items}


@api_app.get("/api/tools")
def list_tools():
    return {
        "tools": [
            {
                "name": "real_estate.search",
                "path": "/api/tools/real_estate/search",
                "description": "Domain retrieval using stored entity geo coordinates and preference constraints",
            }
        ]
    }


@api_app.post("/api/tools/real_estate/search")
def search_real_estate(req: RealEstateSearchRequest):
    return retrieval_service.search(req)


def _start_tools_api():
    port = int(os.getenv("SCOUT_TOOLS_PORT", "8010"))

    def run_server():
        uvicorn.run(api_app, host="0.0.0.0", port=port, log_level="info")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print(f"[✓] Scout tools API online at 0.0.0.0:{port}")


def _register_with_hub(port: int):
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:8005/api").rstrip("/")
    service_base_url = os.getenv(
        "SCOUT_SERVICE_BASE_URL", f"http://hestia_scout:{port}")
    payload = {
        "name": "scout",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "module",
        "service_version": os.getenv("SCOUT_SERVICE_VERSION", "1.0.0"),
        "tags": ["module", "real_estate"],
        "capabilities": {
            "module_tool_domains": [TARGET_DOMAIN],
            "module_tool_endpoint": f"{service_base_url.rstrip('/')}/api/module-tools",
            "commands": [
                {
                    "command": "scout_listings",
                    "title": "🏠 Case disponibili",
                    "description": "Anteprima case da Scout (max 50)",
                    "method": "POST",
                    "path": "/api/tools/real_estate/search",
                    "body_template": {
                        "query": "",
                        "limit": "$arg.limit",
                    },
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": "Mostra una lista breve e leggibile delle case trovate con punti chiave e link.",
                    "telegram_visible": True,
                },
            ],
        },
    }
    try:
        requests.post(f"{hub_api_url}/registry/register",
                      json=payload, timeout=4)
        print("[✓] Scout registered in Hub")
    except Exception as error:
        print(f"[!] Scout Hub registration failed: {error}")


if __name__ == "__main__":
    load_dotenv()
    tools_port = int(os.getenv("SCOUT_TOOLS_PORT", "8010"))
    _start_tools_api()
    _register_with_hub(tools_port)

    while True:
        try:
            worker.run_cycle()
        except Exception as error:
            print(f"[!] Critical Error in Scout Loop: {error}")

        print("\n💤 Scout resting for 30 minutes before checking for new emails...")
        time.sleep(1800)
