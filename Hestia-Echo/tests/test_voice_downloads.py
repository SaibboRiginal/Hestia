"""Voice models through hestia_common.downloads (docs/work/2026-10-30-setup-un-click §4.3). No network."""
from __future__ import annotations

import pytest

from app.core import standards
from hestia_common.downloads import Downloads

pytestmark = pytest.mark.unit


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(standards, "MODELS_DIR", tmp_path)
    d = Downloads("echo")
    fetched = []

    def fake_http(job):
        fetched.append(job.params["url"])
        from pathlib import Path
        Path(job.params["dest"]).parent.mkdir(parents=True, exist_ok=True)
        Path(job.params["dest"]).write_bytes(b"x")

    d.source("http", fake_http)
    d.source("whisper", lambda job: fetched.append("whisper:" + job.params["size"]))
    monkeypatch.setattr(standards, "DOWNLOADS", d)
    return d, fetched


def test_piper_voice_downloads_through_the_manager(manager, tmp_path):
    d, fetched = manager
    path = standards.Piper()._download("it_IT-paola-medium")
    assert path == tmp_path / "piper" / "it_IT-paola-medium.onnx" and path.exists()
    assert {j["id"] for j in d.list()} == {"piper:it_IT-paola-medium.onnx", "piper:it_IT-paola-medium.onnx.json"}
    assert all("rhasspy/piper-voices" in u for u in fetched)


def test_fetch_skips_existing_file(manager, tmp_path):
    d, fetched = manager
    (tmp_path / "f").write_bytes(b"y")
    assert standards.fetch("x", "X", "http://x", tmp_path / "f") == tmp_path / "f"
    assert fetched == [] and d.list() == []


def test_prefetch_by_provider_type(manager):
    d, _ = manager
    assert standards.prefetch("whisper_local", "small") == ["whisper:small"]
    assert len(standards.prefetch("kokoro")) == 2
    assert standards.prefetch("openai") == []
    whisper = d.get("whisper:small")
    assert whisper["size"] == 484_000_000
