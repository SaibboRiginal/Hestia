"""WebUI plugin: the manifest only names elements the bundle defines, the file as base64 for the page. Markers: unit, api"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import base64

from hestia_common.module_kit import FakeArchive, Store

from app.core.service import Documents
from tests.test_calliope import HTML


def _bundle_elements() -> set[str]:
    src = (_ROOT / "ui" / "src" / "index.ts").read_text(encoding="utf-8")
    block = re.search(r"definePlugin\(\{(.*?)\}\)", src, re.S)
    return set(re.findall(r"'([a-z0-9-]+)'\s*:", block.group(1)))


@pytest.mark.unit
def test_manifest_elements_are_in_the_bundle():
    from app import main
    web = main.kit.ui.manifest()["clients"]["webui"]
    used = {p["element"] for p in web["page"]} | {w["element"] for w in web["widget"]}
    assert used == _bundle_elements()
    assert web["entry"] == "/ui/webui/calliope.js" and web["api_prefix"] == "/api/office/"
    assert main.kit.registration()["capabilities"]["ui_manifest"].endswith("/api/ui/manifest")


@pytest.mark.api
def test_file_as_base64(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "docs", Documents(Store(FakeArchive(), "office-store", min_refresh_seconds=0), FakeArchive()))
    c = TestClient(main.app)
    did = c.post("/api/office/tools/crea", json={"title": "Nota", "html": HTML, "format": "pdf"}).json()["id"]
    out = c.get(f"/api/office/{did}/b64").json()
    assert out["mime"] == "application/pdf" and out["name"].endswith(".pdf")
    assert base64.b64decode(out["data_b64"]) == c.get(f"/api/office/{did}/file").content
