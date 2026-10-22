"""Audio inside documents → text, asked to the voice module Echo (Oracle only calls LLMs).

Dossier ``docs/work/2026-10-20-modulo-voce`` §7: Whisper left Oracle. Echo runs its listening chain for the use
``oracle.documenti`` (declared in Oracle's Hub registration, suggested chain ``ascolto-preciso``); Marko chooses
the chain in the «Voce» page. Empty string = Echo unreachable or nothing heard: the caller falls back to a model
that hears audio natively, if the document chain has one.
"""
import logging
import os

from hestia_common.voice_client import VoiceClient
from hestia_common.voice_usecases import capabilities as voice_capabilities, usecase as voice_usecase

logger = logging.getLogger(f"hestia_oracle.{__name__}")

USE_CASE = "oracle.documenti"
VOICE_USECASES = [voice_usecase(USE_CASE, "Oracle · audio nei documenti", direction="ascolto",
                                chain="ascolto-preciso",
                                help="Audio e video mandati in chat o caricati nei Documenti.")]

_client: VoiceClient | None = None


def capabilities() -> dict:
    """Keys for Oracle's Hub registration."""
    return voice_capabilities(VOICE_USECASES)


def transcribe_audio(file_bytes: bytes, mime_type: str) -> str:
    """Transcript of an audio file (or a video's audio track); ``""`` when Echo cannot."""
    global _client
    if _client is None:
        _client = VoiceClient(os.getenv("HUB_API_URL", "http://hestia_hub:19001/api"))
    heard = _client.transcribe(file_bytes, mime_type, use_case=USE_CASE, timeout=600)
    if not heard:
        logger.warning("[🔄] event=document_transcription_unavailable mime=%s fallback=audio_model", mime_type)
        return ""
    logger.info("event=document_transcribed provider=%s seconds=%s", heard.get("provider"), heard.get("duration_s"))
    return str(heard["text"])
