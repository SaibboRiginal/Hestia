"""Metis WebUI plugin (core module, SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/A3).

Markers: unit, api
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_METIS_ROOT = Path(__file__).parents[1]
_SHARED_PATH = _METIS_ROOT.parent / "Hestia-Shared"
for _p in [str(_METIS_ROOT), str(_SHARED_PATH)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

UI_SRC = _METIS_ROOT / "ui" / "src"


@pytest.fixture
def client():
    with patch("app.main.hub", MagicMock()):
        from app.main import app
        with TestClient(app) as c:
            yield c


def _manifest() -> dict:
    from app.main import ui
    return ui.manifest()


@pytest.mark.unit
class TestManifest:
    def test_core_kind_and_prefix(self):
        m = _manifest()
        assert m["module"] == "metis" and m["kind"] == "core"
        web = m["clients"]["webui"]
        assert web["api_prefix"] == "/api/metis/"
        assert web["entry"] == "/ui/webui/metis.js"

    def test_page_miglioramento_order_decade_180(self):
        pages = {p["id"]: p for p in _manifest()["clients"]["webui"]["page"]}
        assert set(pages) == {"miglioramento"}
        assert pages["miglioramento"]["element"] == "metis-improvement"
        assert 180 <= pages["miglioramento"]["order"] < 190

    def test_no_widgets_no_quick_actions(self):
        web = _manifest()["clients"]["webui"]
        assert web["widget"] == [] and web["quick_action"] == []

    def test_bundle_registers_element_and_stays_under_prefix(self):
        index = (UI_SRC / "index.ts").read_text(encoding="utf-8")
        assert "'metis-improvement'" in index
        page = (UI_SRC / "improvement.ts").read_text(encoding="utf-8")
        assert "const API = '/api/metis';" in page
        assert "'/api/" not in page.replace("'/api/metis'", "")

    def test_hub_registration_carries_ui_manifest(self):
        from app.main import _HUB_REGISTRATION_PAYLOAD
        caps = _HUB_REGISTRATION_PAYLOAD["capabilities"]
        assert caps["ui_manifest"].endswith("/api/ui/manifest")
        assert caps["ui_version"]


@pytest.mark.api
class TestEndpoints:
    def test_manifest_served(self, client):
        body = client.get("/api/ui/manifest").json()
        assert body["module"] == "metis" and body["kind"] == "core"

    def test_missing_bundle_file_is_404(self, client):
        assert client.get("/ui/webui/nope.js").status_code == 404

    def test_reads_used_by_the_page_exist(self, client):
        """The page reads lora/jobs, insights and dataset/status: all must answer under /api/metis/."""
        with patch("app.main.hub") as hub:
            hub.fetch_feedback.return_value = [
                {"quality_label": "bad", "tags": ["domain=calendar"], "payload": {"instruction": "x", "output": "y"}},
                {"quality_label": "good", "tags": []},
            ]
            ins = client.get("/api/metis/insights").json()
        assert ins["total_feedback"] == 2 and ins["weak_domains"][0]["domain"] == "calendar"
        jobs = client.get("/api/metis/lora/jobs").json()
        assert jobs["status"] == "ok" and "jobs" in jobs
        ds = client.get("/api/metis/dataset/status")
        assert ds.status_code == 200 and "datasets" in ds.json()
