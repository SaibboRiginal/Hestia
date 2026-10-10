"""Assistant presence — signals → data-defined states → effects.

SPEC docs/work/2026-10-10-assistant-presence (v2.2).

- **Signals** are facts reported by modules, never interpreted by the reporter:
  ``user.last_interaction`` (ping), ``activity.<key>`` (a running job with ``load``/``resource``/
  ``kind``), ``manual.dnd``, ``resource.*``, ``health.*``… Each may expire (``ttl``) so a crashed
  reporter never leaves a stale state. Persisted in Archive (``/api/presence-store``).
- **Derived signals** are computed at evaluation: ``user.idle_minutes``, ``activity.heavy_count``,
  ``activity.maintenance_count``, ``agenda.window.<key>`` (assistant agenda), ``clock.hour``,
  ``setting.<name>`` (``chronos.presence.<name>``).
- **States** are definitions (setting ``chronos.presence.states`` + states declared by modules):
  one *base* at a time (highest priority that matches; ``idle`` when none) + any *overlays*.
  ``awake``/``idle``/``dnd`` are core: always present, never disabled.
- **Effects** are what consumers ask (``work.heavy`` allow/local/defer…): base first, overlays
  combine "most restrictive wins" for ranked effects, override by priority for the others.

Evaluation runs on every signal change and on the agenda worker tick (no loop of its own).
A change is stored (snapshot + history) and published to Hermes as ``assistant.state_changed``;
when the notification level opens again Hermes is asked to release the held notifications.
"""
from __future__ import annotations

import copy
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from core import archive_client
from core import presence_settings as PS
from core.hermes_client import publish_event

logger = logging.getLogger("hestia_chronos.presence")

_HUB = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
NEVER_MINUTES = 10 ** 7          # no interaction recorded yet
_PING_PERSIST_SECONDS = 30       # write-through of user.last_interaction at most this often
_WINDOW_CACHE_SECONDS = 60
_HISTORY_KEEP = 100
OPS = {"<", "<=", ">", ">=", "==", "!=", "in", "true", "false"}
KINDS = {"base", "overlay"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── pure helpers (unit-tested) ──────────────────────────────────────────────


def check(clause: dict, signals: dict[str, Any], resolve: Callable[[str], Any]) -> bool:
    """One clause ``{signal, op, value}``. Missing signal → false (``false`` op → true)."""
    op = str(clause.get("op") or "true")
    present = clause.get("signal") in signals
    current = signals.get(clause.get("signal"))
    if op == "true":
        return bool(current)
    if op == "false":
        return not current
    if not present or current is None:
        return False
    target = clause.get("value")
    if isinstance(target, str) and target.startswith("$"):
        target = resolve(target[1:])
    try:
        if op == "in":
            return current in (target or [])
        if op == "==":
            return current == target
        if op == "!=":
            return current != target
        a, b = float(current), float(target)
    except (TypeError, ValueError):
        return False
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}.get(op, False)


def matches(definition: dict, signals: dict[str, Any], resolve: Callable[[str], Any]) -> bool:
    """``when`` = groups (OR) of clauses (AND); empty → never."""
    groups = definition.get("when") or []
    return any(group and all(check(c, signals, resolve) for c in group) for group in groups)


def combine(base: dict | None, overlays: list[dict]) -> tuple[dict[str, Any], dict[str, str]]:
    """Effects of the base, then overlays by ascending priority. Ranked effects keep the most
    restrictive value; any other effect is taken from the highest priority state."""
    effects: dict[str, Any] = dict(PS.DEFAULT_EFFECTS)
    decided: dict[str, str] = {k: "default" for k in effects}
    if base:
        for name, value in (base.get("effects") or {}).items():
            effects[name], decided[name] = value, base["key"]
    for state in sorted(overlays, key=lambda s: int(s.get("priority") or 0)):
        for name, value in (state.get("effects") or {}).items():
            order = PS.EFFECT_ORDER.get(name)
            if order and value in order and effects.get(name) in order:
                if order.index(value) > order.index(effects[name]):
                    effects[name], decided[name] = value, state["key"]
            else:
                effects[name], decided[name] = value, state["key"]
    return effects, decided


def normalize_states(stored: Any, declared: dict[str, dict] | None = None) -> dict[str, dict]:
    """Effective definitions: built-ins → module-declared → the user's setting (wins by key).
    Core states are always present and enabled; broken entries are skipped with a log."""
    merged: dict[str, dict] = {}
    for source in (PS.BUILTIN_STATES, declared or {}, stored if isinstance(stored, dict) else {}):
        for key, raw in (source or {}).items():
            if not isinstance(raw, dict):
                continue
            base = merged.get(key, {})
            item = {**base, **copy.deepcopy(raw), "key": str(key)}
            if item.get("kind") not in KINDS:
                logger.warning("event=presence_state_invalid key=%s reason=kind", key)
                continue
            merged[key] = item
    for key in PS.CORE_STATES:
        merged.setdefault(key, {**copy.deepcopy(PS.BUILTIN_STATES[key]), "key": key})
        merged[key]["core"] = True
        merged[key]["enabled"] = True
        merged[key]["kind"] = "base"
    return {k: v for k, v in merged.items() if v.get("enabled", True)}


def render(text: str, activities: list[dict]) -> str:
    heavy = [a.get("label") or a.get("key") for a in activities if a.get("load") == "heavy"]
    return str(text or "").replace("{activities}", ", ".join(heavy) or "lavoro in corso")


def decide(states: dict[str, dict], signals: dict[str, Any], resolve: Callable[[str], Any],
           activities: list[dict]) -> dict[str, Any]:
    """Pick base + overlays and their effects (no side effects)."""
    bases = sorted((s for s in states.values() if s["kind"] == "base"),
                   key=lambda s: -int(s.get("priority") or 0))
    base = next((s for s in bases if matches(s, signals, resolve)), None) or states.get("idle")
    overlays = sorted((s for s in states.values() if s["kind"] == "overlay" and matches(s, signals, resolve)),
                      key=lambda s: -int(s.get("priority") or 0))
    effects, decided = combine(base, overlays)
    notices = [render(s["notice"], activities) for s in [base, *overlays] if s and s.get("notice")]
    if notices:
        effects["chat.notice"] = "; ".join(notices)
    labels = [render(s.get("label") or s["key"], activities) for s in [base, *overlays] if s]
    return {
        "base": base["key"] if base else "idle",
        "base_label": labels[0] if labels else "In attesa",
        "emoji": (base or {}).get("emoji") or "",
        "overlays": [{"key": s["key"], "label": render(s.get("label") or s["key"], activities),
                      "emoji": s.get("emoji") or ""} for s in overlays],
        "label": " · ".join(labels),
        "effects": effects,
        "decided_by": decided,
    }


# ── engine ─────────────────────────────────────────────────────────────────


class PresenceEngine:
    def __init__(self, window_status: Callable[[str], dict] | None = None,
                 store: Callable[..., Any] | None = None, emit: Callable[[str, dict], Any] | None = None,
                 tz: str | None = None):
        self._lock = threading.RLock()
        self._signals: dict[str, dict] = {}       # key → {value, meta, expires_at(datetime|None)}
        self._declared: dict[str, dict] = {}      # module-declared states (in memory, re-asserted)
        self._snapshot: dict[str, Any] | None = None
        self._windows: dict[str, tuple[float, bool]] = {}
        self._window_status = window_status
        self._store = store or archive_client._route_archive
        self._emit = emit or self._emit_default
        self._tz = tz
        self._loaded = False
        self._last_ping_persist = 0.0
        self._last_snapshot_persist = 0.0

    # ── persistence ─────────────────────────────────────────────────────────
    def load(self) -> bool:
        payload = self._store("GET", "api/presence-store", timeout=8)
        if not isinstance(payload, dict):
            logger.warning("[🔄] event=presence_load_failed fallback=empty")
            return False
        with self._lock:
            for row in payload.get("signals") or []:
                if isinstance(row, dict) and row.get("key"):
                    self._signals.setdefault(row["key"], {
                        "value": row.get("value"), "meta": row.get("meta") or {},
                        "expires_at": _parse(row.get("expires_at"))})
            if isinstance(payload.get("snapshot"), dict):
                self._snapshot = payload["snapshot"]
            self._loaded = True
        logger.info("event=presence_loaded signals=%d state=%s", len(self._signals),
                    (self._snapshot or {}).get("base"))
        return True

    def _persist_signal(self, key: str) -> None:
        sig = self._signals.get(key)
        if sig is None:
            self._store("DELETE", f"api/presence-store/signals/{key}", timeout=5)
            return
        self._store("PUT", f"api/presence-store/signals/{key}", body={
            "value": sig.get("value"), "meta": sig.get("meta") or {},
            "expires_at": _iso(sig.get("expires_at"))}, timeout=5)

    def _async(self, fn: Callable, *args) -> None:
        threading.Thread(target=fn, args=args, daemon=True, name="presence-io").start()

    # ── signals ─────────────────────────────────────────────────────────────
    def set_signal(self, key: str, value: Any = True, *, meta: dict | None = None,
                   ttl: float | None = None, persist: bool = True, reason: str = "") -> dict:
        key = str(key or "").strip()
        if not key or key.startswith(("user.idle", "setting.", "agenda.window.", "clock.")) \
                or key in {"activity.heavy_count", "activity.maintenance_count", "activity.count"}:
            raise ValueError(f"signal {key!r} is derived or invalid")
        with self._lock:
            self._signals[key] = {"value": value, "meta": dict(meta or {}),
                                  "expires_at": _now() + timedelta(seconds=float(ttl)) if ttl else None}
        if persist:
            self._async(self._persist_signal, key)
        return self.evaluate(reason or f"signal:{key}")

    def clear_signal(self, key: str, reason: str = "") -> dict:
        with self._lock:
            existed = self._signals.pop(str(key), None) is not None
        if existed:
            self._async(self._persist_signal, str(key))
        return self.evaluate(reason or f"clear:{key}")

    def ping(self, client: str = "", kind: str = "chat") -> dict:
        """An interaction of the user (chat, command, UI action)."""
        client, kind = str(client or "unknown")[:30], str(kind or "chat")[:30]
        if kind == "ui" and not PS.settings.get(PS.COUNT_UI):
            return self.view()
        now = time.time()
        with self._lock:
            self._signals["user.last_interaction"] = {
                "value": _iso(_now()), "meta": {"client": client, "kind": kind}, "expires_at": None}
            persist = now - self._last_ping_persist >= _PING_PERSIST_SECONDS
            if persist:
                self._last_ping_persist = now
        if persist:
            self._async(self._persist_signal, "user.last_interaction")
        return self.evaluate(f"interaction:{client}:{kind}")

    def activity_start(self, key: str, *, label: str = "", load: str = "light", resource: str = "",
                       kind: str = "work", module: str = "", ttl: float = 3600) -> dict:
        load = load if load in {"light", "heavy"} else "light"
        meta = {"label": str(label or key)[:80], "load": load, "resource": str(resource or "")[:30],
                "kind": str(kind or "work")[:30], "module": str(module or "")[:30], "since": _iso(_now())}
        return self.set_signal(f"activity.{key}", True, meta=meta, ttl=max(60.0, min(float(ttl), 48 * 3600)),
                               reason=f"activity_start:{key}")

    def activity_stop(self, key: str) -> dict:
        return self.clear_signal(f"activity.{key}", reason=f"activity_stop:{key}")

    def set_dnd(self, minutes: float | None = None, until: str | None = None) -> dict:
        end = _parse(until) if until else None
        if end is None:
            end = _now() + timedelta(minutes=float(minutes or PS.settings.get(PS.DND_DEFAULT) or 120))
        ttl = max(60.0, (end - _now()).total_seconds())
        return self.set_signal("manual.dnd", _iso(end), meta={"by": "user"}, ttl=ttl, reason="dnd_on")

    def clear_dnd(self) -> dict:
        return self.clear_signal("manual.dnd", reason="dnd_off")

    # ── declared states (modules) ───────────────────────────────────────────
    def declare_states(self, owner: str, states: dict[str, dict]) -> int:
        clean = {}
        for key, raw in (states or {}).items():
            if not isinstance(raw, dict) or raw.get("kind") not in KINDS or key in PS.CORE_STATES:
                continue
            clean[str(key)] = {**raw, "owner": owner}
        with self._lock:
            for key in [k for k, v in self._declared.items() if v.get("owner") == owner]:
                self._declared.pop(key, None)
            self._declared.update(clean)
        self.evaluate(f"states_declared:{owner}")
        return len(clean)

    def states(self) -> dict[str, dict]:
        with self._lock:
            declared = dict(self._declared)
        return normalize_states(PS.settings.get(PS.STATES), declared)

    # ── evaluation ──────────────────────────────────────────────────────────
    def _window_open(self, key: str) -> bool:
        hit = self._windows.get(key)
        if hit and time.monotonic() - hit[0] < _WINDOW_CACHE_SECONDS:
            return hit[1]
        active = False
        try:
            active = bool((self._window_status(key) if self._window_status else {}).get("active"))
        except Exception as exc:
            logger.warning("[🔄] event=presence_window_failed key=%s error=%s fallback=closed", key, exc)
            if hit:
                active = hit[1]
        self._windows[key] = (time.monotonic(), active)
        return active

    def _signals_view(self, states: dict[str, dict]) -> tuple[dict[str, Any], list[dict]]:
        now = _now()
        with self._lock:
            expired = [k for k, s in self._signals.items() if s.get("expires_at") and s["expires_at"] <= now]
            for key in expired:
                self._signals.pop(key, None)
            raw = {k: dict(s) for k, s in self._signals.items()}
        for key in expired:
            self._async(self._persist_signal, key)
        values: dict[str, Any] = {k: s.get("value") for k, s in raw.items()}
        activities = [{"key": k[len("activity."):], **(s.get("meta") or {})}
                      for k, s in raw.items() if k.startswith("activity.")]
        last = _parse(values.get("user.last_interaction"))
        values["user.idle_minutes"] = (now - last).total_seconds() / 60 if last else NEVER_MINUTES
        values["user.last_client"] = ((raw.get("user.last_interaction") or {}).get("meta") or {}).get("client")
        values["activity.count"] = len(activities)
        values["activity.heavy_count"] = sum(1 for a in activities if a.get("load") == "heavy"
                                             and a.get("kind") != "maintenance")
        values["activity.maintenance_count"] = sum(1 for a in activities if a.get("kind") == "maintenance")
        values["resource.gpu_busy"] = values.get("resource.gpu_busy") or any(
            a.get("resource") == "gpu" and a.get("load") == "heavy" for a in activities)
        dnd_until = _parse(values.get("manual.dnd"))
        values["manual.dnd"] = bool(dnd_until and dnd_until > now)
        tz = self._tz or "Europe/Rome"
        try:
            local = now.astimezone(ZoneInfo(tz))
        except Exception:
            local = now
        values["clock.hour"] = local.hour
        values["clock.minutes"] = local.hour * 60 + local.minute
        for state in states.values():
            for group in state.get("when") or []:
                for clause in group or []:
                    name = str((clause or {}).get("signal") or "")
                    if name.startswith("agenda.window.") and name not in values:
                        values[name] = self._window_open(name[len("agenda.window."):])
                    elif name.startswith("setting.") and name not in values:
                        values[name] = PS.threshold(name[len("setting."):])
        return values, activities

    def evaluate(self, reason: str = "tick") -> dict:
        enabled = bool(PS.settings.get(PS.ENABLED))
        states = self.states()
        values, activities = self._signals_view(states)
        if enabled:
            decision = decide(states, values, PS.threshold, activities)
        else:
            decision = {"base": "awake", "base_label": "Sveglio", "emoji": "", "overlays": [],
                        "label": "Sveglio", "effects": dict(PS.DEFAULT_EFFECTS),
                        "decided_by": {k: "disabled" for k in PS.DEFAULT_EFFECTS}}
        idle = values["user.idle_minutes"]
        now_iso = _iso(_now())
        with self._lock:
            last_meta = ((self._signals.get("user.last_interaction") or {}).get("meta") or {})
            dnd = self._signals.get("manual.dnd")
            prev = self._snapshot or {}
            changed = (prev.get("base") != decision["base"]
                       or [o["key"] for o in prev.get("overlays") or []] != [o["key"] for o in decision["overlays"]]
                       or prev.get("label") != decision["label"])
            snapshot = {
                **decision,
                "enabled": enabled,
                "show_in_chat": bool(PS.settings.get(PS.ORACLE_LINE)),
                "since": now_iso if prev.get("base") != decision["base"] else (prev.get("since") or now_iso),
                "changed_at": now_iso if changed else (prev.get("changed_at") or now_iso),
                "reason": reason if changed else prev.get("reason", reason),
                "last_interaction_at": values.get("user.last_interaction"),
                "last_interaction_client": last_meta.get("client"),
                "last_interaction_kind": last_meta.get("kind"),
                "idle_minutes": None if idle >= NEVER_MINUTES else round(idle, 1),
                "dnd_until": (dnd or {}).get("value") if values.get("manual.dnd") else None,
                "activities": sorted(activities, key=lambda a: str(a.get("since") or "")),
                "evaluated_at": now_iso,
            }
            self._snapshot = snapshot
            stale = time.time() - self._last_snapshot_persist > 600
            if changed or stale:
                self._last_snapshot_persist = time.time()
        if changed:
            logger.info("event=presence_changed base=%s overlays=%s reason=%s previous=%s",
                        snapshot["base"], ",".join(o["key"] for o in snapshot["overlays"]) or "-",
                        reason, prev.get("base") or "-")
            self._async(self._on_change, prev, snapshot)
        elif stale:
            self._async(self._store, "PUT", "api/presence-store/snapshot", {"data": snapshot}, None, 5)
        return snapshot

    def _on_change(self, prev: dict, snapshot: dict) -> None:
        change = {"base": snapshot["base"], "overlays": [o["key"] for o in snapshot["overlays"]],
                  "label": snapshot["label"], "reason": snapshot["reason"],
                  "from": prev.get("base"), "from_label": prev.get("label")}
        self._store("PUT", "api/presence-store/snapshot",
                    body={"data": snapshot, "change": change, "history_keep": _HISTORY_KEEP}, timeout=5)
        self._emit("assistant.state_changed", {**change, "effects": snapshot["effects"]})
        order = PS.EFFECT_ORDER["notify.level"]
        before = (prev.get("effects") or {}).get("notify.level", "all")
        after = snapshot["effects"].get("notify.level", "all")
        if before in order and after in order and order.index(after) < order.index(before):
            self._release_held(after)

    def _emit_default(self, event_type: str, payload: dict) -> None:
        publish_event("assistant", event_type, "presence", {**payload, "_source": "chronos"})

    def _release_held(self, level: str) -> None:
        """Notification level opened again: Hermes sends the held ones as one digest."""
        try:
            requests.post(f"{_HUB}/route/hermes/api/notifications/release-held",
                          json={"method": "POST", "headers": {}, "query": {}, "body": {"level": level},
                                "timeout_seconds": 20}, timeout=25)
        except Exception as exc:
            logger.warning("[🔄] event=presence_release_held_failed error=%s", exc)

    # ── reading ─────────────────────────────────────────────────────────────
    def view(self) -> dict:
        return self.evaluate("read")

    def history(self, limit: int = 50) -> list[dict]:
        rows = self._store("GET", "api/presence-store/history", query={"limit": int(limit)}, timeout=8)
        return rows if isinstance(rows, list) else []


engine: PresenceEngine | None = None


def get_engine() -> PresenceEngine:
    global engine
    if engine is None:
        from services import agenda
        engine = PresenceEngine(window_status=agenda.window_status, tz=agenda._TZ_DEFAULT)
    return engine
