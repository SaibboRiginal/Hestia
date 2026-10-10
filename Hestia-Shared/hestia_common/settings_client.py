"""Central settings client — every module declares its settings to Themis and reads them back.

Themis (``/api/settings*``, via Hub) is the one place where Hestia's settings live:
modules **declare** what they accept (type, default, options, ranges…), the user and
the assistant change values from any client, Archive stores them.

    from hestia_common.settings_client import SettingsClient, setting, preset

    settings = SettingsClient("argus")
    settings.declare([
        setting("argus.poll.interval", "Intervallo controlli", "int", 30, group="Controlli",
                help="Ogni quanti secondi controllo la salute dei moduli.", min=5, max=600, unit="s"),
        setting("argus.remediate.enabled", "Rimedio automatico", "bool", False, group="Rimedio"),
        setting("argus.remediate.dry_run", "Solo simulazione", "bool", True, group="Rimedio",
                depends_on={"key": "argus.remediate.enabled", "equals": True}),
    ], presets=[preset("calmo", "Tranquillo", group="Controlli", values={"argus.poll.interval": 120})])
    app.include_router(settings.router())          # GET /api/settings/effective, POST /api/settings/reload
    settings.start()                               # on startup: background load + hourly re-assert
    settings.get("argus.poll.interval")            # effective value (stored → default)
    settings.on_change(lambda changed: ...)        # live settings changed by the user

Semantics
- ``apply="live"``: a new value is used at once (``get`` returns it, ``on_change`` fires).
- ``apply="restart"``: the value loaded at startup stays effective until the module restarts;
  Themis compares stored vs effective and shows "riavvio necessario" to every client.
- Themis unreachable → defaults, ``[🔄]`` log; registration retried in background, values applied
  when it answers (restart settings then wait for a restart, honestly reported).
- Secrets and infrastructure (URLs, ports, paths, tokens) are NOT settings: they stay in env.

Definition scopes: ``system`` (one value for Hestia) or ``user`` (layered values:
profile → client → session, e.g. chat tone). Modules read ``system`` values with ``get``;
``user`` values are resolved by the clients through Themis.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

import requests

logger = logging.getLogger("hestia_common.settings")

TYPES = {"enum", "bool", "int", "float", "string", "text", "model", "time", "duration", "list", "object"}
APPLY = {"live", "restart"}
SCOPES = {"system", "user"}
ORACLE_ACCESS = {"propose", "read", "none"}


def _hub_default() -> str:
    return os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")


def setting(key: str, label: str, type: str, default: Any, *, group: str = "Generale", help: str = "",
            options: list | None = None, min: float | None = None, max: float | None = None,
            unit: str = "", apply: str = "live", scope: str = "system", depends_on: dict | None = None,
            oracle: str = "propose", advanced: bool = False, order: int = 0,
            options_source: str = "", fields: dict | None = None) -> dict:
    """Build one setting definition (validated by Themis against its type).

    ``options``: for ``enum`` a list of values or ``(value, label)`` pairs.
    ``options_source``: GET path on the owning module returning dynamic options
    (e.g. models of a provider) as ``{"options": [{"value", "label"}]}``.
    ``fields``: for ``object`` the sub-fields (each a ``setting``-like dict without key).
    ``oracle``: what the assistant may do — ``propose`` (default, always confirmed by the user),
    ``read``, or ``none`` for safety switches.
    """
    if type not in TYPES:
        raise ValueError(f"unknown setting type {type!r}")
    if apply not in APPLY or scope not in SCOPES or oracle not in ORACLE_ACCESS:
        raise ValueError(f"bad apply/scope/oracle for {key}")
    opts = None
    if options is not None:
        opts = [{"value": o[0], "label": o[1]} if isinstance(o, (tuple, list)) else
                (o if isinstance(o, dict) else {"value": o, "label": str(o)}) for o in options]
    out = {"key": key, "label": label, "type": type, "default": default, "group": group, "help": help,
           "apply": apply, "scope": scope, "oracle": oracle, "advanced": bool(advanced), "order": int(order)}
    for name, value in (("options", opts), ("min", min), ("max", max), ("unit", unit or None),
                        ("depends_on", depends_on), ("options_source", options_source or None),
                        ("fields", fields)):
        if value is not None:
            out[name] = value
    return out


def preset(id: str, label: str, *, group: str, values: dict, help: str = "") -> dict:
    """A named bundle of values for one group (e.g. Economico / Qualità)."""
    return {"id": id, "label": label, "group": group, "values": dict(values), "help": help}


class SettingsClient:
    """Declares one module's settings to Themis and keeps their effective values."""

    def __init__(self, owner: str, hub_api_url: str | None = None):
        self.owner = owner
        self.hub = (hub_api_url or _hub_default()).rstrip("/")
        self._defs: dict[str, dict] = {}
        self._presets: list[dict] = []
        self._effective: dict[str, Any] = {}     # what the module really uses now
        self._stored: dict[str, Any] = {}        # last values received from Themis
        self._callbacks: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self._loaded = False
        self._started = False

    # ── declaration ─────────────────────────────────────────────────────────
    def declare(self, definitions: list[dict], presets: list[dict] | None = None) -> "SettingsClient":
        for d in definitions:
            if not str(d.get("key", "")).startswith(f"{self.owner}."):
                raise ValueError(f"setting {d.get('key')!r} must start with '{self.owner}.'")
            self._defs[d["key"]] = d
            self._effective.setdefault(d["key"], d.get("default"))
        self._presets.extend(presets or [])
        return self

    def declare_log_level(self) -> "SettingsClient":
        """Standard ``<owner>.log.level`` setting (live): replaces the LOG_LEVEL env var."""
        key = f"{self.owner}.log.level"
        boot = str(os.getenv("LOG_LEVEL", "INFO")).upper()   # level the service starts with (default)
        self.declare([setting(key, "Livello dei log", "enum", boot if boot in {"TRACE", "DEBUG", "INFO", "WARNING",
                                                                                "ERROR"} else "INFO",
                              group="Diagnostica", advanced=True,
                              options=[("TRACE", "Traccia (massimo dettaglio)"), ("DEBUG", "Debug (tutto)"),
                                       ("INFO", "Normale"),
                                       ("WARNING", "Solo avvisi"), ("ERROR", "Solo errori")],
                              help="Quanto dettaglio scrive il modulo nei log.", order=900)])

        def _apply(changed: dict) -> None:
            if key in changed:
                from .logging_utils import set_log_level
                set_log_level(str(changed[key]))
        self.on_change(_apply)
        return self

    def on_change(self, callback: Callable[[dict], None]) -> None:
        """``callback({key: value})`` after live settings changed."""
        self._callbacks.append(callback)

    # ── reading ─────────────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._effective:
                return self._effective[key]
        d = self._defs.get(key)
        return d.get("default") if d else default

    def values(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._effective)

    def pending_restart(self) -> list[str]:
        with self._lock:
            return sorted(k for k, v in self._stored.items()
                          if k in self._defs and self._defs[k].get("apply") == "restart"
                          and self._effective.get(k) != v)

    # ── transport ───────────────────────────────────────────────────────────
    def _call(self, method: str, path: str, body: dict | None = None, query: dict | None = None,
              timeout: float = 6) -> tuple[int, Any]:
        resp = requests.post(
            f"{self.hub}/route/themis/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": query or {}, "body": body,
                  "timeout_seconds": timeout},
            timeout=timeout + 3)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    # ── applying values ─────────────────────────────────────────────────────
    def apply(self, stored: dict[str, Any], *, initial: bool = False) -> dict[str, Any]:
        """Take stored values from Themis. Keys missing from ``stored`` fall back to their default.
        Returns the live changes applied (also passed to ``on_change``)."""
        changed: dict[str, Any] = {}
        with self._lock:
            self._stored = {k: v for k, v in (stored or {}).items() if k in self._defs}
            for key, d in self._defs.items():
                value = self._stored.get(key, d.get("default"))
                if self._effective.get(key) == value:
                    continue
                if initial or d.get("apply") == "live":
                    self._effective[key] = value
                    changed[key] = value
            self._loaded = True
        if changed and not initial:
            logger.info("event=settings_applied owner=%s keys=%s", self.owner, ",".join(sorted(changed)))
        for cb in list(self._callbacks):   # also on the initial load: modules apply what they read
            if changed:
                try:
                    cb(dict(changed))
                except Exception as exc:
                    logger.warning("event=settings_callback_failed owner=%s error=%s", self.owner, exc)
        return changed

    def register(self) -> bool:
        """Declare definitions + presets; Themis answers with the stored values."""
        try:
            status, payload = self._call("POST", "api/settings/register", body={
                "owner": self.owner, "definitions": list(self._defs.values()), "presets": self._presets,
                "effective": self.values()})
        except Exception as exc:
            logger.warning("[🔄] event=settings_register_failed owner=%s error=%s fallback=defaults",
                           self.owner, exc)
            return False
        if not status or status >= 400 or not isinstance(payload, dict):
            logger.warning("[🔄] event=settings_register_rejected owner=%s status=%s", self.owner, status)
            return False
        self.apply(payload.get("values") or {}, initial=not self._loaded)
        logger.info("event=settings_registered owner=%s definitions=%d", self.owner, len(self._defs))
        return True

    def start(self, *, retry_seconds: float = 60, refresh_seconds: float = 3600,
              blocking: bool = False) -> threading.Thread | None:
        """Register in background (first load, then hourly re-assert: Themis keeps the schema in
        memory, so this also restores it after a Themis restart). ``blocking`` does the first
        attempt inline (use it only when values are needed before serving)."""
        if self._started:
            return None
        self._started = True
        first = self.register() if blocking else None

        def _loop():
            ok = first if first is not None else self.register()
            while True:
                time.sleep(refresh_seconds if ok else retry_seconds)
                ok = self.register()

        thread = threading.Thread(target=_loop, daemon=True, name=f"settings-register-{self.owner}")
        thread.start()
        return thread

    def put(self, key: str, value: Any, *, actor: str = "user", reason: str = "") -> bool:
        """Persist a change the USER made through this module's own UI/command (e.g. a Telegram
        command): Themis validates, stores and pushes it back. Never for the module's own choices."""
        try:
            status, payload = self._call("PUT", f"api/settings/key/{key}",
                                         body={"value": value, "actor": actor, "reason": reason})
        except Exception as exc:
            logger.warning("[🔄] event=settings_put_failed owner=%s key=%s error=%s", self.owner, key, exc)
            return False
        if status >= 400:
            logger.warning("event=settings_put_rejected owner=%s key=%s status=%s detail=%s",
                           self.owner, key, status, str(payload)[:200])
            return False
        return True

    # ── standard endpoints ──────────────────────────────────────────────────
    def router(self):
        """``GET /api/settings/effective`` and ``POST /api/settings/reload`` for Themis."""
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/api/settings/effective")
        def settings_effective():
            return {"owner": self.owner, "loaded": self._loaded, "values": self.values(),
                    "pending_restart": self.pending_restart()}

        @router.post("/api/settings/reload")
        def settings_reload(body: dict | None = None):
            values = (body or {}).get("values")
            if isinstance(values, dict):
                changed = self.apply(values, initial=not self._loaded)
            else:  # no values given: fetch them (register answers with the stored values)
                before = self.values()
                self.register()
                changed = {k: v for k, v in self.values().items() if before.get(k) != v}
            return {"owner": self.owner, "applied": sorted(changed), "pending_restart": self.pending_restart()}

        return router
