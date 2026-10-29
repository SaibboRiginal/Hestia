"""Your voice (Cindy 10 + 17): personal dictionary learnt from corrections and passed as a hint; voiceprint filter
that mutes other voices before listening. Fake speaker engine (dominant frequency), fake Archive."""
import math
import struct

import numpy as np
import pytest

from app.core import audio
from app.core.dictionary import Dictionary, new_words
from app.core.service import Echo, Invalid
from app.core.voiceprint import Voiceprint, VoiceprintError

from .test_echo import FakeArchive, b64, engine, needs_ffmpeg, world  # noqa: F401  (fixtures)

pytestmark = pytest.mark.unit


def tones(*parts, rate=16000):
    """WAV made of (seconds, frequency) parts; frequency 0 = silence."""
    frames = bytearray()
    for seconds, freq in parts:
        for i in range(int(seconds * rate)):
            v = 0.3 * math.sin(2 * math.pi * freq * i / rate) if freq else 0.0
            frames += struct.pack("<h", int(v * 32767))
    return audio.wav_bytes(bytes(frames), rate)


class FakeSpeaker:
    """Owner = low voice (< 600 Hz), others = high voice."""
    error = ""

    def __init__(self):
        self.calls = 0

    def embed(self, samples):
        self.calls += 1
        spectrum = np.abs(np.fft.rfft(samples))
        freq = np.argmax(spectrum) * 16000 / len(samples)
        return [1.0, 0.0] if freq < 600 else [0.0, 1.0]


def test_new_words_are_the_ones_not_heard():
    assert new_words("ho parlato con igea oggi", "ho parlato con Hygieia oggi") == ["Hygieia"]
    assert new_words("ciao", "ciao") == []


def test_dictionary_learns_after_two_corrections_and_is_a_hint(world):
    values = world["values"]
    d = Dictionary(world["keep"], lambda k, default=None: values.get(k, default))
    assert d.learn("vado da igea", "vado da Hygieia") == {"confirmed": [], "candidates": ["Hygieia"]}
    assert d.hint() == ""
    assert d.learn("igea dice", "Hygieia dice")["confirmed"] == ["Hygieia"]
    d.add("Saibbo")
    assert set(d.confirmed()) == {"Hygieia", "Saibbo"}
    assert d.remove("saibbo") and d.confirmed() == ["Hygieia"]
    with pytest.raises(ValueError):
        d.add("!!")


def test_hint_goes_to_the_engine(world):
    values = world["values"]
    get = lambda k, default=None: values.get(k, default)  # noqa: E731
    d = Dictionary(world["keep"], get)
    d.add("Hygieia")
    seen = {}
    eng = world["engine"]
    orig = eng.transcribe

    def spy(provider, model, data, mime, language, opts):
        seen.update(opts)
        return orig(provider, model, data, mime, language, opts)

    eng.transcribe = spy
    echo = Echo(world["blocks"], world["keep"], get, dictionary=d)
    echo.transcribe({"audio_b64": b64(tones((1.0, 440))), "mime_type": "audio/wav", "use_case": "x.y"})
    assert "Hygieia" in seen["initial_prompt"] and "Hygieia" in seen["prompt"]


def _vp(world, uses=("webui.live.ascolto",)):
    values = {**world["values"], "echo.impronta.soglia": 0.5, "echo.impronta.usi": list(uses)}
    return Voiceprint(world["keep"], lambda k, default=None: values.get(k, default), engine=FakeSpeaker())


def test_enroll_needs_enough_voice_and_forget(world):
    vp = _vp(world)
    with pytest.raises(VoiceprintError):
        vp.enroll(tones((2.0, 440)))
    assert vp.enroll(tones((7.0, 440)))["enrolled"] is True
    vp._cache = None                                  # read back from the archive
    assert vp.stored()["embedding"] == [1.0, 0.0]
    assert vp.forget()["enrolled"] is False and not vp.applies("webui.live.ascolto")


def test_filter_mutes_other_voices_only_on_chosen_uses(world):
    vp = _vp(world)
    vp.enroll(tones((7.0, 440)))
    mixed = tones((3.0, 440), (3.0, 880))
    out, stats = vp.filter(mixed, "webui.live.ascolto")
    assert stats == {"applied": True, "kept": 2, "muted": 2}
    samples = np.frombuffer(audio.wav_frames(out)[0], dtype="<i2")
    assert np.abs(samples[: 3 * 16000]).max() > 1000 and np.abs(samples[3 * 16000:]).max() == 0
    assert vp.filter(mixed, "telegram.vocale")[1] == {"applied": False}


def test_cache_judges_each_window_once(world):
    vp = _vp(world)
    vp.enroll(tones((7.0, 440)))
    cache, calls = {}, vp.engine.calls
    vp.filter(tones((3.0, 440)), "webui.live.ascolto", cache)
    first = vp.engine.calls - calls
    vp.filter(tones((3.0, 440)), "webui.live.ascolto", cache)
    assert vp.engine.calls - calls == first           # the second pass reused both windows


def test_only_other_voices_is_not_a_message(world):
    vp = _vp(world)
    vp.enroll(tones((7.0, 440)))
    values = world["values"]
    echo = Echo(world["blocks"], world["keep"], lambda k, default=None: values.get(k, default), voiceprint=vp)
    with pytest.raises(Invalid):
        echo.transcribe({"audio_b64": b64(tones((3.0, 880))), "mime_type": "audio/wav",
                         "use_case": "webui.live.ascolto"})
    out = echo.transcribe({"audio_b64": b64(tones((3.0, 440), (1.5, 880))), "mime_type": "audio/wav",
                           "use_case": "webui.live.ascolto"})
    assert out["text"]


def test_engine_failure_never_stops_listening(world):
    vp = _vp(world)
    vp.enroll(tones((7.0, 440)))

    class Broken:
        error = ""

        def embed(self, samples):
            raise RuntimeError("no model")

    vp.engine = Broken()
    wav = tones((3.0, 880))
    out, stats = vp.filter(wav, "webui.live.ascolto")
    assert out == wav and stats["applied"] is False


def test_routes_exist():
    from app import main
    paths = main.app.openapi()["paths"]
    for p in ("/api/voice/dictionary", "/api/voice/dictionary/learn", "/api/voice/voiceprint"):
        assert p in paths
