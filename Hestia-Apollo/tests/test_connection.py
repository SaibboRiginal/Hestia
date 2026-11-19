"""«ComfyUI» card (docs/work/2026-11-19-unified-connections): the shared contract (hestia_common.connections) with the
address in Themis and the key through Hephaestus, «Test» answering with version, GPU and models. No network: a fake
HTTP session, fake settings, the key writer replaced by a dict. Markers: unit, api"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hestia_common.connections import Connections
from app.core.comfy import ComfyUI

pytestmark = pytest.mark.unit

STATS = {"system": {"comfyui_version": "0.3.40"},
         "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 4080 SUPER : cudaMallocAsync", "type": "cuda",
                      "vram_total": 16 * 2**30, "vram_free": 12 * 2**30}]}


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data
        self.headers = {"content-type": "application/json"}

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class FakeHTTP:
    def __init__(self, up=True):
        self.up, self.calls = up, []

    def get(self, url, params=None, headers=None, timeout=30):
        import requests
        self.calls.append((url, headers))
        if not self.up:
            raise requests.ConnectionError("refused")
        if url.endswith("/system_stats"):
            return Resp(200, STATS)
        if url.endswith("/models/checkpoints"):
            return Resp(200, ["flux1-dev.safetensors", "sdxl.safetensors"])
        return Resp(404, {})


class FakeSettings:
    def __init__(self):
        self.values, self.callbacks = {}, []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def put(self, key, value, **kw):
        self.values[key] = value
        return True

    def on_change(self, cb):
        self.callbacks.append(cb)


@pytest.fixture
def world(monkeypatch, tmp_path):
    from app import main
    http = FakeHTTP()
    comfy = ComfyUI("", "", session=http)
    settings = FakeSettings()
    conns = Connections("apollo", "/api/images/", env_file=tmp_path / ".env")
    saved = {}

    def save_secrets(values):
        for name, value in values.items():
            env = conns.key_env(name)
            saved[env] = value
            if value:
                monkeypatch.setenv(env, value)
            else:
                monkeypatch.delenv(env, raising=False)

    monkeypatch.setattr(conns, "save_secrets", save_secrets)
    monkeypatch.delenv("APOLLO_KEY_COMFYUI", raising=False)
    card = conns.register(main.ComfyConnector(conns, settings=settings, setting_key=main.COMFY_ADDRESS,
                                              probe=lambda a, k: comfy.probe(a, k), apply=comfy.configure))
    app = FastAPI()
    app.include_router(conns.router())
    return {"c": TestClient(app), "comfy": comfy, "http": http, "settings": settings, "saved": saved, "card": card,
            "conns": conns}


def test_not_linked_shows_the_form_and_its_guide(world):
    item = world["c"].get("/api/images/connections").json()["items"][0]
    assert item["id"] == "comfyui" and item["group"] == "home_service" and "comfy" in item["keywords"]
    assert item["state"] == "not_connected" and [f["name"] for f in item["step"]["fields"]] == ["address", "key"]
    assert any("--listen" in g for g in item["step"]["guide"])


def test_save_address_and_key_then_test_says_gpu_and_models(world):
    c = world["c"]
    assert c.post("/api/images/connections/comfyui", json={"values": {"address": "pc:8188"}}).status_code == 422
    r = c.post("/api/images/connections/comfyui", json={"values": {"address": "http://pc.local:8188/", "key": "tok"}}).json()
    assert world["settings"].values == {"apollo.comfyui.address": "http://pc.local:8188"}
    assert world["saved"] == {"APOLLO_KEY_COMFYUI": "tok"}
    assert world["comfy"].url == "http://pc.local:8188" and world["comfy"].key == "tok"   # the next job uses them
    assert r["item"]["state"] == "connected" and [a["id"] for a in r["item"]["actions"]] == ["edit", "forget"]
    assert world["http"].calls[0][1] == {"Authorization": "Bearer tok"}
    result = c.post("/api/images/connections/comfyui/test").json()["result"]
    assert result["ok"] is True
    facts = " ".join(result["facts"])
    assert "0.3.40" in facts and "RTX 4080 SUPER" in facts and "12.0" in facts and "flux1-dev" in facts


def test_unreachable_says_how_to_start_comfyui_and_keeps_the_form(world):
    world["http"].up = False
    r = world["c"].post("/api/images/connections/comfyui", json={"values": {"address": "http://pc.local:8188"}}).json()
    assert r["item"]["state"] == "not_connected" and r["item"]["step"]["fields"][0]["value"] == "http://pc.local:8188"
    result = world["c"].post("/api/images/connections/comfyui/test").json()["result"]
    assert result["ok"] is False and any("--listen 0.0.0.0" in f for f in result["facts"])


def test_unlink_clears_address_and_key(world):
    c = world["c"]
    c.post("/api/images/connections/comfyui", json={"values": {"address": "http://pc.local:8188", "key": "tok"}})
    r = c.delete("/api/images/connections/comfyui").json()
    assert r["item"]["state"] == "not_connected" and world["saved"]["APOLLO_KEY_COMFYUI"] == ""
    assert world["settings"].values["apollo.comfyui.address"] == "" and not world["comfy"].configured


def test_a_change_pushed_by_themis_reaches_the_client(world):
    world["settings"].values["apollo.comfyui.address"] = "http://gpu.lan:8188"
    for cb in world["settings"].callbacks:
        cb({"apollo.comfyui.address": "http://gpu.lan:8188"})
    assert world["comfy"].url == "http://gpu.lan:8188"


def test_reload_keys_reads_only_this_module_and_drops_cleared(world, monkeypatch):
    env = world["conns"].env_file
    env.write_text("APOLLO_KEY_COMFYUI=abc\nORACLE_KEY_X=nope\n", encoding="utf-8")
    assert world["c"].post("/api/connections/reload-keys").json()["keys"] == ["APOLLO_KEY_COMFYUI"]
    import os
    assert os.environ.get("APOLLO_KEY_COMFYUI") == "abc" and world["comfy"].key == "abc"
    env.write_text("APOLLO_KEY_COMFYUI=\n", encoding="utf-8")
    assert world["c"].post("/api/connections/reload-keys").json()["keys"] == []
    assert "APOLLO_KEY_COMFYUI" not in os.environ


def test_manifest_lists_the_card_for_the_catalog():
    from app import main
    web = main.kit.ui.manifest()["clients"]["webui"]
    assert [c["id"] for c in web["connection"]] == ["comfyui"]
    assert web["connection"][0]["source"] == "/api/images/connections"
    setting = main.kit.settings._defs["apollo.comfyui.address"]
    assert setting["editor"] == "connection:apollo.comfyui"
