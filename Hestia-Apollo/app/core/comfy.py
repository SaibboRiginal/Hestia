"""ComfyUI client: queue a workflow, wait for it on the websocket (push), fetch the images.

Only Apollo talks to image generators. ``APOLLO_COMFYUI_URL`` (the remote ComfyUI, e.g. on Marko's PC or a rented
GPU) and ``APOLLO_COMFYUI_KEY`` (optional bearer token of a proxy in front of it) are infrastructure/secret: env.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import requests
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_apollo.comfy")


class ComfyError(RuntimeError):
    pass


class ComfyUI:
    def __init__(self, url: str, key: str = "", *, session: Any = None):
        self.url = (url or "").rstrip("/")
        self.key = key or ""
        self.http = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    def _get(self, path: str, **params) -> requests.Response:
        try:
            resp = self.http.get(f"{self.url}{path}", params=params, headers=self._headers(), timeout=30)
        except requests.RequestException as exc:
            raise ComfyError(tr("the image generator does not answer: {0}", exc)) from exc
        if resp.status_code >= 400:
            raise ComfyError(tr("the generator answered {0}", resp.status_code))
        return resp

    def ping(self) -> bool:
        try:
            self._get("/system_stats")
            return True
        except ComfyError:
            return False

    def queue(self, graph: dict, client_id: str) -> str:
        try:
            resp = self.http.post(f"{self.url}/prompt", json={"prompt": graph, "client_id": client_id},
                                  headers=self._headers(), timeout=30)
        except requests.RequestException as exc:
            raise ComfyError(tr("the image generator does not answer: {0}", exc)) from exc
        if resp.status_code >= 400:
            raise ComfyError(tr("the workflow was rejected ({0}): {1}", resp.status_code, resp.text[:200]))
        pid = (resp.json() or {}).get("prompt_id")
        if not pid:
            raise ComfyError(tr("the generator did not accept the job"))
        return pid

    def ws_url(self, client_id: str) -> str:
        base = "wss://" + self.url[8:] if self.url.startswith("https://") else "ws://" + self.url.removeprefix("http://")
        return f"{base}/ws?clientId={client_id}" + (f"&token={self.key}" if self.key else "")

    def run(self, graph: dict, timeout: float = 600) -> list[tuple[bytes, str]]:
        """Queue and wait (websocket ``executing`` with node null = done); then the images as (bytes, mime)."""
        from websockets.sync.client import connect
        client_id = uuid.uuid4().hex
        deadline = time.monotonic() + timeout
        with connect(self.ws_url(client_id), open_timeout=15, max_size=None,
                     additional_headers=self._headers()) as ws:
            pid = self.queue(graph, client_id)
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise ComfyError(tr("the generator is taking too long"))
                try:
                    raw = ws.recv(timeout=left)
                except TimeoutError:
                    raise ComfyError(tr("the generator is taking too long")) from None
                if not isinstance(raw, str):
                    continue                                          # binary previews
                msg = json.loads(raw)
                data = msg.get("data") or {}
                if data.get("prompt_id") not in (None, pid):
                    continue
                if msg.get("type") == "execution_error":
                    raise ComfyError(tr("workflow error: {0}", str(data.get('exception_message') or '')[:200]))
                if msg.get("type") == "executing" and data.get("node") is None and data.get("prompt_id") == pid:
                    break
        return self.images(pid)

    def images(self, prompt_id: str) -> list[tuple[bytes, str]]:
        hist = (self._get(f"/history/{prompt_id}").json() or {}).get(prompt_id) or {}
        out = []
        for node in (hist.get("outputs") or {}).values():
            for img in node.get("images") or []:
                if img.get("type") == "temp":
                    continue
                resp = self._get("/view", filename=img["filename"], subfolder=img.get("subfolder", ""),
                                 type=img.get("type", "output"))
                out.append((resp.content, resp.headers.get("content-type", "image/png").split(";")[0]))
        if not out:
            raise ComfyError(tr("the workflow produced no images"))
        return out
