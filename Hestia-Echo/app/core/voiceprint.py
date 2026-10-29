"""«Riconosci la mia voce» (Cindy 10, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4).

The owner records ~10 s of speech once (page «Voce» or Telegram «Registra la mia voce»): Echo computes a speaker
embedding and keeps it in Archive (``echo-store`` row ``kind=voiceprint``, the recording as a kept ``recording``).
From then on, on the uses listed in ``echo.impronta.usi`` (live mode, voice notes), every 1.5 s window of speech
that does not sound like the owner (cosine similarity under ``echo.impronta.soglia``) becomes silence **before**
transcription: the TV or other people do not end up in the message and do not keep a live turn open.
No switch: no voiceprint = no filter. The engine (WeSpeaker ResNet34, ONNX, downloaded on first use into
``ECHO_MODELS_DIR/speaker``) is optional: when it cannot load the audio passes unchanged (``[🔄]`` log).
"""
from __future__ import annotations

import io
import logging
import math
import threading
import wave
from pathlib import Path
from typing import Any

import requests

from .standards import MODELS_DIR

logger = logging.getLogger("hestia_echo.voiceprint")

MODEL_FILE = "voxceleb_resnet34_LM.onnx"
MODEL_URL = "https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM/resolve/main/voxceleb_resnet34_LM.onnx"
RATE = 16000
WINDOW_S = 1.5
MIN_ENROLL_S = 6.0
SPEECH_RMS = 0.015


class VoiceprintError(RuntimeError):
    pass


def _samples(wav16k: bytes):
    import numpy as np
    with wave.open(io.BytesIO(wav16k)) as w:
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0


def _wav(samples) -> bytes:
    import numpy as np
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _mel_filters(n_fft: int = 512, n_mels: int = 80, low: float = 20.0, high: float = 7600.0):
    import numpy as np

    def mel(f):
        return 1127.0 * np.log(1.0 + f / 700.0)

    bins = n_fft // 2 + 1
    freqs = np.linspace(0, RATE / 2, bins)
    pts = np.linspace(mel(low), mel(high), n_mels + 2)
    m = mel(freqs)
    fb = np.zeros((n_mels, bins), dtype="float32")
    for i in range(n_mels):
        left, center, right = pts[i], pts[i + 1], pts[i + 2]
        up = (m - left) / (center - left)
        down = (right - m) / (right - center)
        fb[i] = np.maximum(0, np.minimum(up, down))
    return fb


_FB = None


def fbank(samples):
    """Kaldi-like 80-dim log-mel features (25 ms / 10 ms, pre-emphasis, Hamming), mean-normalised."""
    import numpy as np
    global _FB
    if _FB is None:
        _FB = _mel_filters()
    frame, shift = 400, 160
    x = samples * 32768.0
    if len(x) < frame:
        x = np.pad(x, (0, frame - len(x)))
    n = 1 + (len(x) - frame) // shift
    idx = np.arange(frame)[None, :] + shift * np.arange(n)[:, None]
    frames = x[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1], frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    frames = frames * np.hamming(frame)[None, :]
    power = np.abs(np.fft.rfft(frames, n=512)) ** 2
    feats = np.log(np.maximum(power @ _FB.T, 1e-10)).astype("float32")
    return feats - feats.mean(axis=0, keepdims=True)


def cosine(a, b) -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return float(num / den) if den else 0.0


class SpeakerEngine:
    """Speaker embeddings with the ONNX model (loaded once, thread safe). ``embed(samples) -> list[float]``."""

    def __init__(self, models_dir: Path = MODELS_DIR):
        self.dir = Path(models_dir) / "speaker"
        self._session = None
        self._lock = threading.Lock()
        self.error = ""

    def _load(self):
        with self._lock:
            if self._session is None:
                import onnxruntime as ort  # comes with kokoro-onnx
                self.dir.mkdir(parents=True, exist_ok=True)
                path = self.dir / MODEL_FILE
                if not path.exists():
                    resp = requests.get(MODEL_URL, timeout=600)
                    if resp.status_code != 200:
                        raise VoiceprintError(f"download modello voce: HTTP {resp.status_code}")
                    path.write_bytes(resp.content)
                    logger.info("event=voiceprint_model_downloaded bytes=%d", len(resp.content))
                self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            return self._session

    def embed(self, samples) -> list[float]:
        session = self._load()
        feats = fbank(samples)[None, :, :]
        out = session.run(None, {session.get_inputs()[0].name: feats})[0]
        return [float(v) for v in out.reshape(-1)]


class Voiceprint:
    """The owner's voiceprint (Archive) + the filter applied before transcription."""

    def __init__(self, keep, get, engine: Any = None):
        self.keep = keep
        self.get = get
        self.engine = engine or SpeakerEngine()
        self._cache: dict | None = None

    # ── stored print ────────────────────────────────────────────────────────
    def stored(self) -> dict | None:
        if self._cache is None:
            rows = [r for r in self.keep._rows(kind="voiceprint") if not r.get("deleted")]
            self._cache = (rows[-1].get("data") or {}) if rows else {}
        return self._cache or None

    def status(self) -> dict:
        p = self.stored()
        return {"enrolled": bool(p), "at": (p or {}).get("at"), "seconds": (p or {}).get("seconds"),
                "threshold": self.threshold(), "uses": self.uses(), "engine_error": getattr(self.engine, "error", "")}

    def threshold(self) -> float:
        try:
            return float(self.get("echo.impronta.soglia", 0.45))
        except (TypeError, ValueError):
            return 0.45

    def uses(self) -> list[str]:
        raw = self.get("echo.impronta.usi", []) or []
        return [str(u) for u in raw] if isinstance(raw, list) else [u.strip() for u in str(raw).split(",") if u.strip()]

    def enroll(self, wav16k: bytes, recording_blob: str | None = None) -> dict:
        samples = _samples(wav16k)
        seconds = len(samples) / RATE
        if seconds < MIN_ENROLL_S:
            raise VoiceprintError(f"serve almeno {int(MIN_ENROLL_S)} secondi di voce")
        emb = self.engine.embed(samples)
        from .keep import now
        stamp = now().isoformat()
        data = {"embedding": emb, "at": stamp, "seconds": round(seconds, 1), "blob_id": recording_blob}
        self.keep._put([{"kind": "voiceprint", "id": "owner", "at": stamp, "updated_at": stamp, "data": data}])
        self._cache = data
        logger.info("event=voiceprint_enrolled seconds=%.1f dims=%d", seconds, len(emb))
        return self.status()

    def forget(self) -> dict:
        from .keep import now
        stamp = now().isoformat()
        self.keep._put([{"kind": "voiceprint", "id": "owner", "at": stamp, "updated_at": stamp, "data": {},
                         "deleted": True}])
        self._cache = {}
        logger.info("event=voiceprint_forgotten")
        return self.status()

    # ── filter ──────────────────────────────────────────────────────────────
    def applies(self, use_case: str) -> bool:
        return bool(self.stored()) and use_case in self.uses()

    def filter(self, wav16k: bytes, use_case: str, cache: dict | None = None) -> tuple[bytes, dict]:
        """Windows of speech that are not the owner → silence. Returns ``(wav, stats)``; unchanged when not
        applicable or when the engine is not available. ``cache`` (window start → owner?) lets a live stream judge
        each full window once while the buffer grows."""
        if not self.applies(use_case):
            return wav16k, {"applied": False}
        try:
            import numpy as np
            samples = _samples(wav16k).copy()
            ref = self.stored()["embedding"]
            win = int(WINDOW_S * RATE)
            kept = muted = 0
            for start in range(0, len(samples), win):
                chunk = samples[start:start + win]
                if len(chunk) < RATE * 0.4 or float(np.sqrt(np.mean(chunk ** 2))) < SPEECH_RMS:
                    continue                          # silence or a tail too short to judge: leave it
                full = len(chunk) == win
                if cache is not None and full and start in cache:
                    owner = cache[start]
                else:
                    owner = cosine(self.engine.embed(chunk), ref) >= self.threshold()
                    if cache is not None and full:
                        cache[start] = owner
                if owner:
                    kept += 1
                else:
                    samples[start:start + win] = 0.0
                    muted += 1
            if muted:
                logger.info("event=voiceprint_filtered use_case=%s kept=%d muted=%d", use_case, kept, muted)
            return _wav(samples), {"applied": True, "kept": kept, "muted": muted}
        except Exception as exc:  # noqa: BLE001 — a missing engine never stops listening
            self.engine.error = str(exc)[:200]
            logger.warning("[🔄] event=voiceprint_filter_failed use_case=%s error=%s fallback=unfiltered",
                           use_case, exc)
            return wav16k, {"applied": False, "error": str(exc)[:200]}
