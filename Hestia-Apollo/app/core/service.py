"""Apollo — images through a remote ComfyUI («Immagini», dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A1).

Marko uploads **flows** (ComfyUI workflows in API format) with a purpose (``ritratto``, ``sfondo``, ``mascotte``…);
Apollo fills the prompt/size/seed inputs and queues **jobs** one at a time (a worker woken by new jobs, no timer).
Finished images go to Archive blobs; the requester is told by push (``callback`` = ``{service, path}``, e.g. the
appearance module) and/or by a Hermes notice. A purpose with no flow fails at once with a notice saying where to
upload one: nothing is silently dropped.
"""
from __future__ import annotations

import base64
import copy
import logging
import random
import threading
from typing import Any, Callable

from hestia_common.module_kit import Invalid, NotFound, StoreUnavailable, new_id, now_iso

from .comfy import ComfyError

logger = logging.getLogger("hestia_apollo.service")

PURPOSES = {"generico": "Immagine generica", "ritratto": "Ritratto", "sfondo": "Sfondo", "mascotte": "Mascotte",
            "icona": "Icona", "illustrazione": "Illustrazione"}
INPUTS = ("prompt", "negative", "width", "height", "seed")


def detect_inputs(graph: dict) -> dict:
    """Where prompt/negative/size/seed go when the flow does not say: the usual nodes of a txt2img graph."""
    found: dict[str, str] = {}
    texts = [nid for nid, n in graph.items() if n.get("class_type") in ("CLIPTextEncode", "CLIPTextEncodeSDXL")
             and isinstance((n.get("inputs") or {}).get("text"), str)]
    if texts:
        found["prompt"] = f"{texts[0]}.inputs.text"
    if len(texts) > 1:
        found["negative"] = f"{texts[1]}.inputs.text"
    for nid, n in graph.items():
        ins = n.get("inputs") or {}
        if n.get("class_type", "").startswith("Empty") and "width" in ins and "width" not in found:
            found["width"], found["height"] = f"{nid}.inputs.width", f"{nid}.inputs.height"
        if n.get("class_type", "").startswith("KSampler") and "seed" in ins and "seed" not in found:
            found["seed"] = f"{nid}.inputs.seed"
        elif n.get("class_type", "").startswith("KSampler") and "noise_seed" in ins and "seed" not in found:
            found["seed"] = f"{nid}.inputs.noise_seed"
    return found


def fill(graph: dict, inputs: dict, values: dict) -> dict:
    g = copy.deepcopy(graph)
    for name, where in inputs.items():
        if values.get(name) in (None, ""):
            continue
        node, _, field = where.partition(".inputs.")
        if node not in g:
            raise Invalid(f"il flusso non ha il nodo {node}")
        g[node].setdefault("inputs", {})[field] = values[name]
    return g


class Images:
    def __init__(self, store, comfy, hub, get: Callable[[str, Any], Any] = lambda k, d=None: d):
        self.store = store
        self.comfy = comfy
        self.hub = hub
        self.get = get
        self._wake = threading.Event()
        self._busy = threading.Lock()

    # ── flows ───────────────────────────────────────────────────────────────
    def flows(self) -> list[dict]:
        self.store.refresh()
        return sorted(({k: v for k, v in f.items() if k != "graph"} for f in self.store.items("workflow")),
                      key=lambda f: (f["purpose"], f["name"]))

    def save_flow(self, body: dict, fid: str | None = None) -> dict:
        graph = body.get("graph")
        if isinstance(graph, dict) and "prompt" in graph and isinstance(graph["prompt"], dict):
            graph = graph["prompt"]
        if not isinstance(graph, dict) or not graph or not all(isinstance(n, dict) and n.get("class_type")
                                                               for n in graph.values()):
            raise Invalid("serve il flusso in formato API di ComfyUI (Salva → API Format)")
        purpose = body.get("purpose") or "generico"
        if purpose not in PURPOSES:
            raise Invalid("scopo: " + ", ".join(PURPOSES))
        inputs = {**detect_inputs(graph), **{k: v for k, v in (body.get("inputs") or {}).items() if k in INPUTS}}
        if "prompt" not in inputs:
            raise Invalid("non trovo dove va il testo: indica inputs.prompt (es. «6.inputs.text»)")
        fill(graph, inputs, {k: 1 for k in inputs})                     # every target node exists
        data = {"name": str(body.get("name") or PURPOSES[purpose])[:60], "purpose": purpose,
                "description": str(body.get("description") or "")[:300], "inputs": inputs, "graph": graph,
                "default": bool(body.get("default", True)), "updated_at": now_iso()}
        fid = fid or new_id("wf")
        if data["default"]:
            for other in self.store.items("workflow"):
                if other["purpose"] == purpose and other["id"] != fid and other.get("default"):
                    self.store.upsert("workflow", other["id"], {**{k: v for k, v in other.items() if k != "id"},
                                                                "default": False})
        self.store.upsert("workflow", fid, data, ref_id=purpose)
        logger.info("event=apollo_flow_saved purpose=%s nodes=%d", purpose, len(graph))
        return {k: v for k, v in data.items() if k != "graph"} | {"id": fid}

    def delete_flow(self, fid: str) -> dict:
        if not self.store.delete("workflow", fid):
            raise NotFound("flusso non trovato")
        return {"deleted": True}

    def flow_for(self, purpose: str) -> dict | None:
        flows = [f for f in self.store.items("workflow") if f["purpose"] == purpose] or \
                [f for f in self.store.items("workflow") if f["purpose"] == "generico"]
        return next((f for f in flows if f.get("default")), flows[0] if flows else None)

    # ── jobs ────────────────────────────────────────────────────────────────
    def request(self, prompt: str, *, purpose: str = "generico", negative: str = "", width: int | None = None,
                height: int | None = None, seed: int | None = None, callback: dict | None = None,
                ref: str = "", by: str = "user", notify: bool = False) -> dict:
        prompt = str(prompt or "").strip()[:2000]
        if not prompt:
            raise Invalid("descrivi l'immagine")
        purpose = purpose if purpose in PURPOSES else "generico"
        for v in (width, height):
            if v is not None and not 64 <= int(v) <= 2048:
                raise Invalid("larghezza e altezza tra 64 e 2048")
        jid = new_id("job")
        job = {"prompt": prompt, "negative": str(negative or "")[:1000], "purpose": purpose, "width": width,
               "height": height, "seed": seed, "status": "queued", "blob_ids": [], "error": "", "by": by,
               "ref": str(ref or "")[:120], "notify": bool(notify), "created_at": now_iso(),
               "callback": callback if isinstance(callback, dict) and callback.get("service") and callback.get("path")
               else None}
        self.store.upsert("job", jid, job)
        if not self.comfy.configured or not self.flow_for(purpose):
            return self._finish(jid, job, error="missing_flow" if self.comfy.configured else "not_configured")
        self._wake.set()
        return {**job, "id": jid}

    def job(self, jid: str) -> dict:
        self.store.refresh()
        j = self.store.data("job", jid)
        if not j:
            raise NotFound("lavoro non trovato")
        return j

    def jobs(self, limit: int = 30) -> list[dict]:
        self.store.refresh()
        return sorted(self.store.items("job"), key=lambda j: j.get("created_at") or "", reverse=True)[:limit]

    def wait(self, jid: str, seconds: float) -> dict:
        end = threading.Event()
        for _ in range(int(seconds * 2)):
            j = self.job(jid)
            if j["status"] in ("done", "failed"):
                return j
            end.wait(0.5)
        return self.job(jid)

    def work_forever(self, stop: threading.Event | None = None) -> None:
        """The worker: runs queued jobs one by one, sleeps until a new job wakes it (and checks once an hour)."""
        stop = stop or threading.Event()
        while not stop.is_set():
            self._wake.wait(3600)
            self._wake.clear()
            try:
                while self.run_next():
                    pass
            except Exception as exc:
                logger.warning("[🔄] event=apollo_worker_error error=%s fallback=next_wake", exc)

    def run_next(self) -> bool:
        with self._busy:
            self.store.refresh()
            queued = sorted((j for j in self.store.items("job") if j["status"] in ("queued", "running")),
                            key=lambda j: j["created_at"])
            if not queued:
                return False
            j = queued[0]
            jid = j.pop("id")
            flow = self.flow_for(j["purpose"])
            if not flow:
                self._finish(jid, j, error="missing_flow")
                return True
            self.store.upsert("job", jid, {**j, "status": "running", "workflow_id": flow["id"]})
            values = {"prompt": j["prompt"], "negative": j["negative"], "width": j["width"], "height": j["height"],
                      "seed": j["seed"] if j["seed"] is not None else random.randint(1, 2 ** 31)}
            try:
                images = self.comfy.run(fill(flow["graph"], flow["inputs"], values))
                blob_ids = [self._blob(data, mime, jid, n) for n, (data, mime) in enumerate(images)]
                self._finish(jid, {**j, "workflow_id": flow["id"]}, blob_ids=blob_ids)
            except StoreUnavailable:
                raise
            except (ComfyError, Invalid) as exc:
                self._finish(jid, {**j, "workflow_id": flow["id"]}, error=str(exc))
            except Exception as exc:
                logger.warning("[🔄] event=apollo_job_failed error=%s", exc)
                self._finish(jid, {**j, "workflow_id": flow["id"]}, error=f"errore inatteso: {exc}")
            return True

    def _blob(self, data: bytes, mime: str, jid: str, n: int) -> str:
        meta = self.hub.ok("archive", "POST", "api/blobs", body={
            "owner_module": "apollo", "content_type": mime or "image/png", "data_base64": base64.b64encode(data).decode(),
            "meta": {"name": f"{jid}-{n + 1}.png", "kind": "image", "job": jid}}, timeout=30) or {}
        if not meta.get("blob_id"):
            raise ComfyError("non riesco a salvare l'immagine")
        return meta["blob_id"]

    def _finish(self, jid: str, job: dict, *, blob_ids: list[str] | None = None, error: str = "") -> dict:
        job = {**{k: v for k, v in job.items() if k != "id"}, "status": "failed" if error else "done",
               "blob_ids": blob_ids or [], "error": error, "finished_at": now_iso()}
        self.store.upsert("job", jid, job)
        logger.info("event=apollo_job_%s purpose=%s images=%d", job["status"], job["purpose"], len(job["blob_ids"]))
        cb = job.get("callback")
        if cb:
            try:
                self.hub.ok(cb["service"], "POST", cb["path"], body={
                    "job_id": jid, "status": job["status"], "blob_ids": job["blob_ids"], "purpose": job["purpose"],
                    "ref": job.get("ref"), "error": error}, timeout=15)
            except Exception as exc:
                logger.warning("[🔄] event=apollo_callback_failed service=%s error=%s fallback=job_record",
                               cb.get("service"), exc)
        if error in ("missing_flow", "not_configured"):
            self._missing_notice(job["purpose"], error)
        elif job.get("notify"):
            self.hub.notify({"event_type": "service.action_required", "domain": "images", "entity_id": f"apollo-{jid}",
                             "payload": {"kind": "apollo.job", "service": "apollo", "_source": "Immagini",
                                         "_title": "Immagine pronta" if not error else "Immagine non riuscita",
                                         "_message": job["prompt"][:120] if not error else error,
                                         "level": "info" if not error else "warning", "target": "owner",
                                         "icon": "camera", "_link": {"module": "apollo", "page": f"lavoro/{jid}"}}})
        return {**job, "id": jid}

    def _missing_notice(self, purpose: str, error: str) -> None:
        msg = ("Per creare immagini serve il collegamento al generatore (indirizzo nel file .env)."
               if error == "not_configured" else
               f"Non ho un flusso per «{PURPOSES.get(purpose, purpose)}»: caricalo in Immagini → Flussi "
               "(da ComfyUI: Salva → API Format).")
        self.hub.notify({"event_type": "service.action_required", "domain": "images",
                         "entity_id": f"apollo-missing-{purpose}",
                         "payload": {"kind": "apollo.missing_flow", "service": "apollo", "_source": "Immagini",
                                     "_title": "Manca un flusso per le immagini", "_message": msg, "level": "warning",
                                     "target": "owner", "icon": "camera", "replaces": f"apollo.missing.{purpose}",
                                     "_link": {"module": "apollo", "page": "flussi"}}})
