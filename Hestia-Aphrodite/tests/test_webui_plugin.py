"""WebUI plugin: the manifest only names elements the bundle defines, pet pictures uploaded and read back. Markers: unit, api"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import Store

from app.core.service import Appearance
from tests.test_aphrodite import ApolloHub


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
    assert web["entry"] == "/ui/webui/aphrodite.js" and web["api_prefix"] == "/api/appearance/"
    assert main.kit.registration()["capabilities"]["ui_manifest"].endswith("/api/ui/manifest")


@pytest.mark.api
def test_pet_picture_upload_and_read(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    hub = ApolloHub()
    monkeypatch.setattr(main, "look", Appearance(Store(hub, "appearance-store", min_refresh_seconds=0), hub))
    monkeypatch.setattr(main.kit, "hub", hub)
    c = TestClient(main.app)
    pid = c.post("/api/appearance/tools/animale", json={"name": "Pip"}).json()["id"]
    pet = c.post(f"/api/appearance/pets/{pid}/image/happy", json={"mime": "image/png", "data_b64": "AAAA"}).json()
    bid = pet["images"]["happy"]
    assert hub.blobs[bid]["meta"] == {"pet": pid, "pose": "happy"}
    assert c.get(f"/api/appearance/image/{bid}").json() == {"mime": "image/png", "data_b64": "AAAA"}
    assert c.get("/api/appearance/image/nope").status_code == 404
    assert c.post(f"/api/appearance/pets/{pid}/image/jump", json={"data_b64": "AAAA"}).status_code == 422
