"""Hub "inside view" — WebUI plugin (core module, Sistema section) and the read model behind it.

SPEC ``docs/work/2026-10-18-moduli-core-e-mcp-esterno`` §A2 (Hub: *Mappa*, widget *Servizi online*).
Hub is the catalog builder itself and never registers with itself, so:
- its manifest is folded into the catalog in-process (``discover_catalog(..., local_manifests=...)``);
- calls routed to ``hub`` (``/api/route/hub/...``: bundle files, ``/api/ui/*`` reads) are answered in-process
  by :func:`local_route` instead of going through the registry.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from hestia_common.plugin_client import PluginClient, page, widget

logger = logging.getLogger("hestia_hub.inside")

SERVICE_VERSION = "1.0.0"
UI_DIST = os.getenv("HUB_UI_DIST", "/ui/dist")   # outside /code/src: the compose dev mount must not hide it
API = "/api/ui"
ONLINE_WINDOW = 180.0       # modules re-register every 60 s (same window as the catalog)
SELF_TOPOLOGY = ["layer:foundation", "domain:registry", "status:stable"]

ui = PluginClient("hub", title="Hub", icon="host", color="blue", kind="core", dist=UI_DIST,
                  description="La mappa di Hestia: ogni servizio registrato, dove gira e se risponde.",
                  version=SERVICE_VERSION)
ui.webui(
    entry="hub.js", api_prefix=f"{API}/",
    pages=[page("mappa", "Mappa", element="hub-map", icon="host", order=100,
                help="Ogni servizio di Hestia: online o no, nodo, versione, ultimo segnale, tag di topologia.")],
    widgets=[widget("online", "Servizi online", element="hub-online-widget", sizes=["s", "m"], auto=True,
                    open_page="mappa", icon="host",
                    help="Quanti servizi hanno dato segno di vita negli ultimi 3 minuti.")],
)


def _node(svc: dict) -> str:
    """Where the service runs: ``capabilities.node`` when declared, else the host of its base URL."""
    caps = svc.get("capabilities") or {}
    node = caps.get("node") if isinstance(caps, dict) else None
    if isinstance(node, str) and node.strip():
        return node.strip()
    return urlparse(str(svc.get("base_url") or "")).hostname or ""


def _topology(tags: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in tags or []:
        if isinstance(tag, str) and ":" in tag:
            dim, value = tag.split(":", 1)
            out.setdefault(dim, value)
    return out


def _probe(svc: dict, timeout: float) -> tuple[str, int | None]:
    url = f"{str(svc.get('base_url') or '').rstrip('/')}{svc.get('health_endpoint') or '/health'}"
    try:
        resp = requests.get(url, timeout=timeout)
        return ("healthy" if resp.status_code < 400 else "degraded"), resp.status_code
    except requests.RequestException:
        return "unavailable", None


def service_map(services: list[dict], *, revision: int, updated_at: float, probe: bool = False,
                health_timeout: float = 3.0, now: float | None = None) -> dict:
    """One row per service name (newest instance; ``instances`` counts them) + Hub itself.

    ``online`` = re-registered within :data:`ONLINE_WINDOW` (cheap, no network). ``probe=True`` also calls
    each service's health endpoint in parallel (``health`` = healthy | degraded | unavailable)."""
    now = time.time() if now is None else now
    grouped: dict[str, list[dict]] = {}
    for svc in services:
        name = str(svc.get("name") or "").strip().lower()
        if name:
            grouped.setdefault(name, []).append(svc)

    rows: list[dict] = []
    newest: list[dict] = []
    for name, items in sorted(grouped.items()):
        svc = max(items, key=lambda it: float(it.get("updated_at") or 0))
        newest.append(svc)
        beat = float(svc.get("updated_at") or 0)
        tags = list(svc.get("topology_tags") or [])
        caps = svc.get("capabilities") or {}
        rows.append({
            "name": name, "node": _node(svc), "service_type": svc.get("service_type", ""),
            "version": svc.get("service_version", ""), "tags": list(svc.get("tags") or []),
            "topology_tags": tags, "topology": _topology(tags),
            "last_heartbeat": beat or None, "age_seconds": round(now - beat, 1) if beat else None,
            "online": bool(beat) and now - beat < ONLINE_WINDOW, "instances": len(items),
            "has_ui": bool(isinstance(caps, dict) and caps.get("ui_manifest")),
            "has_mcp": bool(isinstance(caps, dict) and caps.get("mcp_endpoint")),
        })

    if probe and newest:
        with ThreadPoolExecutor(max_workers=min(16, len(newest))) as pool:
            results = list(pool.map(lambda s: _probe(s, health_timeout), newest))
        for row, (health, code) in zip(rows, results):
            row["health"], row["health_status_code"] = health, code

    if "hub" not in grouped:
        rows.insert(0, {
            "name": "hub", "node": "", "service_type": "core", "version": SERVICE_VERSION, "tags": ["core"],
            "topology_tags": SELF_TOPOLOGY, "topology": _topology(SELF_TOPOLOGY), "last_heartbeat": now,
            "age_seconds": 0.0, "online": True, "instances": 1, "has_ui": True, "has_mcp": False, "self": True,
            **({"health": "healthy", "health_status_code": 200} if probe else {}),
        })

    online = sum(1 for r in rows if r["online"])
    return {"revision": revision, "updated_at": updated_at or None, "generated_at": now,
            "online_window_seconds": ONLINE_WINDOW, "probed": bool(probe),
            "services_count": len(rows), "online_count": online, "offline_count": len(rows) - online,
            "services": rows}


def local_manifests() -> dict[str, dict]:
    """Hub's own manifest for the catalog (Hub never registers with itself)."""
    return {"hub": ui.manifest()}


def local_route(path: str, method: str, query: dict[str, Any],
                map_fn: Callable[[bool], dict]) -> tuple[int, Any]:
    """Answer ``/api/route/hub/<path>`` in-process: (status_code, payload) like a proxied module."""
    path = "/" + path.lstrip("/")
    method = (method or "GET").upper()
    if method != "GET":
        return 405, {"detail": "method not allowed"}
    if path == f"{API}/manifest":
        return 200, ui.manifest()
    if path == f"{API}/map":
        probe = str((query or {}).get("probe", "")).lower() in {"1", "true", "yes"}
        return 200, map_fn(probe)
    if path.startswith("/ui/"):
        client, _, name = path[len("/ui/"):].partition("/")
        found = ui.file(client, name) if name else None
        if not found:
            logger.info("event=hub_local_file_missing client=%s file=%s", client, name)
            return 404, {"detail": "file not found"}
        text, ctype = found
        # Same shape as proxy_request: JSON parsed, everything else wrapped as {"raw": text}.
        return 200, (json.loads(text) if ctype == "application/json" else {"raw": text})
    return 404, {"detail": f"Hub does not serve {path}"}
