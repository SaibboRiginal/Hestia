"""Tests — hestia_common.downloads (docs/work/2026-10-30-setup-un-click §4.3). No network: HTTP faked."""
from __future__ import annotations

import hashlib
import threading

import pytest
import requests

from hestia_common import downloads as dl

pytestmark = pytest.mark.unit

BLOB = bytes(range(256)) * 4096          # 1 MiB


class FakeResp:
    def __init__(self, status, body=b"", headers=None, gate=None):
        self.status_code, self._body, self.headers, self._gate = status, body, headers or {}, gate

    def iter_content(self, size):
        for i in range(0, len(self._body), 65536):
            if self._gate is not None:
                self._gate.wait(5)
            yield self._body[i:i + 65536]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_get(calls, fail=0, gate=None, status=None):
    def get(url, headers=None, **kw):
        calls.append(dict(headers or {}))
        if status:
            return FakeResp(status)
        if len(calls) <= fail:
            raise requests.ConnectionError("boom")
        start = int((headers or {}).get("Range", "bytes=0-")[6:-1] or 0)
        body = BLOB[start:]
        return FakeResp(206 if start else 200, body, {"Content-Length": str(len(body))}, gate)
    return get


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(dl, "RETRY_DELAYS", (0, 0, 0))


def test_http_download_checksum_and_state(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", fake_get(calls))
    d = dl.Downloads("t", state_path=tmp_path / "s.json")
    d.file("f1", "File", "http://x/f", tmp_path / "out.bin", sha256=hashlib.sha256(BLOB).hexdigest())
    job = d.wait("f1", 10)
    assert job["state"] == "fatto" and job["done"] == len(BLOB)
    assert (tmp_path / "out.bin").read_bytes() == BLOB
    assert not (tmp_path / "out.bin.part").exists()
    assert "params" not in d.list()[0]


def test_retries_then_succeeds(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", fake_get(calls, fail=2))
    d = dl.Downloads("t")
    d.file("f", "File", "http://x/f", tmp_path / "o")
    assert d.wait("f", 10)["state"] == "fatto"
    assert len(calls) == 3


def test_gated_file_is_final_error(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", fake_get(calls, status=403))
    d = dl.Downloads("t")
    d.file("f", "File", "http://x/f", tmp_path / "o")
    job = d.wait("f", 10)
    assert job["state"] == "errore" and "token" in job["error"] and len(calls) == 1


def test_resume_uses_range(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", fake_get(calls))
    (tmp_path / "o.part").write_bytes(BLOB[:1000])
    d = dl.Downloads("t")
    d.file("f", "File", "http://x/f", tmp_path / "o")
    assert d.wait("f", 10)["state"] == "fatto"
    assert calls[0]["Range"] == "bytes=1000-"
    assert (tmp_path / "o").read_bytes() == BLOB


def test_pause_then_resume(tmp_path, monkeypatch):
    calls, gate = [], threading.Event()
    monkeypatch.setattr(requests, "get", fake_get(calls, gate=gate))
    d = dl.Downloads("t")
    d.file("f", "File", "http://x/f", tmp_path / "o")
    for _ in range(100):
        if d.get("f")["state"] == "in_corso":
            break
        threading.Event().wait(0.02)
    assert d.pause("f")["state"] == "in_pausa"
    gate.set()
    assert d.wait("f", 10)["state"] == "in_pausa"
    d.resume("f")
    assert d.wait("f", 10)["state"] == "fatto"
    assert (tmp_path / "o").read_bytes() == BLOB


def test_no_space_refused_before_start(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", fake_get(calls))
    monkeypatch.setattr(dl.shutil, "disk_usage", lambda p: type("U", (), {"free": 10})())
    d = dl.Downloads("t")
    d.file("f", "File", "http://x/f", tmp_path / "o")
    job = d.wait("f", 10)
    assert job["state"] == "errore" and "libera spazio" in job["error"]


def test_custom_source_and_restart_comes_back_paused(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def run(job):
        job.progress(5, 10)
        started.set()
        release.wait(5)
        job.check()
        job.progress(10)

    d = dl.Downloads("t", state_path=tmp_path / "s.json")
    d.source("fake", run)
    d.add("m", "Modello", "fake", {"model": "x"}, size_hint=10)
    assert started.wait(5)
    assert d.get("m")["done"] == 5
    again = dl.Downloads("t", state_path=tmp_path / "s.json")      # a restart while it runs
    assert again.get("m")["state"] == "in_pausa"
    release.set()
    assert d.wait("m", 5)["state"] == "fatto"


def test_add_is_idempotent_and_remove(tmp_path):
    removed = []
    d = dl.Downloads("t")
    d.source("fake", lambda job: None, remove=lambda job: removed.append(job.id))
    d.add("m", "M", "fake")
    assert d.wait("m", 5)["state"] == "fatto"
    assert d.add("m", "M", "fake")["state"] == "fatto"
    d.remove("m")
    assert removed == ["m"] and d.get("m") is None


def test_router(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    d = dl.Downloads("t")
    d.source("fake", lambda job: None)
    d.add("ollama:qwen3:8b", "qwen3:8b", "fake")
    d.wait("ollama:qwen3:8b", 5)
    app = FastAPI()
    app.include_router(d.router())
    c = TestClient(app)
    assert c.get("/api/downloads").json()["downloads"][0]["id"] == "ollama:qwen3:8b"
    assert c.post("/api/downloads/ollama:qwen3:8b/retry").json()["state"] == "fatto"
    assert c.post("/api/downloads/nope/pause").status_code == 404
    assert c.post("/api/downloads/ollama:qwen3:8b/explode").status_code == 404
    assert c.post("/api/downloads/ollama:qwen3:8b/remove").json()["removed"] is True
