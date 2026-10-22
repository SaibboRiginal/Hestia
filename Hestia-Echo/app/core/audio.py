"""Sound plumbing: ffmpeg conversions, WAV helpers, silence measure, text made speakable, sentence cutting.

Engines get 16 kHz mono 16-bit WAV (``to_pcm16k``); clients get the format they ask for (``encode``):
``ogg_opus`` (Telegram voice), ``mp3``/``webm`` (browsers), ``wav``. Kept recordings are re-encoded small
(``keep_encode``: opus 16 kbps mono ≈ 7 MB per hour of speech).
"""
from __future__ import annotations

import io
import math
import re
import shutil
import struct
import subprocess
import wave

FORMATS = {
    "ogg_opus": ("audio/ogg", ["-c:a", "libopus", "-b:a", "32k", "-application", "voip", "-f", "ogg"]),
    "webm": ("audio/webm", ["-c:a", "libopus", "-b:a", "48k", "-f", "webm"]),
    "mp3": ("audio/mpeg", ["-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3"]),
    "wav": ("audio/wav", ["-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", "-f", "wav"]),
}
KEEP_MIME = "audio/ogg"


class AudioError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffmpeg(data: bytes, out_args: list[str], timeout: float = 120) -> bytes:
    if not ffmpeg_available():
        raise AudioError("ffmpeg non installato")
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-vn", *out_args, "pipe:1"],
                          input=data, capture_output=True, timeout=timeout)
    if proc.returncode != 0 or not proc.stdout:
        raise AudioError((proc.stderr or b"conversione fallita").decode(errors="replace")[:300])
    return proc.stdout


def is_wav16k(data: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
    except Exception:
        return False


def to_pcm16k(data: bytes, mime_type: str = "") -> bytes:
    """Any audio (ogg, webm, m4a, mp3, wav, mp4…) → 16 kHz mono 16-bit WAV."""
    if is_wav16k(data):
        return data
    return _ffmpeg(data, ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav"])


def encode(data: bytes, fmt: str) -> tuple[bytes, str]:
    """Audio → client format. Unknown format → ``ogg_opus``."""
    mime, args = FORMATS.get(fmt) or FORMATS["ogg_opus"]
    return _ffmpeg(data, args), mime


def keep_encode(data: bytes) -> bytes:
    """Small, still clear speech for keeping forever."""
    return _ffmpeg(data, ["-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "16k", "-application", "voip",
                          "-f", "ogg"])


def wav_bytes(samples: bytes, rate: int, width: int = 2, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(samples)
    return buf.getvalue()


def wav_frames(data: bytes) -> tuple[bytes, int, int, int]:
    """``(frames, rate, width, channels)`` of a WAV."""
    with wave.open(io.BytesIO(data)) as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getsampwidth(), w.getnchannels()


def wav_duration(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data)) as w:
            return round(w.getnframes() / float(w.getframerate() or 1), 2)
    except Exception:
        return 0.0


def float_to_wav(samples, rate: int) -> bytes:
    """Float samples in [-1, 1] (numpy array or list) → 16-bit WAV."""
    ints = bytearray()
    for s in samples:
        v = max(-1.0, min(1.0, float(s)))
        ints += struct.pack("<h", int(v * 32767))
    return wav_bytes(bytes(ints), rate)


def trailing_silence_ms(wav16k: bytes, threshold: float = 0.012) -> int:
    """How long the end of a 16 kHz mono WAV has been quiet (RMS of 20 ms windows under ``threshold``).
    Live mode uses it to close a turn when Marko stops talking."""
    try:
        frames, rate, width, _ = wav_frames(wav16k)
    except Exception:
        return 0
    if width != 2 or not frames:
        return 0
    win = max(1, rate // 50) * 2                     # 20 ms in bytes
    quiet = 0
    end = len(frames) - (len(frames) % 2)
    while end - win >= 0:
        chunk = frames[end - win:end]
        count = len(chunk) // 2
        values = struct.unpack(f"<{count}h", chunk)
        rms = math.sqrt(sum(v * v for v in values) / count) / 32768.0
        if rms >= threshold:
            break
        quiet += 20
        end -= win
    return quiet


# ── text made speakable ──────────────────────────────────────────────────────
_CODE_BLOCK = re.compile(r"```.*?(```|$)", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_HTML = re.compile(r"<[^>]+>")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍⬀-⯿]")
_MD_MARKS = re.compile(r"(^|\s)[#>]+\s|[*_~|]+")
_BULLET = re.compile(r"^\s*[-•]\s+", re.MULTILINE)


def speakable(text: str) -> str:
    """Markdown, links, code blocks, HTML and emoji are not read aloud."""
    t = _CODE_BLOCK.sub(" ", text or "")
    t = _INLINE_CODE.sub(r"\1", t)
    t = _MD_LINK.sub(r"\1", t)
    t = _URL.sub(" ", t)
    t = _HTML.sub(" ", t)
    t = _EMOJI.sub("", t)
    t = _BULLET.sub("", t)
    t = _MD_MARKS.sub(lambda m: m.group(1) or " ", t)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines()]
    out = []
    for ln in lines:
        if not ln:
            continue
        out.append(ln if re.search(r"[.!?…:;]$", ln) else ln + ".")
    return " ".join(out).strip()


def shorten(text: str, max_chars: int) -> tuple[str, bool]:
    """Cut at a sentence end under ``max_chars``; True when something was left out."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head = text[:max_chars]
    cut = max(head.rfind(". "), head.rfind("! "), head.rfind("? "), head.rfind("… "))
    return (head[:cut + 1] if cut > max_chars // 3 else head.rsplit(" ", 1)[0] + "…"), True


_SENTENCE_END = re.compile(r"(?<!\d)([.!?…]+)(\s+|$)|\n{2,}")


class SentenceCutter:
    """Feed text as it streams; get back complete sentences to speak (first sound after the first sentence).
    Very short sentences are joined to the next one so the voice does not stutter."""

    def __init__(self, min_chars: int = 24):
        self.buf = ""
        self.min_chars = min_chars

    def feed(self, delta: str) -> list[str]:
        self.buf += delta or ""
        out: list[str] = []
        start = 0
        for m in _SENTENCE_END.finditer(self.buf):
            if m.end() >= len(self.buf) and not m.group(0).endswith(("\n", " ")):
                break                                # punctuation at the very end: the sentence may continue
            piece = self.buf[start:m.end()].strip()
            if len(piece) >= self.min_chars:
                out.append(piece)
                start = m.end()
        self.buf = self.buf[start:]
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []
