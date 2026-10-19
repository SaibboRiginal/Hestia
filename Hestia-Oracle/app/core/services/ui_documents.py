"""Documenti page (Oracle WebUI plugin): the documents Hestia keeps for RAG — list, search, add, keep, delete.

Thin layer over what Oracle already does: documents live in Archive (reached through Hub), search is the same
semantic search the chat uses (``DocumentRAG``), adding a file runs the same archiving pipeline as a chat
attachment (``DocumentArchiver``: extract → chunk → embed → Archive), without a chat turn.
SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import threading
import uuid
from typing import Any

logger = logging.getLogger("hestia_oracle.ui_documents")

SESSION = "webui-documenti"   # Archive needs a session id: documents added from the page share this one
_ACCEPTED_PREFIXES = ("image/", "audio/", "video/", "text/")
_ACCEPTED = {
    "application/pdf", "application/json", "application/xml", "application/yaml", "application/x-yaml",
    "application/msword", "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.presentation",
}


class DocumentError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def accepted(mime: str) -> bool:
    return mime.startswith(_ACCEPTED_PREFIXES) or mime in _ACCEPTED


def _archive(engine, method: str, path: str, body: dict | None = None, query: dict | None = None,
             timeout: int = 10) -> Any:
    ok, payload = engine._hub.route_to_service("archive", path, method, body=body, query=query, timeout=timeout)
    if not ok:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        status = 404 if "not found" in str(detail).lower() else 502
        raise DocumentError(status, str(detail or "Archive non raggiungibile"))
    return payload


def _row(d: dict) -> dict:
    tags = d.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = [tags]
    return {"document_id": d.get("document_id") or d.get("id"), "filename": d.get("filename"),
            "title": d.get("title"), "summary": d.get("summary"), "mime_type": d.get("mime_type"),
            "file_size_bytes": d.get("file_size_bytes"), "domain": d.get("domain") or "documents",
            "tags": tags if isinstance(tags, list) else [], "is_permanent": bool(d.get("is_permanent")),
            "chunk_count": d.get("chunk_count") or 0, "access_count": d.get("access_count") or 0,
            "created_at": d.get("created_at"), "last_accessed_at": d.get("last_accessed_at")}


def list_documents(engine, limit: int = 100, domain: str = "", permanent: bool | None = None) -> dict:
    query: dict = {"limit": str(max(1, min(int(limit or 100), 200)))}
    if domain:
        query["domain"] = domain
    if permanent is not None:
        query["is_permanent"] = "true" if permanent else "false"
    rows = _archive(engine, "GET", "api/documents", query=query) or []
    docs = [_row(d) for d in rows if isinstance(d, dict)]
    return {"status": "ok", "count": len(docs), "documents": docs,
            "domains": sorted({d["domain"] for d in docs})}


def search(engine, query: str, limit: int = 8) -> dict:
    q = (query or "").strip()
    if not q:
        raise DocumentError(400, "query required")
    chunks = engine._doc_rag.search_relevant_chunks(q, None, None, limit=max(1, min(int(limit or 8), 20))) or []
    return {"status": "ok", "query": q, "count": len(chunks), "chunks": chunks}


def delete(engine, document_id: str) -> dict:
    _archive(engine, "DELETE", f"api/documents/{document_id}")
    logger.info("event=ui_document_deleted id=%s", document_id)
    return {"status": "deleted", "document_id": document_id}


def set_permanent(engine, document_id: str, permanent: bool) -> dict:
    out = _archive(engine, "PATCH", f"api/documents/{document_id}/permanent", body={"is_permanent": bool(permanent)})
    logger.info("event=ui_document_permanent id=%s permanent=%s", document_id, bool(permanent))
    return {"status": "ok", **(out if isinstance(out, dict) else {"document_id": document_id})}


def ingest(engine, name: str, mime: str, data_b64: str, max_bytes: int) -> dict:
    """Start archiving one file (background, like a chat attachment). The document appears in the list when done."""
    mime = (mime or "application/octet-stream").split(";")[0].strip().lower()
    if not accepted(mime):
        raise DocumentError(415, f"Tipo di file non supportato: {mime}")
    raw = data_b64.split(",", 1)[1] if data_b64.startswith("data:") and "," in data_b64 else data_b64
    try:
        file_bytes = base64.b64decode(raw or "", validate=False)
    except (binascii.Error, ValueError):
        raise DocumentError(400, "data_b64 non è base64 valido")
    if not file_bytes:
        raise DocumentError(400, "file vuoto")
    if len(file_bytes) > max_bytes:
        raise DocumentError(413, f"File troppo grande: massimo {max_bytes // (1024 * 1024)} MB")
    document_id = uuid.uuid4().hex
    model = getattr(getattr(engine, "_agents", None), "generic_model_name", "") or ""
    threading.Thread(target=engine._archiver.archive,
                     args=(file_bytes, mime, "", document_id, SESSION, None, name or None, model),
                     daemon=True).start()
    logger.info("event=ui_document_ingest_started id=%s mime=%s size=%d", document_id, mime, len(file_bytes))
    return {"status": "ingesting", "document_id": document_id, "filename": name, "mime_type": mime,
            "file_size_bytes": len(file_bytes)}
