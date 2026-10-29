"""Hestia-Apollo — images through a remote ComfyUI («Immagini», port 19022, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A1).

The only module that talks to image generators (``APOLLO_COMFYUI_URL`` / ``APOLLO_COMFYUI_KEY`` in env). Flows and
jobs in Archive (``/api/images-store``), images in Archive blobs, results pushed to the requester (``callback``) or
told through Hermes; tools for the assistant and Telegram over MCP.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from fastapi import Body

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common.display import display, file, item
from hestia_common.mcp_helpers import MCPTool
from hestia_common.module_kit import ModuleKit, NotFound
from hestia_common.plugin_client import page
from hestia_common.transfer import StoreSection, Transfer

from .core.comfy import ComfyUI
from .core.service import PURPOSES, Images

API = "/api/images"
kit = ModuleKit("apollo", port=19022, api=API, domain="images", title="Immagini", store="images-store",
                when_to_use="creare immagini (ritratti, sfondi, mascotte, icone, illustrazioni)",
                manual="immagine_crea: descrivi l'immagine in inglese nel prompt, scegli purpose; se è pronta entro "
                       "poco la ricevi subito, altrimenti arriva un avviso (immagine_stato per vederla). I flussi "
                       "(immagine_flussi) li carica l'utente da ComfyUI.")
app = kit.app
comfy = ComfyUI(os.getenv("APOLLO_COMFYUI_URL", ""), os.getenv("APOLLO_COMFYUI_KEY", ""))
images = Images(kit.store, comfy, kit.hub)
kit.health_extra = lambda: {"configured": comfy.configured}


@app.get(f"{API}/status")
def status():
    return {"configured": comfy.configured, "reachable": comfy.ping() if comfy.configured else False,
            "flows": len(images.flows()), "purposes": PURPOSES}


@app.get(f"{API}/flows")
def flows():
    return {"items": images.flows(), "purposes": PURPOSES}


@app.post(f"{API}/flows")
def add_flow(body: dict = Body(...)):
    return images.save_flow(body)


@app.put(f"{API}/flows/{{fid}}")
def update_flow(fid: str, body: dict = Body(...)):
    return images.save_flow(body, fid)


@app.delete(f"{API}/flows/{{fid}}")
def delete_flow(fid: str):
    return images.delete_flow(fid)


@app.post(f"{API}/jobs")
def request_job(body: dict = Body(...)):
    """Other modules (e.g. the appearance one) ask an image here, with ``callback: {service, path}``."""
    return images.request(body.get("prompt", ""), purpose=body.get("purpose", "generico"),
                          negative=body.get("negative", ""), width=body.get("width"), height=body.get("height"),
                          seed=body.get("seed"), callback=body.get("callback"), ref=body.get("ref", ""),
                          by=str(body.get("by") or "module"), notify=bool(body.get("notify")))


@app.get(f"{API}/jobs")
def jobs(limit: int = 30):
    return {"items": images.jobs(limit)}


@app.get(f"{API}/jobs/{{jid}}")
def job(jid: str):
    return images.job(jid)


@app.get(f"{API}/jobs/{{jid}}/image/{{n}}")
def job_image(jid: str, n: int):
    """One image of a finished job as ``{mime, data_b64}`` (WebUI ``host.image``)."""
    j = images.job(jid)
    blobs = j.get("blob_ids") or []
    if not 0 <= n < len(blobs):
        raise NotFound("immagine non trovata")
    blob = kit.hub.ok("archive", "GET", f"api/blobs/{blobs[n]}/base64", timeout=30) or {}
    return {"mime": blob.get("mime") or "image/png", "data_b64": blob.get("data_b64") or ""}


def _job_display(j: dict) -> dict:
    files = [file(b, f"immagine-{n + 1}.png", "image/png") for n, b in enumerate(j.get("blob_ids") or [])]
    if j["status"] == "done":
        return display("Immagine pronta", subtitle=PURPOSES.get(j["purpose"], ""), lines=[j["prompt"][:200]],
                       files=files)
    if j["status"] == "failed":
        why = {"missing_flow": "manca un flusso per questo tipo di immagine: caricalo in Immagini → Flussi.",
               "not_configured": "il generatore di immagini non è ancora collegato."}.get(j["error"], j["error"])
        return display("Immagine non riuscita", lines=[why], tone="warning")
    return display("Immagine in preparazione", lines=["Ti avviso quando è pronta."])


def _create(prompt: str, purpose: str = "generico", negative: str = "", width: int | None = None,
            height: int | None = None) -> dict:
    j = images.request(prompt, purpose=purpose, negative=negative, width=width, height=height, by="user", notify=True)
    if j["status"] in ("queued", "running"):
        j = images.wait(j["id"], 60)
    return {"id": j["id"], "status": j["status"], "error": j.get("error") or None, "display": _job_display(j)}


S, I = {"type": "string"}, {"type": "integer"}
G = "aspetto"
kit.tools([
    MCPTool(name="immagine_crea", description="Crea un'immagine: prompt (meglio in inglese), purpose " +
            "|".join(PURPOSES) + ", negative, width, height.",
            parameters={"type": "object", "properties": {"prompt": S, "purpose": {"type": "string", "enum": list(
                PURPOSES)}, "negative": S, "width": I, "height": I}, "required": ["prompt"]},
            handler=_create, title="Crea immagine", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Immagini", "primary": 1}),
    MCPTool(name="immagine_stato", description="Stato di un'immagine richiesta (e l'immagine se pronta).",
            parameters={"type": "object", "properties": {"job": S}, "required": ["job"]},
            handler=lambda job: (lambda j: {"id": j["id"], "status": j["status"], "display": _job_display(j)})(
                images.job(job)),
            title="Stato immagine", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Immagini"}),
    MCPTool(name="immagine_lista", description="Le ultime immagini richieste.",
            parameters={"type": "object", "properties": {}},
            handler=lambda: (lambda rows: {"items": [{"id": j["id"], "status": j["status"], "purpose": j["purpose"],
                                                      "prompt": j["prompt"][:80]} for j in rows],
                                           "display": display("Immagini", items=[
                                               item(j["prompt"][:60], [PURPOSES.get(j["purpose"], ""), j["status"]])
                                               for j in rows[:20]], lines=[] if rows else ["Nessuna immagine."])})(
                images.jobs(20)),
            title="Immagini recenti", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Immagini", "primary": 2}),
    MCPTool(name="immagine_flussi", description="I flussi caricati (uno per scopo) e se il generatore è collegato.",
            parameters={"type": "object", "properties": {}},
            handler=lambda: (lambda fl: {"configured": comfy.configured, "items": fl, "display": display(
                "Flussi immagini", items=[item(f["name"], [PURPOSES.get(f["purpose"], f["purpose"])]) for f in fl],
                lines=([] if comfy.configured else ["Generatore non collegato."]) +
                      ([] if fl else ["Nessun flusso: caricalo dalla pagina Immagini."]))})(images.flows()),
            title="Flussi immagini", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Immagini"}),
], prefix="immagine_")

transfer = Transfer("apollo", kit.hub, sections=[
    StoreSection("flussi", "Flussi immagini", kit.store, ["workflow"], icon="camera",
                 title=lambda r: r["data"].get("name", "")),
    StoreSection("immagini", "Immagini create", kit.store, ["job"], icon="camera",
                 title=lambda r: r["data"].get("prompt", "")[:60], file_fields=["blob_ids"]),
])
app.include_router(transfer.router())
kit.capabilities(transfer.capabilities)


def _start_worker() -> None:
    threading.Thread(target=images.work_forever, daemon=True, name="apollo-worker").start()
    images._wake.set()                                   # jobs left from before a restart


kit.on_warm(_start_worker)
kit.webui(icon="camera", color="purple", description="Immagini create con il tuo ComfyUI: ritratti, sfondi, mascotte.",
          pages=[page("immagini", "Immagini", element="apollo-images", icon="camera", order=210,
                      help="Crea un'immagine e guarda quelle fatte. Servono il tuo ComfyUI e un flusso per tipo."),
                 page("lavoro/:id", "Immagine", element="apollo-job", detail=True, parent="immagini"),
                 page("flussi", "Flussi", element="apollo-flows", icon="upload", order=211, parent="immagini",
                      help="Carica da ComfyUI il flusso salvato in formato API (Salva → API Format), uno per tipo "
                           "di immagine.")])
kit.finish()
