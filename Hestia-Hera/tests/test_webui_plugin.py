"""WebUI plugin: the manifest only names elements the bundle defines, gift ideas and likes from the page. Markers: unit, api"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Store

from app.core.service import People


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
    assert web["entry"] == "/ui/webui/hera.js" and web["api_prefix"] == "/api/people/"
    assert main.kit.registration()["capabilities"]["ui_manifest"].endswith("/api/ui/manifest")


@pytest.mark.api
def test_gift_and_like_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, "people", People(Store(FakeArchive(), "people-store", min_refresh_seconds=0),
                                               lambda k, d=None: d, hub=FakeArchive()))
    c = TestClient(main.app)
    pid = c.post("/api/people", json={"name": "Anna"}).json()["id"]
    idea = c.post(f"/api/people/{pid}/gift", json={"idea": "Un libro"}).json()
    gid = idea["gift_ideas"][0]["id"]
    c.post(f"/api/people/{pid}/gift/{gid}/done")
    c.post(f"/api/people/{pid}/like", json={"text": "tè"})
    c.post(f"/api/people/{pid}/like", json={"text": "caffè", "dislike": True})
    p = main.people.find(pid)
    assert p["likes"] == ["tè"] and p["dislikes"] == ["caffè"]
    assert all(g.get("done") for g in p["gift_ideas"])
