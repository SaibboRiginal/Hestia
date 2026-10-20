"""Registry snapshot — Hub's routing table on disk, so a Hub restart is not blind.

Single responsibility: save / load the registry as one JSON file in Hub's own volume.
A cache of Hub's own table, not business data (that lives in Archive, which itself is found
through Hub). Services keep re-registering every 60 s: the snapshot only covers the gap.
SPEC ``docs/work/2026-10-20-hub-registro-persistente``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(f"hestia_hub.{__name__}")

SNAPSHOT_PATH = Path("/code/data/registry.json")   # volume ./Hestia-Hub/data:/code/data
SNAPSHOT_VERSION = 1
MAX_AGE_SECONDS = 24 * 3600.0     # older heartbeats are not restored (read before Themis can answer)
REFRESH_WRITE_INTERVAL = 30.0     # heartbeat-only changes are written at most this often (SD card)


class RegistrySnapshot:
    def __init__(self, path: Path | str = SNAPSHOT_PATH, *, max_age: float = MAX_AGE_SECONDS,
                 refresh_interval: float = REFRESH_WRITE_INTERVAL) -> None:
        self.path = Path(path)
        self.max_age = max_age
        self.refresh_interval = refresh_interval
        self._lock = threading.Lock()
        self._last_write = 0.0
        self._dirty = False

    def load(self, now: float | None = None) -> dict[str, Any]:
        """``{"revision", "services", "dropped", "saved_at"}``; empty on a missing or broken file."""
        now = time.time() if now is None else now
        empty = {"revision": 0, "services": [], "dropped": 0, "saved_at": None}
        if not self.path.exists():
            return empty
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("services"), list):
                raise ValueError("unexpected snapshot shape")
            fresh, dropped = [], 0
            for item in data["services"]:
                if not isinstance(item, dict) or not item.get("name") or not item.get("base_url"):
                    dropped += 1
                    continue
                if now - float(item.get("updated_at") or 0) > self.max_age:
                    dropped += 1
                    continue
                fresh.append(item)
            return {"revision": int(data.get("revision") or 0), "services": fresh, "dropped": dropped,
                    "saved_at": data.get("saved_at")}
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("event=hub_registry_restore_failed [🔄] snapshot unreadable, starting empty | "
                           "path=%s error=%s", self.path, exc)
            return empty

    def save(self, services: list[dict[str, Any]], revision: int, *, force: bool = True) -> bool:
        """Write the snapshot. ``force=False`` (heartbeat refresh) writes only if the last write is
        older than ``refresh_interval``; otherwise the change waits for the next write."""
        now = time.time()
        with self._lock:
            if not force and now - self._last_write < self.refresh_interval:
                self._dirty = True
                return False
            payload = {"version": SNAPSHOT_VERSION, "saved_at": now, "revision": int(revision),
                       "services": [dict(s) for s in services]}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_name(self.path.name + ".tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError as exc:
                logger.warning("event=hub_registry_save_failed [🔄] registry kept in memory only | "
                               "path=%s error=%s", self.path, exc)
                self._dirty = True
                return False
            self._last_write = now
            self._dirty = False
            return True

    @property
    def dirty(self) -> bool:
        return self._dirty
