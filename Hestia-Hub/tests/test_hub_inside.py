"""Tests — Hub "inside view" WebUI plugin (docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/A3/A6).

Hub's own manifest (kind core, Mappa page, Servizi online widget, order 100), its presence in the catalog
(Hub never registers with itself), /api/ui/map, and routing ``/api/route/hub/...`` in-process.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import src.main as hub_main
from src.modules import discovery as disc
from src.modules import inside
from src.modules.registry import ServiceRegistry


@pytest.fixture
def client():
    hub_main.registry._services.clear()
    disc._ui_manifest_cache.clear()
    yield TestClient(hub_main.app)
    hub_main.registry._services.clear()


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    (tmp_path / "webui").mkdir()
    (tmp_path / "webui" / "hub.js").write_text("customElements.define('hub-map', class extends HTMLElement {})")
    monkeypatch.setattr(inside.ui, "dist", tmp_path)
    return tmp_path


def _register(name: str, *, age: float = 0.0, **extra) -> None:
    hub_main.registry.register({"name": name, "base_url": f"http://hestia_{name}:1", "service_type": "core",
                                "service_version": "2.1.0", "topology_tags": ["layer:cognition", "status:beta"],
                                "capabilities": {}, **extra})
    if age:
        for svc in hub_main.registry.get(name):
            svc["updated_at"] = time.time() - age


@pytest.mark.unit
class TestHubManifest:
    def test_kind_pages_widgets_order(self):
        m = inside.ui.manifest()
        assert m["module"] == "hub" and m["kind"] == "core"
        webui = m["clients"]["webui"]
        assert webui["entry"] == "/ui/webui/hub.js" and webui["api_prefix"] == "/api/ui/"
        (p,) = webui["page"]
        assert (p["id"], p["label"], p["element"], p["order"]) == ("mappa", "Mappa", "hub-map", 100)
        (w,) = webui["widget"]
        assert (w["id"], w["label"], w["element"], w["auto"], w["open_page"]) == \
            ("online", "Servizi online", "hub-online-widget", True, "mappa")

    def test_hub_in_catalog_without_registering(self):
        reg = ServiceRegistry()
        cat = disc.discover_catalog(reg, client="webui", local_manifests=inside.local_manifests())
        (mod,) = cat["modules"]
        assert mod["module"] == "hub" and mod["kind"] == "core" and mod["online"] is True
        webui = cat["contributions"]["webui"]
        assert webui["bundle"][0]["module"] == "hub" and webui["bundle"][0]["api_prefix"] == "/api/ui/"
        assert [p["id"] for p in webui["page"]] == ["hub.mappa"]
        assert [w["id"] for w in webui["widget"]] == ["hub.online"]

    def test_local_manifest_respects_filters(self):
        reg = ServiceRegistry()
        local = inside.local_manifests()
        assert disc.discover_catalog(reg, client="webui", module="scout", local_manifests=local)["modules"] == []
        assert disc.discover_catalog(reg, client="webui", types=["command"], local_manifests=local)["modules"] == []
        assert disc.discover_catalog(reg, client="telegram", local_manifests=local)["contributions"] == {}


@pytest.mark.unit
class TestServiceMap:
    def test_rows_online_node_topology_and_self(self):
        now = 1000.0
        services = [
            {"name": "oracle", "base_url": "http://hestia_oracle:19004", "service_version": "1.2.0",
             "topology_tags": ["layer:cognition", "domain:llm"], "updated_at": now - 10, "capabilities": {"mcp_endpoint": "x"}},
            {"name": "oracle", "base_url": "http://10.0.0.5:19004", "updated_at": now - 400},
            {"name": "scout", "base_url": "http://192.168.1.20:19006", "updated_at": now - 400,
             "capabilities": {"node": "main-pc", "ui_manifest": "http://x/api/ui/manifest"}},
        ]
        m = inside.service_map(services, revision=7, updated_at=now - 5, now=now)
        names = [r["name"] for r in m["services"]]
        assert names == ["hub", "oracle", "scout"]
        hub, oracle, scout = m["services"]
        assert hub["self"] and hub["online"]
        assert oracle["online"] and oracle["node"] == "hestia_oracle" and oracle["instances"] == 2
        assert oracle["topology"] == {"layer": "cognition", "domain": "llm"} and oracle["has_mcp"]
        assert not scout["online"] and scout["node"] == "main-pc" and scout["has_ui"] and scout["age_seconds"] == 400
        assert (m["revision"], m["online_count"], m["offline_count"], m["services_count"]) == (7, 2, 1, 3)
        assert "health" not in oracle

    def test_probe_adds_health(self, monkeypatch):
        monkeypatch.setattr(inside, "_probe", lambda svc, timeout: ("unavailable", None))
        m = inside.service_map([{"name": "argus", "base_url": "http://a", "updated_at": time.time()}],
                               revision=1, updated_at=0, probe=True)
        assert m["probed"] and m["services"][1]["health"] == "unavailable"
        assert m["services"][0]["health"] == "healthy"   # Hub itself


@pytest.mark.api
class TestHubUiApi:
    def test_ui_map(self, client):
        _register("oracle")
        _register("scout", age=600)
        body = client.get("/api/ui/map").json()
        rows = {r["name"]: r for r in body["services"]}
        assert set(rows) == {"hub", "oracle", "scout"}
        assert rows["oracle"]["online"] and not rows["scout"]["online"]
        assert rows["oracle"]["version"] == "2.1.0" and body["revision"] == hub_main.events.revision

    def test_catalog_endpoint_lists_hub(self, client):
        cat = client.get("/api/discovery/catalog", params={"client": "webui", "type": "page,widget"}).json()
        assert any(m["module"] == "hub" and m["kind"] == "core" for m in cat["modules"])
        assert "hub.mappa" in [p["id"] for p in cat["contributions"]["webui"]["page"]]

    def test_route_to_hub_is_local(self, client, bundle):
        _register("oracle")
        r = client.post("/api/route/hub/api/ui/map", json={"method": "GET", "query": {}})
        assert r.status_code == 200 and r.json()["status_code"] == 200 and r.json()["target"] == "local"
        assert "oracle" in [s["name"] for s in r.json()["payload"]["services"]]
        f = client.post("/api/route/hub/ui/webui/hub.js", json={"method": "GET"}).json()
        assert f["status_code"] == 200 and "hub-map" in f["payload"]["raw"]
        assert client.post("/api/route/hub/ui/webui/../../etc.js", json={"method": "GET"}).json()["status_code"] == 404
        assert client.post("/api/route/hub/api/registry/register", json={"method": "POST"}).json()["status_code"] == 405
        m = client.post("/api/route/hub/api/ui/manifest", json={"method": "GET"}).json()
        assert m["payload"]["module"] == "hub"

    def test_manifest_and_bundle_served_directly(self, client, bundle):
        assert client.get("/api/ui/manifest").json()["kind"] == "core"
        assert client.get("/ui/webui/hub.js").status_code == 200
