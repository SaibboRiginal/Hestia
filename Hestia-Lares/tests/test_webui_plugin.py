"""WebUI plugin: the manifest only names elements the bundle defines, the quick action chips. Markers: unit, api"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Store

from app.core.service import Home
from tests.test_lares import FakeHA


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
    assert web["entry"] == "/ui/webui/lares.js" and web["api_prefix"] == "/api/home/"
    assert main.kit.registration()["capabilities"]["ui_manifest"].endswith("/api/ui/manifest")


@pytest.mark.api
def test_quick_chips_are_the_favorites(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "home", Home(Store(FakeArchive(), "home-store", min_refresh_seconds=0), FakeHA(),
                                           lambda k, d=None: d))
    c = TestClient(main.app)
    assert c.get("/api/home/quick").json() == []
    c.get("/api/home/status")
    fid = c.post("/api/home/favorites", json={"entity": "Luce cucina", "room": "Cucina"}).json()["id"]
    assert c.get("/api/home/quick").json() == [{"id": fid, "label": "Luce cucina", "icon": "home", "hint": "Cucina"}]
    quick = main.kit.ui.manifest()["clients"]["webui"]["quick_action"][0]
    assert quick["source"] == "/api/home/quick" and "{id}" in quick["path"]
