"""WebUI plugin: the manifest only names elements the bundle defines. Markers: unit, api"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


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
    assert web["entry"] == "/ui/webui/kairos.js" and web["api_prefix"] == "/api/deadlines/"
    assert main.kit.registration()["capabilities"]["ui_manifest"].endswith("/api/ui/manifest")
