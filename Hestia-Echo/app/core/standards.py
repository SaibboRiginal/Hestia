"""Speech standards — *how* Echo talks to an engine (dossier ``2026-10-20-modulo-voce`` §4.A).

A standard is a protocol Echo knows (built-in local engines, OpenAI-compatible audio API, Google, ElevenLabs,
Wyoming); a provider is a named instance of a standard (Themis ``echo.providers``). Each standard declares:
directions it serves, whether it needs a key / an address, its **options** (schema drawn by the WebUI as a form,
so a new standard needs no client change), and how to list models and voices.

Engines receive 16 kHz mono WAV when ``wants_pcm`` (local ones); the others accept common formats as they are.
``transcribe`` → ``{text, language}``; ``speak`` → ``(audio bytes, mime)``.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import socket
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from . import audio

logger = logging.getLogger("hestia_echo.standards")

MODELS_DIR = Path(os.getenv("ECHO_MODELS_DIR", "/models"))


class EngineError(RuntimeError):
    """An engine failed; ``status`` 429 = out of quota (the chain skips the pair until its reset)."""

    def __init__(self, message: str, status: int = 0, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status
        self.retry_after = retry_after


def opt(key: str, label: str, type: str, default: Any, *, help: str = "", options: list | None = None,
        min: float | None = None, max: float | None = None, direction: str = "") -> dict:
    out = {"key": key, "label": label, "type": type, "default": default, "help": help}
    for k, v in (("options", options), ("min", min), ("max", max), ("direction", direction or None)):
        if v is not None:
            out[k] = v
    return out


def _http_error(resp: requests.Response, what: str) -> EngineError:
    retry = resp.headers.get("retry-after")
    try:
        retry_s = float(retry) if retry else None
    except ValueError:
        retry_s = None
    return EngineError(f"{what}: HTTP {resp.status_code} {resp.text[:200]}", resp.status_code, retry_s)


def _lang_region(language: str) -> str:
    lang = (language or "it").lower()
    return {"it": "it-IT", "en": "en-US", "es": "es-ES", "fr": "fr-FR", "de": "de-DE"}.get(lang, lang)


class Standard:
    id = ""
    label = ""
    directions: tuple[str, ...] = ()
    needs_key = False
    needs_url = False
    default_url = ""
    wants_pcm = False                  # True: give it 16 kHz mono WAV (local engines)
    options: list[dict] = []

    def describe(self) -> dict:
        return {"id": self.id, "label": self.label, "directions": list(self.directions), "needs_key": self.needs_key,
                "needs_url": self.needs_url, "default_url": self.default_url, "options": self.options}

    def url(self, provider: dict) -> str:
        return str(provider.get("url") or self.default_url).rstrip("/")

    def state(self, provider: dict) -> str:
        if self.needs_key and not provider.get("key"):
            return "no_key"
        if self.needs_url and not self.url(provider):
            return "no_url"
        return "ready"

    def models(self, provider: dict) -> list[dict]:
        return []

    def voices(self, provider: dict, language: str = "it") -> list[dict]:
        return []

    def transcribe(self, provider: dict, model: str, data: bytes, mime: str, language: str, opts: dict) -> dict:
        raise EngineError(f"{self.label} non ascolta")

    def speak(self, provider: dict, model: str, voice: str, text: str, language: str, opts: dict) -> tuple[bytes, str]:
        raise EngineError(f"{self.label} non parla")


# ── local engines ────────────────────────────────────────────────────────────

class WhisperLocal(Standard):
    id, label, directions, wants_pcm = "whisper_local", "Whisper locale (faster-whisper)", ("ascolto",), True
    SIZES = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
    options = [
        opt("beam_size", "Precisione (beam)", "int", 5, min=1, max=10, help="Più alto = più preciso e più lento."),
        opt("vad", "Salta i silenzi", "bool", True),
        opt("initial_prompt", "Parole da riconoscere", "string", "",
            help="Nomi e parole tue (es. Hestia, Hercules), separati da virgola: le scrive giuste."),
        opt("device", "Dove gira", "enum", "auto", options=[{"value": "auto", "label": "Automatico"},
                                                            {"value": "cpu", "label": "CPU"},
                                                            {"value": "cuda", "label": "Scheda video"}]),
    ]

    def __init__(self):
        self._models: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()
        self._loading: set[str] = set()

    def _installed(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    def state(self, provider: dict) -> str:
        if not self._installed():
            return "not_installed"
        return "downloading" if self._loading else "ready"

    def models(self, provider: dict) -> list[dict]:
        return [{"id": s, "label": s} for s in self.SIZES]

    def _model(self, name: str, device: str):
        key = (name, device)
        with self._lock:
            if key in self._models:
                return self._models[key]
            self._loading.add(name)
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(name, device=device, compute_type="int8" if device != "cuda" else "float16",
                                 download_root=str(MODELS_DIR / "whisper"))
            logger.info("event=voice_whisper_loaded model=%s device=%s", name, device)
            with self._lock:
                self._models[key] = model
            return model
        finally:
            with self._lock:
                self._loading.discard(name)

    def transcribe(self, provider, model, data, mime, language, opts):
        if not self._installed():
            raise EngineError("faster-whisper non installato")
        m = self._model(model or "small", str(opts.get("device") or "auto"))
        segments, info = m.transcribe(_whisper_samples(data), language=None if language in ("", "auto") else language,
                                      beam_size=int(opts.get("beam_size") or 5),
                                      vad_filter=bool(opts.get("vad", True)),
                                      initial_prompt=str(opts.get("initial_prompt") or "") or None)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text, "language": getattr(info, "language", language) or language}


def _whisper_samples(data: bytes):
    """16 kHz mono WAV → float32 samples, so faster-whisper never decodes a file itself: its PyAV call breaks on
    PyAV ≥ 14 («open() got an unexpected keyword argument 'metadata_errors'», bench 2026-10-30)."""
    import numpy as np
    frames, rate, width, channels = audio.wav_frames(audio.to_pcm16k(data))
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


PIPER_ITALIAN = ["it_IT-paola-medium", "it_IT-riccardo-x_low"]


class Piper(Standard):
    id, label, directions = "piper", "Piper (locale, veloce)", ("voce",)
    options = [
        opt("length_scale", "Lentezza", "float", 1.0, min=0.5, max=2.0, help="1 = normale; più alto = più lenta."),
        opt("noise_scale", "Variazione", "float", 0.667, min=0.0, max=1.0),
        opt("sentence_silence", "Pausa tra le frasi", "float", 0.2, min=0.0, max=2.0),
    ]

    def __init__(self):
        self._voices: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _installed(self) -> bool:
        try:
            import piper  # noqa: F401
            return True
        except Exception:
            return False

    def state(self, provider):
        return "ready" if self._installed() else "not_installed"

    def voices(self, provider, language="it"):
        names = set(PIPER_ITALIAN if language.startswith("it") else [])
        d = MODELS_DIR / "piper"
        if d.is_dir():
            names |= {p.stem for p in d.glob("*.onnx")}
        return [{"id": n, "label": n.split("-")[1].capitalize() + " · " + n.split("-")[-1] if n.count("-") >= 2 else n}
                for n in sorted(names)]

    def _download(self, name: str) -> Path:
        d = MODELS_DIR / "piper"
        d.mkdir(parents=True, exist_ok=True)
        onnx = d / f"{name}.onnx"
        if onnx.exists() and (d / f"{name}.onnx.json").exists():
            return onnx
        try:
            locale, speaker, quality = name.split("-")
        except ValueError:
            raise EngineError(f"voce Piper {name!r} non valida (es. it_IT-paola-medium)")
        base = (f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{locale.split('_')[0]}/{locale}/"
                f"{speaker}/{quality}/{name}")
        for suffix in (".onnx", ".onnx.json"):
            resp = requests.get(base + suffix, timeout=300)
            if resp.status_code != 200:
                raise EngineError(f"download voce Piper {name}: HTTP {resp.status_code}")
            (d / f"{name}{suffix}").write_bytes(resp.content)
        logger.info("event=voice_piper_downloaded voice=%s", name)
        return onnx

    def _voice(self, name: str):
        with self._lock:
            if name not in self._voices:
                from piper import PiperVoice
                self._voices[name] = PiperVoice.load(str(self._download(name)))
            return self._voices[name]

    def speak(self, provider, model, voice, text, language, opts):
        if not self._installed():
            raise EngineError("piper-tts non installato")
        v = self._voice(voice or model or PIPER_ITALIAN[0])
        import wave
        buf = tempfile.SpooledTemporaryFile()
        with wave.open(buf, "wb") as w:
            try:                                                # piper-tts ≥ 1.3
                from piper import SynthesisConfig
                v.synthesize_wav(text, w, syn_config=SynthesisConfig(
                    length_scale=float(opts.get("length_scale") or 1.0),
                    noise_scale=float(opts.get("noise_scale") or 0.667)))
            except ImportError:                                 # piper-tts 1.2
                v.synthesize(text, w, length_scale=float(opts.get("length_scale") or 1.0),
                             noise_scale=float(opts.get("noise_scale") or 0.667),
                             sentence_silence=float(opts.get("sentence_silence") or 0.2))
        buf.seek(0)
        return buf.read(), "audio/wav"


KOKORO_VOICES = {"it": [("if_sara", "Sara"), ("im_nicola", "Nicola")],
                 "en": [("af_heart", "Heart"), ("af_bella", "Bella"), ("am_michael", "Michael"), ("bf_emma", "Emma")]}
KOKORO_FILES = {"kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
                "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"}


class Kokoro(Standard):
    id, label, directions = "kokoro", "Kokoro (locale, naturale)", ("voce",)
    options = [opt("speed", "Velocità", "float", 1.0, min=0.5, max=2.0)]

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def _installed(self) -> bool:
        try:
            import kokoro_onnx  # noqa: F401
            return True
        except Exception:
            return False

    def state(self, provider):
        return "ready" if self._installed() else "not_installed"

    def voices(self, provider, language="it"):
        lang = (language or "it")[:2]
        return [{"id": v, "label": label} for v, label in KOKORO_VOICES.get(lang, []) + (
            KOKORO_VOICES["en"] if lang != "en" else [])]

    def _load(self):
        with self._lock:
            if self._engine is None:
                d = MODELS_DIR / "kokoro"
                d.mkdir(parents=True, exist_ok=True)
                for name, url in KOKORO_FILES.items():
                    if not (d / name).exists():
                        resp = requests.get(url, timeout=600)
                        if resp.status_code != 200:
                            raise EngineError(f"download Kokoro {name}: HTTP {resp.status_code}")
                        (d / name).write_bytes(resp.content)
                        logger.info("event=voice_kokoro_downloaded file=%s", name)
                from kokoro_onnx import Kokoro as Engine
                self._engine = Engine(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
            return self._engine

    def speak(self, provider, model, voice, text, language, opts):
        if not self._installed():
            raise EngineError("kokoro-onnx non installato")
        engine = self._load()
        lang = {"it": "it", "en": "en-us", "es": "es", "fr": "fr-fr"}.get((language or "it")[:2], "it")
        samples, rate = engine.create(text, voice=voice or model or "if_sara", speed=float(opts.get("speed") or 1.0),
                                      lang=lang)
        return audio.float_to_wav(samples, int(rate)), "audio/wav"


# ── cloud / remote engines ───────────────────────────────────────────────────

class OpenAICompatible(Standard):
    id, label, directions = "openai", "Compatibile OpenAI (OpenAI, Groq, Speaches, LocalAI…)", ("ascolto", "voce")
    needs_key, needs_url, default_url = True, True, "https://api.openai.com/v1"
    options = [
        opt("prompt", "Parole da riconoscere", "string", "", direction="ascolto"),
        opt("temperature", "Temperatura", "float", 0.0, min=0.0, max=1.0, direction="ascolto"),
        opt("speed", "Velocità", "float", 1.0, min=0.25, max=4.0, direction="voce"),
        opt("instructions", "Stile della voce", "string", "", direction="voce",
            help="Per i modelli che lo accettano (es. «calda, tranquilla»)."),
    ]

    def state(self, provider):
        if not self.url(provider):
            return "no_url"
        # Self-hosted servers (Speaches, LocalAI) need no key: a key is required only for public hosts.
        host = urlsplit(self.url(provider)).hostname or ""
        if not provider.get("key") and any(h in host for h in ("openai.com", "groq.com")):
            return "no_key"
        return "ready"

    def _headers(self, provider):
        return {"Authorization": f"Bearer {provider['key']}"} if provider.get("key") else {}

    def models(self, provider):
        try:
            resp = requests.get(f"{self.url(provider)}/models", headers=self._headers(provider), timeout=8)
            if resp.status_code == 200:
                ids = [m.get("id") for m in (resp.json().get("data") or []) if isinstance(m, dict)]
                audio_ids = [i for i in ids if i and any(w in i.lower() for w in ("whisper", "tts", "transcribe",
                                                                                 "speech", "kokoro", "piper"))]
                return [{"id": i, "label": i} for i in (audio_ids or ids)]
        except Exception as exc:
            logger.debug("event=voice_models_failed provider=%s error=%s", provider.get("name"), exc)
        return [{"id": i, "label": i} for i in ("whisper-1", "gpt-4o-mini-transcribe", "whisper-large-v3-turbo",
                                                 "tts-1", "gpt-4o-mini-tts")]

    def voices(self, provider, language="it"):
        return [{"id": v, "label": v} for v in ("alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage",
                                                 "shimmer")]

    def transcribe(self, provider, model, data, mime, language, opts):
        ext = {"audio/ogg": "ogg", "audio/webm": "webm", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/wav": "wav",
               "audio/x-wav": "wav"}.get(mime.split(";")[0], "wav")
        form = {"model": model or "whisper-1", "response_format": "json",
                "temperature": str(opts.get("temperature") or 0)}
        if language and language != "auto":
            form["language"] = language
        if opts.get("prompt"):
            form["prompt"] = str(opts["prompt"])
        resp = requests.post(f"{self.url(provider)}/audio/transcriptions", headers=self._headers(provider),
                             data=form, files={"file": (f"audio.{ext}", data, mime)}, timeout=180)
        if resp.status_code >= 400:
            raise _http_error(resp, "trascrizione")
        return {"text": str(resp.json().get("text") or "").strip(), "language": language}

    def speak(self, provider, model, voice, text, language, opts):
        body = {"model": model or "tts-1", "voice": voice or "alloy", "input": text, "response_format": "wav",
                "speed": float(opts.get("speed") or 1.0)}
        if opts.get("instructions"):
            body["instructions"] = str(opts["instructions"])
        resp = requests.post(f"{self.url(provider)}/audio/speech", headers=self._headers(provider), json=body,
                             timeout=120)
        if resp.status_code >= 400:
            raise _http_error(resp, "sintesi")
        return resp.content, resp.headers.get("content-type", "audio/wav").split(";")[0]


class Google(Standard):
    id, label, directions = "google", "Google Cloud (Speech-to-Text, Text-to-Speech)", ("ascolto", "voce")
    needs_key = True
    options = [
        opt("recognition_model", "Modello di ascolto", "enum", "latest_short", direction="ascolto",
            options=[{"value": "latest_short", "label": "Frasi brevi"}, {"value": "latest_long", "label": "Audio lunghi"},
                     {"value": "default", "label": "Predefinito"}]),
        opt("punctuation", "Punteggiatura", "bool", True, direction="ascolto"),
        opt("speaking_rate", "Velocità", "float", 1.0, min=0.25, max=4.0, direction="voce"),
        opt("pitch", "Tono", "float", 0.0, min=-20.0, max=20.0, direction="voce"),
        opt("profile", "Profilo audio", "enum", "headphone-class-device", direction="voce",
            options=[{"value": "headphone-class-device", "label": "Cuffie"},
                     {"value": "handset-class-device", "label": "Telefono"},
                     {"value": "small-bluetooth-speaker-class-device", "label": "Cassa piccola"},
                     {"value": "large-home-entertainment-class-device", "label": "Impianto"}]),
    ]

    def voices(self, provider, language="it"):
        if provider.get("key"):
            try:
                resp = requests.get("https://texttospeech.googleapis.com/v1/voices",
                                    params={"languageCode": _lang_region(language), "key": provider["key"]}, timeout=8)
                if resp.status_code == 200:
                    return [{"id": v["name"], "label": v["name"]} for v in resp.json().get("voices") or []]
            except Exception as exc:
                logger.debug("event=voice_google_voices_failed error=%s", exc)
        return [{"id": v, "label": v} for v in ("it-IT-Neural2-A", "it-IT-Neural2-C", "it-IT-Wavenet-A",
                                                 "it-IT-Standard-A")]

    def transcribe(self, provider, model, data, mime, language, opts):
        body = {"config": {"encoding": "LINEAR16", "sampleRateHertz": 16000,
                           "languageCode": _lang_region(language if language != "auto" else "it"),
                           "model": model or str(opts.get("recognition_model") or "latest_short"),
                           "enableAutomaticPunctuation": bool(opts.get("punctuation", True))},
                "audio": {"content": base64.b64encode(data).decode()}}
        resp = requests.post("https://speech.googleapis.com/v1/speech:recognize", params={"key": provider["key"]},
                             json=body, timeout=120)
        if resp.status_code >= 400:
            raise _http_error(resp, "trascrizione")
        parts = [r["alternatives"][0].get("transcript", "") for r in resp.json().get("results") or []
                 if r.get("alternatives")]
        return {"text": " ".join(p.strip() for p in parts).strip(), "language": language}

    wants_pcm = True

    def speak(self, provider, model, voice, text, language, opts):
        body = {"input": {"text": text},
                "voice": {"languageCode": _lang_region(language), "name": voice or model or "it-IT-Neural2-A"},
                "audioConfig": {"audioEncoding": "LINEAR16", "speakingRate": float(opts.get("speaking_rate") or 1.0),
                                "pitch": float(opts.get("pitch") or 0.0)}}
        if opts.get("profile"):
            body["audioConfig"]["effectsProfileId"] = [str(opts["profile"])]
        resp = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                             params={"key": provider["key"]}, json=body, timeout=60)
        if resp.status_code >= 400:
            raise _http_error(resp, "sintesi")
        return base64.b64decode(resp.json()["audioContent"]), "audio/wav"


class ElevenLabs(Standard):
    id, label, directions = "elevenlabs", "ElevenLabs", ("ascolto", "voce")
    needs_key, default_url = True, "https://api.elevenlabs.io/v1"
    options = [
        opt("stability", "Stabilità", "float", 0.5, min=0.0, max=1.0, direction="voce"),
        opt("similarity", "Somiglianza", "float", 0.75, min=0.0, max=1.0, direction="voce"),
        opt("style", "Espressività", "float", 0.0, min=0.0, max=1.0, direction="voce"),
    ]

    def models(self, provider):
        return [{"id": m, "label": m} for m in ("scribe_v1", "eleven_multilingual_v2", "eleven_flash_v2_5")]

    def voices(self, provider, language="it"):
        if provider.get("key"):
            try:
                resp = requests.get(f"{self.url(provider)}/voices", headers={"xi-api-key": provider["key"]}, timeout=8)
                if resp.status_code == 200:
                    return [{"id": v["voice_id"], "label": v.get("name") or v["voice_id"]}
                            for v in resp.json().get("voices") or []]
            except Exception as exc:
                logger.debug("event=voice_elevenlabs_voices_failed error=%s", exc)
        return []

    def transcribe(self, provider, model, data, mime, language, opts):
        form = {"model_id": model or "scribe_v1"}
        if language and language != "auto":
            form["language_code"] = language
        resp = requests.post(f"{self.url(provider)}/speech-to-text", headers={"xi-api-key": provider["key"]},
                             data=form, files={"file": ("audio", data, mime)}, timeout=180)
        if resp.status_code >= 400:
            raise _http_error(resp, "trascrizione")
        return {"text": str(resp.json().get("text") or "").strip(), "language": language}

    def speak(self, provider, model, voice, text, language, opts):
        if not voice:
            raise EngineError("ElevenLabs: scegli una voce")
        body = {"text": text, "model_id": model or "eleven_multilingual_v2",
                "voice_settings": {"stability": float(opts.get("stability", 0.5)),
                                   "similarity_boost": float(opts.get("similarity", 0.75)),
                                   "style": float(opts.get("style", 0.0))}}
        resp = requests.post(f"{self.url(provider)}/text-to-speech/{voice}", headers={"xi-api-key": provider["key"]},
                             params={"output_format": "mp3_44100_128"}, json=body, timeout=120)
        if resp.status_code >= 400:
            raise _http_error(resp, "sintesi")
        return resp.content, "audio/mpeg"


class Wyoming(Standard):
    """Home Assistant's voice protocol (whisper/piper servers on the LAN): JSON event lines + binary payloads."""
    id, label, directions, wants_pcm = "wyoming", "Wyoming (server voce di Home Assistant)", ("ascolto", "voce"), True
    needs_url = True
    options = []

    def _addr(self, provider) -> tuple[str, int]:
        parts = urlsplit(self.url(provider) if "://" in self.url(provider) else "tcp://" + self.url(provider))
        return parts.hostname or "localhost", parts.port or 10300

    @staticmethod
    def _send(sock, etype: str, data: dict | None = None, payload: bytes = b"") -> None:
        header = {"type": etype, "data": data or {}}
        if payload:
            header["payload_length"] = len(payload)
        sock.sendall(json.dumps(header).encode() + b"\n" + payload)

    @staticmethod
    def _read(f) -> tuple[str, dict, bytes]:
        line = f.readline()
        if not line:
            raise EngineError("Wyoming: connessione chiusa")
        header = json.loads(line)
        data = header.get("data") or {}
        if header.get("data_length"):
            data.update(json.loads(f.read(int(header["data_length"]))))
        payload = f.read(int(header["payload_length"])) if header.get("payload_length") else b""
        return str(header.get("type")), data, payload

    def transcribe(self, provider, model, data, mime, language, opts):
        frames, rate, width, channels = audio.wav_frames(data)
        fmt = {"rate": rate, "width": width, "channels": channels}
        with socket.create_connection(self._addr(provider), timeout=120) as sock:
            f = sock.makefile("rb")
            self._send(sock, "transcribe", {"language": None if language == "auto" else language,
                                            **({"name": model} if model else {})})
            self._send(sock, "audio-start", fmt)
            step = rate * width * channels                     # one second per chunk
            for i in range(0, len(frames), step):
                self._send(sock, "audio-chunk", fmt, frames[i:i + step])
            self._send(sock, "audio-stop", {})
            while True:
                etype, edata, _ = self._read(f)
                if etype == "transcript":
                    return {"text": str(edata.get("text") or "").strip(), "language": language}

    def speak(self, provider, model, voice, text, language, opts):
        with socket.create_connection(self._addr(provider), timeout=120) as sock:
            f = sock.makefile("rb")
            self._send(sock, "synthesize", {"text": text, **({"voice": {"name": voice}} if voice else {})})
            fmt, frames = {}, bytearray()
            while True:
                etype, edata, payload = self._read(f)
                if etype == "audio-start":
                    fmt = edata
                elif etype == "audio-chunk":
                    fmt = fmt or edata
                    frames += payload
                elif etype == "audio-stop":
                    break
        return audio.wav_bytes(bytes(frames), int(fmt.get("rate") or 22050), int(fmt.get("width") or 2),
                               int(fmt.get("channels") or 1)), "audio/wav"


STANDARDS: dict[str, Standard] = {s.id: s for s in (WhisperLocal(), Piper(), Kokoro(), OpenAICompatible(), Google(),
                                                    ElevenLabs(), Wyoming())}
