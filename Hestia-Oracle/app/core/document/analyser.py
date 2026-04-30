"""User-facing document analysis: streaming response + background archiving.

Single responsibility: given raw file bytes, generate an NDJSON streaming
response answering the user's question, then asynchronously archive the
document for future RAG retrieval.

This module composes:
  - Extractor: local text extraction fallback
  - LocalModels: offline audio transcription
  - DocumentArchiver: background persistence
  - stream_emitter: NDJSON event formatting
"""
import logging
import os
import threading
import uuid
from typing import Generator, Callable

from core.services import stream_emitter
from core.document import capabilities, local_models
from core.document.archiver import DocumentArchiver
from core.document.extractor import extract_text
from core.services.hub_client import HubClient

logger = logging.getLogger(f"hestia_oracle.{__name__}")

_MAX_DOC_ARCHIVE_BYTES = int(
    os.getenv("DOC_MAX_ARCHIVE_BYTES", str(10 * 1024 * 1024)))  # 10 MB


class DocumentAnalyser:
    """Stream an answer about an uploaded file, then archive it for RAG."""

    def __init__(
        self,
        hub_client: HubClient,
        archiver: DocumentArchiver,
        analyst,
        fallback_analyst,
        style_contract_fn: Callable[[], str],
    ) -> None:
        self._hub = hub_client
        self._archiver = archiver
        self._analyst = analyst
        self._fallback = fallback_analyst
        self._style_contract = style_contract_fn

    # ── Public API ────────────────────────────────────────────────────────────

    def analyse(
        self,
        file_bytes: bytes,
        mime_type: str,
        user_message: str,
        session_id: str,
        notify_target: str | None = None,
        client_instructions: str | None = None,
        filename: str | None = None,
        analyst_model_name: str = "",
    ) -> Generator[str, None, None]:
        """Yield NDJSON lines: status updates, a final answer, and a signal event."""
        is_audio = mime_type.startswith("audio/")
        is_video = mime_type.startswith("video/")
        model_has_audio = capabilities.model_supports_audio(analyst_model_name)
        needs_local_audio = (is_audio or is_video) and not model_has_audio

        if is_audio or is_video:
            yield stream_emitter.emit_status("🎙️ Trascrizione audio in corso...")
        else:
            yield stream_emitter.emit_status("📄 Analisi documento in corso...")

        full_prompt = (
            f"{self._style_contract()}\n\n"
            f"The user has attached a file and is asking the following:\n"
            f"{user_message}"
        )
        if client_instructions and str(client_instructions).strip():
            full_prompt += f"\n\nCLIENT_INSTRUCTIONS:\n{str(client_instructions).strip()}"

        final_answer = ""

        if needs_local_audio:
            final_answer = yield from self._answer_via_transcript(
                file_bytes, mime_type, user_message, client_instructions
            )
        else:
            final_answer = self._answer_via_llm(
                file_bytes, mime_type, full_prompt)

        # Persist chat turn
        self._save_history(session_id, filename or mime_type,
                           user_message, final_answer)

        # Archive document in background
        document_id = uuid.uuid4().hex
        if len(file_bytes) <= _MAX_DOC_ARCHIVE_BYTES:
            threading.Thread(
                target=self._archiver.archive,
                args=(file_bytes, mime_type, final_answer, document_id,
                      session_id, notify_target, filename, analyst_model_name),
                daemon=True,
            ).start()
            yield stream_emitter.emit_signal(
                event="document_saved",
                message="📎 Documento salvato nell'archivio.",
                data={
                    "document_id": document_id,
                    "filename": filename,
                    "mime_type": mime_type,
                    "file_size_bytes": len(file_bytes),
                },
            )
        else:
            logger.info(
                "event=analyser_file_too_large_archive [ANALYSER] File too large to archive (%s bytes > %s limit).",
                len(file_bytes), _MAX_DOC_ARCHIVE_BYTES,
            )

        yield stream_emitter.emit_final(final_answer, "document")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _answer_via_transcript(
        self,
        file_bytes: bytes,
        mime_type: str,
        user_message: str,
        client_instructions: str | None,
    ) -> Generator[str, None, str]:
        """Transcribe audio locally then answer via text LLM. Yields status lines."""
        yield stream_emitter.emit_status("🔊 Trascrizione con WhisperX...")
        transcript = local_models.transcribe_audio(file_bytes, mime_type)
        if not transcript:
            return "⚠️ Non riesco a trascrivere l'audio. Prova a inviare un file in un formato supportato (mp3, wav, ogg, m4a)."

        text_prompt = (
            f"{self._style_contract()}\n\n"
            f"The user sent an audio/video file. Here is its transcript:\n"
            f"---\n{transcript[:6000]}\n---\n\n"
            f"User's question: {user_message}"
        )
        if client_instructions and str(client_instructions).strip():
            text_prompt += f"\n\nCLIENT_INSTRUCTIONS:\n{str(client_instructions).strip()}"

        yield stream_emitter.emit_status("🤖 Analisi trascrizione...")
        try:
            return self._analyst.ask(text_prompt)
        except Exception:
            try:
                return self._fallback.ask(text_prompt)
            except Exception:
                return f"📝 Trascrizione:\n\n{transcript[:2000]}"

    def _answer_via_llm(self, file_bytes: bytes, mime_type: str, full_prompt: str) -> str:
        """Send file to analyst (then fallback, then local-text last resort)."""
        try:
            return self._analyst.ask_with_attachment(
                file_bytes=file_bytes, mime_type=mime_type, user_message=full_prompt
            )
        except Exception as exc1:
            logger.warning("event=analyser_primary_analyst_failed [ANALYSER] Primary analyst failed: %s", exc1)

        try:
            return self._fallback.ask_with_attachment(
                file_bytes=file_bytes, mime_type=mime_type, user_message=full_prompt
            )
        except Exception as exc2:
            logger.warning("event=analyser_fallback_analyst_failed [ANALYSER] Fallback analyst failed: %s", exc2)

        # Last resort: extract text locally and ask text-only
        local_text = extract_text(file_bytes, mime_type)
        if local_text:
            fallback_prompt = (
                f"{self._style_contract()}\n\n"
                f"Document content:\n---\n{local_text[:6000]}\n---\n\n"
                f"User question: {full_prompt}"
            )
            try:
                return self._analyst.ask(fallback_prompt)
            except Exception:
                pass

        return "⚠️ Non riesco ad analizzare il documento in questo momento."

    def _save_history(self, session_id: str, file_label: str, user_message: str, answer: str) -> None:
        try:
            self._hub.post("/chat/history", {
                "session_id": session_id,
                "role": "user",
                "content": f"[File: {file_label}] {user_message}",
            })
            self._hub.post("/chat/history", {
                "session_id": session_id,
                "role": "assistant",
                "content": answer,
            })
        except Exception as exc:
            logger.warning("event=analyser_failed_persist_history [ANALYSER] Failed to persist history: %s", exc)
