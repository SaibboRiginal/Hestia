"""Satellite mode — this Hub is a relay to the central one (docs/work/2026-10-30-setup-un-click §4.0).

On a satellite the modules keep their usual ``HUB_API_URL`` (``http://hestia_hub:19001/api``) and know nothing
about machines. This Hub, started with ``HUB_UPSTREAM_URL`` (the central's Hub API), ``HUB_NODE_TOKEN`` (from
pairing) and ``HUB_NODE_ADDRESS`` (this machine's LAN address):

- forwards each registration to the central with the token, rewriting the module's address
  (``http://hestia_echo:19021`` → ``http://<HUB_NODE_ADDRESS>:19021``: compose publishes the same port), so the
  central routes to it over the LAN;
- forwards everything else (routes, streams, discovery, long polls) to the central as it is: the central decides,
  including the way back to this machine's own modules.

The central down → the satellite's calls fail as they would with Hub down (the existing «Non disponibile» path).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

logger = logging.getLogger(f"hestia_hub.{__name__}")

NODE_HEADER = "X-Hestia-Node-Token"
HOP_HEADERS = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "te", "upgrade",
               "proxy-authorization", "proxy-authenticate", "trailer"}


def config() -> dict[str, str] | None:
    upstream = os.getenv("HUB_UPSTREAM_URL", "").strip().rstrip("/")
    if not upstream:
        return None
    return {"upstream": upstream, "token": os.getenv("HUB_NODE_TOKEN", "").strip(),
            "address": os.getenv("HUB_NODE_ADDRESS", "").strip()}


def rewrite(base_url: str, address: str) -> str:
    """The module's container address → the same port at this machine's LAN address."""
    parts = urlsplit(base_url)
    if not address or not parts.hostname:
        return base_url
    netloc = f"{address}:{parts.port}" if parts.port else address
    return urlunsplit((parts.scheme or "http", netloc, parts.path, parts.query, parts.fragment))


class RelayMiddleware:
    """ASGI middleware: in satellite mode every ``/api/*`` request goes to the central Hub."""

    def __init__(self, app, cfg: dict[str, str]):
        self.app = app
        self.cfg = cfg
        self.session = requests.Session()

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or path.startswith("/api/logs"):
            return await self.app(scope, receive, send)
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
        status, headers, chunks = await run_in_threadpool(self._forward, scope, body)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        async for chunk in iterate_in_threadpool(iter(chunks)):   # streams (chat NDJSON) flow as they come
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    def _forward(self, scope, body: bytes) -> tuple[int, list[tuple[bytes, bytes]], Any]:
        path = scope["path"][len("/api"):]
        query = scope.get("query_string", b"").decode()
        url = f"{self.cfg['upstream']}{path}" + (f"?{query}" if query else "")
        headers = {k.decode(): v.decode() for k, v in scope.get("headers", []) if k.decode().lower() not in HOP_HEADERS}
        if path in ("/registry/register", "/registry/deregister"):
            body = self._registration(body)
            headers[NODE_HEADER] = self.cfg["token"]
        try:
            resp = self.session.request(scope["method"], url, data=body or None, headers=headers, stream=True,
                                        timeout=(5, 900))
        except requests.RequestException as exc:
            logger.warning("[🔄] event=hub_relay_upstream_unreachable path=%s error=%s", path, str(exc)[:200])
            payload = json.dumps({"detail": "central Hub unreachable"}).encode()
            return 502, [(b"content-type", b"application/json")], [payload]
        if path == "/registry/register" and resp.status_code >= 400:
            logger.warning("event=hub_relay_register_refused status=%s", resp.status_code)
        out_headers = [(k.lower().encode(), v.encode()) for k, v in resp.headers.items()
                       if k.lower() not in HOP_HEADERS and k.lower() != "content-encoding"]

        def chunks():
            try:
                yield from (c for c in resp.iter_content(8192) if c)
            finally:
                resp.close()
        return resp.status_code, out_headers, chunks()

    def _registration(self, body: bytes) -> bytes:
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return body
        if isinstance(data, dict) and data.get("base_url"):
            old = str(data["base_url"]).rstrip("/")
            new = rewrite(old, self.cfg["address"])
            data = _replace_prefix(data, old, new)      # base_url and absolute URLs in capabilities (mcp, ui)
        return json.dumps(data).encode()


def _replace_prefix(value, old: str, new: str):
    if isinstance(value, str):
        return new + value[len(old):] if value.startswith(old) else value
    if isinstance(value, dict):
        return {k: _replace_prefix(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_prefix(v, old, new) for v in value]
    return value
