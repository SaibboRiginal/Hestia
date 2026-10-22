"""Echo: sound ↔ text, files and streams in blocks (dossier §2–§7). Never calls Oracle, never decides what to say.

- ``transcribe`` / ``speak``: one file in, one result out.
- ``listen`` stream: audio chunks in (``chunk``), partial text + trailing silence out, final text on ``end``.
- ``say`` stream: reply deltas in (``text``), spoken sentences out as soon as each is complete.
Each operation runs on its use's chain (or the external engine), writes a usage row and, when asked, keeps the
audio (``keep = {kind, session_id, message_id | notification_id, client}``).
"""
from __future__ import annotations

import base64
import binascii
import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

from . import audio
from .blocks import Blocks, ChainExhausted
from .keep import Keep
from .standards import STANDARDS

logger = logging.getLogger("hestia_echo.service")

STREAM_IDLE_SECONDS = 60
PARTIAL_MAX_SECONDS = 90


class Invalid(ValueError):
    pass


class NotFound(LookupError):
    pass


def _b64(value: str) -> bytes:
    try:
        return base64.b64decode(str(value or "").split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError):
        raise Invalid("audio non valido (base64)")


def _opts(std, provider: dict, step: dict, direction: str) -> dict:
    defaults = {o["key"]: o["default"] for o in std.options if o.get("direction") in (None, direction)}
    return {**defaults, **(provider.get("options") or {}), **(step.get("options") or {})}


class Echo:
    def __init__(self, blocks: Blocks, keep: Keep, get: Callable[[str, Any], Any]):
        self.blocks = blocks
        self.keep = keep
        self.get = get
        self.recent: deque[dict] = deque(maxlen=20)
        self._streams: dict[str, dict] = {}
        self._lock = threading.Lock()

    def language(self, override: str | None = None) -> str:
        return str(override or self.get("echo.language", "it") or "it")

    # ── bookkeeping ──────────────────────────────────────────────────────────
    def _record(self, kind: str, info: dict, *, ms: int, ok: bool, seconds: float = 0.0, chars: int = 0,
                error: str = "") -> None:
        pricing = self.get("echo.pricing", {}) or {}
        price = pricing.get(f"{info.get('provider')}/{info.get('model') or info.get('voice')}") or \
            pricing.get(str(info.get("provider") or "")) or {}
        cost = 0.0
        if isinstance(price, dict):
            cost = seconds / 60.0 * float(price.get("minute") or 0) + chars / 1e6 * float(price.get("mchars") or 0)
        row = {"kind": kind, "use_case": info.get("use_case"), "chain": info.get("chain"), "mode": info.get("mode"),
               "step": info.get("step"), "provider": info.get("provider"),
               "model": info.get("model") or info.get("voice"), "seconds": round(seconds, 2), "chars": chars,
               "ms": ms, "ok": ok, "cost": round(cost, 6), "fallback": bool(info.get("fallback")),
               "error": error[:200] if error else ""}
        self.recent.appendleft({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **row})
        self.keep.usage_add(row)

    def _keep(self, keep: dict | None, cls_default: str, data: bytes, mime: str, meta: dict) -> str | None:
        if not isinstance(keep, dict):
            return None
        cls = str(keep.get("kind") or cls_default)
        try:
            if cls == "recording":
                data, mime = audio.keep_encode(data), audio.KEEP_MIME
            return self.keep.save(cls, data, mime, {**keep, **meta})
        except Exception as exc:
            logger.warning("[🔄] event=voice_keep_failed class=%s error=%s fallback=not_kept", cls, exc)
            return None

    # ── listening ────────────────────────────────────────────────────────────
    def _heard(self, raw: bytes, mime: str, uc: str, language: str, *, record: bool = True) -> tuple[dict, dict, bytes]:
        """Run the listening chain on one audio. Returns ``(result, info, pcm)``. Partials are not recorded."""
        try:
            pcm = audio.to_pcm16k(raw, mime)
        except audio.AudioError as exc:
            raise Invalid(f"audio non leggibile: {exc}")
        seconds = audio.wav_duration(pcm)
        if seconds <= 0.1:
            raise Invalid("audio vuoto")
        if seconds > float(self.get("echo.ascolto.max_seconds", 600) or 600):
            raise Invalid("audio troppo lungo")

        def call(provider, step):
            std = STANDARDS[provider["type"]]
            # Local engines (and every engine in interna) get clean 16 kHz WAV; an external engine that accepts
            # common formats gets the audio as it came (the proxy does not reshape it).
            external = self.blocks.usecase_config(uc, "ascolto")["mode"] == "esterna" and not std.wants_pcm
            data, kind = (raw, mime) if external else (pcm, "audio/wav")
            return std.transcribe(provider, step.get("model") or "", data, kind, language,
                                  _opts(std, provider, step, "ascolto"))

        started = time.monotonic()
        try:
            result, info = self.blocks.run(uc, "ascolto", call)
        except ChainExhausted as exc:
            if record:
                self._record("ascolto", {"use_case": uc}, ms=int((time.monotonic() - started) * 1000), ok=False,
                             seconds=seconds, error=str(exc))
            raise
        if record:
            self._record("ascolto", info, ms=int((time.monotonic() - started) * 1000), ok=True, seconds=seconds)
        return {**result, "duration_s": seconds}, info, pcm

    def transcribe(self, body: dict) -> dict:
        raw = _b64(body.get("audio_b64"))
        if not raw:
            raise Invalid("audio vuoto")
        mime = str(body.get("mime_type") or "audio/ogg").split(";")[0].strip().lower()
        uc = str(body.get("use_case") or "echo.prova.ascolto")
        result, info, _ = self._heard(raw, mime, uc, self.language(body.get("language")))
        blob_id = self._keep(body.get("keep"), "recording", raw, mime,
                             {"use_case": uc, "duration_s": result["duration_s"], "text": result["text"],
                              "provider": info["provider"]})
        return {"text": result["text"], "language": result.get("language") or self.language(),
                "duration_s": result["duration_s"], "provider": info["provider"], "model": info["model"],
                "mode": info["mode"], "fallback": info["fallback"], "blob_id": blob_id}

    # ── speaking ─────────────────────────────────────────────────────────────
    def _spoken(self, text: str, uc: str, voice: str, language: str) -> tuple[bytes, str, dict]:
        """Run the speaking chain on already speakable text. Returns ``(audio, mime, info)``."""

        def call(provider, step):
            std = STANDARDS[provider["type"]]
            return std.speak(provider, step.get("model") or "", voice or step.get("voice") or "", text, language,
                             _opts(std, provider, step, "voce"))

        started = time.monotonic()
        try:
            (data, mime), info = self.blocks.run(uc, "voce", call)
        except ChainExhausted as exc:
            self._record("voce", {"use_case": uc}, ms=int((time.monotonic() - started) * 1000), ok=False,
                         chars=len(text), error=str(exc))
            raise
        self._record("voce", info, ms=int((time.monotonic() - started) * 1000), ok=True, chars=len(text))
        return data, mime, info

    def prepare_text(self, text: str) -> str:
        clean = audio.speakable(text)
        short, cut = audio.shorten(clean, int(self.get("echo.voce.max_chars", 1200) or 1200))
        return short + (" Il resto è nel testo." if cut else "")

    def speak(self, body: dict) -> dict:
        text = str(body.get("text") or "").strip()
        if not text:
            raise Invalid("testo vuoto")
        fmt = str(body.get("format") or "ogg_opus")
        uc = str(body.get("use_case") or "echo.prova.voce")
        keep = body.get("keep") if isinstance(body.get("keep"), dict) else None
        ref = str((keep or {}).get("message_id") or (keep or {}).get("notification_id") or "")
        if ref:                                      # already made for this message: play it again
            try:
                row = self.keep.find(ref, text=text)
                if row is not None:
                    data, mime = self.keep.read(row["id"])
                    self.keep.touch(row)
                    if fmt != "ogg_opus" or mime != "audio/ogg":
                        data, mime = audio.encode(data, fmt)
                    d = row.get("data") or {}
                    return {"audio_b64": base64.b64encode(data).decode(), "mime_type": mime,
                            "duration_s": d.get("duration_s"), "provider": d.get("provider"), "voice": d.get("voice"),
                            "blob_id": row["id"], "reused": True}
            except Exception as exc:
                logger.debug("event=voice_reuse_failed ref=%s error=%s", ref, exc)
        clean = self.prepare_text(text)
        if not clean:
            raise Invalid("niente da leggere")
        data, mime, info = self._spoken(clean, uc, str(body.get("voice") or ""), self.language(body.get("language")))
        try:
            pcm = audio.to_pcm16k(data, mime)
            out, out_mime = audio.encode(data, fmt)
        except audio.AudioError as exc:
            raise Invalid(f"conversione audio: {exc}")
        seconds = audio.wav_duration(pcm)
        blob_id = None
        if keep:
            kept = out if fmt == "ogg_opus" else audio.encode(data, "ogg_opus")[0]
            blob_id = self._keep(keep, "generated", kept, "audio/ogg",
                                 {"use_case": uc, "duration_s": seconds, "text": text, "voice": info["voice"],
                                  "provider": info["provider"]})
        return {"audio_b64": base64.b64encode(out).decode(), "mime_type": out_mime, "duration_s": seconds,
                "provider": info["provider"], "voice": info["voice"] or info["model"], "mode": info["mode"],
                "fallback": info["fallback"], "blob_id": blob_id}

    # ── streams in blocks ────────────────────────────────────────────────────
    def _sweep(self) -> None:
        now = time.monotonic()
        with self._lock:
            for sid in [s for s, v in self._streams.items() if now - v["last"] > STREAM_IDLE_SECONDS]:
                self._streams.pop(sid, None)
                logger.info("event=voice_stream_idle_closed stream=%s", sid)

    def _stream(self, sid: str, kind: str) -> dict:
        self._sweep()
        with self._lock:
            st = self._streams.get(sid)
        if not st or st["kind"] != kind:
            raise NotFound("stream chiuso o inesistente")
        st["last"] = time.monotonic()
        return st

    def _open(self, kind: str, **data) -> dict:
        self._sweep()
        sid = uuid.uuid4().hex[:16]
        with self._lock:
            self._streams[sid] = {"kind": kind, "last": time.monotonic(), **data}
        return {"stream_id": sid}

    def listen_open(self, body: dict) -> dict:
        return self._open("listen", use_case=str(body.get("use_case") or "echo.prova.ascolto"),
                          mime=str(body.get("mime_type") or "audio/webm").split(";")[0].strip().lower(),
                          language=self.language(body.get("language")), buf=bytearray(), partial="", seq=-1,
                          keep=body.get("keep"))

    def listen_chunk(self, sid: str, body: dict) -> dict:
        st = self._stream(sid, "listen")
        seq = int(body.get("seq") if body.get("seq") is not None else st["seq"] + 1)
        if seq <= st["seq"]:                          # a retried chunk: already have it
            return {"partial": st["partial"], "silence_ms": 0, "duration_s": 0}
        st["seq"] = seq
        st["buf"] += _b64(body.get("audio_b64"))
        try:
            pcm = audio.to_pcm16k(bytes(st["buf"]), st["mime"])
        except audio.AudioError:
            return {"partial": st["partial"], "silence_ms": 0, "duration_s": 0}   # a fragment ffmpeg cannot read yet
        seconds = audio.wav_duration(pcm)
        silence = audio.trailing_silence_ms(pcm)
        if body.get("partial", True) and seconds <= PARTIAL_MAX_SECONDS and silence < seconds * 1000:
            try:
                result, _, _ = self._heard(bytes(st["buf"]), st["mime"], st["use_case"], st["language"], record=False)
                st["partial"] = result["text"]
            except (Invalid, ChainExhausted) as exc:
                logger.debug("event=voice_partial_failed stream=%s error=%s", sid, exc)
        return {"partial": st["partial"], "silence_ms": silence, "duration_s": seconds}

    def listen_end(self, sid: str, body: dict | None = None) -> dict:
        st = self._stream(sid, "listen")
        with self._lock:
            self._streams.pop(sid, None)
        if body and body.get("audio_b64"):
            st["buf"] += _b64(body["audio_b64"])
        return self.transcribe({"audio_b64": base64.b64encode(bytes(st["buf"])).decode(), "mime_type": st["mime"],
                                "use_case": st["use_case"], "language": st["language"],
                                "keep": (body or {}).get("keep") or st.get("keep")})

    def say_open(self, body: dict) -> dict:
        return self._open("say", use_case=str(body.get("use_case") or "echo.prova.voce"),
                          fmt=str(body.get("format") or "mp3"), voice=str(body.get("voice") or ""),
                          language=self.language(body.get("language")), cutter=audio.SentenceCutter(), seq=0,
                          pcm=[], text="", keep=body.get("keep"), failed=0)

    def _say_blocks(self, st: dict, sentences: list[str]) -> list[dict]:
        blocks = []
        for sentence in sentences:
            clean = audio.speakable(sentence)
            if not clean:
                continue
            try:
                data, mime, _ = self._spoken(clean, st["use_case"], st["voice"], st["language"])
                out, out_mime = audio.encode(data, st["fmt"])
                st["pcm"].append(audio.to_pcm16k(data, mime))
            except Exception as exc:                  # one sentence lost is better than a stopped reply
                st["failed"] += 1
                logger.warning("[🔄] event=voice_block_failed use_case=%s error=%s fallback=skip_sentence",
                               st["use_case"], str(exc)[:200])
                continue
            blocks.append({"seq": st["seq"], "text": sentence, "mime_type": out_mime,
                           "audio_b64": base64.b64encode(out).decode()})
            st["seq"] += 1
        return blocks

    def say_text(self, sid: str, body: dict) -> dict:
        st = self._stream(sid, "say")
        delta = str(body.get("delta") or "")
        st["text"] += delta
        if len(st["text"]) > int(self.get("echo.voce.max_chars", 1200) or 1200) * 4:
            return {"blocks": []}                     # very long replies: the text is there, the voice stops
        return {"blocks": self._say_blocks(st, st["cutter"].feed(delta))}

    def say_end(self, sid: str, body: dict | None = None) -> dict:
        st = self._stream(sid, "say")
        with self._lock:
            self._streams.pop(sid, None)
        if body and body.get("delta"):
            st["text"] += str(body["delta"])
            st["cutter"].feed(str(body["delta"]))
        blocks = self._say_blocks(st, st["cutter"].flush())
        blob_id = None
        keep = (body or {}).get("keep") or st.get("keep")
        if keep and st["pcm"]:
            try:
                frames = b"".join(audio.wav_frames(p)[0] for p in st["pcm"])
                whole = audio.wav_bytes(frames, 16000)
                blob_id = self._keep(keep, "generated", audio.encode(whole, "ogg_opus")[0], "audio/ogg",
                                     {"use_case": st["use_case"], "duration_s": audio.wav_duration(whole),
                                      "text": st["text"], "voice": st["voice"]})
            except Exception as exc:
                logger.warning("[🔄] event=voice_say_keep_failed error=%s", exc)
        return {"blocks": blocks, "failed": st["failed"], "blob_id": blob_id}

    def streams(self) -> int:
        self._sweep()
        return len(self._streams)
