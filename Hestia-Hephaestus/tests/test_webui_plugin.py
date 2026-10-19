"""Hephaestus WebUI plugin (core module, SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/A3).

Markers: unit, api
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

UI_SRC = Path(__file__).resolve().parents[1] / "ui" / "src"


def _manifest() -> dict:
    from app.core.webui_plugin import ui
    return ui.manifest()


@pytest.mark.unit
class TestManifest:
    def test_core_kind_and_prefix_cover_remediation_and_forge(self):
        m = _manifest()
        assert m["module"] == "hephaestus" and m["kind"] == "core"
        web = m["clients"]["webui"]
        assert web["api_prefix"] == "/api/hephaestus/"
        assert web["entry"] == "/ui/webui/hephaestus.js"

    def test_page_riparazioni_order_decade_170(self):
        pages = {p["id"]: p for p in _manifest()["clients"]["webui"]["page"]}
        assert set(pages) == {"sviluppo", "riparazioni"}
        assert pages["riparazioni"]["element"] == "hephaestus-repairs"
        assert 170 <= pages["riparazioni"]["order"] < 180

    def test_page_sviluppo_first_with_review_badge(self):
        """SPEC §A4: the built-in Sviluppo page becomes this plugin's first page; badge = tasks waiting for you."""
        pages = {p["id"]: p for p in _manifest()["clients"]["webui"]["page"]}
        sv = pages["sviluppo"]
        assert sv["element"] == "hephaestus-sviluppo" and sv["order"] == 170 and not sv["parent"]
        assert sv["order"] < pages["riparazioni"]["order"]
        assert sv["badge"] == {"source": "/api/hephaestus/forge/counts", "field": "review"}

    def test_widget_forge_auto(self):
        widgets = {w["id"]: w for w in _manifest()["clients"]["webui"]["widget"]}
        assert set(widgets) == {"forge"}
        assert widgets["forge"]["element"] == "hephaestus-forge-widget"
        assert widgets["forge"]["auto"] is True
        assert widgets["forge"]["open_page"] == "sviluppo"

    def test_no_quick_actions_no_new_destructive_paths(self):
        assert _manifest()["clients"]["webui"].get("quick_action") == []

    def test_bundle_registers_declared_elements(self):
        index = (UI_SRC / "index.ts").read_text(encoding="utf-8")
        for el in ("hephaestus-repairs", "hephaestus-forge-widget", "hephaestus-sviluppo", "hephaestus-task-panel",
                   "hephaestus-repo", "hephaestus-transcript", "hephaestus-diff", "hephaestus-md"):
            assert f"'{el}'" in index

    def test_bundle_calls_stay_under_api_prefix(self):
        util = (UI_SRC / "util.ts").read_text(encoding="utf-8")
        assert "export const API = '/api/hephaestus';" in util
        for f in UI_SRC.rglob("*.ts"):
            text = f.read_text(encoding="utf-8")
            assert "'/api/" not in text.replace("'/api/hephaestus'", ""), f.name
            assert "/api/webui/" not in text, f.name   # the plugin calls Forge directly, never the old controller

    def test_capabilities_carry_ui_manifest(self):
        from app.core.service import HephaestusService
        from app.core.service_contract import ServiceDescriptor
        caps = HephaestusService(ServiceDescriptor(name="hephaestus", base_url="http://h:19010")).build_capabilities()
        assert caps["ui_manifest"] == "http://h:19010/api/ui/manifest"
        assert caps["ui_version"]


@pytest.mark.api
class TestManifestEndpoint:
    def _client(self):
        from fastapi.testclient import TestClient
        import app.main as heph_main
        return TestClient(heph_main.app, raise_server_exceptions=False)

    def test_manifest_served(self):
        with patch("requests.post"), patch("requests.get"):
            body = self._client().get("/api/ui/manifest").json()
        assert body["module"] == "hephaestus" and body["kind"] == "core"

    def test_missing_bundle_file_is_404(self):
        with patch("requests.post"), patch("requests.get"):
            resp = self._client().get("/ui/webui/nope.js")
        assert resp.status_code == 404

    def test_bundle_file_served_from_dist(self, tmp_path):
        from app.core.webui_plugin import ui
        (tmp_path / "webui").mkdir()
        (tmp_path / "webui" / "hephaestus.js").write_text("export {};", encoding="utf-8")
        old = ui.dist
        ui.dist = tmp_path
        try:
            with patch("requests.post"), patch("requests.get"):
                resp = self._client().get("/ui/webui/hephaestus.js")
        finally:
            ui.dist = old
        assert resp.status_code == 200 and "javascript" in resp.headers["content-type"]
