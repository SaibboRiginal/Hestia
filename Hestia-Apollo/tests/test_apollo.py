"""Apollo (Immagini): flows, input detection, job queue, blobs, callback push, missing flow notice, endpoints.
No network: a fake ComfyUI. Markers: unit, api"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Invalid, Store

from app.core.comfy import ComfyError, ComfyUI
from app.core.service import Images, detect_inputs, fill

pytestmark = pytest.mark.unit

GRAPH = {"3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20}},
         "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
         "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive"}},
         "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
         "9": {"class_type": "SaveImage", "inputs": {}}}


class FakeComfy(ComfyUI):
    def __init__(self, fail=False):
        super().__init__("http://gpu.local:8188")
        self.graphs, self.fail = [], fail

    def run(self, graph, timeout=600):
        self.graphs.append(graph)
        if self.fail:
            raise ComfyError("errore nel flusso: OOM")
        return [(b"\x89PNG fake", "image/png")]


@pytest.fixture
def ai():
    hub, comfy = FakeArchive(), FakeComfy()
    return Images(Store(hub, "images-store", min_refresh_seconds=0), comfy, hub), hub, comfy


def test_detect_and_fill():
    inputs = detect_inputs(GRAPH)
    assert inputs == {"prompt": "6.inputs.text", "negative": "7.inputs.text", "width": "5.inputs.width",
                      "height": "5.inputs.height", "seed": "3.inputs.seed"}
    g = fill(GRAPH, inputs, {"prompt": "a cat", "width": 768, "negative": ""})
    assert g["6"]["inputs"]["text"] == "a cat" and g["5"]["inputs"]["width"] == 768
    assert g["7"]["inputs"]["text"] == "negative" and GRAPH["6"]["inputs"]["text"] == "positive"
    assert ComfyUI("https://x.io", "k").ws_url("c") == "wss://x.io/ws?clientId=c&token=k"


def test_job_runs_saves_blob_and_pushes_callback(ai):
    images, hub, comfy = ai
    with pytest.raises(Invalid):
        images.save_flow({"graph": {"1": {"inputs": {}}}})
    images.save_flow({"name": "SDXL", "purpose": "generico", "graph": {"prompt": GRAPH}})   # whole /prompt body too
    j = images.request("a cozy house", purpose="sfondo", width=1024, height=576, seed=7,
                       callback={"service": "aphrodite", "path": "/api/appearance/images/done"}, ref="halloween")
    assert j["status"] == "queued"
    assert images.run_next() is True and images.run_next() is False
    done = images.job(j["id"])
    assert done["status"] == "done" and done["blob_ids"] == ["b1"] and hub.blobs["b1"]["mime"] == "image/png"
    assert comfy.graphs[0]["3"]["inputs"]["seed"] == 7 and comfy.graphs[0]["5"]["inputs"]["height"] == 576
    assert ("aphrodite", "POST", "/api/appearance/images/done") in hub.calls


def test_missing_flow_and_failures_are_told(ai):
    images, hub, comfy = ai
    j = images.request("a logo", purpose="icona")
    assert j["status"] == "failed" and j["error"] == "missing_flow"
    assert ("hermes", "POST", "apollo-missing-icona") in hub.calls
    images.save_flow({"purpose": "icona", "graph": GRAPH})
    comfy.fail = True
    j = images.request("a logo", purpose="icona", notify=True)
    images.run_next()
    assert images.job(j["id"])["error"].startswith("errore nel flusso")
    off = Images(Store(FakeArchive(), "images-store"), ComfyUI(""), FakeArchive()).request("x")
    assert off["error"] == "not_configured"


@pytest.mark.api
def test_endpoints_and_tools(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    hub, comfy = FakeArchive(), FakeComfy()
    imgs = Images(Store(hub, "images-store", min_refresh_seconds=0), comfy, hub)
    monkeypatch.setattr(main, "images", imgs)
    monkeypatch.setattr(main, "comfy", comfy)
    monkeypatch.setattr(imgs, "wait", lambda jid, s: (imgs.run_next(), imgs.job(jid))[1])
    c = TestClient(main.app)
    assert c.post("/api/images/flows", json={"purpose": "ritratto", "graph": GRAPH}).json()["inputs"]["prompt"]
    out = c.post("/api/images/tools/crea", json={"prompt": "portrait", "purpose": "ritratto"}).json()
    assert out["status"] == "done" and out["display"]["files"][0]["blob_id"] == "b1"
    assert c.get("/api/images/flows").json()["items"][0]["purpose"] == "ritratto"
    assert "graph" not in c.get("/api/images/flows").json()["items"][0]
