"""ComfyUI client: queue a workflow, wait for it on the websocket (push), fetch the images.

Only Apollo talks to image generators. The remote ComfyUI (e.g. on Marko's PC or a rented GPU) is linked from the
«ComfyUI» card (Connections): its address is the Themis setting ``apollo.comfyui.address``, the optional bearer token of
a proxy in front of it is ``APOLLO_KEY_COMFYUI`` in Apollo's .env (``hestia_common.connections``).
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

    def configure(self, url: str, key: str = "") -> None:
        """The card saved a new address or key: used by the next job."""
        self.url = (url or "").rstrip("/")
        self.key = key or ""
        logger.info("event=comfy_configured configured=%s key=%s", self.configured, bool(self.key))

    def probe(self, url: str | None = None, key: str | None = None) -> dict:
        """The «Test» button: reachable? version, GPU and free memory, the checkpoints it has → ``{ok, detail, facts}``."""
        other = ComfyUI(self.url if url is None else url, self.key if key is None else key, session=self.http)
        if not other.configured:
            return {"ok": False, "detail": tr("Type the ComfyUI address first."), "facts": []}
        try:
            stats = other._get("/system_stats", timeout=8).json() or {}
        except ComfyError as exc:
            return {"ok": False, "detail": tr("ComfyUI does not answer: {0}", str(exc)[:160]), "facts": [
                tr("Start ComfyUI so it accepts the network: python main.py --listen 0.0.0.0 --port 8188"),
                tr("On the same computer as Hestia use http://host.docker.internal:8188, otherwise the computer's address.")]}
        except ValueError:
            return {"ok": False, "detail": tr("Something answers at that address, but it is not ComfyUI."), "facts": []}
        facts = []
        version = (stats.get("system") or {}).get("comfyui_version")
        if version:
            facts.append(tr("ComfyUI {0}", version))
        gpus = [d for d in stats.get("devices") or [] if str(d.get("type") or "").lower() not in ("cpu", "")]
        for d in gpus[:2]:
            total, free = d.get("vram_total") or 0, d.get("vram_free") or 0
            name = str(d.get("name") or "GPU").split(":", 1)[-1].strip()[:60]
            facts.append(tr("Video card {0}: {1} GB free of {2} GB", name, round(free / 2**30, 1), round(total / 2**30, 1)))
        if not gpus:
            facts.append(tr("No video card found: images will be very slow."))
        models = other.checkpoints()
        facts.append(tr("Models: {0}", ", ".join(models[:8]) + (" …" if len(models) > 8 else "")) if models
                     else tr("No model found in ComfyUI's checkpoints folder."))
        return {"ok": True, "detail": tr("ComfyUI answers."), "facts": facts}

    def checkpoints(self) -> list[str]:
        """The model files ComfyUI has (``/models/checkpoints``; older versions: the loader's choices)."""
        try:
            data = self._get("/models/checkpoints", timeout=8).json()
            if isinstance(data, list):
                return [str(m) for m in data]
        except (ComfyError, ValueError):
            pass
        try:
            info = self._get("/object_info/CheckpointLoaderSimple", timeout=8).json() or {}
            choice = (((info.get("CheckpointLoaderSimple") or {}).get("input") or {}).get("required") or {}).get("ckpt_name")
            return [str(m) for m in (choice[0] if isinstance(choice, list) and choice and isinstance(choice[0], list) else [])]
        except (ComfyError, ValueError, AttributeError):
            return []

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    def _get(self, path: str, timeout: float = 30, **params) -> requests.Response:
        try:
            resp = self.http.get(f"{self.url}{path}", params=params, headers=self._headers(), timeout=timeout)
        except requests.RequestException as exc:
            raise ComfyError(tr("the image generator does not answer: {0}", exc)) from exc
        if resp.status_code >= 400:
            raise ComfyError(tr("the generator answered {0}", resp.status_code))
        return resp

    def ping(self) -> bool:
        try:
            self._get("/system_stats", timeout=5)
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
