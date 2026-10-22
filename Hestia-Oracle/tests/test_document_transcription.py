"""Audio in documents is transcribed by the voice module Echo (dossier 2026-10-20-modulo-voce §7): no Whisper in
Oracle, the use ``oracle.documenti`` is declared in the Hub registration, failures return "" (fallback upstream)."""
import pytest

from core.document import transcription

pytestmark = pytest.mark.unit


class FakeVoice:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def transcribe(self, data, mime, **kw):
        self.calls.append((data, mime, kw))
        return self.answer


def test_transcribe_asks_echo_with_documents_use(monkeypatch):
    fake = FakeVoice({"text": "ciao a tutti", "provider": "whisper-locale", "duration_s": 3})
    monkeypatch.setattr(transcription, "_client", fake)
    assert transcription.transcribe_audio(b"ogg", "audio/ogg") == "ciao a tutti"
    assert fake.calls[0][1] == "audio/ogg" and fake.calls[0][2]["use_case"] == "oracle.documenti"


def test_transcribe_unreachable_returns_empty(monkeypatch):
    monkeypatch.setattr(transcription, "_client", FakeVoice(None))
    assert transcription.transcribe_audio(b"x", "audio/mpeg") == ""


def test_voice_use_declared_and_no_whisper_left():
    caps = transcription.capabilities()["voice_usecases"]
    assert caps[0]["id"] == "oracle.documenti" and caps[0]["direction"] == "ascolto"
    from core.document import local_models
    from core.services import oracle_settings
    assert not hasattr(local_models, "transcribe_audio")
    assert not hasattr(oracle_settings, "WHISPER_MODEL")
