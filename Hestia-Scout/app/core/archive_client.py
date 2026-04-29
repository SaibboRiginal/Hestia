import requests
import os
import logging


logger = logging.getLogger("hestia_scout.archive_client")


class ArchiveClient:
    """Handles communication between the AI Worker and the Vault."""

    def __init__(self, api_url: str, hub_api_url: str | None = None):
        self.api_url = api_url
        self.hub_api_url = (hub_api_url or os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")

    def _route_archive(self, method: str, endpoint: str, body=None, query=None, timeout: int = 8):
        normalized = endpoint.lstrip("/")
        response = requests.post(
            f"{self.hub_api_url}/route/archive/{normalized}",
            json={
                "method": method.upper(),
                "headers": {},
                "query": query or {},
                "body": body,
                "timeout_seconds": timeout,
            },
            timeout=timeout + 1,
        )
        if response.status_code != 200:
            return None
        routed = response.json() or {}
        if int(routed.get("status_code", 500)) >= 400:
            return None
        return routed.get("payload")

    def get_unevaluated(self, domain: str) -> list:
        """Asks the Vault for homework."""
        try:
            payload = self._route_archive(
                "GET", f"api/archive/{domain}/unevaluated", query={})
            if isinstance(payload, list):
                return payload
        except Exception as e:
            logger.warning("Vault connection failed: %s", e)
        return []

    def save_evaluation(self, record_id: int, evaluation: dict) -> bool:
        """Sends the graded homework back to the Vault."""
        payload = {"evaluation": evaluation}

        try:
            routed_payload = self._route_archive(
                "PATCH", f"api/archive/{record_id}", body=payload)
            if routed_payload is not None:
                logger.info("Vault updated record | record_id=%s", record_id)
                return True
            logger.warning("Vault rejected update | record_id=%s", record_id)
        except Exception as e:
            logger.warning("Failed to update Vault: %s", e)
        return False

    def upsert_entity(self, entity_data: dict) -> bool:
        """
        Upsert entity to Archive: creates new or updates existing.
        Archive merges data intelligently, preferring longer/more complete values.
        No duplicates will be created - entity_id is unique.
        """
        try:
            routed_payload = self._route_archive(
                "POST", "api/entities", body=entity_data)
            if routed_payload is not None:
                logger.info("Vault upserted entity | entity_id=%s",
                            entity_data.get("entity_id"))
                return True
            logger.warning("Vault rejected entity payload")
        except Exception as e:
            logger.warning("Failed to route entity to Vault: %s", e)
        return False

    def get_entity_records(self, domain: str, status: str = "active", limit: int = 1000) -> list:
        try:
            payload = self._route_archive("GET", "api/entities/records", query={
                "domain": domain,
                "status": status,
                "limit": limit,
            }, timeout=8)
            if isinstance(payload, list):
                return payload
            logger.warning("Vault rejected entity records request")
        except Exception as e:
            logger.warning("Failed to fetch entity records: %s", e)
        return []

    def get_all_entity_ids(self, domain: str, status: str = "active", limit: int = 5000) -> set[str]:
        """Return a set of all known entity_ids for a domain from Archive.

        Used for pre-parse deduplication: the result is a local cache that
        avoids per-URL round trips to Archive during the classification phase.
        """
        records = self.get_entity_records(
            domain=domain, status=status, limit=limit)
        return {str(r["entity_id"]) for r in records if r.get("entity_id")}

    def get_entity_by_id(self, entity_id: str) -> dict | None:
        """Fetch a single entity record by its entity_id."""
        try:
            payload = self._route_archive(
                "GET", f"api/entities/{entity_id}", query={}, timeout=6
            )
            if isinstance(payload, dict):
                return payload
        except Exception as e:
            logger.warning(
                "Failed to fetch entity | entity_id=%s error=%s", entity_id, e)
        return None

    def cleanup_entities(self, domain: str, required_fields: list[str], require_created_at: bool = True, dry_run: bool = False) -> dict:
        payload = {
            "domain": domain,
            "required_fields": required_fields,
            "require_created_at": require_created_at,
            "delete_limit": 2000,
            "dry_run": dry_run,
        }
        try:
            routed_payload = self._route_archive(
                "POST", "api/entities/cleanup", body=payload, timeout=10)
            if isinstance(routed_payload, dict):
                return routed_payload
            logger.warning("Vault cleanup request failed")
        except Exception as e:
            logger.warning("Failed cleanup call: %s", e)
        return {}
