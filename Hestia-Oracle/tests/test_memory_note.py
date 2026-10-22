"""memory_note / memory_recall / Memoria page (SPEC docs/work/2026-10-20-memory-note).

External AIs hand Hestia distilled facts; Oracle saves them as durable preferences with their origin, skips
duplicates, never calls an LLM. Archive is mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.services.memory_service import MEMORY_CLASS_PREFERENCE, NOTE_MAX_FACTS, MemoryService, fact_key


def _svc(existing=None):
    scribe = MagicMock()
    svc = MemoryService(archive_url="", hub_api_url="http://hub", scribe_agent=scribe, context_builder=MagicMock())
    svc._get_active_memory = MagicMock(return_value=existing or [])
    svc._route_archive = MagicMock(return_value={"id": 1})
    return svc, scribe


def _bodies(svc):
    return [c.kwargs["body"] for c in svc._route_archive.call_args_list if c.args[:2] == ("POST", "/memory")]


@pytest.mark.unit
class TestSaveNote:
    def test_lines_saved_with_external_origin(self):
        svc, scribe = _svc()
        ok, out = svc.save_note("- Va in palestra il martedì\n\n• Non mangia latticini", topic="dieta", access="Claude")
        assert ok and [s["fact"] for s in out["saved"]] == ["Va in palestra il martedì", "Non mangia latticini"]
        body = _bodies(svc)[0]
        assert body["memory_class"] == MEMORY_CLASS_PREFERENCE and body["domains"] == ["general"]
        assert body["extra_data"]["source"] == "external" and body["extra_data"]["access"] == "Claude"
        assert body["extra_data"]["topic"] == "dieta" and body["extra_data"]["noted_at"]
        scribe.ask.assert_not_called()   # no LLM: works with the local model down

    def test_list_input_and_no_access_is_chat(self):
        svc, _ = _svc()
        ok, _out = svc.save_note(["Ama il caffè"])
        assert ok and _bodies(svc)[0]["extra_data"]["source"] == "chat"

    def test_duplicates_skipped(self):
        svc, _ = _svc(existing=[{"id": 7, "fact": "Non mangia latticini."}])
        ok, out = svc.save_note("non mangia LATTICINI\nNon mangia latticini\nVive a Trieste")
        assert ok and out["skipped"] == [{"fact": "non mangia LATTICINI", "existing_id": 7}, {"fact": "Non mangia latticini", "existing_id": 7}]
        assert [b["fact"] for b in _bodies(svc)] == ["Vive a Trieste"]

    def test_domains_from_classifier(self):
        svc, _ = _svc()
        svc.pref_domain_classifier = MagicMock(classify=MagicMock(return_value=["fitness", "calendar"]))
        svc.save_note("Palestra il martedì")
        body = _bodies(svc)[0]
        assert body["domain"] == "fitness" and body["domains"] == ["fitness", "calendar"]

    @pytest.mark.parametrize("facts,why", [("", "No facts"), ("\n".join(f"f{i}" for i in range(NOTE_MAX_FACTS + 1)), "Too many"),
                                           ("x" * 301, "at most")])
    def test_rejected(self, facts, why):
        svc, _ = _svc()
        ok, msg = svc.save_note(facts)
        assert not ok and why in msg and not _bodies(svc)

    def test_archive_failure_reported(self):
        svc, _ = _svc()
        svc._route_archive.return_value = None
        ok, msg = svc.save_note("Uno")
        assert not ok and "Archive" in msg

    def test_fact_key(self):
        assert fact_key("  Ciao, Mondo! ") == fact_key("ciao mondo")


@pytest.mark.unit
class TestRecallListForget:
    def test_recall_compact_rows(self):
        svc, _ = _svc(existing=[{"id": 1, "fact": "Va in palestra il martedì", "domains": ["fitness"],
                                 "created_at": "2026-10-20T10:00:00Z", "embedding": [0.1]}])
        ok, rows = svc.recall("palestra")
        assert ok and rows == [{"fact": "Va in palestra il martedì", "domains": ["fitness"], "since": "2026-10-20"}]

    def test_list_origin(self):
        svc, _ = _svc(existing=[{"id": 1, "fact": "a", "domain": "general"},
                                {"id": 2, "fact": "b", "domains": ["x"], "extra_data": {"source": "external", "access": "ChatGPT", "topic": "t"}}])
        rows = svc.list_memories()
        assert rows[0]["source"] == "chat" and rows[0]["domains"] == ["general"]
        assert rows[1]["source"] == "external" and rows[1]["access"] == "ChatGPT" and rows[1]["topic"] == "t"

    def test_forget_deactivates(self):
        svc, _ = _svc()
        assert svc.forget(5)
        svc._route_archive.assert_called_with("PATCH", "/memory/5", body={"is_active": False})

    def test_save_memory_marks_chat_origin(self):
        svc, _ = _svc()
        svc.save_memory("Ama il mare")
        assert _bodies(svc)[0]["extra_data"] == {"source": "chat"}


@pytest.fixture(scope="module")
def main_mod():
    with patch("core.oracle_engine.OracleEngine", return_value=MagicMock()), patch("requests.post"):
        import main  # noqa: PLC0415
        yield main


@pytest.fixture
def rig(main_mod):
    engine = MagicMock()
    with patch.object(main_mod, "engine", engine):
        yield TestClient(main_mod.app), engine


@pytest.mark.api
class TestMemoryNoteApi:
    def test_note_passes_access_header(self, rig):
        c, engine = rig
        engine._memory_service.save_note.return_value = (True, {"saved": [{"fact": "a"}], "skipped": []})
        r = c.post("/api/memory/note", json={"facts": "a", "topic": "t"}, headers={"X-Hestia-Access": "Claude"})
        assert r.status_code == 200 and r.json()["saved"] == [{"fact": "a"}]
        engine._memory_service.save_note.assert_called_with(facts="a", topic="t", access="Claude")

    def test_note_invalid_is_422(self, rig):
        c, engine = rig
        engine._memory_service.save_note.return_value = (False, "No facts to save.")
        assert c.post("/api/memory/note", json={"facts": ""}).status_code == 422

    def test_recall(self, rig):
        c, engine = rig
        engine._memory_service.recall.return_value = (True, [{"fact": "a"}])
        assert c.get("/api/memory/recall", params={"query": "a"}).json() == {"count": 1, "memories": [{"fact": "a"}]}

    def test_ui_list_and_forget(self, rig):
        c, engine = rig
        engine._memory_service.list_memories.return_value = [{"id": 1}]
        assert c.get("/api/ui/memory").json() == {"memories": [{"id": 1}]}
        engine._memory_service.forget.return_value = True
        assert c.delete("/api/ui/memory/1").json()["status"] == "forgotten"
        engine._memory_service.forget.return_value = False
        assert c.delete("/api/ui/memory/1").status_code == 502

    def test_tools_visible_to_external(self, main_mod):
        tools = {t["name"]: t for t in TestClient(main_mod.app).post("/mcp", json={"method": "tools/list", "id": 1}).json()["result"]["tools"]}
        assert "external" in tools["memory_note"]["clients"] and tools["memory_note"]["method"] == "POST"
        assert tools["memory_note"]["path"] == "/api/memory/note" and "external" in tools["memory_recall"]["clients"]
        assert "external" not in (tools["memory.save"].get("clients") or [])

    def test_manifest_has_memoria_page(self, main_mod):
        m = TestClient(main_mod.app).get("/api/ui/manifest").json()
        ids = {p["id"]: p for p in m["clients"]["webui"]["page"]}
        assert ids["memoria"]["element"] == "oracle-memory" and ids["memoria"]["order"] == 122
