"""Connected services as ONE list (Marko 2026-11-07: «dovrebbe abilitare ad averne N come un marketplace… Google e
Garmin hanno meccanismi diversi: uno mostra subito le impostazioni, l'altro no»).

Every account or device Hecate links is a ``Connector`` with the same shape, and the WebUI draws all of them with the
same card (``<hecate-connections>``, Dispositivi page and guided setup):

* ``item()`` → ``{id, label, icon, what, state: connected|waiting|not_connected, detail, step, actions[]}``.
  ``step`` is what to do now, shown as soon as the card is opened, the same for every service:
  ``{kind: form, text, fields[{name, label, type, placeholder?}], submit, guide?[], link?{label, url}}`` or
  ``{kind: wait, text, url, fields[], submit}`` (a page opened elsewhere: the card polls, a field to paste).
* ``submit(values)`` → the next step or connected (``open_url`` when a page must be opened); a refusal raises
  ``ConnectError`` with the reason in words (422).
* ``action(name)`` for the buttons of a connected service (``sync``, ``again``…), ``forget()`` to unlink.

A new service = one more ``Connector`` registered here: no new card, no new page.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Body, HTTPException

logger = logging.getLogger("hecate.connections")
router = APIRouter()


class ConnectError(RuntimeError):
    """A refused step: the message is shown to the user as it is."""


def field(name: str, label: str, type_: str = "text", placeholder: str = "") -> dict:
    return {"name": name, "label": label, "type": type_, "placeholder": placeholder}


class Connector:
    id = ""
    label = ""
    icon = "link"
    what = ""
    in_setup = True            # offered in the guided setup too (the phone sensor is not: Marko 2026-11-07)
    order = 50

    def state(self) -> dict:                       # {state, detail, step, actions}
        raise NotImplementedError

    def submit(self, values: dict) -> dict:        # → {message?, open_url?}
        raise ConnectError("Niente da fare qui.")

    def action(self, name: str) -> dict:
        raise ConnectError("Azione sconosciuta.")

    def forget(self) -> dict:
        raise ConnectError("Non si scollega da qui.")

    def item(self) -> dict:
        try:
            st = self.state()
        except Exception as exc:  # noqa: BLE001 — one broken service never hides the others
            logger.warning("[🔄] event=connection_state_failed id=%s error=%s fallback=unavailable", self.id, exc)
            st = {"state": "not_connected", "detail": "Stato non disponibile.", "step": None, "actions": []}
        return {"id": self.id, "label": self.label, "icon": self.icon, "what": self.what, "in_setup": self.in_setup,
                "state": st.get("state", "not_connected"), "detail": st.get("detail", ""), "step": st.get("step"),
                "actions": st.get("actions", [])}


_REGISTRY: dict[str, Connector] = {}


def register(c: Connector) -> None:
    _REGISTRY[c.id] = c


def items(place: str = "") -> list[dict]:
    rows = sorted(_REGISTRY.values(), key=lambda c: (c.order, c.label))
    return [c.item() for c in rows if place != "setup" or c.in_setup]


def _get(cid: str) -> Connector:
    c = _REGISTRY.get(cid)
    if c is None:
        raise HTTPException(status_code=404, detail="Servizio sconosciuto.")
    return c


def _run(c: Connector, fn: Callable[[], dict | None], what: str) -> dict:
    try:
        out = fn() or {}
    except ConnectError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — the reason in words, never a stack trace
        logger.warning("[🔄] event=connection_%s_failed id=%s error=%s", what, c.id, type(exc).__name__)
        raise HTTPException(status_code=422, detail=f"{c.label} non ha risposto ({type(exc).__name__}): riprova.")
    return {"status": "ok", **out, "item": c.item()}


@router.get("/api/gateway/connections")
def connections_list(place: str = ""):
    """Every service Hecate can link, the same shape for all (``place=setup``: the ones offered in the setup)."""
    return {"status": "ok", "items": items(place)}


@router.post("/api/gateway/connections/{cid}")
def connections_submit(cid: str, body: dict = Body(default={})):
    """The current step's values (never logged) → the next step or connected."""
    c = _get(cid)
    values = body.get("values") if isinstance(body.get("values"), dict) else {}
    return _run(c, lambda: c.submit(values), "submit")


@router.post("/api/gateway/connections/{cid}/{action}")
def connections_action(cid: str, action: str):
    c = _get(cid)
    return _run(c, lambda: c.action(action), "action")


@router.delete("/api/gateway/connections/{cid}")
def connections_forget(cid: str):
    c = _get(cid)
    return _run(c, c.forget, "forget")


# ── the services ─────────────────────────────────────────────────────────────

class GarminConnector(Connector):
    id, label, icon, order = "garmin", "Garmin", "pulse", 20
    what = "Sonno e attività dall'orologio, ogni mattina."

    def __init__(self, service, sync: Callable[[], Any], first_sync: Callable[[], None]):
        self.g, self.sync, self.first_sync = service, sync, first_sync

    def state(self) -> dict:
        s = self.g.status()
        if s["connected"]:
            last = s.get("last_sync") or {}
            detail = f"Ultima lettura {str(last.get('at', ''))[:16].replace('T', ' ')}" if last.get("at") else "Collegato."
            if s.get("last_error"):
                detail += f" · {s['last_error']}"
            actions = [{"id": "sync", "label": "Leggi adesso", "icon": "refresh"}]
            return {"state": "connected", "detail": detail, "step": None,
                    "actions": actions + ([{"id": "forget", "label": "Scollega", "icon": "trash", "danger": True}]
                                          if s.get("tokens") else [])}
        if s.get("waiting_code"):
            return {"state": "waiting", "detail": "Aspetto il codice.", "actions": [],
                    "step": {"kind": "form", "text": "Garmin ti ha mandato un codice (mail o SMS): scrivilo qui.",
                             "fields": [field("code", "Codice di Garmin", "text", "123456")], "submit": "Conferma"}}
        return {"state": "not_connected", "detail": "", "actions": [],
                "step": {"kind": "form", "text": "Email e password di Garmin Connect: le uso una volta sola e non le salvo.",
                         "fields": [field("email", "Email", "email"), field("password", "Password", "password")],
                         "submit": "Collega"}}

    def submit(self, values: dict) -> dict:
        from providers.garmin import GarminError
        try:
            if values.get("code"):
                out = self.g.login_code(str(values["code"]))
            else:
                out = self.g.login(str(values.get("email") or "").strip(), str(values.get("password") or ""))
        except GarminError as exc:
            raise ConnectError(str(exc))
        except Exception as exc:  # noqa: BLE001 — wrong password, Garmin down… (the password is never logged)
            logger.warning("[🔄] event=garmin_login_failed error=%s detail=%s", type(exc).__name__, str(exc)[:200])
            raise ConnectError(self.g.explain(exc))
        if out["status"] == "connected":
            self.first_sync()
            return {"message": "Garmin collegato."}
        return {}

    def action(self, name: str) -> dict:
        if name != "sync":
            raise ConnectError("Azione sconosciuta.")
        out = self.sync() or {}
        if out.get("status") == "error":
            raise ConnectError(out.get("detail") or "Garmin non risponde.")
        return {"message": "Letto."}

    def forget(self) -> dict:
        self.g.forget()
        return {"message": "Garmin scollegato."}


class GoogleConnector(Connector):
    id, label, icon, order = "google", "Google", "calendar", 10
    what = "Calendario e Gmail, più una cartella su Drive per i backup."
    CONSOLE = "https://console.cloud.google.com/apis/credentials"

    def __init__(self, *, state: Callable[[], dict], save_client: Callable[[dict], None], initiate: Callable[[], dict],
                 complete: Callable[[str], None], cancel: Callable[[], None]):
        self._state, self._save, self._initiate, self._complete, self._cancel = (
            state, save_client, initiate, complete, cancel)
        self.editing = False

    def _client_step(self) -> dict:
        return {"kind": "form", "text": "Serve un accesso di Google Cloud (gratis), una volta sola.",
                "guide": ["Apri Google Cloud, Credenziali, e crea un progetto se non ne hai uno.",
                          "Attiva Google Calendar API, Gmail API e Google Drive API.",
                          "«Crea credenziali» → «ID client OAuth» → tipo App desktop.",
                          "Copia qui ID client e segreto, oppure incolla il file JSON che fa scaricare."],
                "link": {"label": "Apri Google Cloud", "url": self.CONSOLE},
                "fields": [field("client_id", "ID client", "text", "…apps.googleusercontent.com"),
                           field("client_secret", "Segreto del client", "password"),
                           field("json", "Oppure il file JSON", "textarea")],
                "submit": "Salva e collega"}

    def state(self) -> dict:
        s = self._state()
        if s.get("linked") and not self.editing:
            return {"state": "connected", "detail": "Collegato.", "step": None,
                    "actions": [{"id": "again", "label": "Collega di nuovo", "icon": "refresh"}]}
        if not s.get("client_set") or self.editing:
            return {"state": "not_connected", "detail": "", "step": self._client_step(), "actions": []}
        if s.get("pending"):
            paste = [] if s.get("public_redirect") else [field("code", "Indirizzo dell'ultima pagina (o solo il codice)")]
            return {"state": "waiting", "detail": "Aspetto Google.", "actions": [{"id": "cancel", "label": "Annulla", "icon": "x"}],
                    "step": {"kind": "wait", "url": s.get("auth_url") or "",
                             "text": "Nella pagina di Google scegli l'account e concedi l'accesso: qui si aggiorna da solo."
                                     + ("" if s.get("public_redirect") else
                                        " Se alla fine la pagina non si apre (dal telefono), incolla qui il suo indirizzo."),
                             "fields": paste, "submit": "Conferma" if paste else ""}}
        err = str(s.get("error") or "")
        return {"state": "not_connected", "detail": "" if err.startswith("Google not authorized") else err[:200],
                "actions": [{"id": "client", "label": "Cambia accesso Google Cloud", "icon": "edit"}],
                "step": {"kind": "form", "text": "Si apre la pagina di Google: scegli l'account e concedi l'accesso.",
                         "fields": [], "submit": "Collega Google"}}

    def submit(self, values: dict) -> dict:
        s = self._state()
        if not s.get("client_set") or self.editing:
            if not any(str(values.get(k) or "").strip() for k in ("client_id", "json")):
                raise ConnectError("Scrivi ID client e segreto, oppure incolla il file JSON.")
            self._save(values)
            self.editing = False
        elif s.get("pending") and values.get("code"):
            self._complete(str(values["code"]))
            return {"message": "Google collegato."}
        out = self._initiate()
        return {"open_url": out.get("auth_url") or ""}

    def action(self, name: str) -> dict:
        if name == "cancel":
            self._cancel()
            return {}
        if name == "client":
            self.editing = True
            return {}
        if name == "again":
            return {"open_url": (self._initiate() or {}).get("auth_url") or ""}
        raise ConnectError("Azione sconosciuta.")


class PhoneConnector(Connector):
    id, label, icon, order, in_setup = "phone", "Telefono Android", "map-pin", 30, False
    what = "Dice da solo se sei a casa e se è in carica; le notifiche delle app scelte diventano spese da rivedere."

    def __init__(self, status: Callable[[], dict]):
        self.status = status

    def state(self) -> dict:
        p = self.status() or {}
        last = p.get("last") or {}
        if p.get("configured"):
            bits = []
            if last.get("home") is not None:
                bits.append("a casa" if last["home"] else "fuori casa")
            if last.get("battery") is not None:
                bits.append(f"batteria {last['battery']}%")
            when = str(last.get("at") or "")[:16].replace("T", " ")
            return {"state": "connected", "step": None, "actions": [],
                    "detail": (f"Ultimo segnale {when}" + (f" · {', '.join(bits)}" if bits else "")) if when
                    else "Configurato, nessun segnale ancora."}
        return {"state": "not_connected", "detail": "", "actions": [],
                "step": {"kind": "form", "fields": [], "submit": "", "text": "Si collega dal telefono, in tre passi:",
                         "guide": ["Nel file di configurazione del server metti il segreto del telefono (la guida di installazione dice dove).",
                                   "Su Tasker o MacroDroid crea un'azione HTTP POST verso /api/gateway/phone/push con l'intestazione X-Hestia-Phone-Token: quando cambia il Wi-Fi o la carica, e alle notifiche delle app che vuoi.",
                                   "Torna qui: vedrai l'ultimo segnale."]}}
