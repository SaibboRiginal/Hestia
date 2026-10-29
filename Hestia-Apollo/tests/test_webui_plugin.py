"""WebUI plugin: the manifest only names elements the bundle defines, one image of a job for the page. Markers: unit, api"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Store

from app.core.service import Images
from tests.test_apollo import GRAPH, FakeComfy


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
    assert web["entry"] == "/ui/webui/apollo.js" and web["api_prefix"] == "/api/images/"
    assert main.kit.registration()["capabilities"]["ui_manifest"].endswith("/api/ui/manifest")


@pytest.mark.api
def test_job_image(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    hub, comfy = FakeArchive(), FakeComfy()
    imgs = Images(Store(hub, "images-store", min_refresh_seconds=0), comfy, hub)
    monkeypatch.setattr(main, "images", imgs)
    monkeypatch.setattr(main, "comfy", comfy)
    monkeypatch.setattr(main.kit, "hub", hub)
    monkeypatch.setattr(imgs, "wait", lambda jid, s: (imgs.run_next(), imgs.job(jid))[1])
    c = TestClient(main.app)
    c.post("/api/images/flows", json={"purpose": "ritratto", "graph": GRAPH})
    jid = c.post("/api/images/tools/crea", json={"prompt": "portrait", "purpose": "ritratto"}).json()["id"]
    img = c.get(f"/api/images/jobs/{jid}/image/0").json()
    assert img["mime"] == "image/png" and img["data_b64"]
    assert c.get(f"/api/images/jobs/{jid}/image/5").status_code == 404
