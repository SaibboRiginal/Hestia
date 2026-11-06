"""Built datasets survive a restart: saved under METIS_DATA_DIR/datasets and read back on first use
(docs/work/2026-10-30-cose-aperte)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.mark.unit
def test_dataset_is_read_back_after_restart(tmp_path, monkeypatch):
    from app.core import dataset_builder as db

    monkeypatch.setenv("METIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "_datasets", {})
    monkeypatch.setattr(db, "_loaded", True)
    db._datasets["prova 1/a"] = {"metadata": {"name": "prova 1/a", "total_kept": 1},
                                 "examples": [{"user": "ciao", "assistant": "ciao!"}]}
    db._save("prova 1/a")
    assert (tmp_path / "datasets" / "prova_1_a.json").exists()

    # a fresh process: empty memory, nothing loaded yet
    monkeypatch.setattr(db, "_datasets", {})
    monkeypatch.setattr(db, "_loaded", False)
    (tmp_path / "datasets" / "broken.json").write_text("{not json", encoding="utf-8")
    assert db.get_dataset_examples("prova 1/a") == [{"user": "ciao", "assistant": "ciao!"}]
    assert [d["name"] for d in db.get_dataset_status()["datasets"]] == ["prova 1/a"]
