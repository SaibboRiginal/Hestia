import requests
import os


class ArchiveClient:
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:8005/api").rstrip("/")

    def _route_archive(self, payload: dict) -> bool:
        response = requests.post(
            f"{self.hub_api_url}/route/archive/api/archive",
            json={
                "method": "POST",
                "headers": {},
                "query": {},
                "body": payload,
                "timeout_seconds": 8,
            },
            timeout=9,
        )
        if response.status_code != 200:
            return False
        routed = response.json() or {}
        return int(routed.get("status_code", 500)) < 400

    def ship_record(self, payload: dict, domain: str, source: str, reference_id: str = None) -> bool:
        """Sends the raw data to the Vault, including the duplicate-protection fingerprint."""

        # We package the data exactly how the new Vault schema expects it
        data = {
            "reference_id": reference_id,
            "domain": domain,
            "source": source,
            "payload": payload
        }

        try:
            if self._route_archive(data):
                print(f"[✓] Vault saved raw record safely.")
                return True

            response = requests.post(self.api_url, json=data)
            if response.status_code == 200:
                print(f"[✓] Vault saved raw record safely.")
                return True
            print(f"[!] Vault rejected record: {response.text}")
            return False
        except Exception as e:
            print(f"[-] Failed to ship to Vault: {e}")
            return False
