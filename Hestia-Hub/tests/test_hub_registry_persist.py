"""Tests — Hub registry snapshot (SPEC docs/work/2026-10-20-hub-registro-persistente)."""
from __future__ import annotations

import json
import time

import pytest

from modules.events import RegistryEvents
from modules.registry import ServiceRegistry
from modules.snapshot import RegistrySnapshot


def _svc(name, url, **extra):
    return {"name": name, "base_url": url, "health_endpoint": "/health", **extra}


@pytest.mark.unit
class TestRegistrySnapshot:
    def test_save_then_load_round_trip(self, tmp_path):
        snap = RegistrySnapshot(tmp_path / "registry.json")
        reg = ServiceRegistry()
        reg.register(_svc("archive", "http://hestia_archive:19002", tags=["core"]))
        reg.register(_svc("oracle", "http://hestia_oracle:19003"))
        assert snap.save(reg.all_services(), revision=7)

        loaded = snap.load()
        assert loaded["revision"] == 7 and loaded["dropped"] == 0
        assert {s["name"] for s in loaded["services"]} == {"archive", "oracle"}

    def test_missing_file_starts_empty(self, tmp_path):
        loaded = RegistrySnapshot(tmp_path / "nope.json").load()
        assert loaded == {"revision": 0, "services": [], "dropped": 0, "saved_at": None}

    @pytest.mark.parametrize("content", ["{not json", "[]", '{"services": "x"}'])
    def test_corrupt_file_starts_empty(self, tmp_path, content):
        path = tmp_path / "registry.json"
        path.write_text(content, encoding="utf-8")
        loaded = RegistrySnapshot(path).load()
        assert loaded["services"] == [] and loaded["revision"] == 0

    def test_old_heartbeats_are_dropped(self, tmp_path):
        path = tmp_path / "registry.json"
        now = time.time()
        path.write_text(json.dumps({"version": 1, "revision": 3, "services": [
            _svc("fresh", "http://f:1", updated_at=now - 60),
            _svc("ghost", "http://g:1", updated_at=now - 25 * 3600),
            {"name": "", "base_url": "http://x:1"},
        ]}), encoding="utf-8")
        loaded = RegistrySnapshot(path).load(now=now)
        assert [s["name"] for s in loaded["services"]] == ["fresh"]
        assert loaded["dropped"] == 2

    def test_heartbeat_writes_are_throttled(self, tmp_path):
        snap = RegistrySnapshot(tmp_path / "registry.json", refresh_interval=30)
        assert snap.save([], 1, force=True)
        assert not snap.save([], 2, force=False)          # heartbeat inside 30 s: skipped
        assert snap.dirty
        assert snap.save([], 3, force=True)              # real change: always written
        assert snap.load()["revision"] == 3 and not snap.dirty

    def test_unwritable_path_does_not_raise(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        assert not RegistrySnapshot(blocker / "registry.json").save([], 1)


@pytest.mark.unit
class TestRegistryRestore:
    def test_restored_instances_are_routable_and_flagged(self):
        reg = ServiceRegistry()
        assert reg.restore([_svc("Archive", "http://hestia_archive:19002", updated_at=1.0)]) == 1
        [inst] = reg.get("archive")
        assert inst["restored"] is True and inst["base_url"] == "http://hestia_archive:19002"

    def test_reregistration_clears_flag_as_refresh(self):
        reg = ServiceRegistry()
        reg.restore([_svc("archive", "http://a:1", updated_at=1.0)])
        assert reg.register(_svc("archive", "http://a:1")) == "refreshed"
        [inst] = reg.get("archive")
        assert "restored" not in inst and inst["updated_at"] > 1.0

    def test_restore_does_not_override_live_registration(self):
        reg = ServiceRegistry()
        reg.register(_svc("archive", "http://a:1", service_version="2.0"))
        assert reg.restore([_svc("archive", "http://a:1", service_version="1.0")]) == 0
        [inst] = reg.get("archive")
        assert inst["service_version"] == "2.0" and "restored" not in inst

    def test_revision_continues_after_restore(self):
        events = RegistryEvents()
        events.restore(41)
        events.bump([], reason="restore")
        assert events.revision == 42


@pytest.mark.api
def test_register_endpoint_writes_snapshot(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import src.main as hub_main

    monkeypatch.setattr(hub_main.snapshot, "path", tmp_path / "registry.json")
    hub_main.registry._services.clear()
    try:
        client = TestClient(hub_main.app)
        resp = client.post("/api/registry/register", json={
            "name": "dummy", "base_url": "http://hestia_dummy:1", "service_type": "module",
            "tags": ["module"], "topology_tags": []})
        assert resp.status_code == 200, resp.text
        saved = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
        assert [s["name"] for s in saved["services"]] == ["dummy"]
        assert saved["revision"] == hub_main.events.revision
    finally:
        hub_main.registry._services.clear()
