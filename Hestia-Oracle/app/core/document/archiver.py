"""Document archiving: text extraction, chunking, embedding, and persistence.

Single responsibility: given raw file bytes, orchestrate the full pipeline
(media-type branching → text/metadata extraction → chunking → embedding →
Archive upsert) in a background thread.

This class depends on:
  - HubClient: for Archive API access
  - embed_fn: callable (text → list[float])
  - analyst / fallback_analyst: UniversalAgent instances for LLM-assisted extraction
  - Extractor module: pure static text extractors
  - LocalModels module: CLIP/YOLO/WhisperX inference
  - Capabilities module: model capability flags
"""
import hashlib
import json
import logging
import os
from typing import Callable

from core.services.hub_client import HubClient
from core.document import capabilities, extractor as file_extractor, local_models

logger = logging.getLogger(__name__)

# ── Chunking constants ────────────────────────────────────────────────────────
_CHUNK_SIZE = 900
_CHUNK_OVERLAP = 150
_MAX_CHUNKS_PER_DOC = 120
_MAX_EXTRACTED_TEXT_CHARS = 40_000


def _chunk_text(text: str) -> list[str]:
    """Split *text* into overlapping fixed-size chunks for RAG retrieval."""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - _CHUNK_OVERLAP
    return chunks[:_MAX_CHUNKS_PER_DOC]


class DocumentArchiver:
    """Orchestrate the full document ingestion pipeline."""

    def __init__(
        self,
        hub_client: HubClient,
        embed_fn: Callable[[str], list[float]],
        analyst,
        fallback_analyst,
    ) -> None:
        self._hub = hub_client
        self._embed = embed_fn
        self._analyst = analyst
        self._fallback = fallback_analyst

    # ── Public API ────────────────────────────────────────────────────────────

    def archive(
        self,
        file_bytes: bytes,
        mime_type: str,
        final_answer: str,
        document_id: str,
        session_id: str,
        chat_id: str | None,
        filename: str | None,
        analyst_model_name: str,
    ) -> None:
        """Extract, chunk, embed, and persist a document to Archive.

        Intended to run in a daemon thread — logs failures but never raises.
        """
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        model_has_vision = capabilities.model_supports_vision(
            analyst_model_name)
        model_has_audio = capabilities.model_supports_audio(analyst_model_name)

        available_domains: list[str] = []
        try:
            available_domains = self._hub.get("/domains") or []
        except Exception:
            pass
        domains_hint = ", ".join(
            available_domains) if available_domains else "documents, general"

        # State collected during extraction
        extracted_text = ""
        title: str | None = None
        summary: str | None = None
        domain = "documents"
        tags: list[str] = []

        # ── Extraction routing ────────────────────────────────────────────────
        is_audio = mime_type.startswith("audio/")
        is_video = mime_type.startswith("video/")

        if is_audio or is_video:
            extracted_text, title, summary, domain, tags = self._extract_audio_video(
                file_bytes, mime_type, model_has_audio, domains_hint,
            )
        elif mime_type.startswith("image/"):
            extracted_text, title, summary, domain, tags = self._extract_image(
                file_bytes, mime_type, model_has_vision, domains_hint,
            )
        elif mime_type == "application/pdf":
            extracted_text, title, summary, domain, tags = self._extract_pdf(
                file_bytes, mime_type, model_has_vision, domains_hint,
            )
        else:
            # Office / text / unknown
            extracted_text = file_extractor.extract_text(file_bytes, mime_type)
            if extracted_text and not title:
                title, summary, domain, tags = self._enrich_metadata(
                    extracted_text, domains_hint,
                )

        # ── Fallback defaults ─────────────────────────────────────────────────
        if not extracted_text:
            extracted_text = final_answer
        if not summary:
            summary = (extracted_text[:400]
                       or final_answer[:400]).strip() or None
        if available_domains and domain not in available_domains:
            domain = "documents"

        # ── Chunking + embedding ──────────────────────────────────────────────
        extracted_text = extracted_text[:_MAX_EXTRACTED_TEXT_CHARS]
        chunks = _chunk_text(extracted_text)
        context_prefix = f"Document: {title or filename or 'Attachment'}\n{summary or ''}\n\n"

        embedded_chunks = []
        for i, chunk_text in enumerate(chunks):
            emb = self._embed(context_prefix + chunk_text)
            embedded_chunks.append({
                "chunk_index": i,
                "chunk_text": chunk_text,
                "embedding": emb or None,
            })

        doc_emb_text = f"{title or ''}\n{summary or ''}\n{extracted_text[:400]}".strip(
        )
        doc_embedding = self._embed(doc_emb_text) if doc_emb_text else []

        body = {
            "document_id": document_id,
            "session_id": session_id,
            "chat_id": chat_id,
            "filename": filename,
            "mime_type": mime_type,
            "file_size_bytes": len(file_bytes),
            "file_hash": file_hash,
            "title": title,
            "summary": summary,
            "extracted_text": extracted_text,
            "embedding": doc_embedding or None,
            "is_permanent": False,
            "domain": domain,
            "tags": json.dumps(tags) if tags else None,
            "chunks": embedded_chunks,
        }
        try:
            self._hub.post("/documents", body, timeout=60)
            logger.info(
                "[ARCHIVER] Saved | id=%s chunks=%s title=%r domain=%s tags=%s",
                document_id, len(embedded_chunks), title, domain, tags,
            )
        except Exception as exc:
            logger.warning("[ARCHIVER] Save failed: %s", exc)

    # ── Extraction branches ───────────────────────────────────────────────────

    def _extract_audio_video(
        self,
        file_bytes: bytes,
        mime_type: str,
        model_has_audio: bool,
        domains_hint: str,
    ) -> tuple[str, str | None, str | None, str, list[str]]:
        extracted_text = title = summary = None
        domain = "documents"
        tags: list[str] = []

        # WhisperX first (offline, accurate)
        transcribed = local_models.transcribe_audio(file_bytes, mime_type)

        if not transcribed and model_has_audio:
            prompt = self._extraction_prompt(
                "complete verbatim transcription of the audio/video", domains_hint
            )
            raw = self._llm_with_attachment(file_bytes, mime_type, prompt)
            if raw:
                data = self._parse_json(raw)
                if data:
                    extracted_text = data.get("text", "")
                    title = data.get("title")
                    summary = data.get("summary")
                    domain = str(data.get("domain", domain)).strip().lower()
                    tags = [str(t)
                            for t in (data.get("tags") or []) if str(t).strip()]

        if transcribed and not extracted_text:
            extracted_text = transcribed

        if extracted_text and not title:
            meta = self._enrich_metadata(extracted_text, domains_hint)
            title, summary, domain, tags = meta

        return extracted_text or "", title, summary, domain, tags

    def _extract_image(
        self,
        file_bytes: bytes,
        mime_type: str,
        model_has_vision: bool,
        domains_hint: str,
    ) -> tuple[str, str | None, str | None, str, list[str]]:
        extracted_text = title = summary = None
        domain = "documents"
        tags: list[str] = []

        try:
            local = local_models.analyze_image(file_bytes)
            tags = local["tags"]
            extracted_text = local["description"]
        except Exception as exc:
            logger.warning("[ARCHIVER] Local image analysis error: %s", exc)

        if model_has_vision:
            prompt = self._extraction_prompt(
                "complete visual description of the image", domains_hint)
            raw = self._llm_with_attachment(file_bytes, mime_type, prompt)
            if raw:
                data = self._parse_json(raw)
                if data:
                    llm_tags = [str(t) for t in (
                        data.get("tags") or []) if str(t).strip()]
                    merged = list(dict.fromkeys(llm_tags + tags))[:10]
                    data["tags"] = merged
                    extracted_text = data.get("text") or extracted_text
                    title = data.get("title")
                    summary = data.get("summary")
                    domain = str(data.get("domain", domain)).strip().lower()
                    tags = merged

        if not extracted_text and tags:
            extracted_text = "Image content: " + ", ".join(tags)

        return extracted_text or "", title, summary, domain, tags

    def _extract_pdf(
        self,
        file_bytes: bytes,
        mime_type: str,
        model_has_vision: bool,
        domains_hint: str,
    ) -> tuple[str, str | None, str | None, str, list[str]]:
        extracted_text = title = summary = None
        domain = "documents"
        tags: list[str] = []

        if model_has_vision:
            prompt = self._extraction_prompt(
                "complete verbatim text content of the PDF", domains_hint)
            raw = self._llm_with_attachment(file_bytes, mime_type, prompt)
            if raw:
                data = self._parse_json(raw)
                if data:
                    extracted_text = data.get("text")
                    title = data.get("title")
                    summary = data.get("summary")
                    domain = str(data.get("domain", domain)).strip().lower()
                    tags = [str(t)
                            for t in (data.get("tags") or []) if str(t).strip()]

        if not extracted_text:
            extracted_text = file_extractor.extract_text(
                file_bytes, "application/pdf")

        if extracted_text and not title:
            title, summary, domain, tags = self._enrich_metadata(
                extracted_text, domains_hint)

        return extracted_text or "", title, summary, domain, tags

    # ── LLM helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _extraction_prompt(text_field_hint: str, domains_hint: str) -> str:
        return (
            "Analyze this content thoroughly.\n"
            "Output ONLY valid JSON with exactly these keys:\n"
            '{"title": "<concise title, max 120 chars>", '
            '"summary": "<2-3 sentence summary, max 400 chars>", '
            f'"text": "<{text_field_hint}>", '
            f'"domain": "<best match from: {domains_hint}>", '
            '"tags": ["<kw1>", "<kw2>", "<kw3>"]}\n'
            "tags: 3-8 short keywords. No commentary. No markdown fences. Only JSON."
        )

    @staticmethod
    def _parse_json(raw: str) -> dict:
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s >= 0 and e > s:
            try:
                return json.loads(raw[s:e])
            except Exception:
                pass
        return {}

    def _llm_with_attachment(self, file_bytes: bytes, mime_type: str, prompt: str) -> str:
        """Call analyst (then fallback) with a file attachment. Returns raw text."""
        try:
            return self._analyst.ask_with_attachment(
                file_bytes=file_bytes, mime_type=mime_type, user_message=prompt
            )
        except Exception as exc1:
            logger.warning(
                "[ARCHIVER] Primary LLM attachment call failed: %s", exc1)
        try:
            return self._fallback.ask_with_attachment(
                file_bytes=file_bytes, mime_type=mime_type, user_message=prompt
            )
        except Exception as exc2:
            logger.warning(
                "[ARCHIVER] Fallback LLM attachment call failed: %s", exc2)
        return ""

    def _enrich_metadata(
        self, extracted_text: str, domains_hint: str
    ) -> tuple[str | None, str | None, str, list[str]]:
        """Ask a text-only LLM to produce title/summary/domain/tags for *extracted_text*."""
        meta_prompt = (
            "Given the following document content, produce only valid JSON:\n"
            f'{{"title": "...", "summary": "...", "domain": "<best match from: {domains_hint}>", "tags": [...]}}\n'
            "tags: 3-8 short keywords.\n"
            f"Content (first 2000 chars):\n{extracted_text[:2000]}"
        )
        try:
            raw = self._analyst.ask(meta_prompt)
            data = self._parse_json(raw)
            title = data.get("title") or None
            summary = data.get("summary") or None
            domain = str(data.get("domain", "documents")).strip().lower()
            tags = [str(t) for t in (data.get("tags") or []) if str(t).strip()]
            return title, summary, domain, tags
        except Exception as exc:
            logger.debug("[ARCHIVER] Metadata enrichment failed: %s", exc)
            return None, None, "documents", []
