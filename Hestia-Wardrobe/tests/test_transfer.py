"""Export / import of the wardrobe with photos (Archive blobs): files travel only on request, ids are remapped.
SPEC docs/work/2026-10-20-import-export.

Markers: unit
"""
import base64
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core.service import Wardrobe  # noqa: E402
from app.core.store import Store  # noqa: E402
from hestia_common.transfer import StoreSection, Transfer, TransferError  # noqa: E402
from tests.test_wardrobe import FakeHub  # noqa: E402

pytestmark = pytest.mark.unit


class BlobHub(FakeHub):
    """FakeHub + blob meta (owner check) and new ids that differ between two Hestia."""

    def __init__(self, prefix):
        super().__init__()
        self.prefix = prefix

    def ok(self, service, method, path, *, body=None, query=None, timeout=8):
        if service == "archive" and path == "api/blobs" and method == "POST":
            bid = f"{self.prefix}{len(self.blobs) + 1}"
            self.blobs[bid] = body
            return {"blob_id": bid}
        if service == "archive" and path.startswith("api/blobs/") and path.endswith("/meta"):
            b = self.blobs[path.split("/")[2]]
            return {"blob_id": path.split("/")[2], "owner_module": b["owner_module"], "content_type": b["content_type"],
                    "meta": b.get("meta") or {}}
        return super().ok(service, method, path, body=body, query=query, timeout=timeout)


def _hestia(prefix):
    hub = BlobHub(prefix)
    store = Store(hub, min_refresh_seconds=0)
    w = Wardrobe(store, hub, lambda key, default=None: default, tz="Europe/Rome")
    w.ensure_vocabularies()
    t = Transfer("wardrobe", hub, sections=[
        StoreSection("capi", "Capi", store, ["piece"], depends_on=["vocabolari", "foto"]),
        StoreSection("vocabolari", "Vocabolari", store, ["taxonomy"]),
        StoreSection("foto", "Foto", store, ["photo"], file_fields=["original", "medium", "thumb"]),
    ])
    return w, t


def test_photos_travel_only_on_request_and_are_remapped():
    cloud, ct = _hestia("c")
    tee = cloud.save_piece({"name": "T-shirt bianca", "category": "tshirt", "colors": ["white"]})
    try:
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (400, 300), (200, 30, 30)).save(buf, "JPEG")
        raw = base64.b64encode(buf.getvalue()).decode()
    except ModuleNotFoundError:                       # no Pillow: bytes are stored as they are
        raw = base64.b64encode(b"\xff\xd8\xff fake jpeg").decode()
    cloud.add_photo("piece", tee["id"], {"name": "t.jpg", "mime": "image/jpeg", "data_b64": raw})

    light = ct.export({"capi": {"keys": [f"piece:{tee['id']}"]}})
    assert "foto" not in light["sections"] and light["files"] == []

    full = json.loads(json.dumps(ct.export({"capi": {"keys": [f"piece:{tee['id']}"]}}, include_files=True)))
    assert len(full["sections"]["foto"]["records"]) == 1 and len(full["files"]) == 3
    files = [ct.file_get(f) for f in full["files"]]

    home, ht = _hestia("h")
    mapping = {}
    for f in files:
        out = ht.file_put(f)
        mapping[out["old_id"]] = out["new_id"]
    assert all(v.startswith("h") for v in mapping.values())
    ht.import_(full, mode="merge", dry_run=False, files_map=mapping)
    photo = home.store.items("photo")[0]
    assert {photo["original"], photo["medium"], photo["thumb"]} == set(mapping.values())
    assert home.store.data("piece", tee["id"])["photos"] == [photo["id"]]


def test_file_of_another_module_is_refused():
    cloud, ct = _hestia("c")
    cloud.hub.blobs["x1"] = {"owner_module": "hygieia", "content_type": "image/png", "data_base64": "AA=="}
    with pytest.raises(TransferError):
        ct.file_get("x1")
