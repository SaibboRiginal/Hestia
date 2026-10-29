"""Module kit: the common skeleton of a Hestia domain module (dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5).

The older modules (Hercules, Hygieia, Wardrobe, Plutus) each carry a copy of the same pieces: Hub client, Archive
mirror, error handlers, MCP router with REST paths, Hub registration with keepalive, warm-up. The modules born in
wave 5 (Apollo, Aphrodite, Lares, Hera, Demeter, Calliope, Kairos) take them from here, so each one is only its own
domain code:

    kit = ModuleKit("hera", port=19025, api="/api/people", domain="people", title="Persone",
                    store="people-store", when_to_use="persone importanti: compleanni, gusti, idee regalo",
                    manual="…")
    people = People(kit.store, kit.settings.get)
    kit.settings.declare([...])
    kit.tools([MCPTool(...), ...], prefix="people_")      # MCP + one REST path per tool, Telegram hints inside
    kit.agenda_rules(lambda: [job_rule(...)])
    kit.on_warm(people.ensure_seed)
    app = kit.app                                          # uvicorn app.main:app

Rules kept: Hub is the only door (``Hub``), Archive the only DB (``Store`` over ``/api/<store>/records``), settings
in Themis, schedules in the agenda, ``[🔄]`` logs on every fallback.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import requests

logger = logging.getLogger("hestia_common.module_kit")


# ── errors every module maps to HTTP ────────────────────────────────────────
class Invalid(ValueError):
    """422: the request is wrong (message in Italian, shown to the user)."""


class NotFound(LookupError):
    """404."""


class StoreUnavailable(RuntimeError):
    """503: Archive is not reachable."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def new_id(prefix: str = "") -> str:
    import uuid
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ── Hub ─────────────────────────────────────────────────────────────────────
class HubError(RuntimeError):
    def __init__(self, status: int, payload: Any = None):
        super().__init__(f"status {status}")
        self.status = status
        self.payload = payload


class Hub:
    """``POST {HUB}/route/<svc>/<path>`` with the standard envelope."""

    def __init__(self, hub_api_url: str):
        self.base = hub_api_url.rstrip("/")
        self._session = requests.Session()

    def call(self, service: str, method: str, path: str, *, body: Any = None, query: dict | None = None,
             timeout: float = 8) -> tuple[int, Any]:
        resp = self._session.post(
            f"{self.base}/route/{service}/{path.lstrip('/')}",
            json={"method": method.upper(), "headers": {},
                  "query": {k: v for k, v in (query or {}).items() if v is not None},
                  "body": body, "timeout_seconds": timeout},
            timeout=timeout + 3)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    def ok(self, service: str, method: str, path: str, **kw) -> Any:
        status, payload = self.call(service, method, path, **kw)
        if status >= 400:
            raise HubError(status, payload)
        return payload

    def notify(self, event: dict) -> bool:
        """A Hermes event (the only one who writes to the owner). False when it did not reach Hermes."""
        try:
            self.ok("hermes", "POST", "api/events/ingest", body=event, timeout=10)
            return True
        except Exception as exc:
            logger.warning("[🔄] event=module_notify_failed error=%s", exc)
            return False

    def llm(self, prompt: str, *, use_case: str, max_tokens: int = 1200, temperature: float = 0.2) -> str | None:
        """Oracle ``/api/llm/chat`` (the only door to models). None on failure: the caller keeps a fallback."""
        body = {"use_case": use_case, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        try:
            out = self.ok("oracle", "POST", "api/llm/chat", body=body, timeout=120)
            text = ((out or {}).get("choices") or [{}])[0].get("message", {}).get("content") or ""
            if isinstance(text, list):
                text = " ".join(str(t.get("text", "")) for t in text if isinstance(t, dict))
            return str(text)
        except Exception as exc:
            logger.warning("[🔄] event=module_llm_failed use_case=%s error=%s fallback=deterministic", use_case, exc)
            return None


# ── Archive mirror ──────────────────────────────────────────────────────────
class Store:
    """In-memory mirror of ``/api/<store>/records`` (Archive, via Hub) kept in step by cursor. Every write goes to
    Archive first; reads stay instant and survive a short Archive outage (``[🔄]`` stale reads)."""

    def __init__(self, hub: Hub, store: str, *, name: str = "module", min_refresh_seconds: float = 2.0):
        self.hub = hub
        self.path = f"api/{store.strip('/')}/records"
        self.name = name
        self.rows: dict[tuple[str, str], dict] = {}
        self.cursor = 0
        self.loaded = False
        self.epoch: str | None = None
        self.revision = 0
        self._lock = threading.RLock()
        self._last_refresh = 0.0
        self._min_refresh = min_refresh_seconds

    def refresh(self, force: bool = False) -> bool:
        with self._lock:
            if not force and self.loaded and time.monotonic() - self._last_refresh < self._min_refresh:
                return True
            try:
                query = {"since_seq": self.cursor, "limit": 20000} if self.loaded else {"include_deleted": "true",
                                                                                     "limit": 20000}
                while True:
                    data = self.hub.ok("archive", "GET", self.path, query=query, timeout=15)
                    epoch = (data or {}).get("epoch")
                    if epoch and self.epoch and epoch != self.epoch:
                        logger.warning("[🔄] event=%s_mirror_reset reason=data_epoch", self.name)
                        self.rows.clear()
                        self.cursor, self.loaded, self.epoch = 0, False, epoch
                        self.revision += 1
                        query = {"include_deleted": "true", "limit": 20000}
                        continue
                    self.epoch = epoch or self.epoch
                    rows = (data or {}).get("rows") or []
                    for r in rows:
                        self._put(r)
                    if rows:
                        self.cursor = max(self.cursor, max(int(r.get("seq") or 0) for r in rows))
                    if len(rows) < 20000:
                        break
                    query = {"since_seq": self.cursor, "limit": 20000}
                if not self.loaded:
                    logger.info("event=%s_mirror_loaded rows=%d cursor=%d", self.name, len(self.rows), self.cursor)
                self.loaded = True
                self._last_refresh = time.monotonic()
                return True
            except Exception as exc:
                logger.warning("[🔄] event=%s_mirror_refresh_failed error=%s fallback=stale_mirror", self.name, exc)
                return False

    def _put(self, r: dict) -> None:
        key = (r["kind"], r["id"])
        old = self.rows.get(key)
        floor = datetime.min.replace(tzinfo=timezone.utc)
        if old and (parse_dt(old.get("updated_at")) or floor) > (parse_dt(r.get("updated_at")) or floor):
            return
        self.rows[key] = r
        self.revision += 1

    def get(self, kind: str, id: str, *, deleted: bool = False) -> dict | None:
        row = self.rows.get((kind, id))
        if row is None or (row.get("deleted") and not deleted):
            return None
        return row

    def data(self, kind: str, id: str) -> dict | None:
        row = self.get(kind, id)
        return {**row["data"], "id": row["id"]} if row else None

    def all(self, kind: str, *, deleted: bool = False) -> list[dict]:
        return [r for (k, _), r in self.rows.items() if k == kind and (deleted or not r.get("deleted"))]

    def items(self, kind: str) -> list[dict]:
        return [{**r["data"], "id": r["id"]} for r in self.all(kind)]

    def write(self, rows: Iterable[dict]) -> dict:
        rows = [dict(r) for r in rows]
        if not rows:
            return {"applied": [], "stale": [], "cursor": self.cursor}
        for r in rows:
            r.setdefault("updated_at", now_iso())
            r.setdefault("data", {})
            r.setdefault("deleted", False)
            if isinstance(r.get("at"), datetime):
                r["at"] = r["at"].isoformat()
        try:
            out: dict = {"applied": [], "stale": []}
            for i in range(0, len(rows), 2000):
                part = self.hub.ok("archive", "PUT", self.path, body={"rows": rows[i:i + 2000]}, timeout=20) or {}
                out["applied"] += part.get("applied") or []
                out["stale"] += part.get("stale") or []
                out["cursor"] = part.get("cursor", self.cursor)
        except Exception as exc:
            logger.warning("[🔄] event=%s_write_failed rows=%d error=%s", self.name, len(rows), exc)
            raise StoreUnavailable(str(exc)) from exc
        seqs = {(a["kind"], a["id"]): a["seq"] for a in out["applied"]}
        with self._lock:
            for r in rows:
                seq = seqs.get((r["kind"], r["id"]))
                if seq is not None:
                    self._put({**r, "seq": seq})
            for s in out["stale"]:
                self._put(s)
        self.refresh(force=True)
        return out

    def upsert(self, kind: str, id: str, data: dict, *, parent_id: str | None = None, ref_id: str | None = None,
               at: Any = None) -> dict:
        self.write([{"kind": kind, "id": id, "parent_id": parent_id, "ref_id": ref_id,
                     "at": at.isoformat() if isinstance(at, datetime) else at, "data": data}])
        return {**data, "id": id}

    def delete(self, kind: str, id: str) -> bool:
        row = self.get(kind, id)
        if not row:
            return False
        self.write([{**{k: row.get(k) for k in ("kind", "id", "parent_id", "ref_id", "at", "data")}, "deleted": True}])
        return True


class FakeArchive:
    """Archive stand-in for unit tests (same LWW + seq protocol). ``Store(FakeArchive(), "x-store")``."""

    def __init__(self):
        self.rows: dict = {}
        self.seq = 0
        self.down = False
        self.calls: list[tuple] = []
        self.blobs: dict[str, dict] = {}

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        self.calls.append((service, method, path))
        if service != "archive":
            return {}
        if self.down:
            raise OSError("archive down")
        if path.startswith("api/blobs"):
            return self._blob(method, path, body)
        if method == "PUT":
            applied, stale = [], []
            for r in body["rows"]:
                key = (r["kind"], r["id"])
                old = self.rows.get(key)
                if old and parse_dt(old["updated_at"]) > parse_dt(r["updated_at"]):
                    stale.append(old)
                    continue
                self.seq += 1
                self.rows[key] = {**r, "seq": self.seq}
                applied.append({"kind": r["kind"], "id": r["id"], "seq": self.seq})
            return {"applied": applied, "stale": stale, "cursor": self.seq}
        since = int((query or {}).get("since_seq") or 0)
        rows = sorted((r for r in self.rows.values() if r["seq"] > since), key=lambda r: r["seq"])
        return {"rows": rows, "cursor": self.seq}

    def _blob(self, method, path, body):
        if method == "POST":
            bid = f"b{len(self.blobs) + 1}"
            self.blobs[bid] = {"mime": body["content_type"], "data_b64": body["data_base64"], "meta": body.get("meta")}
            return {"blob_id": bid, "content_type": body["content_type"]}
        bid = path.split("/")[2]
        if method == "DELETE":
            return {"status": "deleted" if self.blobs.pop(bid, None) else "absent"}
        blob = self.blobs.get(bid)
        if blob is None:
            raise OSError("blob not found")
        return {"blob_id": bid, "mime": blob["mime"], "data_b64": blob["data_b64"]}

    def call(self, service, method, path, **kw):
        return 200, self.ok(service, method, path, **kw)

    def notify(self, event):
        self.calls.append(("hermes", "POST", event.get("entity_id")))
        return True

    def llm(self, prompt, **kw):
        return None


# ── the module skeleton ─────────────────────────────────────────────────────
def coerce(tool) -> Callable[..., Any]:
    """REST callers (Telegram, gateway) send strings: coerce by the tool's schema, drop unknown keys, map errors."""
    props = (tool.parameters or {}).get("properties") or {}
    inner = tool.handler

    def run(**kw):
        for k, v in list(kw.items()):
            typ = (props.get(k) or {}).get("type")
            if not isinstance(v, str):
                continue
            if typ == "integer" and v.strip().lstrip("-").isdigit():
                kw[k] = int(v)
            elif typ == "number":
                try:
                    kw[k] = float(v.replace(",", "."))
                except ValueError:
                    pass
            elif typ == "boolean":
                kw[k] = v.lower() in ("1", "true", "si", "sì", "yes")
            elif typ == "array":
                kw[k] = [x.strip() for x in v.split(",") if x.strip()]
        try:
            return inner(**{k: v for k, v in kw.items() if k in props and v is not None})
        except (Invalid, NotFound) as exc:
            return {"error": str(exc)}
        except StoreUnavailable:
            return {"error": "archivio non raggiungibile, riprova tra poco"}
    return run


class ModuleKit:
    def __init__(self, name: str, *, port: int, api: str, domain: str, title: str, store: str,
                 when_to_use: str, manual: str, tags: Iterable[str] = (), version: str = "1.0.0"):
        from fastapi import FastAPI, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse

        from .logging_utils import create_log_control_router, setup_service_logging
        from .settings_client import SettingsClient

        self.name, self.api, self.domain, self.title = name, api.rstrip("/"), domain, title
        self.logger, _ = setup_service_logging(f"hestia_{name}")
        self.base_url = os.getenv("SERVICE_BASE_URL", f"http://hestia_{name}:{port}")
        self.version = os.getenv("SERVICE_VERSION", version)
        self.hub_url = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
        self.tz = os.getenv("TZ") or "Europe/Rome"
        self.tags = ["module", domain, *tags]
        self.when_to_use, self.manual = when_to_use, manual
        self.hub = Hub(self.hub_url)
        self.store = Store(self.hub, store, name=name)
        self.settings = SettingsClient(name)
        self.caps: dict[str, Any] = {}
        self._rules: Callable[[], list[dict]] | None = None
        self._warm: list[Callable[[], Any]] = []
        self._tools: list = []
        self._extra_caps: list[Callable[[], dict]] = []

        app = FastAPI(title=f"Hestia-{name.capitalize()}", version=self.version)
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

        @app.exception_handler(Invalid)
        async def _invalid(_: Request, exc: Invalid):
            return JSONResponse(status_code=422, content={"detail": str(exc)})

        @app.exception_handler(NotFound)
        async def _not_found(_: Request, exc: NotFound):
            return JSONResponse(status_code=404, content={"detail": str(exc)})

        @app.exception_handler(StoreUnavailable)
        async def _store_down(_: Request, exc: StoreUnavailable):
            return JSONResponse(status_code=503, content={"detail": "archivio non raggiungibile, riprova tra poco"})

        @app.get("/health")
        def health():
            return {"status": "ok", "service": f"hestia_{name}", "version": self.version,
                    "mirror_loaded": self.store.loaded, "rows": len(self.store.rows), **self.health_extra()}

        app.include_router(create_log_control_router(f"hestia_{name}"))
        app.router.add_event_handler("startup", self.start)
        self.app = app

    def health_extra(self) -> dict:
        return {}

    # ── wiring ──────────────────────────────────────────────────────────────
    def tools(self, tools: list, *, prefix: str) -> None:
        """MCP router + one REST path per tool (``{api}/tools/<name without prefix>``)."""
        from .mcp_helpers import create_mcp_router, mount_missing_rest_routes
        for t in tools:
            t.path = f"{self.api}/tools/{t.name.removeprefix(prefix)}"
            t.handler = coerce(t)
        self._tools = tools
        self.app.include_router(create_mcp_router(tools, service_name=self.name))
        self._mount_rest = lambda: mount_missing_rest_routes(self.app, tools, service_name=self.name)

    def finish(self) -> None:
        """Call after the module's own routes: REST paths of the tools, settings router."""
        if getattr(self, "_mount_rest", None):
            self._mount_rest()
            # tool paths first: «{api}/tools/done» must not be taken by a module's «{api}/{id}/done»
            tools_prefix = f"{self.api}/tools/"
            routes = self.app.router.routes
            routes[:] = sorted(routes, key=lambda r: not str(getattr(r, "path", "")).startswith(tools_prefix))
        self.app.include_router(self.settings.router())

    def webui(self, *, icon: str, color: str, description: str, pages: list, widgets: list | None = None,
              quick_actions: list | None = None) -> Any:
        """The module's WebUI plugin (bundle ``ui/`` → ``<dist>/webui/<name>.js``, built in the image): manifest
        router + Hub capabilities. ``<NAME>_UI_DIST`` overrides the folder (default ``/code/ui/dist``)."""
        from .plugin_client import PluginClient
        ui = PluginClient(self.name, title=self.title, icon=icon, color=color, description=description,
                          dist=os.getenv(f"{self.name.upper()}_UI_DIST", "/code/ui/dist"), version=self.version)
        ui.webui(entry=f"{self.name}.js", api_prefix=f"{self.api}/", pages=pages, widgets=widgets or [],
                 quick_actions=quick_actions or [])
        self.app.include_router(ui.router())
        self.capabilities(lambda: ui.capabilities(self.base_url))
        self.ui = ui
        return ui

    def agenda_rules(self, rules: Callable[[], list[dict]]) -> None:
        self._rules = rules

    def on_warm(self, fn: Callable[[], Any]) -> None:
        self._warm.append(fn)

    def capabilities(self, fn: Callable[[], dict]) -> None:
        self._extra_caps.append(fn)

    def registration(self) -> dict:
        caps = {"when_to_use": self.when_to_use, "manual": self.manual,
                "mcp_endpoint": f"{self.base_url.rstrip('/')}/mcp", "module_tool_domains": [self.domain], **self.caps}
        for fn in self._extra_caps:
            try:
                caps.update(fn() or {})
            except Exception as exc:
                self.logger.warning("[🔄] event=%s_caps_failed error=%s", self.name, exc)
        return {"name": self.name, "base_url": self.base_url, "health_endpoint": "/health", "service_type": "module",
                "service_version": self.version, "tags": self.tags,
                "topology_tags": ["layer:domain", f"domain:{self.domain}", "status:alpha"], "capabilities": caps}

    def register(self) -> None:
        resp = requests.post(f"{self.hub_url}/registry/register", json=self.registration(), timeout=4)
        if resp.status_code >= 400:
            self.logger.warning("event=hub_registration_non_success status=%s", resp.status_code)
        else:
            self.logger.info("event=registered_on_hub hub=%s base_url=%s", self.hub_url, self.base_url)

    def _warm_up(self) -> None:
        for attempt in range(1, 1000):
            try:
                if self.store.refresh(force=True):
                    for fn in self._warm:
                        fn()
                    return
            except Exception as exc:
                self.logger.warning("[🔄] event=%s_warmup_failed attempt=%d error=%s", self.name, attempt, exc)
            time.sleep(min(60, 5 * attempt))

    def start(self) -> None:
        from .startup_utils import start_hub_keepalive
        try:
            self.register()
        except Exception as exc:
            self.logger.warning("[🔄] event=hub_registration_failed_non_fatal error=%s", exc)
        start_hub_keepalive(self.register, logger=self.logger, name=f"{self.name}-hub-keepalive")
        self.settings.start()
        if self._rules is not None:
            from .agenda_client import AgendaClient
            AgendaClient(self.name, self.hub_url).register_async(self._rules)
        threading.Thread(target=self._warm_up, daemon=True, name=f"{self.name}-warmup").start()
