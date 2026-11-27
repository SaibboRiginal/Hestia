"""Connections: every external thing a module needs, linked the same way from the WebUI (dossier
docs/work/2026-11-19-unified-connections; Marko 2026-11-19: one logic to link, like plugins, what
the modules need; .env is only for secrets).

A module that talks to an outside service (an account, a device, a program at home) declares it as a ``Connector``;
who talks to the service declares it (ComfyUI → Apollo, Home Assistant → Lares, Google/Outlook/Garmin → Hecate). The
WebUI draws every connector of every module with ONE card (``<hxk-connections>``, page «Connections», guided setup):

* ``item()`` → ``{id, label, icon, what, group, keywords, in_setup, state: connected|waiting|not_connected, detail,
  step, actions[], test}``. ``step`` is what to do now, the same for every service:
  ``{kind: form, text, fields[{name, label, type, placeholder?, value?}], submit, guide?[], link?{label, url}}`` or
  ``{kind: wait, text, url, code?, fields[], submit}`` (a page opened elsewhere: the card polls, a field to paste).
* ``submit(values)`` → the next step or connected (``open_url`` when a page must be opened); a refusal raises
  ``ConnectError`` with the reason in words (422).
* ``action(name)`` for the buttons (``test`` on every card, ``sync``, ``again``…), ``forget()`` to unlink.
* ``test()`` → ``{ok, detail, facts[]}``: the «Test» button, in plain words (e.g. GPU and models of ComfyUI).

Storage rule: addresses and names are Themis settings of the module (``editor="connection"``: Settings shows a link to
the card); a secret the owner types is ``<MODULE>_KEY_<NAME>`` in the module's own ``.env``, written by Hephaestus
(``POST /api/setup/connection-secret``) and re-read here live (``POST /api/connections/reload-keys``), never logged nor
returned. Tokens a login produces stay in the module's data folder.

    connections = Connections("apollo", prefix="/api/images/", env_file=Path(__file__).parent / ".env")
    connections.register(AddressConnector(connections, "comfyui", "ComfyUI", settings=kit.settings, ...))
    app.include_router(connections.router())
    ui.connections(connections)              # the static list in the plugin manifest (catalog type «connection»)
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_common.connections")

GROUPS = ("account", "device", "home_service")
STATES = ("connected", "waiting", "not_connected")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_ADDRESS_RE = re.compile(r"^https?://[^\s/]+(:\d{1,5})?(/[^\s]*)?$")


class ConnectError(RuntimeError):
    """A refused step: the message is shown to the user as it is."""


def field(name: str, label: str, type_: str = "text", placeholder: str = "", value: str = "") -> dict:
    out = {"name": name, "label": label, "type": type_, "placeholder": placeholder}
    if value:
        out["value"] = value
    return out


def key_env(module: str, name: str) -> str:
    """``apollo`` + ``comfyui`` → ``APOLLO_KEY_COMFYUI`` (the only secret names a connection writes)."""
    return f"{module.upper()}_KEY_{re.sub(r'[^A-Z0-9]+', '_', name.upper()).strip('_')}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Connector:
    id = ""
    label = ""
    icon = "link"
    what = ""
    group = "account"          # account · device · home_service (the sections of the page)
    keywords: tuple[str, ...] = ()   # search words (English; the label and «what» are searched too)
    in_setup = True            # offered in the guided setup too
    order = 50

    def state(self) -> dict:                       # {state, detail, step, actions}
        raise NotImplementedError

    def submit(self, values: dict) -> dict:        # → {message?, open_url?}
        raise ConnectError(tr("Nothing to do here."))

    def action(self, name: str) -> dict:
        raise ConnectError(tr("Unknown action."))

    def forget(self) -> dict:
        raise ConnectError(tr("It can't be unlinked from here."))

    def test(self) -> dict:
        """The «Test» button: by default the state itself, in words."""
        st = self.state()
        ok = st.get("state") == "connected"
        return {"ok": ok, "detail": st.get("detail") or (tr("Connected.") if ok else tr("Not linked yet.")), "facts": []}

    def on_keys(self) -> None:
        """The module's keys were re-read (a card saved one): apply them to the client."""

    def manifest(self) -> dict:
        return {"id": self.id, "label": self.label, "icon": self.icon, "what": self.what, "group": self.group,
                "keywords": list(self.keywords), "in_setup": self.in_setup, "order": self.order}

    def item(self) -> dict:
        try:
            st = self.state()
        except Exception as exc:  # noqa: BLE001 — one broken service never hides the others
            logger.warning("[🔄] event=connection_state_failed id=%s error=%s fallback=unavailable", self.id, exc)
            st = {"state": "not_connected", "detail": tr("State not available."), "step": None, "actions": []}
        state = st.get("state") if st.get("state") in STATES else "not_connected"
        return {**self.manifest(), "state": state, "detail": st.get("detail", ""), "step": st.get("step"),
                "actions": st.get("actions", []), "test": True}


class Connections:
    """The connectors of one module + their routes under the module's plugin ``api_prefix``."""

    def __init__(self, module: str, prefix: str, *, env_file: str | os.PathLike | None = None,
                 hub_api_url: str | None = None):
        if not prefix.startswith("/api/") or not prefix.endswith("/"):
            raise ValueError("prefix must look like /api/<something>/ (the plugin api_prefix)")
        self.module = module.strip().lower()
        self.prefix = prefix
        self.env_file = Path(env_file) if env_file else None
        self.hub_api_url = (hub_api_url or os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")
        self._registry: dict[str, Connector] = {}

    # ── registry ────────────────────────────────────────────────────────────
    def register(self, c: Connector) -> Connector:
        if not _ID_RE.match(c.id or ""):
            raise ValueError(f"bad connection id {c.id!r}")
        if c.group not in GROUPS:
            raise ValueError(f"connection {c.id}: group must be one of {GROUPS}")
        self._registry[c.id] = c
        return c

    def get(self, cid: str) -> Connector | None:
        return self._registry.get(cid)

    def _sorted(self) -> list[Connector]:
        return sorted(self._registry.values(), key=lambda c: (c.order, c.label))

    def items(self, place: str = "") -> list[dict]:
        return [c.item() for c in self._sorted() if place != "setup" or c.in_setup]

    def manifest(self) -> list[dict]:
        """The static list for the plugin manifest (catalog type ``connection``)."""
        return [c.manifest() for c in self._sorted()]

    # ── secrets ─────────────────────────────────────────────────────────────
    def key_env(self, name: str) -> str:
        return key_env(self.module, name)

    def has_key(self, name: str) -> bool:
        return bool((os.getenv(self.key_env(name)) or "").strip())

    def secret(self, name: str) -> str:
        return (os.getenv(self.key_env(name)) or "").strip()

    def save_secret(self, name: str, value: str) -> None:
        self.save_secrets({name: value})

    def save_secrets(self, values: dict[str, str]) -> None:
        """Hephaestus writes each ``<MODULE>_KEY_<NAME>`` into this module's ``.env`` and asks it to re-read them (no
        restart). Empty value = remove. Values are never logged."""
        self._send({self.key_env(name): str(value or "").strip() for name, value in values.items()})

    def clear_legacy(self, envs: list[str]) -> None:
        """Remove old lines written by hand in this module's ``.env`` (e.g. ``HECATE_MCP_<NAME>_URL``) once their value
        moved into a card. Hephaestus accepts only names it lists as old ones of this module, and only to empty them."""
        self._send({str(e): "" for e in envs})

    def _send(self, envs: dict[str, str]) -> None:
        try:
            resp = requests.post(f"{self.hub_api_url}/route/hephaestus/api/setup/connection-secret",
                                 json={"method": "POST", "headers": {}, "query": {}, "timeout_seconds": 40,
                                       "body": {"module": self.module, "values": envs}},
                                 timeout=45)
            resp.raise_for_status()
            routed = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=connection_secret_unsaved module=%s keys=%d error=%s", self.module,
                           len(envs), type(exc).__name__)
            raise ConnectError(tr("I couldn't save the key: try again in a minute.")) from None
        status, payload = int(routed.get("status_code", 500)), routed.get("payload") or {}
        if status >= 400 or not (isinstance(payload, dict) and payload.get("applied", False)):
            detail = payload.get("detail") if isinstance(payload, dict) else ""
            logger.warning("event=connection_secret_refused module=%s keys=%d status=%s", self.module,
                           len(envs), status)
            raise ConnectError(tr("I couldn't save the key: {0}", str(detail or status)[:160]))
        for env, value in envs.items():         # the live re-read already ran; make sure this process sees it
            if value:
                os.environ[env] = value
            else:
                os.environ.pop(env, None)
        logger.info("event=connection_secret_saved module=%s keys=%d", self.module, len(envs))

    def reload_keys(self) -> list[str]:
        """Re-read ``<MODULE>_KEY_*`` from the module's ``.env`` (empty line = removed) → the names that have a value."""
        from hestia_common import env_keys
        prefix = f"{self.module.upper()}_KEY_"
        found = env_keys.read(self.env_file, prefix) if self.env_file else {}
        for name, value in found.items():
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
        names = sorted(n for n, v in found.items() if v)
        for c in self._registry.values():
            try:
                c.on_keys()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[🔄] event=connection_keys_apply_failed id=%s error=%s", c.id, exc)
        logger.info("event=connection_keys_reloaded module=%s keys=%s", self.module, len(names))
        return names

    # ── HTTP ────────────────────────────────────────────────────────────────
    def _get(self, cid: str) -> Connector:
        from fastapi import HTTPException
        c = self._registry.get(cid)
        if c is None:
            raise HTTPException(status_code=404, detail=tr("Unknown service."))
        return c

    def _run(self, c: Connector, fn: Callable[[], dict | None], what: str) -> dict:
        from fastapi import HTTPException
        try:
            out = fn() or {}
        except ConnectError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — the reason in words, never a stack trace
            logger.warning("[🔄] event=connection_%s_failed module=%s id=%s error=%s", what, self.module, c.id,
                           type(exc).__name__)
            raise HTTPException(status_code=422, detail=tr("{0} did not answer ({1}): try again.", c.label,
                                                           type(exc).__name__))
        return {"status": "ok", **out, "item": c.item()}

    def _test(self, c: Connector) -> dict:
        out = c.test() or {}
        result = {"ok": bool(out.get("ok")), "detail": str(out.get("detail") or ""),
                  "facts": [str(f) for f in out.get("facts") or []], "at": _now()}
        logger.info("event=connection_tested module=%s id=%s ok=%s", self.module, c.id, result["ok"])
        return {"result": result}

    def router(self):
        from fastapi import APIRouter, Body

        router = APIRouter()
        base = f"{self.prefix}connections"

        @router.get(base)
        def connections_list(place: str = ""):
            """Every service this module links, the same shape for all (``place=setup``: the ones offered in the setup)."""
            return {"status": "ok", "module": self.module, "items": self.items(place)}

        @router.post(f"{base}/{{cid}}")
        def connections_submit(cid: str, body: dict = Body(default={})):
            """The current step's values (never logged) → the next step or connected."""
            c = self._get(cid)
            values = body.get("values") if isinstance(body.get("values"), dict) else {}
            return self._run(c, lambda: c.submit(values), "submit")

        @router.post(f"{base}/{{cid}}/{{action}}")
        def connections_action(cid: str, action: str):
            c = self._get(cid)
            if action == "test":
                return self._run(c, lambda: self._test(c), "test")
            return self._run(c, lambda: c.action(action), "action")

        @router.delete(f"{base}/{{cid}}")
        def connections_forget(cid: str):
            c = self._get(cid)
            return self._run(c, c.forget, "forget")

        @router.post("/api/connections/reload-keys")
        def connections_reload_keys():
            """Internal (Hephaestus after writing a key): re-read ``<MODULE>_KEY_*`` from this module's own .env."""
            return {"status": "ok", "keys": self.reload_keys()}

        return router


class AddressConnector(Connector):
    """A program reached at an address, with an optional key (ComfyUI, Home Assistant…): one form (address + key),
    «Test», «Change», «Unlink». The address is the Themis setting ``setting_key`` of the module; the key is
    ``<MODULE>_KEY_<ID>`` in its ``.env``. ``probe(address, key)`` → ``{ok, detail, facts[]}`` in words;
    ``apply(address, key)`` hands both to the module's client."""

    group = "home_service"
    address_label = "Address"
    address_placeholder = "http://192.168.1.50:8188"
    key_label = "Key"
    key_placeholder = ""
    key_required = False
    key_help = ""
    guide: tuple[str, ...] = ()

    def __init__(self, connections: Connections, *, settings: Any, setting_key: str,
                 probe: Callable[[str, str], dict], apply: Callable[[str, str], None]):
        self.connections, self.settings, self.setting_key = connections, settings, setting_key
        self.probe, self._apply = probe, apply
        self.editing = False
        self.last: dict | None = None            # the last «Test» (cached: the list never waits for the network)
        self._address: str | None = None          # what the card saved, before Themis pushes it back
        self._lock = threading.Lock()
        if hasattr(settings, "on_change"):
            settings.on_change(self._changed)

    # ── values ──────────────────────────────────────────────────────────────
    def address(self) -> str:
        if self._address is not None:
            return self._address
        return str(self.settings.get(self.setting_key, "") or "").strip()

    def key(self) -> str:
        return self.connections.secret(self.id)

    def apply_now(self) -> None:
        try:
            self._apply(self.address(), self.key())
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=connection_apply_failed id=%s error=%s", self.id, exc)

    def _changed(self, changed: dict) -> None:
        if self.setting_key in (changed or {}):
            self._address = None
            self.last = None
            self.apply_now()

    def on_keys(self) -> None:
        self.last = None
        self.apply_now()

    # ── card ────────────────────────────────────────────────────────────────
    def _form(self) -> dict:
        fields = [field("address", tr(self.address_label), "url", self.address_placeholder, self.address())]
        key_note = tr("saved: leave empty to keep it") if self.connections.has_key(self.id) else (
            "" if self.key_required else tr("only if it asks for one"))
        fields.append(field("key", f"{tr(self.key_label)}" + (f" ({key_note})" if key_note else ""), "password",
                            self.key_placeholder))
        step = {"kind": "form", "text": tr(self.key_help) if self.key_help else "", "fields": fields,
                "submit": tr("Save and test")}
        if self.guide:
            step["guide"] = [tr(g) for g in self.guide]
        return step

    def _probe(self, timeout_note: bool = False) -> dict:
        with self._lock:
            try:
                out = self.probe(self.address(), self.key()) or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("[🔄] event=connection_probe_failed id=%s error=%s", self.id, type(exc).__name__)
                out = {"ok": False, "detail": tr("{0} does not answer.", self.label)}
            self.last = {"ok": bool(out.get("ok")), "detail": str(out.get("detail") or ""),
                         "facts": list(out.get("facts") or []), "at": _now()}
            return self.last

    def state(self) -> dict:
        addr = self.address()
        if not addr or self.editing:
            actions = [{"id": "cancel", "label": tr("Cancel"), "icon": "x"}] if (addr and self.editing) else []
            return {"state": "not_connected", "detail": "", "step": self._form(), "actions": actions}
        if self.key_required and not self.connections.has_key(self.id):
            return {"state": "not_connected", "detail": tr("The key is missing."), "step": self._form(), "actions": []}
        last = self.last or self._probe()
        edit = {"id": "edit", "label": tr("Change"), "icon": "edit"}
        forget = {"id": "forget", "label": tr("Unlink"), "icon": "trash", "danger": True}
        if last["ok"]:
            return {"state": "connected", "detail": last["detail"] or addr, "step": None, "actions": [edit, forget]}
        return {"state": "not_connected", "detail": last["detail"], "step": self._form(), "actions": [forget]}

    def submit(self, values: dict) -> dict:
        addr = str(values.get("address") or "").strip().rstrip("/")
        key = str(values.get("key") or "").strip()
        if not addr:
            raise ConnectError(tr("Type the address."))
        if not _ADDRESS_RE.match(addr):
            raise ConnectError(tr("The address starts with http:// or https://, for example {0}.", self.address_placeholder))
        if self.key_required and not key and not self.connections.has_key(self.id):
            raise ConnectError(tr("Type the key."))
        if key:
            self.connections.save_secret(self.id, key)
        if addr != self.address():
            if not self.settings.put(self.setting_key, addr, actor="user", reason="connection card"):
                raise ConnectError(tr("I couldn't save the address: try again in a minute."))
            self._address = addr
        self.editing = False
        self.apply_now()
        last = self._probe()
        logger.info("event=connection_saved module=%s id=%s ok=%s", self.connections.module, self.id, last["ok"])
        return {"message": tr("{0} linked.", self.label) if last["ok"] else tr("Saved, but: {0}", last["detail"])}

    def action(self, name: str) -> dict:
        if name == "edit":
            self.editing = True
            return {}
        if name == "cancel":
            self.editing = False
            return {}
        raise ConnectError(tr("Unknown action."))

    def test(self) -> dict:
        if not self.address():
            return {"ok": False, "detail": tr("Type the address first."), "facts": []}
        return self._probe()

    def forget(self) -> dict:
        if self.connections.has_key(self.id):
            self.connections.save_secret(self.id, "")
        if not self.settings.put(self.setting_key, "", actor="user", reason="connection card"):
            raise ConnectError(tr("I couldn't save the address: try again in a minute."))
        self._address, self.last, self.editing = "", None, False
        self.apply_now()
        return {"message": tr("{0} unlinked.", self.label)}
