"""Hecate's connections: the accounts several modules use (Google, Outlook), the devices (Garmin watch, Android phone)
and Gmail's instant notices (dossier docs/work/2026-11-19-unified-connections).

The contract (``Connector``, the card's shape, the routes, the keys written by Hephaestus) is shared by every module:
``hestia_common.connections``. Here only Hecate's services; the WebUI draws them with the same card as ComfyUI or
Home Assistant (page «Connections», guided setup).
"""
from __future__ import annotations

import base64
import json
import logging
import secrets as _secrets
from pathlib import Path
from typing import Any, Callable

from hestia_common.connections import ConnectError, Connections, Connector, field
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hecate.connections")

hub = Connections("hecate", "/api/gateway/", env_file=Path(__file__).resolve().parent / ".env")
register = hub.register


# ── the services ─────────────────────────────────────────────────────────────

class GarminConnector(Connector):
    id, label, icon, order, group = "garmin", "Garmin", "pulse", 20, "device"
    what = "Sleep and activities from the watch, every morning."
    keywords = ("watch", "garmin connect", "sleep")

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
    id, label, icon, order, group = "google", "Google", "calendar", 10, "account"
    what = "Calendar and Gmail, plus a Drive folder for backups."
    keywords = ("gmail", "calendar", "drive", "backup")
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
                                     + (tr(" If Google says the app is not verified: «Advanced», then «Go to Hestia».")
                                        if s.get("builtin") else "")
                                     + ("" if s.get("public_redirect") else
                                        tr(" If in the end the page does not open (from the phone), paste its address here.")),
                             "fields": paste, "submit": tr("Confirm") if paste else ""}}
        err = str(s.get("error") or "")
        return {"state": "not_connected", "detail": "" if err.startswith("Google not authorized") else err[:200],
                "actions": [{"id": "client", "icon": "edit",
                             "label": "Use your own Google app" if s.get("builtin") else "Change Google Cloud access"}],
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
    id, label, icon, order, in_setup, group = "phone", "Android phone", "map-pin", 30, False, "device"
    what = "It tells by itself whether you are at home and charging; notifications of the chosen apps become expenses to review."
    keywords = ("tasker", "macrodroid", "android", "presence")

    def __init__(self, status: Callable[[], dict], connections: Connections | None = None):
        self.status = status
        self.connections = connections or hub
        self.shown = ""          # the key just created: shown once, then only «saved»

    def _guide(self, key: str) -> list[str]:
        return [tr("In Tasker or MacroDroid create an HTTP POST action to /api/gateway/phone/push, with the header "
                   "X-Hestia-Phone-Token and this key as its value: when Wi-Fi or charging changes, and on the "
                   "notifications of the apps you want.") + (f" {key}" if key else ""),
                tr("Come back here: you'll see the last signal.")]

    def state(self) -> dict:
        p = self.status() or {}
        last = p.get("last") or {}
        if p.get("configured") and self.shown:
            return {"state": "waiting", "detail": tr("Key created: copy it on the phone now, it won't be shown again."),
                    "actions": [{"id": "hide", "label": tr("Done"), "icon": "check"}],
                    "step": {"kind": "form", "fields": [], "submit": "", "code": self.shown,
                             "text": tr("The phone's key:"), "guide": self._guide("")}}
        if p.get("configured"):
            bits = []
            if last.get("home") is not None:
                bits.append(tr("at home") if last["home"] else tr("away from home"))
            if last.get("battery") is not None:
                bits.append(tr("battery {0}%", last['battery']))
            when = str(last.get("at") or "")[:16].replace("T", " ")
            return {"state": "connected", "step": None,
                    "actions": [{"id": "forget", "label": tr("Unlink"), "icon": "trash", "danger": True}],
                    "detail": (tr("Last signal {0}", when) + (f" · {', '.join(bits)}" if bits else "")) if when
                    else tr("Configured, no signal yet.")}
        return {"state": "not_connected", "detail": "", "actions": [],
                "step": {"kind": "form", "fields": [], "submit": tr("Create the phone's key"),
                         "text": tr("It links from the phone: create its key here, then put it in the phone's app."),
                         "guide": self._guide("")}}

    def submit(self, values: dict) -> dict:
        key = _secrets.token_urlsafe(24)
        self.connections.save_secret("phone", key)
        self.shown = key
        return {"message": tr("Key created.")}

    def action(self, name: str) -> dict:
        if name == "hide":
            self.shown = ""
            return {}
        raise ConnectError(tr("Unknown action."))

    def forget(self) -> dict:
        self.connections.save_secret("phone", "")
        self.shown = ""
        return {"message": tr("Phone unlinked.")}


class OutlookConnector(Connector):
    """Outlook calendar: the app of the Microsoft account (client ID, tenant, optional secret) typed here, then
    Microsoft's sign-in with a code (device code): the card shows the code and the page, and waits."""
    id, label, icon, order, group = "outlook", "Outlook", "mail", 15, "account"
    what = "The Outlook calendar of your Microsoft account."
    keywords = ("microsoft", "office", "365", "hotmail", "calendar")
    PORTAL = "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"

    def __init__(self, *, linked: Callable[[], bool], initiate: Callable[[], dict], poll: Callable[[], dict],
                 cancel: Callable[[], None], unlink: Callable[[], None], connections: Connections | None = None):
        self._linked, self._initiate, self._poll, self._cancel, self._unlink = linked, initiate, poll, cancel, unlink
        self.connections = connections or hub
        self.flow: dict = {}
        self.editing = False

    def _client_step(self) -> dict:
        return {"kind": "form", "text": tr("An app of your Microsoft account is needed (free), only once."),
                "guide": [tr("Open Microsoft Entra, «App registrations», «New registration»: any name, accounts «personal and work»."),
                          tr("In «Authentication» turn on «Allow public client flows»; in «API permissions» add Calendars.ReadWrite."),
                          tr("Copy here the «Application (client) ID»; tenant: leave «common» unless your organization gave you one.")],
                "link": {"label": tr("Open Microsoft Entra"), "url": self.PORTAL},
                "fields": [field("client_id", tr("Client ID"), "text", "00000000-0000-0000-0000-000000000000"),
                           field("tenant", tr("Tenant"), "text", "common"),
                           field("client_secret", tr("Client secret (only for a work app)"), "password")],
                "submit": tr("Save and link")}

    def state(self) -> dict:
        from providers import outlook
        has_client = bool(outlook.client()[0])
        if self.flow:
            out = self._poll() or {}
            if out.get("status") == "authorized":
                self.flow = {}
                return {"state": "connected", "detail": tr("Connected."), "step": None, "actions": self._actions()}
            if out.get("status") == "pending":
                return {"state": "waiting", "detail": tr("Waiting for Microsoft."),
                        "actions": [{"id": "cancel", "label": tr("Cancel"), "icon": "x"}],
                        "step": {"kind": "wait", "url": self.flow.get("verification_url") or "", "code": self.flow.get("user_code") or "",
                                 "text": tr("Open Microsoft's page, type this code and grant access: this updates by itself."),
                                 "fields": [], "submit": ""}}
            self.flow = {}
            if out.get("error"):
                return {"state": "not_connected", "detail": str(out["error"])[:200], "actions": self._actions(),
                        "step": {"kind": "form", "text": tr("Microsoft's sign-in did not end: try again."), "fields": [],
                                 "submit": tr("Link Outlook")}}
        if not has_client or self.editing:
            return {"state": "not_connected", "detail": "", "step": self._client_step(), "actions": []}
        if self._linked():
            return {"state": "connected", "detail": tr("Connected."), "step": None, "actions": self._actions()}
        return {"state": "not_connected", "detail": "", "actions": self._actions(),
                "step": {"kind": "form", "text": tr("Microsoft's page opens with a code to type: then grant access."),
                         "fields": [], "submit": tr("Link Outlook")}}

    def _actions(self) -> list[dict]:
        return [{"id": "client", "label": tr("Change the Microsoft app"), "icon": "edit"},
                {"id": "forget", "label": tr("Unlink"), "icon": "trash", "danger": True}]

    def submit(self, values: dict) -> dict:
        from providers import outlook
        if not outlook.client()[0] or self.editing:
            cid = str(values.get("client_id") or "").strip()
            tenant = str(values.get("tenant") or "").strip() or "common"
            if not (8 <= len(cid) <= 80) or any(c.isspace() for c in cid):
                raise ConnectError(tr("Copy the «Application (client) ID» from Microsoft Entra."))
            keys = {"outlook_client_id": cid, "outlook_tenant": tenant}
            if str(values.get("client_secret") or "").strip():
                keys["outlook_client_secret"] = str(values["client_secret"]).strip()
            self.connections.save_secrets(keys)
            self.editing = False
        out = self._initiate() or {}
        self.flow = {"user_code": out.get("user_code") or "", "verification_url": out.get("verification_url") or ""}
        return {"open_url": self.flow["verification_url"]}

    def action(self, name: str) -> dict:
        if name == "cancel":
            self.flow = {}
            self._cancel()
            return {}
        if name == "client":
            self.editing = True
            return {}
        raise ConnectError(tr("Unknown action."))

    def forget(self) -> dict:
        self.flow = {}
        self._unlink()
        return {"message": tr("Outlook unlinked.")}


class GmailPushConnector(Connector):
    """Gmail's instant notices through Google Cloud Pub/Sub (streaming pull, no public address): topic and subscription
    are Themis settings, the service account JSON a key in Hecate's .env. Not linked = the light check every 15 min."""
    id, label, icon, order, group, in_setup = "gmail_push", "Gmail instant notices", "zap", 12, "account", False
    what = "New emails arrive at once instead of at the next check (optional, needs Google Cloud Pub/Sub)."
    keywords = ("pubsub", "pub/sub", "gmail", "push", "email")
    CONSOLE = "https://console.cloud.google.com/cloudpubsub/topic/list"

    def __init__(self, *, settings: Any, topic_key: str, subscription_key: str, status: Callable[[], dict],
                 restart: Callable[[], None], connections: Connections | None = None):
        self.settings, self.topic_key, self.subscription_key = settings, topic_key, subscription_key
        self.status, self.restart = status, restart
        self.connections = connections or hub
        self.editing = False

    def _form(self) -> dict:
        return {"kind": "form", "text": tr("In your Google Cloud project (the same one of the Google access):"),
                "guide": [tr("Pub/Sub → create a topic; in its permissions give «Pub/Sub Publisher» to gmail-api-push@system.gserviceaccount.com."),
                          tr("Create a «Pull» subscription on that topic."),
                          tr("IAM → Service accounts → a new one with only «Pub/Sub Subscriber» → Keys → add a JSON key and paste it here.")],
                "link": {"label": tr("Open Pub/Sub"), "url": self.CONSOLE},
                "fields": [field("topic", tr("Topic"), "text", "projects/<project>/topics/<topic>",
                                 str(self.settings.get(self.topic_key, "") or "")),
                           field("subscription", tr("Subscription"), "text", "projects/<project>/subscriptions/<sub>",
                                 str(self.settings.get(self.subscription_key, "") or "")),
                           field("account", tr("Service account JSON") + (
                               f" ({tr('saved: leave empty to keep it')})" if self.connections.has_key("gmail_pubsub_account") else ""),
                               "textarea")],
                "submit": tr("Save and turn on")}

    def state(self) -> dict:
        s = self.status() or {}
        if not s.get("configured") or self.editing:
            actions = [{"id": "cancel", "label": tr("Cancel"), "icon": "x"}] if self.editing else []
            return {"state": "not_connected", "detail": "", "step": self._form(), "actions": actions}
        actions = [{"id": "edit", "label": tr("Change"), "icon": "edit"},
                   {"id": "forget", "label": tr("Turn off"), "icon": "trash", "danger": True}]
        if s.get("active"):
            last = str(s.get("last_message_at") or "")[:16].replace("T", " ")
            return {"state": "connected", "step": None, "actions": actions,
                    "detail": tr("Listening; last notice {0}", last) if last else tr("Listening.")}
        return {"state": "waiting", "step": None, "actions": actions,
                "detail": str(s.get("error") or tr("Starting…"))[:200]}

    def submit(self, values: dict) -> dict:
        topic = str(values.get("topic") or "").strip()
        sub = str(values.get("subscription") or "").strip()
        if not topic.startswith("projects/") or "/topics/" not in topic:
            raise ConnectError(tr("The topic looks like projects/<project>/topics/<topic>."))
        if not sub.startswith("projects/") or "/subscriptions/" not in sub:
            raise ConnectError(tr("The subscription looks like projects/<project>/subscriptions/<sub>."))
        raw = str(values.get("account") or "").strip()
        if raw:
            try:
                data = json.loads(raw)
            except ValueError:
                raise ConnectError(tr("The file is not valid JSON."))
            if not isinstance(data, dict) or data.get("type") != "service_account" or not data.get("private_key"):
                raise ConnectError(tr("This is not the JSON key of a service account."))
            self.connections.save_secret("gmail_pubsub_account",
                                         base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode())
        elif not self.connections.has_key("gmail_pubsub_account"):
            raise ConnectError(tr("Paste the service account JSON."))
        for key, value in ((self.topic_key, topic), (self.subscription_key, sub)):
            if not self.settings.put(key, value, actor="user", reason="connection card"):
                raise ConnectError(tr("I couldn't save it: try again in a minute."))
        self.editing = False
        self.restart()
        return {"message": tr("Gmail instant notices on.")}

    def action(self, name: str) -> dict:
        if name in ("edit", "cancel"):
            self.editing = name == "edit"
            return {}
        raise ConnectError(tr("Unknown action."))

    def forget(self) -> dict:
        for key in (self.topic_key, self.subscription_key):
            self.settings.put(key, "", actor="user", reason="connection card")
        if self.connections.has_key("gmail_pubsub_account"):
            self.connections.save_secret("gmail_pubsub_account", "")
        self.restart()
        return {"message": tr("Gmail instant notices off.")}


class ExternalMcpConnector(Connector):
    """Third-party MCP servers Hestia may use (``core/outbound.py``): one card for all of them, N servers. Name and
    address go in the Themis setting ``hecate.mcp.servers``, the key (optional) is ``HECATE_KEY_MCP_<NAME>``. Servers
    written by hand in .env (``HECATE_MCP_<NAME>_URL/_KEY``) keep working and are moved here once (``adopt``)."""
    id, label, icon, order, group, in_setup = "external_mcp", "External MCP servers", "terminal", 40, "home_service", False
    what = "Other MCP servers {assistant} can use (address and, if it asks for one, its key)."
    keywords = ("mcp", "server", "tools", "external", "model context protocol")

    def __init__(self, *, settings: Any, connections: Connections | None = None, http: Any = None):
        self.settings, self.http = settings, http
        self.connections = connections or hub
        self.adding = False
        self._adopted = False

    # ── helpers ─────────────────────────────────────────────────────────────
    def _rows(self) -> list[dict]:
        from core import outbound
        return outbound.configured(self.settings)

    def _put(self, rows: list[dict]) -> None:
        from core import outbound
        if not self.settings.put(outbound.SERVERS, rows, actor="user", reason="connection card"):
            raise ConnectError(tr("I couldn't save it: try again in a minute."))

    def _form(self) -> dict:
        return {"kind": "form", "text": tr("Give it a short name (letters, numbers, _), its address and, if it asks for one, its key."),
                "fields": [field("name", tr("Name"), "text", "github"),
                           field("url", tr("Address"), "url", "https://mcp.example.com/mcp"),
                           field("key", tr("Key (only if it asks for one)"), "password")],
                "submit": tr("Add and test")}

    # ── card ────────────────────────────────────────────────────────────────
    def state(self) -> dict:
        from core import outbound
        servers = outbound.outbound_servers(self.settings)
        if not servers or self.adding:
            actions = [{"id": "cancel", "label": tr("Cancel"), "icon": "x"}] if self.adding else []
            return {"state": "not_connected", "detail": "", "step": self._form(), "actions": actions}
        actions = [{"id": "add", "label": tr("Add a server"), "icon": "plus"}]
        actions += [{"id": f"remove-{s['name']}", "label": tr("Remove {0}", s["name"]), "icon": "trash", "danger": True}
                    for s in servers]
        names = ", ".join(f"{s['name']} ({s['host'] or tr('wrong address')})" for s in servers)
        return {"state": "connected", "step": None, "actions": actions, "detail": names}

    def submit(self, values: dict) -> dict:
        from core import outbound
        name = str(values.get("name") or "").strip().lower().replace("-", "_").replace(" ", "_")
        url = str(values.get("url") or "").strip()
        key = str(values.get("key") or "").strip()
        if not outbound.NAME_RE.match(name):
            raise ConnectError(tr("The name: letters, numbers and _, at most 31."))
        if not outbound.valid_url(url):
            raise ConnectError(tr("The address starts with http:// or https://, for example {0}.", "https://mcp.example.com/mcp"))
        if key:
            self.connections.save_secret(outbound.key_name(name), key)
        rows = [r for r in self._rows() if r["name"] != name] + [{"name": name, "url": url}]
        self._put(rows)
        self.adding = False
        ok, why = outbound.probe(url, key or outbound.bearer_for(name) or "", http=self.http)
        logger.info("event=external_mcp_added name=%s ok=%s", name, ok)
        return {"message": tr("{0} added.", name) if ok else tr("Saved, but: {0}", self._why(why))}

    def action(self, name: str) -> dict:
        from core import outbound
        if name in ("add", "cancel"):
            self.adding = name == "add"
            return {}
        if name.startswith("remove-"):
            server = name[len("remove-"):]
            self._put([r for r in self._rows() if r["name"] != server])
            if self.connections.has_key(outbound.key_name(server)):
                self.connections.save_secret(outbound.key_name(server), "")
            if any(r["name"] == server for r in outbound.legacy_servers()):   # an old hand-written line too
                self.connections.clear_legacy(outbound.legacy_envs(server))
            logger.info("event=external_mcp_removed name=%s", server)
            return {"message": tr("{0} removed.", server)}
        raise ConnectError(tr("Unknown action."))

    def forget(self) -> dict:
        raise ConnectError(tr("Remove the servers one by one."))

    def test(self) -> dict:
        from core import outbound
        rows = {r["name"]: r["url"] for r in self._rows()}
        for r in outbound.legacy_servers():
            rows.setdefault(r["name"], r["url"])
        if not rows:
            return {"ok": False, "detail": tr("No server yet."), "facts": []}
        facts, ok_all = [], True
        for name in sorted(rows):
            ok, why = outbound.probe(rows[name], outbound.bearer_for(name) or "", http=self.http)
            ok_all = ok_all and ok
            facts.append(tr("{0}: answers", name) if ok else tr("{0}: {1}", name, self._why(why)))
        return {"ok": ok_all, "detail": tr("Every server answers.") if ok_all else tr("Some servers do not answer."),
                "facts": facts}

    @staticmethod
    def _why(code: str) -> str:
        if code == "key":
            return tr("the key is refused")
        if code == "unreachable":
            return tr("it does not answer at that address")
        return tr("it answered {0}", code.removeprefix("http_"))

    def adopt(self) -> None:
        """Once, when the settings are there: servers written by hand in .env move into the card (address in the
        setting, key through Hephaestus), then their old lines are emptied. On failure they keep working from .env and
        the next start tries again."""
        from core import outbound
        if self._adopted:
            return
        self._adopted = True       # set first: the settings change below calls back here
        legacy = [r for r in outbound.legacy_servers() if outbound.NAME_RE.match(r["name"])]
        if not legacy:
            return
        mine = {r["name"] for r in self._rows()}
        todo = [r for r in legacy if r["name"] not in mine]
        try:
            for r in todo:
                if r["key"] and not self.connections.has_key(outbound.key_name(r["name"])):
                    self.connections.save_secret(outbound.key_name(r["name"]), r["key"])
            if todo:
                self._put(self._rows() + [{"name": r["name"], "url": r["url"]} for r in todo])
            self.connections.clear_legacy([e for r in legacy for e in outbound.legacy_envs(r["name"])])
            logger.info("[🔄] event=external_mcp_adopted_from_env servers=%d", len(legacy))
        except Exception as exc:  # noqa: BLE001
            self._adopted = False
            logger.warning("[🔄] event=external_mcp_adopt_failed error=%s — they keep working from .env",
                           type(exc).__name__)
