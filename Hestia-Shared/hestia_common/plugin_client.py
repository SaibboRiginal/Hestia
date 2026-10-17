"""Client plugins — a module ships its own UI and advertises it to the clients through Hub.

Contract: ``docs/work/2026-10-17-client-plugins/SPEC.md`` §4. A module with a UI builds a browser bundle
(Web Components, ``Hestia-<Name>/ui/`` → ``ui/dist/<client>/``) and declares what it contributes per client
(pages, widgets, quick actions). Hub aggregates every module's manifest into one catalog
(``GET /api/discovery/catalog``) organized by client × type; each client loads what it supports and keeps its
own configuration (visibility, dashboards) as its own Themis settings.

    from hestia_common.plugin_client import PluginClient, page, widget, quick_action

    ui = PluginClient("scout", title="Scout", icon="home", color="amber", dist="/code/app/ui/dist")
    ui.webui(
        entry="scout.js", api_prefix="/api/ui/",
        pages=[page("case", "Case", element="scout-listings", icon="home", order=10),
               page("case/:id", "Annuncio", element="scout-listing", detail=True)],
        widgets=[widget("nuove", "Nuove case", element="scout-new-widget", sizes=["m", "l"], auto=True,
                        params={"city": {"type": "string", "label": "Città"}})],
        quick_actions=[quick_action("fetch", "Controlla email", "POST", "/api/ui/cycle", icon="refresh")],
    )
    app.include_router(ui.router())                 # GET /api/ui/manifest · GET /ui/<client>/<file>
    payload["capabilities"].update(ui.capabilities(base_url))   # in the Hub registration

Rules
- A plugin talks only to its own module: every quick action path and every ``host.api`` call from the bundle must
  start with ``api_prefix`` (the WebUI proxy enforces it).
- Bundle files are served as text through Hub (js, mjs, css, json, svg, map). Images go through the module's
  own API as ``{mime, data_b64}`` (SDK ``host.image``).
- No secrets or personal data in manifests: they are code (the repo is public).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("hestia_common.plugins")

SDK_VERSION = "1"
CLIENTS = {"webui", "telegram"}
SIZES = ("s", "m", "l", "xl")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
PARAM_TYPES = {"string", "text", "int", "float", "bool", "enum", "date", "time", "list"}
TEXT_FILES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
              ".json": "application/json", ".svg": "image/svg+xml", ".map": "application/json"}

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*(/[a-z0-9_\-:]+)*$")
_ELEMENT_RE = re.compile(r"^[a-z][a-z0-9]*-[a-z0-9\-]+$")


def _params(params: dict | None) -> dict:
    out: dict[str, dict] = {}
    for name, spec in (params or {}).items():
        spec = dict(spec or {})
        spec.setdefault("type", "string")
        if spec["type"] not in PARAM_TYPES:
            raise ValueError(f"param {name}: type {spec['type']!r} not in {sorted(PARAM_TYPES)}")
        spec.setdefault("label", name)
        out[str(name)] = spec
    return out


def page(id: str, label: str, *, element: str, icon: str = "", order: int = 100, parent: str = "",
         detail: bool = False, help: str = "") -> dict:
    """A full page. Non-detail pages are always visible by default (sidebar entry); ``detail`` pages open
    from an item (``case/:id``); ``parent`` makes a sub-page."""
    if not _ID_RE.match(id):
        raise ValueError(f"bad page id {id!r}")
    return {"id": id, "label": label, "element": element, "icon": icon, "order": int(order),
            "parent": parent, "detail": bool(detail or ":" in id), "help": help}


def widget(id: str, label: str, *, element: str, sizes: list[str] | None = None, size: str = "",
           auto: bool = False, params: dict | None = None, open_page: str = "", icon: str = "",
           help: str = "") -> dict:
    """A dashboard block. ``sizes`` allowed (s 1×1 · m 2×1 · l 2×2 · xl 4×2), ``size`` default,
    ``auto`` = proposed on the automatic Home, ``params`` = what the user/Oracle configures per instance."""
    sizes = list(sizes or ["m"])
    if not _ID_RE.match(id) or "/" in id:
        raise ValueError(f"bad widget id {id!r}")
    if any(s not in SIZES for s in sizes):
        raise ValueError(f"widget {id}: sizes must be in {SIZES}")
    size = size or sizes[0]
    if size not in sizes:
        raise ValueError(f"widget {id}: default size {size!r} not in sizes")
    return {"id": id, "label": label, "element": element, "sizes": sizes, "size": size, "auto": bool(auto),
            "params": _params(params), "open_page": open_page, "icon": icon, "help": help}


def quick_action(id: str, label: str, method: str = "POST", path: str = "", *, icon: str = "",
                 group: str = "", source: str = "", confirm: str = "", undo: dict | None = None,
                 params: dict | None = None, favorite: bool = False, order: int = 100) -> dict:
    """A one-tap action drawn by the client itself (Home strip, Ctrl+K palette).

    Static (one chip) or dynamic: ``source`` (GET under api_prefix) returns the chips of the moment
    ``[{id, label, icon?, state?: todo|done|late, hint?, favorite?}]``; ``{id}`` in ``path``/``undo`` is the chip id.
    ``undo`` = ``{method, path}`` offered in the toast. ``params`` open a tiny inline sheet (the client adds ``date``
    for "another day")."""
    method = method.upper()
    if method not in METHODS or not path:
        raise ValueError(f"quick action {id}: method/path required")
    if undo and (str(undo.get("method", "")).upper() not in METHODS or not undo.get("path")):
        raise ValueError(f"quick action {id}: bad undo")
    return {"id": id, "label": label, "method": method, "path": path, "icon": icon, "group": group,
            "source": source, "confirm": confirm or None,
            "undo": {"method": str(undo["method"]).upper(), "path": undo["path"]} if undo else None,
            "params": _params(params), "favorite": bool(favorite), "order": int(order)}


class PluginClient:
    """Builds the module's manifest, serves it and the bundle files, and gives the Hub capabilities."""

    def __init__(self, module: str, *, title: str, icon: str = "", color: str = "", description: str = "",
                 dist: str | os.PathLike | None = None, version: str = ""):
        self.module = module.strip().lower()
        self.title = title
        self.icon = icon
        self.color = color
        self.description = description
        self.dist = Path(dist) if dist else None
        self.version = version or os.getenv("SERVICE_VERSION", "") or "1.0.0"
        self._clients: dict[str, dict] = {}

    # ── declaring ──────────────────────────────────────────────────────────
    def client(self, client: str, *, entry: str = "", api_prefix: str = "/api/ui/", **contributions: list) -> "PluginClient":
        """Contributions for one client (``webui``, ``telegram``…): lists keyed by type
        (``page``/``pages``, ``widget``/``widgets``, ``quick_action``/``quick_actions``)."""
        if client not in CLIENTS:
            raise ValueError(f"unknown client {client!r} (known: {sorted(CLIENTS)})")
        if not api_prefix.startswith("/api/") or not api_prefix.endswith("/"):
            raise ValueError("api_prefix must look like /api/<something>/")
        block: dict[str, Any] = {"entry": f"/ui/{client}/{entry}" if entry else "", "api_prefix": api_prefix,
                                 "sdk": SDK_VERSION}
        for key, items in contributions.items():
            kind = key[:-1] if key.endswith("s") else key
            if kind not in {"page", "widget", "quick_action"}:
                raise ValueError(f"unknown contribution type {key!r}")
            block[kind] = list(items or [])
        self._validate(client, block)
        self._clients[client] = block
        return self

    def webui(self, *, entry: str, api_prefix: str = "/api/ui/", pages: list | None = None,
              widgets: list | None = None, quick_actions: list | None = None) -> "PluginClient":
        return self.client("webui", entry=entry, api_prefix=api_prefix, page=pages or [],
                           widget=widgets or [], quick_action=quick_actions or [])

    def _validate(self, client: str, block: dict) -> None:
        prefix = block["api_prefix"]
        elements_needed = bool(block.get("page") or block.get("widget"))
        if elements_needed and not block["entry"]:
            raise ValueError(f"{self.module}/{client}: pages/widgets need a bundle entry")
        ids: set[str] = set()
        for kind in ("page", "widget", "quick_action"):
            for item in block.get(kind, []):
                key = f"{kind}:{item['id']}"
                if key in ids:
                    raise ValueError(f"{self.module}/{client}: duplicate {key}")
                ids.add(key)
                el = item.get("element")
                if el is not None and (not _ELEMENT_RE.match(el) or not el.startswith(f"{self.module}-")):
                    raise ValueError(f"{self.module}: element {el!r} must be a custom element named '{self.module}-…'")
                for path in (item.get("path"), item.get("source"), (item.get("undo") or {}).get("path")):
                    if path and not path.startswith(prefix):
                        raise ValueError(f"{self.module}: {path!r} outside api_prefix {prefix!r}")
        pages = {p["id"] for p in block.get("page", [])}
        for p in block.get("page", []):
            if p["parent"] and p["parent"] not in pages:
                raise ValueError(f"{self.module}: page {p['id']} has unknown parent {p['parent']!r}")
        for w in block.get("widget", []):
            if w["open_page"] and w["open_page"] not in pages:
                raise ValueError(f"{self.module}: widget {w['id']} opens unknown page {w['open_page']!r}")

    # ── manifest ───────────────────────────────────────────────────────────
    def _bundle_hash(self) -> str:
        if not self.dist or not self.dist.is_dir():
            return ""
        h = hashlib.sha1()
        for f in sorted(self.dist.rglob("*")):
            if f.is_file() and f.suffix in TEXT_FILES:
                st = f.stat()
                h.update(f"{f.relative_to(self.dist)}:{st.st_size}:{int(st.st_mtime)}".encode())
        return h.hexdigest()[:10]

    def manifest(self) -> dict:
        body = {"module": self.module, "title": self.title, "icon": self.icon, "color": self.color,
                "description": self.description, "clients": self._clients}
        digest = hashlib.sha1((json.dumps(body, sort_keys=True) + self._bundle_hash()).encode()).hexdigest()[:10]
        return {**body, "version": f"{self.version}+{digest}"}

    def capabilities(self, base_url: str) -> dict:
        """Keys to merge into ``capabilities`` of the Hub registration (next to ``mcp_endpoint``).
        ``ui_version`` changes with the manifest or the bundle, so Hub refetches at once."""
        return {"ui_manifest": f"{base_url.rstrip('/')}/api/ui/manifest",
                "ui_version": self.manifest()["version"]}

    # ── HTTP ───────────────────────────────────────────────────────────────
    def file(self, client: str, name: str) -> tuple[str, str] | None:
        """(text, content type) of a bundle file, or None. Never leaves ``dist/<client>/``."""
        if not self.dist or client not in self._clients:
            return None
        base = (self.dist / client).resolve()
        target = (base / name).resolve()
        if base not in target.parents or target.suffix not in TEXT_FILES or not target.is_file():
            return None
        return target.read_text(encoding="utf-8"), TEXT_FILES[target.suffix]

    def router(self):
        from fastapi import APIRouter, Header, HTTPException
        from fastapi.responses import Response

        router = APIRouter()

        @router.get("/api/ui/manifest")
        def ui_manifest():
            return self.manifest()

        @router.get("/ui/{client}/{name:path}")
        def ui_file(client: str, name: str, if_none_match: str = Header(default="")):
            found = self.file(client, name)
            if not found:
                logger.info("event=plugin_file_missing module=%s client=%s file=%s", self.module, client, name)
                raise HTTPException(status_code=404, detail="file not found")
            text, ctype = found
            etag = '"' + hashlib.sha1(text.encode()).hexdigest()[:16] + '"'
            if if_none_match == etag:
                return Response(status_code=304)
            return Response(text, media_type=ctype, headers={"ETag": etag, "Cache-Control": "no-cache"})

        return router
