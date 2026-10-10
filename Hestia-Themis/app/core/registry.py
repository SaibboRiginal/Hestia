"""Schema registry: what every module declared (definitions + presets).

Kept in memory and mirrored to a JSON cache in Themis' data dir, so the panel can
show a module's settings while that module is offline. Modules re-assert their
schema periodically (``SettingsClient.start``), which also rebuilds it after a
Themis restart.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("hestia_themis.registry")


def _norm(text: Any) -> str:
    return str(text or "").lower()


class Registry:
    def __init__(self, cache_file: Path | None = None):
        self._lock = threading.Lock()
        self._modules: dict[str, dict] = {}
        self._cache_file = cache_file
        self._load_cache()

    # ── persistence ─────────────────────────────────────────────────────────
    def _load_cache(self) -> None:
        if not self._cache_file or not self._cache_file.exists():
            return
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8") or "{}")
            if isinstance(data, dict):
                self._modules = {k: v for k, v in data.items() if isinstance(v, dict)}
                logger.info("event=themis_schema_cache_loaded modules=%d", len(self._modules))
        except Exception as exc:
            logger.warning("[🔄] event=themis_schema_cache_invalid error=%s", exc)

    def _save_cache(self) -> None:
        if not self._cache_file:
            return
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._modules, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._cache_file)
        except Exception as exc:
            logger.warning("event=themis_schema_cache_save_failed error=%s", exc)

    # ── registration ────────────────────────────────────────────────────────
    def register(self, owner: str, definitions: list[dict], presets: list[dict] | None = None,
                 effective: dict | None = None) -> bool:
        """Replace ``owner``'s schema. Returns True when the schema changed."""
        defs = [dict(d, module=owner) for d in definitions or []
                if isinstance(d, dict) and str(d.get("key", "")).startswith(f"{owner}.")]
        entry = {"definitions": defs, "presets": [p for p in presets or [] if isinstance(p, dict)]}
        with self._lock:
            old = self._modules.get(owner) or {}
            changed = (old.get("definitions"), old.get("presets")) != (entry["definitions"], entry["presets"])
            self._modules[owner] = {**entry, "registered_at": time.time(), "effective": dict(effective or {})}
            if changed:
                self._save_cache()
        return changed

    def set_effective(self, owner: str, effective: dict) -> None:
        with self._lock:
            if owner in self._modules:
                self._modules[owner]["effective"] = dict(effective or {})

    # ── reading ─────────────────────────────────────────────────────────────
    def modules(self) -> list[str]:
        with self._lock:
            return sorted(self._modules)

    def module(self, owner: str) -> dict | None:
        with self._lock:
            entry = self._modules.get(owner)
            return json.loads(json.dumps(entry)) if entry else None

    def definition(self, key: str) -> dict | None:
        owner = key.split(".", 1)[0]
        with self._lock:
            for d in (self._modules.get(owner) or {}).get("definitions", []):
                if d.get("key") == key:
                    return dict(d)
        return None

    def definitions(self, module: str | None = None, q: str = "") -> list[dict]:
        """Definitions, optionally filtered by module and a search over label, help, key, group, module."""
        terms = [t for t in _norm(q).split() if t]
        out: list[dict] = []
        with self._lock:
            for owner, entry in sorted(self._modules.items()):
                if module and owner != module:
                    continue
                for d in entry.get("definitions", []):
                    hay = " ".join(_norm(d.get(f)) for f in ("key", "label", "help", "group", "module"))
                    hay += " " + " ".join(_norm(o.get("label")) for o in d.get("options") or [])
                    if all(t in hay for t in terms):
                        out.append(dict(d))
        return out

    def presets(self, owner: str) -> list[dict]:
        with self._lock:
            return [dict(p) for p in (self._modules.get(owner) or {}).get("presets", [])]
