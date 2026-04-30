"""Document-aware RAG helpers for prompt injection.

Single responsibility: retrieve archived document chunks semantically
relevant to a user query and format them for the analyst prompt.

Open/Closed: new retrieval strategies (e.g. BM25 hybrid) can be added
as additional public methods without changing existing ones.
"""
import json
import logging
import os
from typing import Callable

import requests

from core.services.hub_client import HubClient

logger = logging.getLogger(f"hestia_oracle.{__name__}")

_DOC_SEARCH_THRESHOLD = float(os.getenv("DOC_SEARCH_THRESHOLD", "1.2"))

# Keywords that indicate the user is asking about their stored documents
_DOC_AWARENESS_KEYWORDS: frozenset[str] = frozenset([
    "document", "documents", "documento", "documenti",
    "file", "files",
    "pdf", "attachment", "allegato",
    "saved", "salvato", "salvati", "archiviato", "archiviati",
    "uploaded", "caricato", "caricati",
    "hai", "have", "know about", "remember",
])


class DocumentRAG:
    """Semantic retrieval and catalogue helpers for archived documents."""

    def __init__(self, hub_client: HubClient, embed_fn: Callable[[str], list[float]]) -> None:
        self._hub = hub_client
        self._embed = embed_fn

    # ── Public API ────────────────────────────────────────────────────────────

    def search_relevant_chunks(
        self,
        user_message: str,
        chat_id: str | None,
        session_id: str | None,
        limit: int = 4,
    ) -> list[dict]:
        """Return semantically matching document chunks for *user_message*."""
        query_vector = self._embed(user_message)
        if not query_vector:
            return []
        try:
            body = {
                "query_vector": query_vector,
                "chat_id": chat_id,
                "session_id": session_id,
                "limit": limit,
                "threshold": _DOC_SEARCH_THRESHOLD,
            }
            routed = self._hub.post("/documents/search", body, timeout=8)
            payload = routed.get("payload") if isinstance(
                routed, dict) else routed
            if isinstance(payload, list):
                return payload
        except Exception as exc:
            logger.debug("event=rag_chunk_search_failed_non [RAG] Chunk search failed (non-fatal): %s", exc)
        return []

    def list_user_docs_brief(
        self, chat_id: str | None, session_id: str | None, limit: int = 10
    ) -> str:
        """Return a compact catalogue of the user's archived documents for prompt injection."""
        try:
            query: dict = {"limit": str(limit)}
            if chat_id:
                query["chat_id"] = str(chat_id)
            elif session_id:
                query["session_id"] = str(session_id)

            docs: list[dict] = self._hub.get(
                f"/documents?{'&'.join(f'{k}={v}' for k, v in query.items())}") or []
            if not docs:
                return ""

            lines = [f"📎 USER'S ARCHIVED DOCUMENTS ({len(docs)} stored):"]
            for doc in docs:
                title = doc.get("title") or doc.get("filename") or "Untitled"
                domain = doc.get("domain", "documents")
                perm = "📌 permanent" if doc.get(
                    "is_permanent") else "temporary"
                accessed = doc.get("access_count", 0)
                tag_str = self._format_tags(doc.get("tags"))
                lines.append(
                    f"  • {title}{tag_str} — domain:{domain}, {perm}, accessed {accessed}×")
            return "\n".join(lines)
        except Exception as exc:
            logger.debug("event=rag_brief_doc_list_failed [RAG] Brief doc list failed (non-fatal): %s", exc)
            return ""

    @staticmethod
    def format_chunks_for_prompt(chunks: list[dict]) -> str:
        """Format retrieved chunks into a labelled prompt section."""
        if not chunks:
            return ""
        lines = ["📎 RELEVANT ARCHIVED DOCUMENT PASSAGES:"]
        seen: dict[str, str] = {}
        for chunk in chunks:
            doc_id = chunk.get("document_id", "?")
            title = chunk.get("title") or chunk.get(
                "filename") or "Untitled document"
            if doc_id not in seen:
                seen[doc_id] = title
                lines.append(f"\n[{title}]")
            lines.append(f"  …{chunk.get('chunk_text', '')}…")
        return "\n".join(lines)

    def message_is_about_docs(self, message: str) -> bool:
        """Heuristic: return True if *message* likely asks about stored documents."""
        lower = message.lower()
        return any(kw in lower for kw in _DOC_AWARENESS_KEYWORDS)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _format_tags(tags_raw) -> str:
        if not tags_raw:
            return ""
        try:
            tag_list = json.loads(tags_raw) if isinstance(
                tags_raw, str) else tags_raw
            if isinstance(tag_list, list):
                return f" [{', '.join(str(t) for t in tag_list[:4])}]"
        except Exception:
            pass
        return ""
