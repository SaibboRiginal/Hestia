"""Client for the Atlas web-fetch service, routed through Hub.

Atlas is Hestia's dedicated web-fetching service that attaches to a host
browser via CDP. All HTML fetching in Scout is delegated to Atlas so Scout
never manages browsers or direct HTTP sessions itself.
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

import requests


logger = logging.getLogger("hestia_scout.atlas_client")


@dataclass(frozen=True)
class FetchResult:
    """Immutable result from an Atlas fetch operation."""

    html: str
    url: str
    final_url: str
    fetch_method: str
    blocked: bool = False
    content_length: int = 0
    http_status: int = 200


class AtlasClient:
    """Fetches HTML via Hub -> Atlas routing."""

    def __init__(self, hub_api_url: str | None = None):
        configured = str(hub_api_url or os.getenv("HUB_API_URL", "")).strip()
        if configured:
            candidates = [configured.rstrip("/")]
            if "hestia_hub" in configured:
                # Host-side debug often inherits Docker env values; retry localhost.
                localhost_candidate = configured.replace(
                    "hestia_hub", "localhost")
                if localhost_candidate.rstrip("/") not in candidates:
                    candidates.append(localhost_candidate.rstrip("/"))
        else:
            candidates = ["http://hestia_hub:19001/api",
                          "http://localhost:19001/api"]

        self._hub_api_candidates = candidates

    def fetch_html(
        self,
        url: str,
        timeout_seconds: int = 30,
        wait_ms: int = 3000,
        strategy: str = "edge_cdp",
    ) -> Optional[FetchResult]:
        """Fetch HTML for a URL via Hub -> Atlas.

        Returns a FetchResult on success, or None if every candidate Hub URL fails.
        """
        body = {
            "url": url,
            "timeout_seconds": max(timeout_seconds, 8),
            "wait_ms": wait_ms,
            "strategy": strategy,
        }
        route_payload = {
            "method": "POST",
            "body": body,
            "timeout_seconds": max(timeout_seconds + 6, 15),
        }

        failures: list[str] = []
        for index, hub_api_url in enumerate(self._hub_api_candidates):
            try:
                response = requests.post(
                    f"{hub_api_url}/route/atlas/api/fetch/html",
                    json=route_payload,
                    timeout=max(timeout_seconds + 8, 16),
                )
                if response.status_code >= 400:
                    failures.append(
                        f"HTTP {response.status_code} via {hub_api_url}")
                    continue

                route_data = response.json() if response.content else {}
                payload = route_data.get("payload") if isinstance(
                    route_data, dict) else None
                if not isinstance(payload, dict):
                    failures.append(f"No payload via {hub_api_url}")
                    continue

                if str(payload.get("status", "")).lower() != "ok":
                    error = payload.get("error", "unknown")
                    failures.append(f"Fetch error via {hub_api_url}: {error}")
                    continue

                html = str(payload.get("html", ""))
                if not html:
                    failures.append(f"Empty HTML via {hub_api_url}")
                    continue

                if index > 0:
                    logger.info(
                        "event=atlas_fallback_hub_candidate_succeeded Atlas fallback hub candidate succeeded | hub_api_url=%s", hub_api_url)

                return FetchResult(
                    html=html,
                    url=url,
                    final_url=str(payload.get("final_url", url)),
                    fetch_method=str(payload.get("fetch_method", "atlas")),
                    blocked=bool(payload.get("blocked", False)),
                    content_length=len(html),
                    http_status=int(payload.get("http_status", 200)),
                )
            except requests.RequestException as exc:
                failures.append(f"Request exception via {hub_api_url}: {exc}")
                continue

        if failures:
            logger.warning("event=all_atlas_hub_candidates_failed All Atlas hub candidates failed | url=%s", url)
            for item in failures:
                logger.warning(
                    "event=atlas_candidate_failure_detail_detail Atlas candidate failure detail | detail=%s", item)

        return None
