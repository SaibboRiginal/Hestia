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

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _shared = Path(__file__).resolve().parents[2] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

from hestia_common.agenda_client import AgendaClient, job_rule
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
from .core.standards import STANDARDS

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
MODES = [("interna", "Interna: catene di Echo"), ("esterna", "Esterna: un motore voce fa tutto, Echo fa da porta")]
FALLBACKS = [("interna", "Torna alle catene interne"), ("nessuno", "Nessuno: dimmi che non va")]
LANGUAGES = [("it", "Italiano"), ("en", "Inglese"), ("es", "Spagnolo"), ("fr", "Francese"), ("de", "Tedesco"),
             ("auto", "Riconosci da solo (solo ascolto)")]

settings = SettingsClient("echo")
settings.declare([
    setting(PROVIDERS_KEY, "Fornitori della voce", "object", DEFAULT_PROVIDERS, group="Voce", order=0,
            editor="voice_providers",
            help="Dove stanno i motori della voce: nome, standard (Whisper locale, Piper, Kokoro, compatibile OpenAI, "
                 "Google, ElevenLabs, Wyoming), indirizzo e opzioni. La chiave sta solo nel file .env come "
                 "ECHO_KEY_<NOME>."),
    setting(CHAINS_KEY, "Catene di ascolto e voce", "object", DEFAULT_CHAINS, group="Voce", order=1,
            editor="voice_chains",
            help="Liste ordinate fornitore/modello o voce, ognuna di ascolto o di voce: se un passo non va o finisce "
                 "la quota passo al successivo."),
    setting(USECASES_KEY, "Usi della voce", "object", {}, group="Voce", order=2, editor="voice_usecases",
            help="Per ogni uso dichiarato (vocali di Telegram, dettatura, risposte lette…): catena e modalità. "
                 "Vuoto = la scelta suggerita."),
    setting(MODE_KEY, "Modalità della voce", "enum", "interna", group="Voce", order=3, options=MODES,
            help="Interna: Echo usa le sue catene. Esterna: Echo passa tutto a un motore voce (tuo o nel cloud) e "
                 "fa solo da porta. Ogni uso può scegliere la sua."),
    setting(EXTERNAL_KEY, "Motore esterno", "enum", "", group="Voce", order=4, options_source=f"{API}/providers/options",
            depends_on={"key": MODE_KEY, "equals": "esterna"}),
    setting(EXTERNAL_MODEL_KEY, "Modello o voce del motore esterno", "string", "", group="Voce", order=5,
            depends_on={"key": MODE_KEY, "equals": "esterna"}, help="Vuoto = quello predefinito del motore."),
    setting(FALLBACK_KEY, "Se il motore esterno non risponde", "enum", "interna", group="Voce", order=6,
            options=FALLBACKS, depends_on={"key": MODE_KEY, "equals": "esterna"}),
    setting("echo.language", "Lingua", "enum", "it", group="Voce", order=7, options=LANGUAGES),
    setting("echo.voce.max_chars", "Lettura massima", "int", 1200, group="Voce", order=8, min=200, max=10000,
            unit="caratteri", help="Oltre, la voce legge l'inizio e dice che il resto è nel testo."),
    setting("echo.ascolto.max_seconds", "Audio più lungo accettato", "int", 600, group="Voce", order=9, min=30,
            max=7200, unit="s", advanced=True),
    setting("echo.live.silence_ms", "Pausa che chiude il turno dal vivo", "int", 1250, group="Voce", order=10,
            min=300, max=5000, unit="ms", help="In modalità live: quanto silenzio vuol dire «ho finito di parlare»."),
    setting(COOLDOWN_KEY, "Pausa di un motore senza quota", "int", 60, group="Voce", order=11, min=1, max=1440,
            unit="min", advanced=True, help="Quando il fornitore non dice quando si ricarica la quota."),
    setting("echo.audio.space_mb", "Spazio per gli audio", "int", 2048, group="Audio conservati", order=20, min=100,
            max=200000, unit="MB",
            help="Oltre, tolgo prima gli audio generati più vecchi (si rifanno dal testo). Le tue registrazioni non "
                 "le tolgo mai: se da sole superano il limite ti avviso."),
    setting("echo.audio.generated_days", "Giorni per gli audio generati", "int", 30, group="Audio conservati",
            order=21, min=1, max=3650, unit="giorni",
            help="Dopo l'ultimo ascolto. Riascoltando si rigenerano dal testo."),
    # ── La tua voce (Cindy 10 + 17, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4) ──
    setting("echo.impronta.soglia", "Quanto deve somigliare alla tua voce", "float", 0.45, group="La tua voce",
            order=40, min=0.1, max=0.9,
            help="Con la tua impronta registrata, le voci sotto questa somiglianza (TV, altre persone) diventano "
                 "silenzio prima dell'ascolto. Più alto = più severo."),
    setting("echo.impronta.usi", "Dove riconosco solo la tua voce", "list", ["webui.live.ascolto"],
            group="La tua voce", order=41,
            help="Usi della voce dove filtro le altre voci (es. webui.live.ascolto, telegram.vocale). "
                 "Senza impronta registrata non filtro nulla."),
    setting("echo.dizionario.conferme", "Correzioni per imparare una parola", "int", 2, group="La tua voce",
            order=42, min=1, max=10, unit="volte",
            help="Dopo quante tue correzioni una parola entra nel dizionario che passo al riconoscimento."),
    setting("echo.pricing", "Prezzi", "object", {}, group="Voce", order=30, advanced=True,
            help="«fornitore/modello» → {minute: € al minuto ascoltato, mchars: € per milione di caratteri letti}, "
                 "per il pannello Uso."),
])

hub = Hub(HUB_API_URL)


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
    return JSONResponse(status_code=503, content={"detail": f"nessun motore disponibile: {exc}"})


@app.exception_handler(HubError)
async def _store_down(_: Request, exc: HubError):
    return JSONResponse(status_code=503, content={"detail": "archivio non raggiungibile, riprova tra poco"})


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
        raise NotFound("parte sconosciuta: providers, chains o usecases")
    if not isinstance(value, dict) or any(not isinstance(v, dict) for v in value.values()):
        raise Invalid("serve un oggetto nome → impostazioni")
    if part == "providers":
        bad = [n for n, p in value.items() if p.get("type") not in STANDARDS]
        if bad or not value:
            raise Invalid(f"standard sconosciuto per: {', '.join(bad) or 'nessun fornitore'}")
    elif part == "chains":
        if not value or any(c.get("direction") not in ("ascolto", "voce") or not isinstance(c.get("steps"), list)
                            for c in value.values()):
            raise Invalid("ogni catena vuole una direzione (ascolto o voce) e una lista di passi")
    if not settings.put(key, value, actor="user", reason="WebUI Voce"):
        raise HTTPException(status_code=502, detail="Le impostazioni non hanno accettato la modifica")
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
        raise NotFound("nessun audio per questo messaggio")
    keep.touch(row)
    return {**audio_get(row["id"], format), **(row.get("data") or {})}


@app.delete(API + "/audio/{blob_id}")
def audio_delete(blob_id: str):
    rows = [r for r in keep.list("", 20000) if r["id"] == blob_id]
    if not rows:
        raise NotFound("audio non trovato")
    keep.delete(rows[0])
    return {"status": "deleted", "blob_id": blob_id}


@app.delete(f"{API}/audio")
def audio_forget(notification_id: str = "", message_id: str = ""):
    """A notification (or message) was removed: its regenerable audio goes with it."""
    if not (notification_id or message_id):
        raise Invalid("serve notification_id o message_id")
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
                "message": "Parola aggiunta"}
    except ValueError as exc:
        raise Invalid(str(exc))


@app.delete(API + "/dictionary/{word}")
def dictionary_remove(word: str):
    if not dictionary.remove(word):
        raise NotFound("parola non nel dizionario")
    return {"status": "ok", "message": "Parola tolta"}


@app.post(f"{API}/dictionary/learn")
def dictionary_learn(body: dict = Body(...)):
    """A transcript corrected by the owner: ``{heard, corrected}`` → words counted (confirmed after N)."""
    return dictionary.learn(str(body.get("heard") or ""), str(body.get("corrected") or ""))


def _audio_body(body: dict) -> tuple[bytes, str]:
    f = body.get("audio") if isinstance(body.get("audio"), dict) else {}
    raw = base64.b64decode(str(body.get("audio_b64") or f.get("data_b64") or "").split(",", 1)[-1] or b"")
    if not raw:
        raise Invalid("audio vuoto")
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
        raise Invalid(f"audio non leggibile: {exc}")
    blob = None
    try:
        blob = keep.save("recording", audio.keep_encode(raw), audio.KEEP_MIME,
                         {"use_case": "echo.impronta", "text": "impronta della voce"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=voiceprint_recording_not_kept error=%s", exc)
    try:
        out = voiceprint.enroll(pcm, blob)
    except VoiceprintError as exc:
        raise Invalid(str(exc))
    except Exception as exc:  # noqa: BLE001 — engine not available
        logger.warning("[🔄] event=voiceprint_engine_unavailable error=%s", exc)
        raise HTTPException(status_code=503, detail="riconoscimento della voce non disponibile ora")
    return {**out, "status": "ok", "message": "Impronta della voce salvata"}


@app.delete(f"{API}/voiceprint")
def voiceprint_forget():
    return {**voiceprint.forget(), "status": "ok", "message": "Impronta tolta: ascolto tutte le voci"}


def _agenda_rules() -> list[dict]:
    return [job_rule("echo.audio_cleanup", "Voce: pulizia degli audio", service="echo", path=f"{API}/audio/cleanup",
                     recurrence="FREQ=DAILY", start_at="2026-01-01T04:30:00", tz=TZ,
                     description="Toglie gli audio generati non ascoltati da tempo e tiene lo spazio sotto il limite. "
                                 "Le registrazioni non si toccano.")]


# ── plugin (UI bundle, core) ─────────────────────────────────────────────────
ui = PluginClient("echo", title="Voce", icon="mic", color="teal", kind="core", dist=UI_DIST,
                  description="Ascolto e voce di Hestia: fornitori, catene, usi, prove, uso e audio conservati.",
                  version=SERVICE_VERSION)
ui.webui(entry="echo.js", api_prefix=f"{API}/",
         pages=[page("voce", "Voce", element="echo-voice", icon="mic", order=125,
                     help="Come Hestia ascolta e parla: fornitori, catene di ascolto e di voce, usi di ogni modulo, "
                          "modalità esterna, prova del microfono e delle voci, uso e costi, le tue registrazioni.")])
# ── MCP tools (assistant, Telegram, WebUI): your voice ───────────────────────
from hestia_common.mcp_helpers import MCPTool, create_mcp_router  # noqa: E402


def _t(name, title, description, method, path, props=None, required=None, label=None, writes_note=""):
    return MCPTool(name=name, title=title, description=description + writes_note,
                   parameters={"type": "object", "properties": props or {}, "required": required or []},
                   handler=lambda **_kw: {"status": "ok"}, method=method, path=path,
                   clients=["telegram", "ui"], response_mode="oracle_natural",
                   telegram_visible=True, telegram_group="sistema",
                   telegram={"section": "Voce", **({"label": label} if label else {})})


_echo_tools = [
    _t("voce_dizionario", "Dizionario della voce", "Le parole tue (nomi, termini) che passo al riconoscimento "
       "della voce, e quelle che sto imparando dalle tue correzioni.", "GET", f"{API}/dictionary",
       label="Dizionario"),
    _t("voce_parola", "Aggiungi una parola", "Aggiungi una parola al dizionario della voce (un nome, un termine "
       "che non capisco bene).", "POST", f"{API}/dictionary",
       {"word": {"type": "string", "description": "La parola, scritta giusta"}}, ["word"]),
    _t("voce_parola_togli", "Togli una parola", "Togli una parola dal dizionario della voce.", "DELETE",
       API + "/dictionary/{word}", {"word": {"type": "string", "description": "La parola da togliere"}}, ["word"]),
    _t("voce_correzione", "Correggi una trascrizione", "Quando l'utente corregge un vocale trascritto male "
       "(«volevo dire …»): testo sentito e testo giusto; le parole nuove entrano nel dizionario dopo qualche "
       "correzione.", "POST", f"{API}/dictionary/learn",
       {"heard": {"type": "string", "description": "Cosa avevo trascritto"},
        "corrected": {"type": "string", "description": "Il testo giusto"}}, ["heard", "corrected"]),
    _t("voce_impronta", "La tua voce", "Se ho la tua impronta della voce e dove riconosco solo te.", "GET",
       f"{API}/voiceprint"),
    _t("voce_impronta_registra", "Registra la tua voce", "Registra almeno 10 secondi della tua voce: poi le "
       "altre voci (TV, persone) non finiscono nei tuoi messaggi dove lo hai scelto.", "POST", f"{API}/voiceprint",
       {"audio": {"type": "string", "contentMediaType": "audio/*",
                  "description": "Un vocale di almeno 10 secondi in cui parli tu"}}, ["audio"]),
    _t("voce_impronta_togli", "Togli l'impronta della voce", "Dimentica la tua impronta: ascolto tutte le voci.",
       "DELETE", f"{API}/voiceprint"),
]
app.include_router(create_mcp_router(_echo_tools, service_name="echo"))
app.include_router(ui.router())
app.include_router(settings.router())
app.include_router(create_log_control_router("hestia_echo"))


# ── Hub registration ─────────────────────────────────────────────────────────
def _registration() -> dict:
    caps: dict = {"voice": {"api": API, "standards": list(STANDARDS)},
                  "mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp", "module_tool_domains": ["voice"]}
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
