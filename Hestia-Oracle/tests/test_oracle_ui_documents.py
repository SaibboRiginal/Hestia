"""Documenti page (Oracle WebUI plugin, SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4):
/api/ui/documents list · search · add (background archiving) · permanent · delete, all through Hub → Archive."""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.services import ui_documents


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


DOC = {"document_id": "d1", "filename": "contratto.pdf", "title": "Contratto", "mime_type": "application/pdf",
       "domain": "documents", "tags": '["casa", "affitto"]', "is_permanent": False, "chunk_count": 4,
       "created_at": "2026-10-01T10:00:00Z"}


@pytest.mark.unit
def test_accepted_mimes():
    assert ui_documents.accepted("application/pdf") and ui_documents.accepted("image/png")
    assert ui_documents.accepted("text/markdown") and not ui_documents.accepted("application/x-msdownload")


@pytest.mark.api
class TestDocumentsPage:
    def test_manifest_has_documenti_page(self, main_mod):
        m = TestClient(main_mod.app).get("/api/ui/manifest").json()
        ids = {p["id"]: p for p in m["clients"]["webui"]["page"]}
        assert ids["documenti"]["element"] == "oracle-documents" and ids["documenti"]["order"] == 121

    def test_list_reads_archive_through_hub(self, rig):
        c, engine = rig
        engine._hub.route_to_service.return_value = (True, [DOC])
        body = c.get("/api/ui/documents", params={"domain": "documents", "permanent": "true"}).json()
        assert body["count"] == 1 and body["documents"][0]["tags"] == ["casa", "affitto"]
        assert body["domains"] == ["documents"]
        args, kwargs = engine._hub.route_to_service.call_args
        assert args[:3] == ("archive", "api/documents", "GET")
        assert kwargs["query"] == {"limit": "100", "domain": "documents", "is_permanent": "true"}

    def test_archive_down_is_502(self, rig):
        c, engine = rig
        engine._hub.route_to_service.return_value = (False, "Hub unreachable")
        assert c.get("/api/ui/documents").status_code == 502

    def test_search_uses_chat_rag(self, rig):
        c, engine = rig
        engine._doc_rag.search_relevant_chunks.return_value = [{"document_id": "d1", "chunk_text": "scade il 3"}]
        body = c.get("/api/ui/documents/search", params={"query": "scadenza"}).json()
        assert body["count"] == 1 and body["chunks"][0]["chunk_text"] == "scade il 3"
        engine._doc_rag.search_relevant_chunks.assert_called_once_with("scadenza", None, None, limit=8)
        assert c.get("/api/ui/documents/search", params={"query": " "}).status_code == 400

    def test_add_starts_archiving(self, rig):
        c, engine = rig
        data = base64.b64encode(b"ciao mondo").decode()
        with patch("core.services.ui_documents.threading.Thread") as thread:
            r = c.post("/api/ui/documents", json={"name": "nota.txt", "mime": "text/plain", "data_b64": data})
        assert r.status_code == 200 and r.json()["status"] == "ingesting" and r.json()["file_size_bytes"] == 10
        kwargs = thread.call_args.kwargs
        assert kwargs["target"] is engine._archiver.archive
        assert kwargs["args"][0] == b"ciao mondo" and kwargs["args"][1] == "text/plain"
        assert kwargs["args"][4] == ui_documents.SESSION and kwargs["args"][6] == "nota.txt"
        thread.return_value.start.assert_called_once()

    def test_add_refuses_bad_files(self, rig, main_mod):
        c, _ = rig
        ok = base64.b64encode(b"x").decode()
        assert c.post("/api/ui/documents", json={"name": "a.exe", "mime": "application/x-msdownload",
                                                 "data_b64": ok}).status_code == 415
        assert c.post("/api/ui/documents", json={"name": "a.txt", "mime": "text/plain", "data_b64": ""}).status_code == 400
        with patch.object(main_mod._oracle_settings, "get_int", return_value=0):
            assert c.post("/api/ui/documents", json={"name": "a.txt", "mime": "text/plain",
                                                     "data_b64": ok}).status_code == 413

    def test_permanent_and_delete(self, rig):
        c, engine = rig
        engine._hub.route_to_service.return_value = (True, {"document_id": "d1", "is_permanent": True})
        assert c.patch("/api/ui/documents/d1/permanent", json={"is_permanent": True}).json()["is_permanent"] is True
        args, kwargs = engine._hub.route_to_service.call_args
        assert args[:3] == ("archive", "api/documents/d1/permanent", "PATCH") and kwargs["body"] == {"is_permanent": True}
        engine._hub.route_to_service.return_value = (True, {"status": "deleted"})
        assert c.delete("/api/ui/documents/d1").json() == {"status": "deleted", "document_id": "d1"}
        engine._hub.route_to_service.return_value = (False, {"detail": "Document not found"})
        assert c.delete("/api/ui/documents/zz").status_code == 404
