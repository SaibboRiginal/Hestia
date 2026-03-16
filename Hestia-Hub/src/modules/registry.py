import threading
import time
from typing import Any


class ServiceRegistry:
    def __init__(self):
        self._services: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def register(self, service: dict[str, Any]):
        normalized_name = service["name"].strip().lower()
        service["name"] = normalized_name
        service["updated_at"] = time.time()

        with self._lock:
            current = self._services.setdefault(normalized_name, [])
            existing = None
            for item in current:
                if item.get("base_url") == service.get("base_url"):
                    existing = item
                    break
            if existing:
                existing.update(service)
            else:
                current.append(service)

    def deregister(self, name: str, base_url: str | None = None):
        normalized_name = name.strip().lower()
        with self._lock:
            if normalized_name not in self._services:
                return

            if not base_url:
                self._services.pop(normalized_name, None)
                return

            self._services[normalized_name] = [
                item for item in self._services[normalized_name]
                if item.get("base_url") != base_url
            ]
            if not self._services[normalized_name]:
                self._services.pop(normalized_name, None)

    def all_services(self) -> list[dict[str, Any]]:
        output = []
        with self._lock:
            for items in self._services.values():
                output.extend(items)
        return output

    def get(self, name: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._services.get(name.strip().lower(), []))
