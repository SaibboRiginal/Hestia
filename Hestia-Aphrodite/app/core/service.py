"""Aphrodite — how the clients look («Aspetto», dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A2).

Profiles (palette, a light effect, a background) and pets (a small companion with a few poses). Aphrodite decides
by itself which profile is on: a special moment of today pushed by the calendar (the owner's birthday, the owner's
important events), then the holidays (Natale, Capodanno, San Valentino, Pasqua, Halloween…), then the season.
Marko's only switch is per client: ``auto`` off = the standard look. The pet is a per-client choice. Pictures are
asked to the image module (``POST /api/images/jobs`` with a callback here); clients only read ``GET /now``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from hestia_common.module_kit import Invalid, NotFound, new_id, now_iso

logger = logging.getLogger("hestia_aphrodite.service")

EFFECTS = ("none", "snow", "leaves", "petals", "sun", "hearts", "confetti", "pumpkins", "stars")
POSES = ("idle", "happy", "sleep")
CLIENTS = {"webui": "Sito"}


def easter(year: int) -> date:
    """Gregorian Easter (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)


# key: (name, palette, effect, background prompt). Palettes are accents over the client's own light/dark theme.
BUILTIN: dict[str, dict] = {
    "standard": {"name": "Standard", "palette": {}, "effect": "none", "prompt": ""},
    "compleanno": {"name": "Compleanno", "palette": {"accent": "#D97706", "accent2": "#DB2777"}, "effect": "confetti",
                   "prompt": "soft festive birthday background, balloons, warm light, minimal, no text"},
    "evento": {"name": "Giornata speciale", "palette": {"accent": "#7C3AED"}, "effect": "stars",
               "prompt": "soft celebratory background, gentle sparkles, minimal, no text"},
    "capodanno": {"name": "Capodanno", "palette": {"accent": "#CA8A04", "accent2": "#1E3A8A"}, "effect": "confetti",
                  "prompt": "new year night, gold fireworks, elegant minimal, no text"},
    "natale": {"name": "Natale", "palette": {"accent": "#B91C1C", "accent2": "#166534"}, "effect": "snow",
               "prompt": "cozy christmas, warm lights, snow, minimal illustration, no text"},
    "san_valentino": {"name": "San Valentino", "palette": {"accent": "#DB2777"}, "effect": "hearts",
                      "prompt": "soft pink hearts, minimal, no text"},
    "pasqua": {"name": "Pasqua", "palette": {"accent": "#65A30D", "accent2": "#EAB308"}, "effect": "petals",
               "prompt": "spring easter, pastel flowers, minimal, no text"},
    "halloween": {"name": "Halloween", "palette": {"accent": "#EA580C", "accent2": "#6D28D9"}, "effect": "pumpkins",
                  "prompt": "friendly halloween, pumpkins, purple dusk, minimal illustration, no text"},
    "primavera": {"name": "Primavera", "palette": {"accent": "#16A34A"}, "effect": "petals", "prompt": ""},
    "estate": {"name": "Estate", "palette": {"accent": "#0284C7"}, "effect": "sun", "prompt": ""},
    "autunno": {"name": "Autunno", "palette": {"accent": "#C2410C"}, "effect": "leaves", "prompt": ""},
    "inverno": {"name": "Inverno", "palette": {"accent": "#2563EB"}, "effect": "none", "prompt": ""},
}


def holiday(day: date) -> str | None:
    md = (day.month, day.day)
    if md in ((12, 31), (1, 1)):
        return "capodanno"
    if (12, 8) <= md or md <= (1, 6):
        return "natale"
    if md == (2, 14):
        return "san_valentino"
    if abs((day - easter(day.year)).days) <= 1:
        return "pasqua"
    if (10, 25) <= md <= (10, 31) or md == (11, 1):
        return "halloween"
    return None


def season(day: date) -> str:
    md = (day.month, day.day)
    if (3, 21) <= md < (6, 21):
        return "primavera"
    if (6, 21) <= md < (9, 23):
        return "estate"
    if (9, 23) <= md < (12, 21):
        return "autunno"
    return "inverno"


class Appearance:
    def __init__(self, store, hub, *, tz_name: str = "Europe/Rome", get: Callable[[str, Any], Any] = lambda k, d=None: d):
        self.store = store
        self.hub = hub
        self.tz = ZoneInfo(tz_name)
        self.get = get

    def today(self) -> date:
        return datetime.now(self.tz).date()

    # ── profiles ────────────────────────────────────────────────────────────
    def profiles(self) -> list[dict]:
        self.store.refresh()
        stored = {p["id"]: p for p in self.store.items("profile")}
        out = [{**v, "id": k, "builtin": True, **stored.pop(k, {})} for k, v in BUILTIN.items()]
        return out + [{**p, "builtin": False} for p in stored.values()]

    def profile(self, key: str) -> dict:
        p = next((p for p in self.profiles() if p["id"] == key), None)
        if not p:
            raise NotFound(f"nessun profilo «{key}»")
        return p

    def save_profile(self, body: dict, key: str | None = None) -> dict:
        old = self.profile(key) if key else {}
        name = str(body.get("name") or old.get("name") or "").strip()[:40]
        if not name:
            raise Invalid("serve un nome")
        effect = body.get("effect") or old.get("effect") or "none"
        if effect not in EFFECTS:
            raise Invalid("effetto: " + ", ".join(EFFECTS))
        palette = body.get("palette") if isinstance(body.get("palette"), dict) else old.get("palette") or {}
        when = body.get("when") if isinstance(body.get("when"), dict) else old.get("when")
        if when and not all(isinstance(when.get(k), str) and len(when[k]) == 5 for k in ("from", "to")):
            raise Invalid("quando: {from: MM-GG, to: MM-GG}")
        data = {"name": name, "palette": {k: str(v)[:9] for k, v in palette.items() if k in ("accent", "accent2")},
                "effect": effect, "prompt": str(body.get("prompt", old.get("prompt") or ""))[:400], "when": when,
                "background": old.get("background"), "updated_at": now_iso()}
        key = key or new_id("pr")
        self.store.upsert("profile", key, data)
        return {**data, "id": key}

    def moment(self, moment: dict) -> dict:
        """Calendar ``special_moment`` of today: the owner's own moments change the look for the day."""
        if moment.get("person_id"):
            return {"handled": False}                       # other people's dates: gifts, not decorations
        kind = "compleanno" if moment.get("kind") == "birthday" else "evento"
        day = str(moment.get("date") or self.today().isoformat())[:10]
        self.store.upsert("moment", f"{day}-{moment.get('key') or kind}", {
            "date": day, "profile": kind, "title": str(moment.get("title") or "")[:80]})
        return {"handled": True, "profile": kind}

    def active(self, day: date | None = None) -> tuple[str, str]:
        """(profile key, why) for a day: today's moment > custom dated profiles > holidays > season."""
        day = day or self.today()
        self.store.refresh()
        moments = [m for m in self.store.items("moment") if m.get("date") == day.isoformat()]
        if moments:
            m = sorted(moments, key=lambda m: m["profile"] != "compleanno")[0]
            return m["profile"], m.get("title") or BUILTIN[m["profile"]]["name"]
        md = f"{day.month:02d}-{day.day:02d}"
        for p in self.profiles():
            w = p.get("when")
            if w and (w["from"] <= md <= w["to"] if w["from"] <= w["to"] else (md >= w["from"] or md <= w["to"])):
                return p["id"], p["name"]
        h = holiday(day)
        if h:
            return h, BUILTIN[h]["name"]
        s = season(day)
        return s, BUILTIN[s]["name"]

    # ── per client ──────────────────────────────────────────────────────────
    def choice(self, client: str) -> dict:
        self.store.refresh()
        return {"client": client, "auto": True, "pet": "", **(self.store.data("choice", client) or {})}

    def set_choice(self, client: str, *, auto: bool | None = None, pet: str | None = None) -> dict:
        client = str(client or "webui")[:20]
        old = self.choice(client)
        if pet:
            self.pet(pet)
        data = {"auto": old["auto"] if auto is None else bool(auto), "pet": old["pet"] if pet is None else pet,
                "updated_at": now_iso()}
        self.store.upsert("choice", client, data)
        return {"client": client, **data}

    def now(self, client: str = "webui") -> dict:
        c = self.choice(client)
        key, why = self.active() if c["auto"] else ("standard", "scelto da te")
        p = self.profile(key)
        pet = None
        if c["pet"]:
            try:
                pet = self.pet(c["pet"])
            except NotFound:
                pet = None
        return {"client": client, "auto": c["auto"], "profile": {
            "key": key, "name": p["name"], "palette": p.get("palette") or {}, "effect": p.get("effect") or "none",
            "background": p.get("background")}, "why": why, "pet": pet and {
            "id": pet["id"], "name": pet["name"], "images": pet.get("images") or {}}}

    # ── pets ────────────────────────────────────────────────────────────────
    def pets(self) -> list[dict]:
        self.store.refresh()
        return sorted(self.store.items("pet"), key=lambda p: p["name"].casefold())

    def pet(self, ref: str) -> dict:
        self.store.refresh()
        p = self.store.data("pet", ref) or next((p for p in self.store.items("pet")
                                                  if p["name"].casefold() == str(ref).casefold()), None)
        if not p:
            raise NotFound(f"nessun animaletto «{ref}»")
        return p

    def save_pet(self, body: dict, pid: str | None = None) -> dict:
        old = self.pet(pid) if pid else {}
        name = str(body.get("name") or old.get("name") or "").strip()[:30]
        if not name:
            raise Invalid("come si chiama?")
        data = {"name": name, "species": str(body.get("species", old.get("species") or "gatto"))[:30],
                "look": str(body.get("look", old.get("look") or ""))[:300], "images": old.get("images") or {},
                "updated_at": now_iso()}
        for pose in POSES:                                   # an uploaded picture (blob id) wins over a generated one
            if body.get(f"image_{pose}"):
                data["images"][pose] = str(body[f"image_{pose}"])
        pid = old.get("id") or new_id("pet")
        self.store.upsert("pet", pid, data, ref_id=name.casefold())
        return {**data, "id": pid}

    def delete_pet(self, ref: str) -> dict:
        p = self.pet(ref)
        self.store.delete("pet", p["id"])
        return {"deleted": True}

    # ── pictures from the image module ──────────────────────────────────────
    def generate(self, target: str, ref: str) -> dict:
        """Ask pictures: a profile's background or every pose of a pet. The result comes back by push (``done``)."""
        asks = []
        if target == "profile":
            p = self.profile(ref)
            if not p.get("prompt"):
                raise Invalid("questo profilo non ha una descrizione per lo sfondo")
            asks.append((f"profile:{p['id']}:background", p["prompt"], "sfondo", 1536, 864))
        elif target == "pet":
            p = self.pet(ref)
            look = f"{p['look']} " if p.get("look") else ""
            for pose, words in (("idle", "sitting calmly"), ("happy", "happy, jumping"), ("sleep", "sleeping curled up")):
                asks.append((f"pet:{p['id']}:{pose}", f"cute small {p['species']} mascot, {look}{words}, flat "
                             "sticker illustration, plain white background", "mascotte", 512, 512))
        else:
            raise Invalid("target: profile o pet")
        jobs = []
        for ref_key, prompt, purpose, w, h in asks:
            out = self.hub.ok("apollo", "POST", "api/images/jobs", body={
                "prompt": prompt, "purpose": purpose, "width": w, "height": h, "ref": ref_key, "by": "aphrodite",
                "callback": {"service": "aphrodite", "path": "/api/appearance/images/done"}}, timeout=15) or {}
            jobs.append({"ref": ref_key, "job_id": out.get("id"), "status": out.get("status"), "error": out.get("error")})
        return {"asked": len(jobs), "jobs": jobs}

    def image_done(self, body: dict) -> dict:
        ref = str(body.get("ref") or "")
        blobs = body.get("blob_ids") or []
        if body.get("status") != "done" or not blobs:
            logger.info("event=aphrodite_image_not_done ref=%s error=%s", ref, body.get("error"))
            return {"stored": False}
        kind, _, rest = ref.partition(":")
        oid, _, slot = rest.partition(":")
        if kind == "profile":
            p = self.profile(oid)
            data = {k: v for k, v in p.items() if k not in ("id", "builtin")}
            self.store.upsert("profile", oid, {**data, "background": blobs[0], "updated_at": now_iso()})
        elif kind == "pet" and slot in POSES:
            p = self.pet(oid)
            images = {**(p.get("images") or {}), slot: blobs[0]}
            self.store.upsert("pet", oid, {**{k: v for k, v in p.items() if k != "id"}, "images": images,
                                           "updated_at": now_iso()}, ref_id=p["name"].casefold())
        else:
            return {"stored": False}
        return {"stored": True}

    def upcoming(self, days: int = 60) -> list[dict]:
        """What the look will be in the next days (only the changes)."""
        out, last = [], None
        for i in range(days):
            d = self.today() + timedelta(days=i)
            key, why = self.active(d)
            if key != last:
                out.append({"date": d.isoformat(), "profile": key, "why": why})
                last = key
        return out
