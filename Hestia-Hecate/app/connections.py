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
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

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
        raise ConnectError(tr("Nothing to do here."))

    def action(self, name: str) -> dict:
        raise ConnectError(tr("Unknown action."))

    def forget(self) -> dict:
        raise ConnectError(tr("It can't be unlinked from here."))

    def item(self) -> dict:
        try:
            st = self.state()
        except Exception as exc:  # noqa: BLE001 — one broken service never hides the others
            logger.warning("[🔄] event=connection_state_failed id=%s error=%s fallback=unavailable", self.id, exc)
            st = {"state": "not_connected", "detail": tr("State not available."), "step": None, "actions": []}
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
        raise HTTPException(status_code=404, detail=tr("Unknown service."))
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
        raise HTTPException(status_code=422, detail=tr("{0} did not answer ({1}): try again.", c.label, type(exc).__name__))
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
    what = "Sleep and activities from the watch, every morning."

    def __init__(self, service, sync: Callable[[], Any], first_sync: Callable[[], None]):
        self.g, self.sync, self.first_sync = service, sync, first_sync

    def state(self) -> dict:
        s = self.g.status()
        if s["connected"]:
            last = s.get("last_sync") or {}
            detail = tr("Last reading {0}", str(last.get('at', ''))[:16].replace('T', ' ')) if last.get("at") else tr("Connected.")
            if s.get("last_error"):
                detail += f" · {s['last_error']}"
            actions = [{"id": "sync", "label": tr("Read now"), "icon": "refresh"}]
            return {"state": "connected", "detail": detail, "step": None,
                    "actions": actions + ([{"id": "forget", "label": tr("Unlink"), "icon": "trash", "danger": True}]
                                          if s.get("tokens") else [])}
        if s.get("waiting_code"):
            return {"state": "waiting", "detail": tr("Waiting for the code."), "actions": [],
                    "step": {"kind": "form", "text": tr("Garmin sent you a code (mail or SMS): type it here."),
                             "fields": [field("code", tr("Garmin code"), "text", "123456")], "submit": tr("Confirm")}}
        return {"state": "not_connected", "detail": "", "actions": [],
                "step": {"kind": "form", "text": tr("Garmin Connect email and password: I use them only once and don't save them."),
                         "fields": [field("email", tr("Email"), "email"), field("password", "Password", "password")],
                         "submit": tr("alt::Link")}}

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
            return {"message": tr("Garmin linked.")}
        return {}

    def action(self, name: str) -> dict:
        if name != "sync":
            raise ConnectError(tr("Unknown action."))
        out = self.sync() or {}
        if out.get("status") == "error":
            raise ConnectError(out.get("detail") or tr("Garmin does not answer."))
        return {"message": tr("Read.")}

    def forget(self) -> dict:
        self.g.forget()
        return {"message": tr("Garmin unlinked.")}


class GoogleConnector(Connector):
    id, label, icon, order = "google", "Google", "calendar", 10
    what = "Calendar and Gmail, plus a Drive folder for backups."
    CONSOLE = "https://console.cloud.google.com/apis/credentials"

    def __init__(self, *, state: Callable[[], dict], save_client: Callable[[dict], None], initiate: Callable[[], dict],
                 complete: Callable[[str], None], cancel: Callable[[], None]):
        self._state, self._save, self._initiate, self._complete, self._cancel = (
            state, save_client, initiate, complete, cancel)
        self.editing = False

    def _client_step(self) -> dict:
        return {"kind": "form", "text": tr("A Google Cloud access (free) is needed, only once."),
                "guide": [tr("Open Google Cloud, Credentials, and create a project if you don't have one."),
                          "Enable Google Calendar API, Gmail API and Google Drive API.",
                          "«Create credentials» → «OAuth client ID» → type Desktop app.",
                          tr("Copy the client ID and secret here, or paste the JSON file it lets you download.")],
                "link": {"label": tr("Open Google Cloud"), "url": self.CONSOLE},
                "fields": [field("client_id", tr("Client ID"), "text", "…apps.googleusercontent.com"),
                           field("client_secret", tr("Client secret"), "password"),
                           field("json", tr("Or the JSON file"), "textarea")],
                "submit": tr("Save and link")}

    def state(self) -> dict:
        s = self._state()
        if s.get("linked") and not self.editing:
            return {"state": "connected", "detail": tr("Connected."), "step": None,
                    "actions": [{"id": "again", "label": tr("Link again"), "icon": "refresh"}]}
        if not s.get("client_set") or self.editing:
            return {"state": "not_connected", "detail": "", "step": self._client_step(), "actions": []}
        if s.get("pending"):
            paste = [] if s.get("public_redirect") else [field("code", tr("Address of the last page (or just the code)"))]
            return {"state": "waiting", "detail": tr("Waiting for Google."), "actions": [{"id": "cancel", "label": tr("Cancel"), "icon": "x"}],
                    "step": {"kind": "wait", "url": s.get("auth_url") or "",
                             "text": tr("On Google's page choose the account and grant access: this updates by itself.")
                                     + ("" if s.get("public_redirect") else
                                        tr(" If in the end the page does not open (from the phone), paste its address here.")),
                             "fields": paste, "submit": tr("Confirm") if paste else ""}}
        err = str(s.get("error") or "")
        return {"state": "not_connected", "detail": "" if err.startswith("Google not authorized") else err[:200],
                "actions": [{"id": "client", "label": "Change Google Cloud access", "icon": "edit"}],
                "step": {"kind": "form", "text": tr("Google's page opens: choose the account and grant access."),
                         "fields": [], "submit": tr("Link Google")}}

    def submit(self, values: dict) -> dict:
        s = self._state()
        if not s.get("client_set") or self.editing:
            if not any(str(values.get(k) or "").strip() for k in ("client_id", "json")):
                raise ConnectError(tr("Type the client ID and secret, or paste the JSON file."))
            self._save(values)
            self.editing = False
        elif s.get("pending") and values.get("code"):
            self._complete(str(values["code"]))
            return {"message": tr("Google linked.")}
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
        raise ConnectError(tr("Unknown action."))


class PhoneConnector(Connector):
    id, label, icon, order, in_setup = "phone", "Android phone", "map-pin", 30, False
    what = "It tells by itself whether you are at home and charging; notifications of the chosen apps become expenses to review."

    def __init__(self, status: Callable[[], dict]):
        self.status = status

    def state(self) -> dict:
        p = self.status() or {}
        last = p.get("last") or {}
        if p.get("configured"):
            bits = []
            if last.get("home") is not None:
                bits.append("at home" if last["home"] else tr("away from home"))
            if last.get("battery") is not None:
                bits.append(f"batteria {last['battery']}%")
            when = str(last.get("at") or "")[:16].replace("T", " ")
            return {"state": "connected", "step": None, "actions": [],
                    "detail": (tr("Last signal {0}", when) + (f" · {', '.join(bits)}" if bits else "")) if when
                    else tr("Configured, no signal yet.")}
        return {"state": "not_connected", "detail": "", "actions": [],
                "step": {"kind": "form", "fields": [], "submit": "", "text": tr("It links from the phone, in three steps:"),
                         "guide": [tr("In the server configuration file put the phone secret (the install guide says where)."),
                                   tr("In Tasker or MacroDroid create an HTTP POST action to /api/gateway/phone/push with the header X-Hestia-Phone-Token: when Wi-Fi or charging changes, and on the notifications of the apps you want."),
                                   tr("Come back here: you'll see the last signal.")]}}
