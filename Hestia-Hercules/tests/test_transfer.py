"""Export / import (hestia_common.transfer) over Hercules' store: two Hestia, a file between them.

Markers: unit
"""
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core.store import Store
from hestia_common.transfer import StoreSection, Transfer, TransferError
from tests.test_hercules import FakeArchive

pytestmark = pytest.mark.unit

OLD, NEW, NEWER = "2026-10-01T10:00:00+00:00", "2026-10-10T10:00:00+00:00", "2026-10-15T10:00:00+00:00"


def _hestia():
    store = Store(FakeArchive(), min_refresh_seconds=0)
    t = Transfer("hercules", sections=[
        StoreSection("esercizi", "Esercizi", store, ["exercise"]),
        StoreSection("schede", "Schede", store, ["template"], depends_on=["esercizi"]),
        StoreSection("sessioni", "Sessioni", store, ["session", "set"], item_kinds=["session"],
                     depends_on=["esercizi", "schede"]),
        StoreSection("misure", "Misure", store, ["measurement"]),
    ])
    return store, t


def _row(kind, id, data, updated_at=NEW, **kw):
    return {"kind": kind, "id": id, "data": data, "updated_at": updated_at, **kw}


@pytest.fixture
def cloud():
    store, t = _hestia()
    store.write([
        _row("exercise", "ex-bench", {"name": "Panca"}),
        _row("exercise", "ex-squat", {"name": "Squat"}),
        _row("exercise", "ex-curl", {"name": "Curl"}),
        _row("template", "tp-push", {"name": "Push", "items": [{"exercise_id": "ex-bench"}]}),
        _row("session", "s1", {"name": "Lunedì", "template_id": "tp-push"}),
        _row("set", "set1", {"exercise_id": "ex-squat", "reps": 5}, parent_id="s1", ref_id="ex-squat"),
        _row("measurement", "m1", {"kind": "bodyweight", "value": 80}),
    ])
    return store, t


def _roundtrip(payload):
    return json.loads(json.dumps(payload))      # what really travels: a JSON file


def test_describe_counts_items_only(cloud):
    _, t = cloud
    by = {s["id"]: s["count"] for s in t.describe()["sections"]}
    assert by == {"esercizi": 3, "schede": 1, "sessioni": 1, "misure": 1}
    assert t.capabilities()["transfer"]["sections"]["sessioni"] == 1


def test_item_export_pulls_children_and_dependencies(cloud):
    _, t = cloud
    out = t.export({"sessioni": {"keys": ["session:s1"]}})
    keys = {sid: sorted(r["key"] for r in b["records"]) for sid, b in out["sections"].items()}
    assert keys["sessioni"] == ["session:s1", "set:set1"]                 # the set travels with its session
    assert keys["schede"] == ["template:tp-push"]                          # referenced template
    assert keys["esercizi"] == ["exercise:ex-bench", "exercise:ex-squat"]  # via set and via the template
    assert out["sections"]["esercizi"]["partial"] and out["sections"]["sessioni"]["partial"]
    assert "misure" not in out["sections"]


def test_import_into_empty_hestia_then_unchanged(cloud):
    _, t = cloud
    data = _roundtrip(t.export())
    home_store, home = _hestia()
    preview = home.import_(data, mode="merge", dry_run=True)
    assert preview["totals"]["added"] == 6 and not home_store.all("exercise")   # dry run writes nothing
    done = home.import_(data, mode="merge", dry_run=False)
    assert done["totals"]["added"] == 6 and done["sections"]["sessioni"]["related"] == 1
    assert home_store.get("set", "set1")["parent_id"] == "s1"
    again = home.import_(data, mode="merge", dry_run=True)
    assert again["totals"]["added"] == 0 and again["totals"]["unchanged"] == 6


def test_modes_on_existing_records(cloud):
    _, t = cloud
    home_store, home = _hestia()
    home_store.write([_row("exercise", "ex-bench", {"name": "Panca piana"}, updated_at=NEWER),   # newer at home
                      _row("exercise", "ex-squat", {"name": "Squat vecchio"}, updated_at=OLD),   # older at home
                      _row("exercise", "ex-home", {"name": "Solo a casa"}, updated_at=OLD)])
    data = _roundtrip(t.export({"esercizi": {}}))

    r = home.import_(data, mode="append", dry_run=True)["sections"]["esercizi"]
    assert (r["added"], r["updated"], r["skipped"], r["deleted"]) == (1, 0, 2, 0)

    r = home.import_(data, mode="merge", dry_run=True)["sections"]["esercizi"]
    assert (r["added"], r["updated"], r["skipped"], r["deleted"]) == (1, 1, 1, 0)

    r = home.import_(data, mode="replace", dry_run=False)["sections"]["esercizi"]
    assert (r["added"], r["updated"], r["skipped"], r["deleted"]) == (1, 2, 0, 1)
    assert home_store.data("exercise", "ex-bench")["name"] == "Panca"     # file wins
    assert home_store.get("exercise", "ex-home") is None                    # only at home → deleted (tombstone)


def test_replace_of_partial_section_never_deletes(cloud):
    _, t = cloud
    home_store, home = _hestia()
    home_store.write([_row("exercise", "ex-home", {"name": "Solo a casa"})])
    data = _roundtrip(t.export({"esercizi": {"keys": ["exercise:ex-curl"]}}))
    r = home.import_(data, mode="replace", dry_run=False)["sections"]["esercizi"]
    assert r["partial"] and r["deleted"] == 0 and home_store.get("exercise", "ex-home")


def test_since_exports_changes_and_deletions(cloud):
    store, t = cloud
    store.write([_row("measurement", "m1", {"kind": "bodyweight", "value": 80}, updated_at=NEWER, deleted=True)])
    out = t.export({"misure": {}, "esercizi": {}}, since="2026-10-12T00:00:00+00:00")
    assert [r["key"] for r in out["sections"]["misure"]["records"]] == ["measurement:m1"]
    assert out["sections"]["misure"]["records"][0]["deleted"] and out["sections"]["esercizi"]["records"] == []
    home_store, home = _hestia()
    home_store.write([_row("measurement", "m1", {"kind": "bodyweight", "value": 80}, updated_at=NEW)])
    r = home.import_(_roundtrip(out), mode="merge", dry_run=False)["sections"]["misure"]
    assert r["deleted"] == 1 and home_store.get("measurement", "m1") is None


def test_import_selection_and_newer_schema(cloud):
    _, t = cloud
    data = _roundtrip(t.export())
    home_store, home = _hestia()
    r = home.import_(data, dry_run=False, selection={"misure": {}})
    assert list(r["sections"]) == ["misure"] and home_store.get("measurement", "m1") and not home_store.all("exercise")
    data["sections"]["misure"]["schema"] = 99
    assert home.import_(data, dry_run=True)["sections"]["misure"]["problems"] == 1
    data["format"] = 99
    with pytest.raises(TransferError):
        home.import_(data, dry_run=True)
    with pytest.raises(TransferError):
        home.import_({"sections": {}}, mode="overwrite")


def test_items_picker_and_http(cloud):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    _, t = cloud
    items = t.section("esercizi").items(q="pan")
    assert items["total"] == 1 and items["items"][0]["title"] == "Panca"
    app = FastAPI()
    app.include_router(t.router())
    c = TestClient(app)
    assert c.get("/api/transfer/describe").json()["module"] == "hercules"
    assert c.post("/api/transfer/items", json={"section": "nope"}).status_code == 404
    exp = c.post("/api/transfer/export", json={"sections": {"misure": {}}}).json()
    rep = c.post("/api/transfer/import", json={"data": exp, "mode": "merge"}).json()
    assert rep["dry_run"] is True and rep["totals"]["unchanged"] == 1


def test_no_secret_like_keys_in_export(cloud):
    _, t = cloud
    text = json.dumps(t.export()).lower()
    for word in ("api_key", "token", "password", "secret"):
        assert word not in text
