"""Tests — client plugins: hestia_common.plugin_client + Hub catalog (docs/work/2026-10-17-client-plugins)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hestia_common.plugin_client import PluginClient, page, quick_action, widget
import modules.discovery as disc
from modules.registry import ServiceRegistry


@pytest.fixture
def ui(tmp_path):
    (tmp_path / "webui").mkdir()
    (tmp_path / "webui" / "scout.js").write_text("customElements.define('scout-x', class extends HTMLElement {})")
    client = PluginClient("scout", title="Scout", icon="home", dist=tmp_path)
    client.webui(
        entry="scout.js",
        pages=[page("case", "Case", element="scout-listings"), page("case/:id", "Annuncio", element="scout-listing")],
        widgets=[widget("nuove", "Nuove case", element="scout-new", sizes=["m", "l"], auto=True,
                        params={"city": {"type": "string"}})],
        quick_actions=[quick_action("fetch", "Controlla email", "POST", "/api/ui/cycle",
                                    undo={"method": "DELETE", "path": "/api/ui/cycle"})],
    )
    return client


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


@pytest.mark.unit
class TestPluginClient:
    def test_manifest_shape(self, ui):
        m = ui.manifest()
        webui = m["clients"]["webui"]
        assert webui["entry"] == "/ui/webui/scout.js" and webui["api_prefix"] == "/api/ui/"
        assert [p["detail"] for p in webui["page"]] == [False, True]
        assert webui["widget"][0]["size"] == "m" and webui["quick_action"][0]["undo"]["method"] == "DELETE"
        assert m["version"].startswith("1.0.0+")

    def test_version_follows_bundle(self, ui, tmp_path):
        before = ui.manifest()["version"]
        (tmp_path / "webui" / "extra.css").write_text(":host{}")
        assert ui.manifest()["version"] != before

    def test_capabilities(self, ui):
        caps = ui.capabilities("http://hestia_scout:19006/")
        assert caps["ui_manifest"] == "http://hestia_scout:19006/api/ui/manifest" and caps["ui_version"]

    @pytest.mark.parametrize("bad", [
        lambda c: c.webui(entry="x.js", quick_actions=[quick_action("a", "A", "POST", "/api/other/x")]),
        lambda c: c.webui(entry="x.js", pages=[page("a", "A", element="other-page")]),
        lambda c: c.webui(entry="", pages=[page("a", "A", element="scout-a")]),
        lambda c: c.webui(entry="x.js", pages=[page("b", "B", element="scout-b", parent="missing")]),
        lambda c: c.webui(entry="x.js", widgets=[widget("w", "W", element="scout-w", sizes=["huge"])]),
    ])
    def test_validation(self, bad):
        with pytest.raises(ValueError):
            bad(PluginClient("scout", title="Scout"))

    def test_router_serves_bundle_only_inside_dist(self, ui):
        app = FastAPI()
        app.include_router(ui.router())
        c = TestClient(app)
        assert c.get("/api/ui/manifest").json()["module"] == "scout"
        r = c.get("/ui/webui/scout.js")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
        assert c.get("/ui/webui/scout.js", headers={"if-none-match": r.headers["etag"]}).status_code == 304
        assert c.get("/ui/webui/../../secret.js").status_code == 404
        assert c.get("/ui/telegram/scout.js").status_code == 404


@pytest.mark.unit
class TestHubCatalog:
    def setup_method(self):
        disc._ui_manifest_cache.clear()

    def test_catalog_by_client_and_type(self, ui, monkeypatch):
        monkeypatch.setattr(disc.requests, "get", lambda url, timeout=0: _Resp(ui.manifest()))
        reg = ServiceRegistry()
        reg.register({"name": "scout", "base_url": "http://s", "capabilities": ui.capabilities("http://s")})
        cat = disc.discover_catalog(reg, client="webui", types=["page", "widget", "quick_action"])
        webui = cat["contributions"]["webui"]
        assert [p["id"] for p in webui["page"]] == ["scout.case", "scout.case/:id"]
        assert webui["widget"][0]["module"] == "scout" and webui["bundle"][0]["entry"] == "/ui/webui/scout.js"
        assert cat["modules"][0]["online"] is True

    def test_offline_module_keeps_last_manifest(self, ui, monkeypatch):
        monkeypatch.setattr(disc.requests, "get", lambda url, timeout=0: _Resp(ui.manifest()))
        reg = ServiceRegistry()
        reg.register({"name": "scout", "base_url": "http://s", "capabilities": ui.capabilities("http://s")})
        disc.discover_catalog(reg, client="webui", types=["page"])

        def down(url, timeout=0):
            raise RuntimeError("down")
        monkeypatch.setattr(disc.requests, "get", down)
        disc.ui_manifest_cache_invalidate()
        cat = disc.discover_catalog(reg, client="webui", types=["page"])
        assert cat["modules"][0]["online"] is False
        assert len(cat["contributions"]["webui"]["page"]) == 2
