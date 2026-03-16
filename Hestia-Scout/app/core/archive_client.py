import requests
import os


class ArchiveClient:
    """Handles communication between the AI Worker and the Vault."""

    def __init__(self, api_url: str, hub_api_url: str | None = None):
        self.api_url = api_url
        self.hub_api_url = (hub_api_url or os.getenv(
            "HUB_API_URL", "http://hestia_hub:8005/api")).rstrip("/")

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
            print(f"[-] Vault connection failed: {e}")
        return []

    def save_evaluation(self, record_id: int, evaluation: dict) -> bool:
        """Sends the graded homework back to the Vault."""
        payload = {"evaluation": evaluation}

        try:
            routed_payload = self._route_archive(
                "PATCH", f"api/archive/{record_id}", body=payload)
            if routed_payload is not None:
                print(f"[✓] Vault updated record #{record_id}")
                return True
            print(f"[!] Vault rejected update for #{record_id}")
        except Exception as e:
            print(f"[-] Failed to update Vault: {e}")
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
                print(
                    f"[✓] Vault upserted Entity: {entity_data.get('entity_id')}")
                return True
            print(f"[!] Vault rejected Entity payload")
        except Exception as e:
            print(f"[-] Failed to route Entity to Vault: {e}")
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
            print("[!] Vault rejected entity records request")
        except Exception as e:
            print(f"[-] Failed to fetch entity records: {e}")
        return []

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
            print("[!] Vault cleanup request failed")
        except Exception as e:
            print(f"[-] Failed cleanup call: {e}")
        return {}
