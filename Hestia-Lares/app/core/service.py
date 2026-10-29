"""Lares — the house on Home Assistant («Casa», dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A3).

A live mirror of the entities Marko cares about (lights, switches, covers, climate, sensors, scenes, the person),
fed by the Home Assistant websocket (push; a full read only on connect). Commands go to HA services. Favourites
(quick actions with a label and a room) live in Archive (``home-store``). The person entity chosen in the settings
(``lares.persona``) becomes the presence signal ``home.present``: Chronos shows «Fuori casa» from it.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from hestia_common.module_kit import Invalid, NotFound, new_id, now_iso

from .ha import HAError

logger = logging.getLogger("hestia_lares.service")

DOMAINS = ("light", "switch", "cover", "climate", "fan", "media_player", "lock", "scene", "script", "sensor",
           "binary_sensor", "person")
COMMANDS = {"on": "turn_on", "off": "turn_off", "toggle": "toggle", "open": "open_cover", "close": "close_cover",
            "lock": "lock", "unlock": "unlock"}
LABELS = {"light": "Luci", "switch": "Prese", "cover": "Tapparelle", "climate": "Clima", "fan": "Ventilatori",
          "media_player": "Media", "lock": "Serrature", "scene": "Scene", "script": "Azioni", "sensor": "Sensori",
          "binary_sensor": "Sensori", "person": "Persone"}
STATE_IT = {"on": "acceso", "off": "spento", "open": "aperta", "closed": "chiusa", "locked": "chiusa",
            "unlocked": "aperta", "home": "a casa", "not_home": "fuori", "unavailable": "non raggiungibile"}


def slim(s: dict) -> dict:
    a = s.get("attributes") or {}
    eid = s.get("entity_id", "")
    return {"id": eid, "domain": eid.split(".")[0], "name": a.get("friendly_name") or eid, "state": s.get("state"),
            "unit": a.get("unit_of_measurement") or "", "device_class": a.get("device_class") or "",
            "brightness": a.get("brightness"), "temperature": a.get("current_temperature"),
            "changed_at": s.get("last_changed")}


class Home:
    def __init__(self, store, ha, get: Callable[[str, Any], Any], *, presence=None):
        self.store = store
        self.ha = ha
        self.get = get
        self.presence = presence
        self.entities: dict[str, dict] = {}
        self.connected = False
        self._lock = threading.Lock()

    # ── mirror (websocket push) ─────────────────────────────────────────────
    def load(self) -> int:
        rows = [slim(s) for s in self.ha.states() if s.get("entity_id", "").split(".")[0] in DOMAINS]
        with self._lock:
            self.entities = {e["id"]: e for e in rows}
        self.connected = True
        self._presence(self.entities.get(self.get("lares.persona", "") or ""))
        logger.info("event=lares_loaded entities=%d", len(rows))
        return len(rows)

    def changed(self, new_state: dict) -> None:
        e = slim(new_state)
        if e["domain"] not in DOMAINS:
            return
        with self._lock:
            self.entities[e["id"]] = e
        if e["id"] == (self.get("lares.persona", "") or ""):
            self._presence(e)

    def _presence(self, person: dict | None) -> None:
        if self.presence and person and person["state"] not in (None, "unknown", "unavailable"):
            self.presence.signal("home.present", person["state"] == "home",
                                 meta={"module": "lares", "source": "home"}, ttl_seconds=24 * 3600)

    def _ensure(self) -> None:
        if not self.ha.configured:
            raise Invalid("la casa non è collegata: servono indirizzo e token di Home Assistant nel file .env")
        if not self.entities:
            try:
                self.load()
            except HAError as exc:
                raise Invalid(str(exc)) from None

    # ── reading ─────────────────────────────────────────────────────────────
    def list(self, domain: str = "", query: str = "") -> list[dict]:
        self._ensure()
        q = query.strip().casefold()
        rows = [e for e in self.entities.values() if (not domain or e["domain"] == domain)
                and (not q or q in e["name"].casefold() or q in e["id"])]
        return sorted(rows, key=lambda e: (e["domain"], e["name"].casefold()))

    def find(self, ref: str, domains: tuple[str, ...] = ()) -> dict:
        self._ensure()
        if ref in self.entities:
            return self.entities[ref]
        q = str(ref or "").strip().casefold()
        pool = [e for e in self.entities.values() if not domains or e["domain"] in domains]
        hits = [e for e in pool if e["name"].casefold() == q] or [e for e in pool if q and q in e["name"].casefold()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise NotFound(f"in casa non trovo «{ref}»")
        raise Invalid("più dispositivi corrispondono: " + ", ".join(h["name"] for h in hits[:6]))

    def status(self) -> dict:
        if not self.ha.configured:
            return {"configured": False, "connected": False}
        try:
            self._ensure()
        except Invalid as exc:
            return {"configured": True, "connected": False, "error": str(exc)}
        ents = list(self.entities.values())
        lights_on = [e["name"] for e in ents if e["domain"] == "light" and e["state"] == "on"]
        temps = [f"{e['name']} {e['state']}{e['unit']}" for e in ents
                 if e["domain"] == "sensor" and e["device_class"] == "temperature"][:6]
        open_ = [e["name"] for e in ents if e["domain"] == "binary_sensor" and e["device_class"] in
                 ("door", "window", "opening") and e["state"] == "on"]
        person = self.entities.get(self.get("lares.persona", "") or "")
        return {"configured": True, "connected": self.connected, "entities": len(ents), "lights_on": lights_on,
                "temperatures": temps, "open": open_, "person": person["state"] if person else None,
                "favorites": self.favorites()}

    # ── commands ────────────────────────────────────────────────────────────
    def command(self, ref: str, command: str, value: Any = None) -> dict:
        if command not in COMMANDS:
            raise Invalid("comando: " + ", ".join(COMMANDS))
        e = self.find(ref, ("light", "switch", "cover", "climate", "fan", "media_player", "lock", "scene", "script"))
        domain, service = e["domain"], COMMANDS[command]
        data: dict[str, Any] = {"entity_id": e["id"]}
        if domain in ("scene", "script"):
            service = "turn_on"
        elif domain == "light" and value not in (None, "") and command == "on":
            data["brightness_pct"] = max(1, min(100, int(value)))
        elif domain == "climate" and value not in (None, ""):
            service, data["temperature"] = "set_temperature", float(value)
        elif domain in ("switch", "fan", "media_player") and command in ("open", "close", "lock", "unlock"):
            raise Invalid(f"{e['name']}: usa on, off o toggle")
        try:
            self.ha.call(domain, service, data)
        except HAError as exc:
            raise Invalid(str(exc)) from None
        logger.info("event=lares_command domain=%s service=%s", domain, service)
        return {"ok": True, "name": e["name"], "command": command}

    def scene(self, ref: str) -> dict:
        e = self.find(ref, ("scene", "script"))
        return self.command(e["id"], "on")

    # ── favourites (quick actions) ──────────────────────────────────────────
    def favorites(self) -> list[dict]:
        self.store.refresh()
        return sorted(self.store.items("favorite"), key=lambda f: (f.get("room") or "", f.get("label") or ""))

    def add_favorite(self, entity: str, label: str = "", room: str = "", command: str = "toggle") -> dict:
        e = self.find(entity)
        if command not in COMMANDS:
            raise Invalid("comando: " + ", ".join(COMMANDS))
        fid = new_id("f")
        data = {"entity_id": e["id"], "label": (label or e["name"])[:60], "room": room[:40], "command": command,
                "at": now_iso()}
        self.store.upsert("favorite", fid, data, ref_id=e["id"])
        return {**data, "id": fid}

    def run_favorite(self, fid: str) -> dict:
        f = self.store.data("favorite", fid)
        if not f:
            raise NotFound("azione rapida non trovata")
        return self.command(f["entity_id"], f.get("command") or "toggle")

    def delete_favorite(self, fid: str) -> dict:
        if not self.store.delete("favorite", fid):
            raise NotFound("azione rapida non trovata")
        return {"deleted": True}

    @staticmethod
    def say(e: dict) -> str:
        if e["domain"] == "sensor":
            return f"{e['state']}{e['unit']}"
        return STATE_IT.get(str(e["state"]), str(e["state"]))
