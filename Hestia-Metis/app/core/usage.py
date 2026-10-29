"""Usage log, «Adesso» and «Scopri» (brainstorm C11 + C14, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W6).

Clients push **taps** (`POST /api/metis/usage`: a tool run, a page opened, a quick action) into Archive
``metis-store`` (kind ``tap``). From them, with no model:

- **Adesso** — what fits now: tools used at this hour / on this kind of day (habit score with recency decay), the
  last ones used, agenda items of the next hours that name a tool; plus up to 3 **ideas** written by the assistant a
  few times a day (agenda job ``metis.adesso``, Oracle use case ``metis.adesso``; never when a client opens). Each
  item says why. Tools that the client cannot run or that no longer exist are dropped.
- **Scopri** — the tools of the Hub catalog never or rarely used, with what they do.

Only the owner's own taps are counted; nothing leaves Hestia.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from hestia_common.areas import area_of, for_people
from hestia_common.module_kit import Invalid, new_id, now_iso, parse_dt

logger = logging.getLogger("hestia_metis.usage")

CLIENTS = ("telegram", "webui", "mcp")
KINDS = ("tool", "page", "action")
CLIENT_KEY = {"webui": "ui", "telegram": "telegram", "mcp": "mcp"}      # MCPTool.clients names
IDEAS_USE = "metis.adesso"
KEEP_DAYS = 180
WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
_SKIP = re.compile(r"(_delete|_elimina|_remove|_rimuovi|_annulla|_conferma|_off|_on)$")


class Usage:
    def __init__(self, store, hub, *, tz_name: str = "Europe/Rome", agenda=None, catalog_ttl: float = 600,
                 catalog_fn=None):
        self.store = store
        self.hub = hub
        self._catalog_fn = catalog_fn or self._hub_catalog
        self.tz = ZoneInfo(tz_name)
        self.agenda = agenda
        self._catalog: tuple[float, list[dict]] = (0.0, [])
        self._ttl = catalog_ttl

    def now(self) -> datetime:
        return datetime.now(self.tz)

    # ── taps ────────────────────────────────────────────────────────────────
    def record(self, taps: list[dict]) -> dict:
        rows = []
        for t in taps[:200]:
            client = str(t.get("client") or "").lower()
            kind = str(t.get("kind") or "tool").lower()
            ref = str(t.get("ref") or "").strip()[:120]
            if client not in CLIENTS or kind not in KINDS or not ref:
                continue
            at = parse_dt(t.get("at")) or datetime.now(timezone.utc)
            local = at.astimezone(self.tz)
            rows.append({"kind": "tap", "id": new_id("t"), "ref_id": ref, "at": at.isoformat(),
                         "data": {"client": client, "kind": kind, "ref": ref, "label": str(t.get("label") or "")[:80],
                                  "weekday": local.weekday(), "hour": local.hour}})
        if not rows and taps:
            raise Invalid("tap: client telegram|webui|mcp, kind tool|page|action, ref")
        if rows:
            self.store.write(rows)
        return {"recorded": len(rows)}

    def taps(self, days: int = 90, client: str = "") -> list[dict]:
        self.store.refresh()
        since = datetime.now(timezone.utc) - timedelta(days=days)
        out = []
        for r in self.store.all("tap"):
            at = parse_dt(r.get("at"))
            if at and at >= since and (not client or r["data"].get("client") == client):
                out.append({**r["data"], "at": at})
        return sorted(out, key=lambda t: t["at"])

    def prune(self) -> int:
        """Taps older than KEEP_DAYS go (called by the agenda job)."""
        cut = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
        old = [r for r in self.store.all("tap") if (parse_dt(r.get("at")) or cut) < cut]
        if old:
            self.store.write([{**{k: r.get(k) for k in ("kind", "id", "parent_id", "ref_id", "at", "data")},
                               "deleted": True} for r in old])
        return len(old)

    # ── catalog (Hub) ───────────────────────────────────────────────────────
    def _hub_catalog(self) -> dict:
        """Hub's own discovery API (like Telegram's /registry/services read): not a module, so no /route."""
        resp = requests.get(f"{self.hub.base}/discovery/catalog", params={"type": "tool"}, timeout=15)
        resp.raise_for_status()
        return resp.json() or {}

    def catalog(self) -> list[dict]:
        at, rows = self._catalog
        if rows and time.monotonic() - at < self._ttl:
            return rows
        try:
            out = self._catalog_fn() or {}
            rows = (((out.get("contributions") or {}).get("*") or {}).get("tool") or [])
            rows = [r for r in rows if isinstance(r, dict) and r.get("name")]
            self._catalog = (time.monotonic(), rows)
        except Exception as exc:
            logger.warning("[🔄] event=metis_catalog_failed error=%s fallback=last_catalog", exc)
        return self._catalog[1]

    def tools_for(self, client: str) -> dict[str, dict]:
        key = CLIENT_KEY.get(client, client)
        return {t["name"]: t for t in self.catalog()
                if not t.get("clients") or key in t["clients"] or "*" in t["clients"]}

    # ── Adesso ──────────────────────────────────────────────────────────────
    def habits(self, client: str, now: datetime) -> list[tuple[str, float, str]]:
        scores: dict[str, float] = defaultdict(float)
        why: dict[str, Counter] = defaultdict(Counter)
        weekend = now.weekday() >= 5
        for t in self.taps(60, client):
            if t["kind"] != "tool":
                continue
            age = (now - t["at"].astimezone(self.tz)).total_seconds() / 86400
            dh = min(abs(t["hour"] - now.hour), 24 - abs(t["hour"] - now.hour))
            hour_w = 1.0 if dh <= 1 else 0.4 if dh <= 2 else 0.05
            day_w = 1.5 if t["weekday"] == now.weekday() else 1.0 if (t["weekday"] >= 5) == weekend else 0.4
            scores[t["ref"]] += math.exp(-age / 21) * hour_w * day_w
            why[t["ref"]]["day" if t["weekday"] == now.weekday() and dh <= 1 else "hour" if dh <= 1 else "often"] += 1
        out = []
        for ref, score in sorted(scores.items(), key=lambda kv: -kv[1]):
            if score < 0.3:
                break
            top = why[ref].most_common(1)[0][0]
            reason = {"day": f"Di solito il {WEEKDAYS[now.weekday()]} a quest'ora", "hour": "Di solito a quest'ora",
                      "often": "La usi spesso"}[top]
            out.append((ref, score, reason))
        return out

    def _agenda_items(self, now: datetime) -> list[dict]:
        if not self.agenda:
            return []
        out = []
        for occ in self.agenda.agenda(days=1):
            start = parse_dt(occ.get("start_at"))
            if not start or not 0 <= (start - now).total_seconds() <= 3 * 3600:
                continue
            out.append({"title": str(occ.get("title") or "")[:80], "at": start.astimezone(self.tz).strftime("%H:%M"),
                        "tool": ((occ.get("params") or {}).get("tool") or "")})
        return out

    def adesso(self, client: str = "telegram", now: datetime | None = None, limit: int = 6) -> dict:
        if client not in CLIENTS:
            raise Invalid("client: " + ", ".join(CLIENTS))
        now = (now or self.now()).astimezone(self.tz)
        tools = self.tools_for(client)
        items: list[dict] = []
        seen: set[str] = set()

        def add(ref: str, reason: str, source: str, args: dict | None = None) -> None:
            if ref in seen or ref not in tools or len(items) >= limit or _SKIP.search(ref):
                return
            seen.add(ref)
            t = tools[ref]
            items.append({"tool": ref, "title": t.get("title") or ref, "module": t.get("module"), "args": args or {},
                          "reason": reason, "source": source})

        for a in self._agenda_items(now):
            if a["tool"]:
                add(a["tool"], f"In agenda alle {a['at']}: {a['title']}", "agenda")
        for ref, _, reason in self.habits(client, now)[:3]:
            add(ref, reason, "habit")
        recent = [t["ref"] for t in reversed(self.taps(7, client)) if t["kind"] == "tool"]
        for ref in dict.fromkeys(recent):
            if sum(1 for i in items if i["source"] in ("habit", "recent")) >= 3:
                break
            add(ref, "Usata di recente", "recent")
        ideas = self.store.data("idea", client) or {}
        if ideas and (parse_dt(ideas.get("expires")) or now) > now:
            for idea in ideas.get("items") or []:
                add(str(idea.get("tool") or ""), str(idea.get("reason") or "Un'idea per adesso")[:120], "idea",
                    idea.get("args") if isinstance(idea.get("args"), dict) else None)
        return {"client": client, "at": now.isoformat(timespec="minutes"), "items": items,
                "ideas_at": ideas.get("at")}

    def refresh_ideas(self, client: str = "telegram") -> dict:
        """Agenda job: the assistant writes up to 3 ideas for the next hours (fails soft: the old ones expire)."""
        now = self.now()
        tools = {k: v for k, v in self.tools_for(client).items() if not _SKIP.search(k)}
        if not tools:
            return {"ideas": 0, "reason": "no_catalog"}
        habits = [r for r, _, _ in self.habits(client, now)[:6]]
        used = Counter(t["ref"] for t in self.taps(30, client) if t["kind"] == "tool")
        menu = "\n".join(f"{n}: {t.get('title') or ''}" for n, t in sorted(tools.items())[:150])
        agenda = "; ".join(f"{a['at']} {a['title']}" for a in self._agenda_items(now)) or "niente"
        prompt = (f"Ora: {WEEKDAYS[now.weekday()]} {now:%H:%M}. Abitudini: {', '.join(habits) or 'nessuna'}. "
                  f"Agenda prossime ore: {agenda}. Strumenti:\n{menu}\n"
                  "Scegli 3 strumenti utili ADESSO diversi dalle abitudini, meglio se poco usati "
                  f"({', '.join(n for n in tools if not used[n])[:600]}). "
                  'Rispondi SOLO JSON: [{"tool":"nome","reason":"perché, max 60 caratteri, italiano"}]')
        text = self.hub.llm(prompt, use_case=IDEAS_USE, max_tokens=300, temperature=0.4) if self.hub else None
        ideas = []
        try:
            m = re.search(r"\[.*\]", text or "", re.S)
            for raw in json.loads(m.group(0)) if m else []:
                name = str((raw or {}).get("tool") or "")
                if name in tools and name not in habits and name not in {i["tool"] for i in ideas}:
                    ideas.append({"tool": name, "reason": str(raw.get("reason") or "")[:80] or "Un'idea per adesso"})
        except (ValueError, TypeError, AttributeError):
            ideas = []
        if not ideas:
            logger.info("[🔄] event=metis_ideas_empty client=%s fallback=habits_only", client)
            return {"ideas": 0}
        self.store.upsert("idea", client, {"items": ideas[:3], "at": now_iso(),
                                           "expires": (now + timedelta(hours=8)).isoformat()})
        return {"ideas": len(ideas[:3])}

    # ── Scopri ──────────────────────────────────────────────────────────────
    def scopri(self, client: str = "webui", limit: int = 12) -> dict:
        tools = {k: v for k, v in self.tools_for(client).items() if not _SKIP.search(k)}
        used = Counter(t["ref"] for t in self.taps(90) if t["kind"] == "tool")
        rows = []
        for n, t in tools.items():
            if used[n] > 2:
                continue
            area = area_of(t, str(t.get("module") or ""))
            # people read the area and a short text, never the module name or the notes meant for the model
            rows.append({"tool": n, "title": t.get("title") or n, "description": for_people(t),
                         "module": t.get("module"), "area": area["key"], "area_label": area["label"],
                         "area_icon": area["icon"], "area_order": area["order"], "uses": used[n],
                         "reason": "Non l'hai mai usata" if not used[n]
                         else f"Usata {used[n]} volt{'a' if used[n] == 1 else 'e'}"})
        rows.sort(key=lambda r: (r["uses"], r["area_order"], r["title"]))
        # one per area first, so the page shows many different things
        first, rest, seen = [], [], set()
        for r in rows:
            (rest if r["area"] in seen else first).append(r)
            seen.add(r["area"])
        return {"client": client, "items": (first + rest)[:limit], "total": len(rows), "tools": len(tools)}

    def stats(self, days: int = 30) -> dict:
        taps = self.taps(days)
        by_client = Counter(t["client"] for t in taps)
        top = Counter(t["ref"] for t in taps if t["kind"] == "tool").most_common(10)
        return {"days": days, "taps": len(taps), "by_client": dict(by_client),
                "top": [{"tool": r, "uses": n} for r, n in top]}
