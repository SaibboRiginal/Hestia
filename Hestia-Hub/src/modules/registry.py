import threading
import time
from typing import Any

NODE_FRESH_SECONDS = 180   # a satellite module re-registered within this window counts as answering


class ServiceRegistry:
    def __init__(self):
        self._services: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def register(self, service: dict[str, Any]) -> str:
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
                # Treat identical keepalive re-registration as a refresh, not a change.
                # A restored instance re-registering clears ``restored`` without counting as a change.
                comparable_existing = {
                    k: v for k, v in existing.items() if k not in ("updated_at", "restored")
                }
                comparable_incoming = {
                    k: v for k, v in service.items() if k not in ("updated_at", "restored")
                }
                existing.pop("restored", None)
                existing.update(service)
                return "updated" if comparable_existing != comparable_incoming else "refreshed"
            else:
                current.append(service)
                return "created"

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

    def restore(self, instances: list[dict[str, Any]]) -> int:
        """Load instances from a snapshot (Hub restart). Each gets ``restored: True`` until it
        re-registers. Instances already registered (same name + base_url) are kept as they are."""
        count = 0
        with self._lock:
            for item in instances:
                name = str(item.get("name") or "").strip().lower()
                base_url = item.get("base_url")
                if not name or not base_url:
                    continue
                current = self._services.setdefault(name, [])
                if any(it.get("base_url") == base_url for it in current):
                    continue
                current.append({**item, "name": name, "restored": True})
                count += 1
        return count

    def get(self, name: str) -> list[dict[str, Any]]:
        """Instances for *name*, most recently refreshed first, so a dead
        instance that stopped re-registering is tried last (failover latency).
        A satellite's copy (``node``) that answers comes before the central's own: the module runs where the
        hardware is, and the central's copy is the fallback (docs/work/2026-10-30-setup-un-click §4.0)."""
        with self._lock:
            items = list(self._services.get(name.strip().lower(), []))
        now = time.time()

        def rank(it: dict[str, Any]) -> tuple[bool, float]:
            seen = float(it.get("updated_at") or 0)
            return bool(it.get("node")) and now - seen < NODE_FRESH_SECONDS, seen
        return sorted(items, key=rank, reverse=True)
