"""Hestia-Echo — the voice of Hestia: speech → text (ascolto) and text → speech (voce), files and streams in blocks.

SPEC docs/work/2026-10-20-modulo-voce. Built like Oracle a blocchi: named providers (Themis ``echo.providers``,
keys only in env ``ECHO_KEY_<NAME>``), reusable chains with a direction, uses declared by callers, an external
mode where Echo is only the door (proxy to a speech engine). Echo converts sound ↔ text and nothing else: it never
calls Oracle and never decides what to answer. Audio is kept in Archive (blobs + ``echo-store``) by the rule
«never throw away what cannot be made again»; settings in Themis; the daily cleanup is an agenda job (Chronos);
the space warning goes through Hermes; the UI is a core plugin (page «Voce»).
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import requests
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _shared = Path(__file__).resolve().parents[2] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

from hestia_common.agenda_client import AgendaClient, job_rule
from hestia_common.downloads import Downloads
from hestia_common.plugin_client import PluginClient, page
from hestia_common.reminders import reminder_event
from hestia_common.settings_client import SettingsClient, setting

from .core import audio
from .core.blocks import (CHAINS_KEY, COOLDOWN_KEY, DEFAULT_CHAINS, DEFAULT_PROVIDERS, EXTERNAL_KEY,
                          EXTERNAL_MODEL_KEY, FALLBACK_KEY, MODE_KEY, PROVIDERS_KEY, USECASES_KEY, Blocks,
                          ChainExhausted)
from .core.hub import Hub, HubError
from .core.dictionary import Dictionary
from .core.keep import Keep
from .core.voiceprint import Voiceprint, VoiceprintError
from .core.service import Echo, Invalid, NotFound
from .core import standards as _standards
from .core.standards import MODELS_DIR, STANDARDS

logger, log_buffer = setup_service_logging("hestia_echo")

SERVICE_NAME = os.getenv("SERVICE_NAME", "echo")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_echo:19021")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "core")
SERVICE_TAGS = [t.strip().lower() for t in os.getenv("SERVICE_TAGS", "core,voice").split(",") if t.strip()]
SERVICE_TOPOLOGY_TAGS = [t.strip().lower() for t in os.getenv(
    "SERVICE_TOPOLOGY_TAGS", "layer:cognition,domain:voice,status:alpha").split(",") if t.strip()]
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
UI_DIST = os.getenv("ECHO_UI_DIST", "/code/ui/dist")
TZ = os.getenv("TZ") or "Europe/Rome"
API = "/api/voice"

# ── settings (Themis) ────────────────────────────────────────────────────────
MODES = [("interna", "Internal: Echo chains"), ("esterna", "External: one voice engine does everything, Echo is the door")]
FALLBACKS = [("interna", "Back to the internal chains"), ("nessuno", "None: tell me it's not working")]
LANGUAGES = [("auto", "Follow the conversation"), ("it", "Italiano"), ("en", "alt::English"), ("es", "Spanish"),
             ("fr", "French"), ("de", "German")]

settings = SettingsClient("echo").follow_personal()      # owner language for fixed texts (i18n)
settings.declare([
    setting(PROVIDERS_KEY, "Voice providers", "object", DEFAULT_PROVIDERS, group="Voice", order=0,
            editor="voice_providers",
            help="Where the voice engines are: name, standard (local Whisper, Piper, Kokoro, OpenAI compatible, Google, ElevenLabs, Wyoming), address and options. The key lives only in the .env file as ECHO_KEY_<NAME>."),
    setting(CHAINS_KEY, "Listening and voice chains", "object", DEFAULT_CHAINS, group="Voice", order=1,
            editor="voice_chains",
            help="Ordered provider/model or voice lists, each for listening or for voice: if a step fails or runs out of quota I move to the next."),
    setting(USECASES_KEY, "Voice uses", "object", {}, group="Voice", order=2, editor="voice_usecases",
            help="For each declared use (Telegram voice messages, dictation, answers read aloud…): chain and mode. Empty = the suggested choice."),
    setting(MODE_KEY, "Voice mode", "enum", "interna", group="Voice", order=3, options=MODES,
            help="Internal: Echo uses its chains. External: Echo passes everything to a voice engine (yours or in the cloud) and is only the door. Each use can choose its own."),
    setting(EXTERNAL_KEY, "External engine", "enum", "", group="Voice", order=4, options_source=f"{API}/providers/options",
            depends_on={"key": MODE_KEY, "equals": "esterna"}),
    setting(EXTERNAL_MODEL_KEY, "External engine model or voice", "string", "", group="Voice", order=5,
            depends_on={"key": MODE_KEY, "equals": "esterna"}, help="Empty = the engine's default."),
    setting(FALLBACK_KEY, "If the external engine does not answer", "enum", "interna", group="Voice", order=6,
            options=FALLBACKS, depends_on={"key": MODE_KEY, "equals": "esterna"}),
    setting("echo.language", "Language", "enum", "auto", group="Voice", order=7, options=LANGUAGES),
    setting("echo.voce.max_chars", "Longest reading", "int", 1200, group="Voice", order=8, min=200, max=10000,
            unit="characters", help="Beyond it, the voice reads the start and says the rest is in the text."),
    setting("echo.ascolto.max_seconds", "Longest audio accepted", "int", 600, group="Voice", order=9, min=30,
            max=7200, unit="s", advanced=True),
    setting("echo.live.silence_ms", "Pause that ends the live turn", "int", 1250, group="Voice", order=10,
            min=300, max=5000, unit="ms", help="In live mode: how much silence means «I'm done talking»."),
    setting(COOLDOWN_KEY, "Pause of an engine without quota", "int", 60, group="Voice", order=11, min=1, max=1440,
            unit="min", advanced=True, help="When the provider does not say when the quota refills."),
    setting("echo.audio.space_mb", "Space for audio", "int", 2048, group="Audio kept", order=20, min=100,
            max=200000, unit="MB",
            help="Beyond it, I first remove the oldest generated audio (it is remade from the text). I never remove your recordings: if they alone exceed the limit I tell you."),
    setting("echo.audio.generated_days", "Days for generated audio", "int", 30, group="Audio kept",
            order=21, min=1, max=3650, unit="days",
            help="After the last listen. Listening again regenerates them from the text."),
    # ── La tua voce (Cindy 10 + 17, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4) ──
    setting("echo.impronta.soglia", "How much it must resemble your voice", "float", 0.45, group="Your voice",
            order=40, min=0.1, max=0.9,
            help="With your voiceprint recorded, voices below this similarity (TV, other people) become silence before listening. Higher = stricter."),
    setting("echo.impronta.usi", "Where I recognise only your voice", "list", ["webui.live.ascolto"],
            group="Your voice", order=41,
            help="Voice uses where I filter other voices (e.g. webui.live.ascolto, telegram.vocale). Without a recorded voiceprint I filter nothing."),
    setting("echo.dizionario.conferme", "Corrections to learn a word", "int", 2, group="Your voice",
            order=42, min=1, max=10, unit="times",
            help="After how many of your corrections a word enters the dictionary I pass to recognition."),
    setting("echo.pricing", "Prices", "object", {}, group="Voice", order=30, advanced=True,
            help="«provider/model» → {minute: € per minute listened, mchars: € per million characters read}, for the Usage panel."),
])

hub = Hub(HUB_API_URL)

# Voice models (Whisper, Piper, Kokoro, the voiceprint) go through the shared download manager: progress, resume,
# retries, the Download page and a notice when a big one is ready (docs/work/2026-10-30-setup-un-click §4.3).
downloads = Downloads("echo", state_path=MODELS_DIR / "downloads.json", hub=hub, page="voce")
downloads.source("whisper", _standards.whisper_download)
_standards.DOWNLOADS = downloads


def _registry() -> list[dict]:
    resp = requests.get(f"{HUB_API_URL}/registry/services", timeout=4)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        data = data.get("services") or list(data.values())
    return [s for s in data or [] if isinstance(s, dict)]


def _notify(event: dict) -> None:
    try:
        hub.call("hermes", "POST", "api/events/ingest", body=reminder_event(
            module="echo", domain="system", key="echo.audio_space", title=event["title"], text=event["text"],
            actions=[], page="voce", level="warning"))
    except Exception as exc:
        logger.warning("[🔄] event=voice_notify_failed error=%s", exc)


blocks = Blocks(settings.get, _registry)
keep = Keep(hub, settings.get, _notify)
dictionary = Dictionary(keep, settings.get)
voiceprint = Voiceprint(keep, settings.get)
echo = Echo(blocks, keep, settings.get, dictionary=dictionary, voiceprint=voiceprint)
agenda = AgendaClient("echo", HUB_API_URL)

app = FastAPI(title="Hestia-Echo", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Invalid)
async def _invalid(_: Request, exc: Invalid):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ChainExhausted)
async def _exhausted(_: Request, exc: ChainExhausted):
    return JSONResponse(status_code=503, content={"detail": tr("no engine available: {0}", exc)})


@app.exception_handler(HubError)
async def _store_down(_: Request, exc: HubError):
    return JSONResponse(status_code=503, content={"detail": tr("archive not reachable, try again shortly")})


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_echo", "version": SERVICE_VERSION, "ffmpeg": audio.ffmpeg_available(),
            "streams": echo.streams(), "mode": settings.get(MODE_KEY, "interna")}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    logs = log_buffer.query(limit=limit, level=level, contains=contains)
    return {"service": "hestia_echo", "count": len(logs), "logs": logs}


# ── files ────────────────────────────────────────────────────────────────────
@app.post(f"{API}/transcribe")
def transcribe(body: dict = Body(...)):
    return echo.transcribe(body)


@app.post(f"{API}/speak")
def speak(body: dict = Body(...)):
    return echo.speak(body)


# ── streams in blocks ────────────────────────────────────────────────────────
@app.post(f"{API}/listen")
def listen_open(body: dict = Body(default={})):
    return {**echo.listen_open(body), "silence_ms": int(settings.get("echo.live.silence_ms", 900) or 900)}


@app.post(API + "/listen/{sid}/chunk")
def listen_chunk(sid: str, body: dict = Body(...)):
    return echo.listen_chunk(sid, body)


@app.post(API + "/listen/{sid}/end")
def listen_end(sid: str, body: dict = Body(default={})):
    return echo.listen_end(sid, body)


@app.post(f"{API}/say")
def say_open(body: dict = Body(default={})):
    return echo.say_open(body)


@app.post(API + "/say/{sid}/text")
def say_text(sid: str, body: dict = Body(...)):
    return echo.say_text(sid, body)


@app.post(API + "/say/{sid}/end")
def say_end(sid: str, body: dict = Body(default={})):
    return echo.say_end(sid, body)


# ── blocks ───────────────────────────────────────────────────────────────────
@app.get(f"{API}/standards")
def standards():
    return {"items": [s.describe() for s in STANDARDS.values()]}


@app.get(f"{API}/providers")
def providers():
    return {"items": blocks.describe_providers(echo.language()), "mode": settings.get(MODE_KEY, "interna"),
            "external": settings.get(EXTERNAL_KEY, "")}


@app.get(f"{API}/providers/options")
def provider_options():
    """Options of «Motore esterno» (Themis ``options_source``)."""
    return {"options": [{"value": "", "label": "—"}] + [
        {"value": p["name"], "label": p["label"]} for p in blocks.providers().values()]}


@app.post(API + "/providers/{name}/retry")
def provider_retry(name: str):
    blocks.clear_exhausted(name)
    return {"status": "ok"}


@app.get(f"{API}/chains")
def chains():
    return {"items": blocks.describe_chains()}


@app.get(f"{API}/usecases")
def usecases():
    return {"items": blocks.describe_usecases()}


_PARTS = {"providers": PROVIDERS_KEY, "chains": CHAINS_KEY, "usecases": USECASES_KEY}


@app.put(API + "/blocks/{part}")
def blocks_write(part: str, body: dict = Body(...)):
    """Marko's edit from the page Voce (providers | chains | usecases): stored through Themis."""
    key = _PARTS.get(part)
    value = body.get("value")
    if not key:
        raise NotFound(tr("unknown part: providers, chains or usecases"))
    if not isinstance(value, dict) or any(not isinstance(v, dict) for v in value.values()):
        raise Invalid(tr("an object name → settings is needed"))
    if part == "providers":
        bad = [n for n, p in value.items() if p.get("type") not in STANDARDS]
        if bad or not value:
            raise Invalid(tr("unknown standard for: {0}", ', '.join(bad) or tr('no provider')))
    elif part == "chains":
        if not value or any(c.get("direction") not in ("ascolto", "voce") or not isinstance(c.get("steps"), list)
                            for c in value.values()):
            raise Invalid(tr("each chain needs a direction (listening or voice) and a list of steps"))
    if not settings.put(key, value, actor="user", reason=tr("WebUI Voice")):
        raise HTTPException(status_code=502, detail=tr("The settings did not accept the change"))
    return {"status": "ok", "key": key}


@app.get(f"{API}/usage")
def usage(days: int = 30):
    rows = keep.usage(days)
    by: dict[str, dict] = {}
    for r in rows:
        for key in (f"use:{r.get('use_case')}", f"provider:{r.get('provider')}/{r.get('model')}"):
            b = by.setdefault(key, {"calls": 0, "seconds": 0.0, "chars": 0, "cost": 0.0, "errors": 0})
            b["calls"] += 1
            b["seconds"] += float(r.get("seconds") or 0)
            b["chars"] += int(r.get("chars") or 0)
            b["cost"] += float(r.get("cost") or 0)
            b["errors"] += 0 if r.get("ok") else 1
    totals = {"calls": len(rows), "minutes": round(sum(float(r.get("seconds") or 0) for r in rows) / 60, 1),
              "chars": sum(int(r.get("chars") or 0) for r in rows),
              "cost": round(sum(float(r.get("cost") or 0) for r in rows), 4),
              "errors": sum(1 for r in rows if not r.get("ok"))}
    return {"days": days, "totals": totals,
            "by_use": {k[4:]: v for k, v in by.items() if k.startswith("use:")},
            "by_provider": {k[9:]: v for k, v in by.items() if k.startswith("provider:")},
            "recent": rows[:50]}


@app.get(f"{API}/live")
def live_config():
    """What a client needs for live mode («Parla», /live): the pause that closes a turn."""
    return {"silence_ms": int(settings.get("echo.live.silence_ms", 1250) or 1250), "language": echo.language(),
            "voiceprint": voiceprint.applies("webui.live.ascolto")}


@app.get(f"{API}/recent")
def recent():
    return {"items": list(echo.recent)}


# ── kept audio ───────────────────────────────────────────────────────────────
@app.get(f"{API}/audio")
def audio_list(kind: str = "", limit: int = 200):
    rows = keep.list(kind, limit)
    return {"items": [{"blob_id": r["id"], "at": r.get("at"), "ref_id": r.get("ref_id"),
                       "session_id": r.get("parent_id"), **(r.get("data") or {})} for r in rows],
            "space": keep.space()}


@app.get(API + "/audio/{blob_id}")
def audio_get(blob_id: str, format: str = ""):
    data, mime = keep.read(blob_id)
    if format:
        data, mime = audio.encode(data, format)
    return {"blob_id": blob_id, "mime_type": mime, "audio_b64": base64.b64encode(data).decode()}


@app.get(f"{API}/audio-for")
def audio_for(ref_id: str, format: str = ""):
    """Kept audio of a message or notification (an old voice note plays the original)."""
    row = keep.find(ref_id)
    if row is None:
        raise NotFound(tr("no audio for this message"))
    keep.touch(row)
    return {**audio_get(row["id"], format), **(row.get("data") or {})}


@app.delete(API + "/audio/{blob_id}")
def audio_delete(blob_id: str):
    rows = [r for r in keep.list("", 20000) if r["id"] == blob_id]
    if not rows:
        raise NotFound(tr("audio not found"))
    keep.delete(rows[0])
    return {"status": "deleted", "blob_id": blob_id}


@app.delete(f"{API}/audio")
def audio_forget(notification_id: str = "", message_id: str = ""):
    """A notification (or message) was removed: its regenerable audio goes with it."""
    if not (notification_id or message_id):
        raise Invalid(tr("notification_id or message_id needed"))
    return {"removed": keep.forget(notification_id=notification_id, message_id=message_id)}


@app.post(f"{API}/audio/cleanup")
def audio_cleanup():
    return keep.cleanup()


# ── your voice: dictionary + voiceprint (Cindy 17 + 10) ─────────────────────
@app.get(f"{API}/dictionary")
def dictionary_list():
    """Personal words passed to the listening engines (confirmed) and the candidates learnt from corrections."""
    items = dictionary.list()
    return {"items": items, "confirmed": sum(1 for d in items if d.get("status") == "confirmed"),
            "needed": dictionary.needed()}


@app.post(f"{API}/dictionary")
def dictionary_add(body: dict = Body(...)):
    try:
        return {"status": "ok", "word": dictionary.add(str(body.get("word") or ""), source="manual"),
                "message": tr("Word added")}
    except ValueError as exc:
        raise Invalid(str(exc))


@app.delete(API + "/dictionary/{word}")
def dictionary_remove(word: str):
    if not dictionary.remove(word):
        raise NotFound(tr("word not in the dictionary"))
    return {"status": "ok", "message": tr("Word removed")}


@app.post(f"{API}/dictionary/learn")
def dictionary_learn(body: dict = Body(...)):
    """A transcript corrected by the owner: ``{heard, corrected}`` → words counted (confirmed after N)."""
    return dictionary.learn(str(body.get("heard") or ""), str(body.get("corrected") or ""))


def _audio_body(body: dict) -> tuple[bytes, str]:
    f = body.get("audio") if isinstance(body.get("audio"), dict) else {}
    raw = base64.b64decode(str(body.get("audio_b64") or f.get("data_b64") or "").split(",", 1)[-1] or b"")
    if not raw:
        raise Invalid(tr("empty audio"))
    return raw, str(body.get("mime_type") or f.get("mime") or "audio/ogg").split(";")[0].strip().lower()


@app.get(f"{API}/voiceprint")
def voiceprint_status():
    return voiceprint.status()


@app.post(f"{API}/voiceprint")
def voiceprint_enroll(body: dict = Body(...)):
    """Record the owner's voice once (≥ 6 s of speech): ``{audio_b64, mime_type}`` or ``{audio: {data_b64, mime}}``."""
    raw, mime = _audio_body(body)
    try:
        pcm = audio.to_pcm16k(raw, mime)
    except audio.AudioError as exc:
        raise Invalid(tr("audio not readable: {0}", exc))
    blob = None
    try:
        blob = keep.save("recording", audio.keep_encode(raw), audio.KEEP_MIME,
                         {"use_case": "echo.impronta", "text": tr("voice print")})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=voiceprint_recording_not_kept error=%s", exc)
    try:
        out = voiceprint.enroll(pcm, blob)
    except VoiceprintError as exc:
        raise Invalid(str(exc))
    except Exception as exc:  # noqa: BLE001 — engine not available
        logger.warning("[🔄] event=voiceprint_engine_unavailable error=%s", exc)
        raise HTTPException(status_code=503, detail=tr("voice recognition not available now"))
    return {**out, "status": "ok", "message": tr("Voice print saved")}


@app.delete(f"{API}/voiceprint")
def voiceprint_forget():
    return {**voiceprint.forget(), "status": "ok", "message": tr("Voice print removed: I listen to every voice")}


def _agenda_rules() -> list[dict]:
    return [job_rule("echo.audio_cleanup", "Voice: audio cleanup", service="echo", path=f"{API}/audio/cleanup",
                     recurrence="FREQ=DAILY", start_at="2026-01-01T04:30:00", tz=TZ,
                     description="Removes generated audio not listened to for a long time and keeps the space under the limit. Recordings are never touched.")]


# ── plugin (UI bundle, core) ─────────────────────────────────────────────────
ui = PluginClient("echo", title="Voice", icon="mic", color="teal", kind="core", dist=UI_DIST,
                  description="Hestia's listening and voice: providers, chains, uses, tests, usage and stored audio.",
                  version=SERVICE_VERSION)
ui.webui(entry="echo.js", api_prefix=f"{API}/",
         pages=[page("voce", "Voice", element="echo-voice", icon="mic", order=125,
                     help="How Hestia listens and speaks: providers, listening and voice chains, uses of every module, external mode, microphone and voice test, usage and costs, your recordings.")])
# ── MCP tools (assistant, Telegram, WebUI): your voice ───────────────────────
from hestia_common.mcp_helpers import MCPTool, create_mcp_router  # noqa: E402


def _t(name, title, description, method, path, props=None, required=None, label=None, writes_note=""):
    return MCPTool(name=name, title=title, description=description + writes_note,
                   parameters={"type": "object", "properties": props or {}, "required": required or []},
                   handler=lambda **_kw: {"status": "ok"}, method=method, path=path,
                   clients=["telegram", "ui"], response_mode="oracle_natural",
                   telegram_visible=True, telegram_group="sistema",
                   telegram={"section": tr("Voice"), **({"label": label} if label else {})})


_echo_tools = [
    _t("voce_download", "Voice download", "The voices and the listening models being downloaded or downloaded, with progress.", "GET", "/api/downloads", label="alt::Download"),
    _t("voce_scarica", "Download the voices", ("Download now (or retry) the local voices and listening models of the chains in use, so the "
                                           "first sentence does not wait."), "POST", f"{API}/models/prefetch", label="Download voices"),
    _t("voce_dizionario", "Voice dictionary", ("The user's own words (names, terms) passed to speech recognition, and those being learned from "
                                                    "their corrections."), "GET", f"{API}/dictionary",
       label="Dictionary"),
    _t("voce_parola", "Add a word", "Add a word to the voice dictionary (a name, a term speech recognition gets wrong).", "POST", f"{API}/dictionary",
       {"word": {"type": "string", "description": "The word, spelled right"}}, ["word"]),
    _t("voce_parola_togli", "Remove a word", "Remove a word from the voice dictionary.", "DELETE",
       API + "/dictionary/{word}", {"word": {"type": "string", "description": "The word to remove"}}, ["word"]),
    _t("voce_correzione", "Fix a transcription", ("When the user corrects a badly transcribed voice message («I meant …»): text heard and right text; new words enter the dictionary after a few corrections."), "POST", f"{API}/dictionary/learn",
       {"heard": {"type": "string", "description": "What was transcribed"},
        "corrected": {"type": "string", "description": "The right text"}}, ["heard", "corrected"]),
    _t("voce_impronta", "Your voice", "Whether the user's voiceprint exists and where only their voice is recognised.", "GET",
       f"{API}/voiceprint"),
    _t("voce_impronta_registra", "Record your voice", ("Record at least 10 seconds of the user's voice: then other voices (TV, people) do not end up in "
                                                          "their messages where they chose so."), "POST", f"{API}/voiceprint",
       {"audio": {"type": "string", "contentMediaType": "audio/*",
                  "description": "A voice message of at least 10 seconds where the user speaks"}}, ["audio"]),
    _t("voce_impronta_togli", "alt::Remove the voiceprint", "Forget the user's voiceprint: listen to every voice.",
       "DELETE", f"{API}/voiceprint"),
]
app.include_router(create_mcp_router(_echo_tools, service_name="echo"))
app.include_router(ui.router())
app.include_router(settings.router())
app.include_router(create_log_control_router("hestia_echo"))
app.include_router(downloads.router())


@app.post(f"{API}/models/prefetch")
def models_prefetch():
    """Queue the local models of the first steps of the «ascolto» and «voce» chains (guided setup, Download page),
    so the first spoken sentence does not wait for them. Cloud steps need nothing."""
    return _prefetch()


def _prefetch(chains: dict | None = None) -> dict:
    """``chains`` = the ones just written (Themis pushes the new value back a moment later)."""
    providers = settings.get(PROVIDERS_KEY, DEFAULT_PROVIDERS) or {}
    chains = chains or settings.get(CHAINS_KEY, DEFAULT_CHAINS) or {}
    queued: list[str] = []
    for name in ("ascolto", "voce"):
        for step in (chains.get(name) or {}).get("steps") or []:
            kind = (providers.get(step.get("provider")) or {}).get("type", "")
            ids = _standards.prefetch(kind, step.get("model") or "", step.get("voice") or "")
            if ids:
                queued += ids
                break
    logger.info("event=voice_models_prefetch jobs=%d", len(queued))
    return {"queued": queued, "downloads": downloads.list()}


# ── Setup guidato «Voce» (core/voice_setup.py): same shape as the models screen ─────────────
@app.get(f"{API}/setup/catalog")
def voice_setup_catalog(hosts: str = ""):
    """Providers per direction (listening, speaking), local first, with their models/voices and the current step;
    plus the speech programs found at home (this computer and the computers named in ``hosts``)."""
    from .core import voice_setup
    return {"status": "ok", **voice_setup.catalog(blocks, echo.language(), hosts)}


@app.post(f"{API}/setup/test")
def voice_setup_test(body: dict = Body(...)):
    """«Prova» of a speech service: its list read with the key, nothing spent."""
    from .core import voice_setup
    return {"status": "ok", **voice_setup.check(blocks, str(body.get("provider") or ""), echo.language())}


@app.post(f"{API}/setup/preview")
def voice_setup_preview(body: dict = Body(...)):
    """«Ascolta» in the setup: a short sentence with that provider and voice, before the choice is saved."""
    return {"status": "ok", **echo.setup_preview(body)}


@app.post(f"{API}/setup/hear")
def voice_setup_hear(body: dict = Body(...)):
    """«Prova» of listening in the setup: the recording heard by that provider and model, before saving."""
    return {"status": "ok", **echo.setup_hear(body)}


@app.post(f"{API}/setup/reload-keys")
def voice_setup_reload_keys():
    """Re-read the ``ECHO_KEY_*`` lines of Echo's own .env (no restart) → the names that have a value."""
    from .core import blocks as _blocks
    return {"status": "ok", "keys": _blocks.reload_keys()}


@app.post(f"{API}/setup/apply")
def voice_setup_apply(body: dict = Body(...)):
    """The choice → ``echo.chains`` (chosen step first, the others as fallbacks), then the local models it needs
    are queued in Download."""
    from .core import voice_setup
    listen, speak = body.get("listen") or None, body.get("speak") or None
    result = voice_setup.apply(blocks, settings.put, listen, speak)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("detail"))
    return {"status": "ok", **_prefetch(result["chains"])}


# ── Hub registration ─────────────────────────────────────────────────────────
def _registration() -> dict:
    caps: dict = {"voice": {"api": API, "standards": list(STANDARDS)},
                  "mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp", "module_tool_domains": ["voice"],
                  # Owner of the "voice" tools in chat: without it Oracle's domain gate dropped them (2026-10-30).
                  "owns_tool_domains": ["voice"], **downloads.capabilities()}
    try:
        caps.update(ui.capabilities(SERVICE_BASE_URL))
    except Exception as exc:
        logger.warning("[🔄] event=echo_ui_manifest_failed error=%s fallback=no_ui", exc)
    return {"name": SERVICE_NAME, "base_url": SERVICE_BASE_URL, "health_endpoint": "/health",
            "service_type": SERVICE_TYPE, "service_version": SERVICE_VERSION, "tags": SERVICE_TAGS,
            "topology_tags": SERVICE_TOPOLOGY_TAGS, "capabilities": caps}


def _register() -> None:
    resp = requests.post(f"{HUB_API_URL}/registry/register", json=_registration(), timeout=4)
    if resp.status_code >= 400:
        logger.warning("event=hub_registration_non_success status=%s body=%s", resp.status_code, resp.text[:200])
    else:
        logger.info("event=registered_on_hub hub=%s base_url=%s", HUB_API_URL, SERVICE_BASE_URL)


@app.on_event("startup")
def startup():
    try:   # keys saved by the setup after the container was created
        from .core import blocks as _blocks
        _blocks.reload_keys()
    except Exception as exc:
        logger.warning("[🔄] event=echo_keys_reload_failed error=%s", exc)
    if not audio.ffmpeg_available():
        logger.error("event=echo_ffmpeg_missing (conversions will fail)")
    try:
        _register()
    except Exception as exc:
        logger.warning("[🔄] event=hub_registration_failed_non_fatal error=%s", exc)
    from hestia_common.startup_utils import start_hub_keepalive
    start_hub_keepalive(_register, logger=logger, name="echo-hub-keepalive")
    settings.start()
    agenda.register_async(_agenda_rules)
