"""Client of the voice module Echo, through the Hub (the only door). Dossier ``docs/work/2026-10-20-modulo-voce``.

Callers (Telegram, Oracle, Hermes, the WebUI backend) never touch audio engines: they send bytes and get text,
or send text and get bytes. Failures return ``None`` so every caller keeps its own fallback (``[🔄]``).

    voice = VoiceClient(HUB_API_URL)
    heard = voice.transcribe(ogg_bytes, "audio/ogg", use_case="telegram.vocale",
                             keep={"kind": "recording", "session_id": sid, "message_id": mid, "client": "telegram"})
    spoken = voice.speak(text, use_case="telegram.risposta", fmt="ogg_opus",
                         keep={"kind": "generated", "message_id": mid})
    if spoken: send_voice(spoken["audio"])
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

import requests

logger = logging.getLogger("hestia_common.voice_client")


class VoiceClient:
    def __init__(self, hub_api_url: str | None = None, *, service: str = "echo"):
        self.base = (hub_api_url or os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")
        self.service = service
        self._session = requests.Session()

    def call(self, method: str, path: str, body: Any = None, *, query: dict | None = None,
             timeout: float = 60) -> tuple[int, Any]:
        resp = self._session.post(
            f"{self.base}/route/{self.service}/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": query or {}, "body": body, "timeout_seconds": timeout},
            timeout=timeout + 5)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    def _ok(self, method: str, path: str, body: Any = None, **kw) -> Any:
        try:
            status, payload = self.call(method, path, body, **kw)
        except Exception as exc:
            logger.warning("[🔄] event=voice_unreachable path=%s error=%s", path, exc)
            return None
        if status >= 400:
            logger.warning("[🔄] event=voice_failed path=%s status=%s detail=%s", path, status, str(payload)[:200])
            return None
        return payload

    def transcribe(self, audio: bytes, mime_type: str, *, use_case: str, language: str = "",
                   keep: dict | None = None, timeout: float = 180) -> dict | None:
        """``{text, language, duration_s, provider, model, blob_id?}`` or ``None``."""
        body = {"audio_b64": base64.b64encode(audio).decode(), "mime_type": mime_type, "use_case": use_case,
                "language": language or None, "keep": keep}
        out = self._ok("POST", "api/voice/transcribe", body, timeout=timeout)
        return out if isinstance(out, dict) and str(out.get("text") or "").strip() else None

    def speak(self, text: str, *, use_case: str, fmt: str = "ogg_opus", voice: str = "",
              keep: dict | None = None, timeout: float = 120) -> dict | None:
        """``{audio (bytes), mime_type, duration_s, provider, voice, blob_id?}`` or ``None``."""
        body = {"text": text, "format": fmt, "use_case": use_case, "voice": voice or None, "keep": keep}
        out = self._ok("POST", "api/voice/speak", body, timeout=timeout)
        if not isinstance(out, dict) or not out.get("audio_b64"):
            return None
        return {**{k: v for k, v in out.items() if k != "audio_b64"}, "audio": base64.b64decode(out["audio_b64"])}

    def forget(self, *, notification_id: str = "", message_id: str = "") -> None:
        """Drop the audio that belongs to a removed notification (or message)."""
        query = {k: v for k, v in (("notification_id", notification_id), ("message_id", message_id)) if v}
        if query:
            self._ok("DELETE", "api/voice/audio", None, query=query, timeout=15)
