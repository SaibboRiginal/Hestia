"""The owner's devices: Garmin watch (B10) and Android phone as a sensor (Cindy 32).

Dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4. Hecate owns the devices and only passes their data on:
- **Garmin**: «Collega Garmin» asks email/password with the Hermes secret form (never stored, only the tokens in
  ``HECATE_GARMIN_TOKENS``), a second form for the two-step code; the agenda job ``hecate.garmin.sync`` (daily
  09:30, user-movable) reads yesterday and today and pushes each day as the ``wearable.daily`` feed (Hercules:
  activities + readiness, Hygieia: sleep) and tells presence when the owner woke up.
- **Phone**: a Tasker-like app POSTs to ``/api/gateway/phone/push`` with header ``X-Hestia-Phone-Token`` =
  ``HECATE_PHONE_TOKEN`` (env, secret; empty = the webhook answers 503). ``{type: state, wifi, charging, battery}``
  → presence signals ``phone.home`` / ``phone.charging`` + feed ``phone.state``; ``{type: notification, app, title,
  text}`` → feed ``phone.notification`` when the app is in ``hecate.telefono.app`` (empty list = every app).
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from fastapi import APIRouter, Body, Header, HTTPException

from core.hecate_settings import PHONE_APPS, PHONE_HOME_WIFI, settings as hecate_settings
from providers.garmin import GarminError, GarminService

logger = logging.getLogger("hestia_hecate.devices")

HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
TZ = os.getenv("TZ") or "Europe/Rome"
GARMIN_JOB = "hecate.garmin.sync"
LOGIN_PATH = "/api/gateway/garmin/login"

garmin = GarminService()
router = APIRouter()
_phone_state: dict = {}


def _today() -> date:
    return datetime.now(ZoneInfo(TZ)).date()


_clients: dict = {}


def _feeds():
    if "feeds" not in _clients:
        from hestia_common.feeds import FeedPublisher
        _clients["feeds"] = FeedPublisher(HUB_API_URL)
    return _clients["feeds"]


def _presence():
    if "presence" not in _clients:
        from hestia_common.presence_client import PresenceClient
        _clients["presence"] = PresenceClient("hecate", HUB_API_URL)
    return _clients["presence"]


def _hermes(event: dict) -> bool:
    try:
        resp = requests.post(f"{HUB_API_URL}/route/hermes/api/events/ingest",
                             json={"method": "POST", "headers": {}, "query": {}, "body": event, "timeout_seconds": 10},
                             timeout=14)
        resp.raise_for_status()
        return int((resp.json() or {}).get("status_code", 500)) < 400
    except Exception as exc:
        logger.warning("[🔄] event=device_notify_failed error=%s", exc)
        return False


def _ask_secret(step: str) -> bool:
    """Hermes secret form: email + password, or the two-step code. Hecate receives the values, never Hermes."""
    fields = ([{"name": "code", "label": "Codice ricevuto da Garmin", "type": "text"}] if step == "code" else
              [{"name": "email", "label": "Email di Garmin Connect", "type": "text"},
               {"name": "password", "label": "Password", "type": "password"}])
    message = ("Garmin ti ha mandato un codice: scrivilo qui." if step == "code" else
               "Inserisci l'accesso a Garmin Connect: lo uso una volta sola per collegare l'orologio, "
               "la password non viene salvata.")
    return _hermes({"event_type": "service.action_required", "domain": "system", "entity_id": f"hecate-garmin-{step}",
                    "payload": {"kind": "hecate.garmin.login", "service": "hecate", "source": "hecate",
                                "_source": "hecate", "_title": "Collega Garmin", "_message": message, "level": "info",
                                "target": "owner", "replaces": "hecate.garmin.login", "icon": "watch", "tone": "info",
                                "_secret": {"service": "hecate", "path": LOGIN_PATH, "fields": fields}}})


# ── Garmin ───────────────────────────────────────────────────────────────────
@router.get("/api/gateway/garmin/status")
def garmin_status():
    return garmin.status()


@router.post("/api/gateway/garmin/connect")
def garmin_connect():
    """«Collega Garmin»: a secret form reaches the owner (WebUI / Telegram Mini App)."""
    sent = _ask_secret("login")
    return {"status": "asked" if sent else "error",
            "message": "Ti ho mandato il modulo per collegare Garmin." if sent else "Non riesco a mandarti il modulo."}


@router.post(LOGIN_PATH)
def garmin_login(body: dict = Body(...)):
    """Target of the secret form: ``{values: {email, password} | {code}}``. Values are never logged."""
    values = body.get("values") if isinstance(body.get("values"), dict) else body
    try:
        if values.get("code"):
            out = garmin.login_code(values["code"])
        else:
            out = garmin.login(str(values.get("email") or "").strip(), str(values.get("password") or ""))
    except GarminError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — wrong password, Garmin down…
        logger.warning("event=garmin_login_failed error=%s", type(exc).__name__)
        raise HTTPException(status_code=422, detail="Garmin non ha accettato l'accesso, riprova")
    if out["status"] == "needs_code":
        _ask_secret("code")
        return {**out, "message": "Serve il codice che Garmin ti ha mandato: ti ho mandato il modulo."}
    threading.Thread(target=lambda: garmin_sync({"days": 2}), daemon=True, name="garmin-first-sync").start()
    return {**out, "message": "Garmin collegato: leggo sonno e attività ogni mattina."}


@router.delete("/api/gateway/garmin")
def garmin_forget():
    return garmin.forget()


@router.get("/api/gateway/garmin/day")
def garmin_day(day: str = ""):
    try:
        d = date.fromisoformat(day) if day else _today()
    except ValueError:
        raise HTTPException(status_code=422, detail="giorno YYYY-MM-DD")
    try:
        return garmin.day(d)
    except GarminError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/api/gateway/garmin/sync")
def garmin_sync(body: dict = Body(default={})):
    """Agenda job: the last ``days`` days (default 2 = yesterday + today) → feed ``wearable.daily``."""
    days = max(1, min(14, int(body.get("days") or 2)))
    if not garmin.status()["connected"]:
        return {"status": "not_connected"}
    today = _today()
    pushed = []
    try:
        for k in range(days - 1, -1, -1):
            item = garmin.day(today - timedelta(days=k))
            out = _feeds().publish("wearable.daily", item)
            pushed.append({"date": item["date"], **out})
            sleep = item.get("sleep") or {}
            if k == 0 and sleep.get("end"):
                _presence().signal("wearable.woke_at", sleep["end"], meta={"module": "hecate", "source": "garmin"},
                                   ttl_seconds=18 * 3600)
    except GarminError as exc:
        garmin.last_error = str(exc)
        logger.warning("[🔄] event=garmin_sync_failed error=%s fallback=next_job", exc)
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        garmin.last_error = type(exc).__name__
        logger.warning("[🔄] event=garmin_sync_failed error=%s fallback=next_job", exc)
        return {"status": "error", "detail": "Garmin non risponde"}
    garmin.last_error = ""
    garmin.last_sync = {"at": datetime.now(timezone.utc).isoformat(), "days": [p["date"] for p in pushed]}
    logger.info("event=garmin_synced days=%d", len(pushed))
    return {"status": "ok", "days": pushed}


def agenda_rules() -> list[dict]:
    from hestia_common.agenda_client import job_rule
    return [job_rule(GARMIN_JOB, "Garmin: sonno e attività", service="hecate", path="/api/gateway/garmin/sync",
                     body={"days": 2}, recurrence="FREQ=DAILY", start_at="2026-01-01T09:30:00", tz=TZ,
                     description="Legge dall'orologio la notte e le attività di ieri e oggi e le passa ad "
                                 "allenamento e cura di sé. Senza Garmin collegato non fa niente.",
                     timeout_seconds=120)]


# ── Phone ────────────────────────────────────────────────────────────────────
def _home(wifi: str, explicit) -> bool | None:
    if isinstance(explicit, bool):
        return explicit
    names = [str(n).strip().casefold() for n in (hecate_settings.get(PHONE_HOME_WIFI) or []) if str(n).strip()]
    if not names:
        return None
    return bool(wifi) and wifi.strip().casefold() in names


def _app_wanted(app: str) -> bool:
    apps = [str(a).strip().casefold() for a in (hecate_settings.get(PHONE_APPS) or []) if str(a).strip()]
    return not apps or app.strip().casefold() in apps


@router.post("/api/gateway/phone/push")
def phone_push(body: dict = Body(...), x_hestia_phone_token: str = Header(default="")):
    """Webhook of the phone (Tasker, MacroDroid…): ``{type: state|notification, …}``."""
    secret = os.getenv("HECATE_PHONE_TOKEN", "")
    if not secret:
        raise HTTPException(status_code=503, detail="telefono non configurato (HECATE_PHONE_TOKEN)")
    if not hmac.compare_digest(str(x_hestia_phone_token or ""), secret):
        logger.warning("event=phone_push_refused reason=token")
        raise HTTPException(status_code=401, detail="token non valido")
    at = str(body.get("at") or datetime.now(timezone.utc).isoformat())
    kind = str(body.get("type") or "state")
    if kind == "notification":
        app_name = str(body.get("app") or "").strip()[:80]
        if not app_name or not _app_wanted(app_name):
            return {"status": "ignored"}
        item = {"app": app_name, "title": str(body.get("title") or "")[:200], "text": str(body.get("text") or "")[:1000],
                "at": at}
        threading.Thread(target=lambda: _feeds().publish("phone.notification", item), daemon=True,
                         name="phone-notification").start()
        logger.info("event=phone_notification app=%s", app_name)
        return {"status": "ok"}
    wifi = str(body.get("wifi") or "").strip()
    state = {"home": _home(wifi, body.get("home")), "charging": body.get("charging") if isinstance(
        body.get("charging"), bool) else None, "battery": body.get("battery"), "at": at}
    _phone_state.clear()
    _phone_state.update({k: v for k, v in state.items() if v is not None})
    p = _presence()
    if state["home"] is not None:
        p.signal("phone.home", state["home"], meta={"module": "hecate", "source": "phone"}, ttl_seconds=12 * 3600)
    if state["charging"] is not None:
        p.signal("phone.charging", state["charging"], meta={"module": "hecate", "source": "phone"},
                 ttl_seconds=6 * 3600)
    threading.Thread(target=lambda: _feeds().publish("phone.state", dict(_phone_state)), daemon=True,
                     name="phone-state").start()
    logger.info("event=phone_state home=%s charging=%s", state["home"], state["charging"])
    return {"status": "ok", "state": dict(_phone_state)}


@router.get("/api/gateway/phone/status")
def phone_status():
    return {"configured": bool(os.getenv("HECATE_PHONE_TOKEN")), "last": dict(_phone_state),
            "home_wifi": len(hecate_settings.get(PHONE_HOME_WIFI) or []), "apps": hecate_settings.get(PHONE_APPS) or []}


# presence: a data-defined overlay so the state line says it (no effect: being out never loosens anything)
PRESENCE_STATES = {"away_from_home": {
    "kind": "overlay", "priority": 20, "label": "Fuori casa", "icon": "map-pin", "tone": "muted",
    "help": "Il telefono (Wi-Fi di casa non connesso) o la casa dicono che non sei a casa.",
    # «==» needs the signal to exist: no phone and no house connected → never «Fuori casa»
    "when": [[{"signal": "phone.home", "op": "==", "value": False}],
             [{"signal": "home.present", "op": "==", "value": False}]], "effects": {}}}


def declare_presence() -> None:
    """Chronos keeps declared states in memory: re-assert hourly (background thread started by main)."""
    import time
    while True:
        _presence().declare_states(PRESENCE_STATES)
        time.sleep(3600)


def tools(MCPTool) -> list:
    """MCP tools (Telegram + WebUI + assistant): group sistema, section «Dispositivi»."""
    def t(name, title, description, method, path, props=None, required=None, label=None):
        return MCPTool(name=name, title=title, description=description,
                       parameters={"type": "object", "properties": props or {}, "required": required or []},
                       handler=lambda **kw: {"status": "ok", "tool": name, "params": kw}, method=method, path=path,
                       clients=["telegram", "ui"], response_mode="oracle_natural", telegram_group="sistema",
                       telegram={"section": "Dispositivi", **({"label": label} if label else {})})
    return [
        t("garmin_stato", "Garmin", "Se l'orologio Garmin è collegato e quando ho letto gli ultimi dati.", "GET",
          "/api/gateway/garmin/status", label="Garmin"),
        t("garmin_collega", "Collega Garmin", "Manda all'utente il modulo per collegare Garmin Connect "
          "(email e password non passano dalla chat).", "POST", "/api/gateway/garmin/connect"),
        t("garmin_sincronizza", "Leggi Garmin ora", "Legge adesso sonno, passi, battito e attività degli ultimi "
          "giorni (days, default 2) e li passa ad allenamento e cura di sé.", "POST", "/api/gateway/garmin/sync",
          {"days": {"type": "integer", "minimum": 1, "maximum": 14}}),
        t("garmin_giorno", "Dati Garmin di un giorno", "Sonno, passi, battito a riposo, body battery, HRV, "
          "prontezza e attività di un giorno (day YYYY-MM-DD, vuoto = oggi).", "GET", "/api/gateway/garmin/day",
          {"day": {"type": "string", "format": "date", "title": "Giorno"}}),
        t("garmin_scollega", "Scollega Garmin", "Toglie l'accesso a Garmin (cancella i token).", "DELETE",
          "/api/gateway/garmin"),
        t("telefono_stato", "Telefono", "Ultimo stato mandato dal telefono (a casa, in carica, batteria) e se il "
          "collegamento è configurato.", "GET", "/api/gateway/phone/status", label="Telefono"),
    ]
