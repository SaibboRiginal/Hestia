"""Notification center — one notification, delivered to every client.

SPEC: docs/work/2026-10-10-hermes-global-notifications/SPEC.md

- A notification is ONE ``outbound_events`` row (channel ``notification``) with
  per-client ``deliveries`` in its payload. State is global: seen on one client
  = seen everywhere; the first answer wins.
- Audience: ``global`` (every client) or ``origin`` (pushed only to the client
  the request came from; the others get it ``silent`` for their inbox).
- Actions: ``{id, label, style, service, method, path, body}`` (Hermes routes the
  answer to the asking module via Hub; ``"<client>"`` in body = answering client)
  or legacy ``{text, command}`` (the answering client runs the Hub command).
- Repeat chains (SPEC 2026-10-17-hermes-repeat-notifications): an event with
  ``replaces: <key>`` is a new occurrence of the same reminder; the previous open
  one is ``superseded`` on every client, so at most one is live, and Hermes keeps
  the counter (``repeat: {count, skipped, since}``). An action with
  ``resolves: true`` (or ``closes`` with decision done/resolved) ends the chain.
- Secret form (Cindy 4): ``_secret {service, path, fields: [{name, label, type}]}`` asks the owner for values
  (a password, a token). The client shows a form; ``POST /api/notifications/{id}/secret`` claims the notification
  (first answer wins) and forwards the values to the module through the Hub. Hermes never stores or logs them.
- «Da decidere» (Cindy 5): notifications still waiting for an answer after ``hermes.attesa.richiamo_ore`` get ONE
  grouped reminder (agenda job ``hermes.notifications.remind_pending``), once per notification.
- Active client (Cindy 20): if the owner used a client in the last ``hermes.consegna.client_attivo_minuti``,
  only that client rings; the others get the notification ``silent``.
- Web Push (C15): the WebUI's browsers subscribed through ``/api/push/*`` get a push too (``webpush.py``).
- Hermes keeps no domain logic: it delivers, claims answers, forwards them and
  tells every client what happened (``update``) or to drop a stale message
  (``retract``).
"""
from __future__ import annotations

import base64
import logging
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from . import webpush
from .clients import ClientRegistry, NotifyClient
from .hermes_settings import (ACTIVE_CLIENT_MINUTES, DELIVERY_MAX_ATTEMPTS, PENDING_REMIND_HOURS,
                              REPEAT_RESET_AFTER_DAYS, RETRACT_AFTER, settings)
from hestia_common.presence_client import PresenceClient   # path set up by hermes_settings
from hestia_common.voice_client import VoiceClient
from hestia_common.voice_usecases import usecase as voice_usecase

logger = logging.getLogger("hestia_hermes.notifications")

CHANNEL = "notification"
VOICE_USECASE = "hermes.notifica"
VOICE_USECASES = [voice_usecase(VOICE_USECASE, "Notifiche a voce", direction="voce",
                                help="Le notifiche che un modulo vuole anche a voce (impostazione del modulo).")]
UNREAD_STATES = ["created", "queued", "delivered", "failed"]
ANSWERABLE_STATES = ["created", "queued", "delivered", "seen", "failed"]
CLOSED_STATES = ["answered", "dismissed", "expired", "superseded", "dead"]
# Inbox "all": every state but superseded (a replaced reminder is history, only the live one is listed).
LISTED_STATES = UNREAD_STATES + ["seen", "answered", "dismissed", "expired", "dead"]
# ``closes`` decisions that end a repeat chain (the next reminder starts from zero).
RESOLVING_DECISIONS = {"done", "resolved"}
_MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
# Messages already seen/handled are retracted from transient client surfaces
# (Telegram chat) after the setting hermes.retract.after (hours); the inbox keeps
# them. Telegram lets a bot delete its own messages only within 48 h, hence the window.
RETRACT_WINDOW_SECONDS = 47 * 3600

LEVELS = {"info", "success", "warning", "error"}
# Assistant presence effect notify.level (SPEC assistant-presence §4.6): what still gets pushed.
# Held notifications go only to the inbox (silent) and come back as one digest when the level opens.
DIGEST_WINDOW_SECONDS = 48 * 3600


def presence_holds(notify_level: str, level: str, actions: list, event_payload: dict | None) -> bool:
    """``all`` → nothing held; ``important`` → info/success held unless they ask something;
    ``urgent`` → only errors or events flagged ``_urgent`` pass."""
    payload = event_payload if isinstance(event_payload, dict) else {}
    if notify_level not in {"important", "urgent"} or payload.get("_urgent") or level == "error":
        return False
    if notify_level == "important":
        return level not in {"warning"} and not actions and not payload.get("_important")
    return True
_DEFAULT_LEVELS = {"service.action_required": "warning", "service.health": "warning"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def public_link(raw: Any) -> dict[str, Any] | None:
    """``_link: {module, page, params?}`` from a module event → a client opens that plugin page
    (WebUI ``/p/<module>/<page>``; client plugins SPEC §4). Anything else is dropped."""
    if not isinstance(raw, dict):
        return None
    module, page = str(raw.get("module") or "").strip(), str(raw.get("page") or "").strip()
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", module) or not re.fullmatch(r"[A-Za-z0-9_/:.-]{1,120}", page):
        return None
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    return {"module": module, "page": page,
            "params": {str(k)[:40]: str(v)[:300] for k, v in list(params.items())[:8]}}


def public_repeat(repeat: Any) -> dict[str, Any] | None:
    """Client-facing counter of a repeat chain, only from the second occurrence on.
    ``text`` is short Italian, ready to show or read aloud: «Saltato 3 volte · dal 12 ott»."""
    if not isinstance(repeat, dict) or int(repeat.get("count") or 1) <= 1:
        return None
    skipped = int(repeat.get("skipped") or 0)
    text = f"Saltato {skipped} volt{'a' if skipped == 1 else 'e'}"
    since = _parse_ts(repeat.get("since"))
    if since:
        text += f" · dal {since.day} {_MONTHS[since.month - 1]}"
    return {"count": int(repeat["count"]), "skipped": skipped, "since": repeat.get("since"), "text": text}


def normalize_actions(raw: Any) -> list[dict[str, Any]]:
    """Accept Themis-style flat route actions and legacy {text, command}."""
    actions: list[dict[str, Any]] = []
    for index, act in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(act, dict):
            continue
        label = str(act.get("label") or act.get("text") or "").strip()
        if not label:
            continue
        item: dict[str, Any] = {
            "id": str(act.get("id") or f"a{index}").strip()[:20],  # Telegram callback ≤ 64 bytes
            "label": label,
            "style": str(act.get("style") or "default"),
        }
        if act.get("service") and act.get("path"):
            item.update({
                "service": str(act["service"]).strip(),
                "method": str(act.get("method") or "POST").upper(),
                "path": str(act["path"]).strip(),
                "body": act.get("body"),
            })
        elif act.get("command"):
            item["command"] = str(act["command"]).strip()
        else:
            continue
        if act.get("resolves"):
            item["resolves"] = True   # answering with it ends a repeat chain
        actions.append(item)
    return actions


_SECRET_TYPES = {"password", "text", "token"}


def normalize_secret(raw: Any) -> dict[str, Any] | None:
    """``_secret`` of an event → ``{service, path, fields}`` or None (malformed = ignored)."""
    if not isinstance(raw, dict) or not raw.get("service") or not str(raw.get("path") or "").startswith("/"):
        return None
    fields = []
    for f in raw.get("fields") or []:
        if isinstance(f, dict) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", str(f.get("name") or "")):
            fields.append({"name": f["name"], "label": str(f.get("label") or f["name"])[:80],
                           "type": f.get("type") if f.get("type") in _SECRET_TYPES else "password"})
    if not fields:
        return None
    return {"service": str(raw["service"]).strip(), "path": str(raw["path"]).strip(), "fields": fields[:6]}


def public_secret(secret: Any) -> dict[str, Any] | None:
    """What clients see of a secret form: only the fields to ask."""
    if not isinstance(secret, dict) or not secret.get("fields"):
        return None
    return {"fields": [dict(f) for f in secret["fields"]]}


def public_actions(actions: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"id": a["id"], "label": a["label"], "style": a.get("style", "default")} for a in actions]


def _replace_client(value: Any, client: str) -> Any:
    if isinstance(value, str):
        return value.replace("<client>", client)
    if isinstance(value, dict):
        return {k: _replace_client(v, client) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_client(v, client) for v in value]
    return value


def public_voice(raw: Any) -> dict[str, Any] | None:
    """Kept audio of a notification, for a play button (bytes come from the voice module by ``blob_id``)."""
    if not isinstance(raw, dict) or not raw.get("blob_id"):
        return None
    return {"blob_id": str(raw["blob_id"]), "duration_s": raw.get("duration_s")}


def view(row: dict[str, Any], client: str = "") -> dict[str, Any]:
    """Client-facing shape of a stored notification (WebUI inbox)."""
    stored = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    n = stored.get("notification") if isinstance(stored.get("notification"), dict) else {}
    deliveries = stored.get("deliveries") if isinstance(stored.get("deliveries"), dict) else {}
    state = str(row.get("lifecycle_state") or "")
    actions = n.get("actions") or []
    secret = public_secret(n.get("secret"))
    origin = n.get("origin") if isinstance(n.get("origin"), dict) else None
    return {
        "id": row.get("outbound_event_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "state": state,
        "read": state not in UNREAD_STATES,
        "pending": bool(actions or secret) and state in ANSWERABLE_STATES,
        "secret": secret,
        "title": n.get("title") or "",
        "message": n.get("message") or "",
        "level": n.get("level") or "info",
        "source": n.get("source") or row.get("domain") or "",
        "domain": row.get("domain") or "",
        "event_type": row.get("event_type") or "",
        "actions": public_actions(actions),
        "audience": n.get("audience") or "global",
        "origin": origin,
        "other_client": bool(client and origin and origin.get("client") and origin.get("client") != client),
        "seen": stored.get("read"),
        "answer": stored.get("answer"),
        "deliveries": {k: (v or {}).get("state") for k, v in deliveries.items()},
        "repeat": public_repeat(n.get("repeat")),
        "link": public_link(n.get("link")),
        "voice": public_voice(stored.get("voice")),
    }


class NotificationCenter:
    def __init__(self, archive, clients: ClientRegistry | None = None, hub_api_url: str | None = None):
        self.archive = archive
        self.clients = clients or ClientRegistry(hub_api_url)
        self.hub_api_url = (hub_api_url or os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="hermes-notify")
        self.presence = PresenceClient("hermes", self.hub_api_url)
        self.voice = VoiceClient(self.hub_api_url)

    # ── Hub calls ───────────────────────────────────────────────────────────

    def _route(self, service: str, path: str, body: Any, method: str = "POST",
               timeout: float = 8, trace_id: str = "") -> tuple[int, Any]:
        headers = {"X-Trace-Id": trace_id} if trace_id else {}
        try:
            resp = requests.post(
                f"{self.hub_api_url}/route/{service}/{path.lstrip('/')}",
                json={"method": method, "headers": headers, "query": {}, "body": body,
                      "timeout_seconds": timeout},
                timeout=timeout + 1,
            )
            if resp.status_code != 200:
                return resp.status_code, resp.text[:250]
            routed = resp.json() or {}
            return int(routed.get("status_code", 500) or 500), routed.get("payload")
        except Exception as exc:
            return 0, str(exc)[:250]

    def _deliver(self, client: NotifyClient, body: dict[str, Any]) -> dict[str, Any]:
        status, payload = self._route(client.name, client.endpoint, body, timeout=8,
                                      trace_id=str(body.get("notification_id") or ""))
        ok = 200 <= status < 300
        result = payload if isinstance(payload, dict) else {}
        if ok and result.get("skipped"):
            return {"state": "skipped", "at": _now()}
        if ok and result.get("delivered", True):
            return {"state": "delivered", "at": _now(), "ref": result.get("ref")}
        return {"state": "failed", "at": _now(), "detail": str(payload)[:200]}

    # ── Publish ─────────────────────────────────────────────────────────────

    def publish(
        self,
        *,
        message: str,
        event_type: str,
        domain: str,
        entity_id: str = "",
        title: str = "",
        level: str = "",
        source: str = "",
        actions: Any = None,
        audience: str = "global",
        origin: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        dedupe_max_age: float | None = None,
        event_payload: dict[str, Any] | None = None,
        subscription_id: str | None = None,
        replaces: str | None = None,
        link: dict[str, Any] | None = None,
        quiet: bool = False,
        voice: bool = False,
        secret: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store one notification and fan it out to every client.
        ``replaces``: key of a repeat chain — never deduped, supersedes the previous open one.
        ``voice``: the sending module wants it also as audio (its ``<module>.notifiche.voce``): the written
        notification goes out first, the audio follows as an ``update`` with ``voice`` (dossier modulo-voce §7.3)."""
        if replaces:
            dedupe_key = replaces
        elif dedupe_key:
            existing = self.archive.find_active_outbound_event(dedupe_key, max_age_seconds=dedupe_max_age)
            if existing:
                logger.info("event=notification_deduped dedupe_key=%s existing=%s",
                            dedupe_key, existing.get("outbound_event_id"))
                return {"notification_id": existing.get("outbound_event_id"), "deduped": True,
                        "deliveries": 0}
        notification_id = str(uuid.uuid4())
        level = level if level in LEVELS else _DEFAULT_LEVELS.get(event_type, "info")
        normalized_actions = normalize_actions(actions)
        if audience != "origin" or not (origin or {}).get("client"):
            audience, origin = "global", None
        notify_level = self.presence.effect("notify.level", "all")
        held = presence_holds(notify_level, level, normalized_actions, event_payload)
        spec = {
            "title": str(title or "")[:200],
            "message": str(message or ""),
            "level": level,
            "source": source or (event_type.split(".", 1)[0] if "." in event_type else domain),
            "audience": audience,
            "origin": origin,
            "actions": normalized_actions,
            "created_at": _now(),
        }
        if public_link(link):
            spec["link"] = public_link(link)
        if normalize_secret(secret):
            spec["secret"] = normalize_secret(secret)
        if quiet:   # the answer is asked elsewhere (e.g. a confirm card in the chat): inbox copy, no push
            spec["quiet"] = True
        if held:
            spec["held"] = notify_level
        if replaces:
            spec["repeat"] = self._advance_chain(replaces, notification_id)
        self.archive.upsert_outbound_event({
            "outbound_event_id": notification_id,
            "dedupe_key": dedupe_key or f"notification:{notification_id}",
            "lifecycle_state": "created",
            "event_type": event_type,
            "domain": domain or "general",
            "entity_id": entity_id or None,
            "subscription_id": str(subscription_id) if subscription_id is not None else None,
            "channel": CHANNEL,
            "target": origin["client"] if origin else "*",
            "source_service": "hermes",
            "payload": {"event_payload": event_payload or {}, "notification": spec, "deliveries": {}},
        })
        deliveries = self._fan_out(notification_id, spec, event_payload)
        delivered = sum(1 for d in deliveries.values() if d.get("state") == "delivered")
        if held:   # inbox only on every client: a skipped push is the expected outcome
            delivered = sum(1 for d in deliveries.values() if d.get("state") in ("delivered", "skipped"))
        state = "delivered" if delivered else "failed"
        status, current = self.archive.patch_outbound_event(
            notification_id, state, only_if_states=["created"], payload_merge={"deliveries": deliveries},
            detail=f"delivered to {delivered}/{len(deliveries)} clients")
        if status == 409 and isinstance(current, dict):
            # Seen/answered while we were delivering: keep that state, store deliveries.
            self.archive.patch_outbound_event(
                notification_id, str(current.get("lifecycle_state")), payload_merge={"deliveries": deliveries})
        logger.info("event=notification_published notification_id=%s event_type=%s audience=%s held=%s "
                    "repeat=%s clients=%s delivered=%d", notification_id, event_type, audience,
                    spec.get("held") or "-", (spec.get("repeat") or {}).get("count", "-"),
                    ",".join(f"{k}:{v.get('state')}" for k, v in deliveries.items()) or "-", delivered)
        result = {"notification_id": notification_id, "deduped": False, "deliveries": delivered}
        if voice:
            self._pool.submit(self._add_voice, notification_id, spec)
        if replaces:
            result["repeat"] = spec["repeat"]
        return result

    def _advance_chain(self, key: str, new_id: str) -> dict[str, Any]:
        """Next counter of the repeat chain ``key``; every still-open occurrence is superseded
        (compare-and-set: an answer arriving meanwhile wins) and every client drops it."""
        now = datetime.now(timezone.utc)
        rows = self.archive.get_outbound_events({"channel": CHANNEL, "dedupe_key": key, "limit": 20})
        rows = sorted(rows, key=lambda r: str(r.get("created_at") or ""), reverse=True)
        latest = rows[0] if rows else None
        for row in rows:
            if row.get("lifecycle_state") not in ANSWERABLE_STATES:
                continue
            code, current = self.archive.patch_outbound_event(
                str(row.get("outbound_event_id")), "superseded", only_if_states=ANSWERABLE_STATES,
                payload_merge={"superseded_by": new_id}, detail=f"superseded by {new_id}")
            if code == 200 and isinstance(current, dict):
                self._broadcast(current, {"state": "superseded", "superseded_by": new_id})
                if (current.get("payload") or {}).get("voice"):
                    self._pool.submit(self.voice.forget, notification_id=str(row.get("outbound_event_id")))
                logger.info("event=notification_superseded notification_id=%s by=%s key=%s",
                            row.get("outbound_event_id"), new_id, key)
            elif code == 409 and row is latest:
                latest = self.archive.get_outbound_event(str(row.get("outbound_event_id"))) or row
        fresh = {"count": 1, "skipped": 0, "since": now.isoformat()}
        if not latest:
            return fresh
        stored = latest.get("payload") if isinstance(latest.get("payload"), dict) else {}
        previous = (stored.get("notification") or {}).get("repeat") or {}
        last_at = _parse_ts(latest.get("created_at"))
        reset_after = timedelta(days=int(settings.get(REPEAT_RESET_AFTER_DAYS)))
        if stored.get("repeat_resolved") or (last_at and now - last_at > reset_after):
            return fresh
        return {"count": int(previous.get("count") or 1) + 1,
                "skipped": int(previous.get("skipped") or 0) + 1,
                "since": previous.get("since") or latest.get("created_at") or now.isoformat()}

    def _add_voice(self, notification_id: str, spec: dict) -> None:
        """Audio of a notification (kept by the voice module while the notification lives), then an ``update``
        so clients add a voice message / play button. Failure leaves the written notification as it is."""
        text = ". ".join(t for t in (str(spec.get("title") or "").strip(), str(spec.get("message") or "").strip()) if t)
        spoken = self.voice.speak(text, use_case=VOICE_USECASE, fmt="ogg_opus",
                                  keep={"kind": "notification", "notification_id": notification_id})
        if not spoken:
            logger.warning("[🔄] event=notification_voice_failed notification_id=%s fallback=text_only", notification_id)
            return
        voice = {"blob_id": spoken.get("blob_id"), "duration_s": spoken.get("duration_s"),
                 "mime_type": spoken.get("mime_type") or "audio/ogg"}
        row = self.archive.get_outbound_event(notification_id) or {}
        state = str(row.get("lifecycle_state") or "")
        if not state or state in ("superseded", "dead"):
            self.voice.forget(notification_id=notification_id)
            return
        code, current = self.archive.patch_outbound_event(notification_id, state, payload_merge={"voice": voice})
        if code != 200 or not isinstance(current, dict):
            return
        self._broadcast(current, {"voice": {**voice, "audio_b64": base64.b64encode(spoken["audio"]).decode()}})
        logger.info("event=notification_voice_added notification_id=%s duration_s=%s", notification_id,
                    voice.get("duration_s"))

    def active_client(self) -> str:
        """The client the owner used in the last ``hermes.consegna.client_attivo_minuti`` (Cindy 20), or ''."""
        try:
            minutes = int(settings.get(ACTIVE_CLIENT_MINUTES) or 0)
        except (TypeError, ValueError):
            minutes = 0
        state = self.presence.get() if minutes > 0 else None
        if not state or not state.get("last_interaction_client"):
            return ""
        try:
            idle = float(state.get("idle_minutes"))
        except (TypeError, ValueError):
            return ""
        return str(state["last_interaction_client"]) if idle <= minutes else ""

    def _client_body(self, notification_id: str, spec: dict, client: str,
                     event_payload: dict | None, active: str = "") -> dict[str, Any]:
        origin = spec.get("origin") or {}
        is_origin = bool(origin) and origin.get("client") == client
        urgent = bool((event_payload or {}).get("_urgent"))
        return {
            "kind": "notification",
            "notification_id": notification_id,
            "target": str(origin.get("session_id") or "owner") if is_origin else "owner",
            "silent": (spec.get("audience") == "origin" and not is_origin) or bool(spec.get("held"))
                      or bool(spec.get("quiet")) or (bool(active) and active != client and not urgent),
            "title": spec.get("title", ""),
            "message": spec.get("message", ""),
            "level": spec.get("level", "info"),
            "source": spec.get("source", ""),
            "created_at": spec.get("created_at"),
            "actions": public_actions(spec.get("actions") or []),
            "origin": origin or None,
            "repeat": public_repeat(spec.get("repeat")),
            "link": spec.get("link"),
            "secret": public_secret(spec.get("secret")),
            "payload": event_payload or {},
        }

    def _fan_out(self, notification_id: str, spec: dict, event_payload: dict | None,
                 only: list[str] | None = None) -> dict[str, dict]:
        clients = [c for c in self.clients.clients() if only is None or c.name in only]
        active = self.active_client() if spec.get("audience") != "origin" else ""
        if active and active not in {c.name for c in self.clients.clients()}:
            active = ""            # a client that receives no notifications (e.g. the voice) → ring everywhere
        bodies = {c.name: self._client_body(notification_id, spec, c.name, event_payload, active) for c in clients}
        futures = {c.name: self._pool.submit(self._deliver, c, bodies[c.name]) for c in clients}
        if only is None and webpush.configured():
            ring = [b for name, b in bodies.items() if name == webpush.CLIENT]
            if ring and not ring[0]["silent"]:
                self._pool.submit(webpush.send_all, self.archive, ring[0])
        results: dict[str, dict] = {}
        for name, fut in futures.items():
            try:
                results[name] = fut.result(timeout=12)
            except Exception as exc:
                results[name] = {"state": "failed", "at": _now(), "detail": str(exc)[:200]}
            results[name]["attempts"] = 1
            if results[name]["state"] == "failed":
                logger.warning("[🔄] event=notification_client_failed notification_id=%s client=%s detail=%s",
                               notification_id, name, results[name].get("detail"))
        return results

    # ── Updates to every client ─────────────────────────────────────────────

    def _broadcast(self, row: dict[str, Any], change: dict[str, Any]) -> None:
        stored = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        deliveries = stored.get("deliveries") if isinstance(stored.get("deliveries"), dict) else {}
        notification_id = row.get("outbound_event_id")

        def _send():
            for client in self.clients.clients():
                d = deliveries.get(client.name) or {}
                if d.get("state") not in ("delivered", "skipped") and client.name in deliveries:
                    continue
                body = {"kind": "update", "notification_id": notification_id,
                        "ref": d.get("ref"), **change}
                status, _ = self._route(client.name, client.endpoint, body, timeout=6)
                if not 200 <= status < 300:
                    logger.warning("[🔄] event=notification_update_failed notification_id=%s client=%s status=%s",
                                   notification_id, client.name, status)

        threading.Thread(target=_send, daemon=True, name="hermes-notify-update").start()

    # ── Read state (global) ────────────────────────────────────────────────

    def mark_seen(self, notification_id: str, client: str) -> dict[str, Any]:
        seen = {"by": client, "at": _now()}
        status, row = self.archive.patch_outbound_event(
            notification_id, "seen", only_if_states=UNREAD_STATES, payload_merge={"read": seen})
        if status == 200 and isinstance(row, dict):
            spec = ((row.get("payload") or {}).get("notification") or {})
            self._broadcast(row, {"state": "seen", "seen": seen, "pending": bool(spec.get("actions"))})
            logger.info("event=notification_seen notification_id=%s client=%s", notification_id, client)
            return {"status": "ok", "changed": True}
        if status == 409:
            return {"status": "ok", "changed": False}
        return {"status": "error", "http_status": status}

    def mark_all_seen(self, client: str, delivered_to: str | None = None) -> dict[str, Any]:
        rows = self.archive.get_outbound_events({
            "channel": CHANNEL, "lifecycle_states": ",".join(UNREAD_STATES), "limit": 200})
        changed = 0
        for row in rows:
            if delivered_to:
                d = ((row.get("payload") or {}).get("deliveries") or {}).get(delivered_to) or {}
                if d.get("state") != "delivered":
                    continue
            changed += int(self.mark_seen(str(row.get("outbound_event_id")), client).get("changed", False))
        return {"status": "ok", "changed": changed}

    # ── Answers: first wins, routed to the asking module ────────────────────

    def answer(self, notification_id: str, action_id: str, client: str) -> tuple[int, dict[str, Any]]:
        row = self.archive.get_outbound_event(notification_id)
        if not row:
            return 404, {"status": "not_found"}
        spec = ((row.get("payload") or {}).get("notification") or {})
        action = next((a for a in spec.get("actions") or [] if a.get("id") == action_id), None)
        if not action:
            return 404, {"status": "unknown_action"}
        answer = {"action_id": action_id, "label": action.get("label"), "by": client,
                  "at": _now(), "status": "pending"}
        status, current = self.archive.patch_outbound_event(
            notification_id, "answered", only_if_states=ANSWERABLE_STATES,
            payload_merge={"answer": answer}, detail=f"answered by {client}")
        if status == 409:
            previous = ((current or {}) if isinstance(current, dict) else {})
            stored = (self.archive.get_outbound_event(notification_id) or {}).get("payload") or {}
            logger.info("event=notification_answer_late notification_id=%s client=%s state=%s",
                        notification_id, client, previous.get("lifecycle_state"))
            return 409, {"status": "already_handled", "answer": stored.get("answer"),
                         "state": previous.get("lifecycle_state")}
        if status != 200:
            return 503, {"status": "error", "detail": "archive unavailable"}
        logger.info("event=notification_answer_claimed notification_id=%s client=%s action_id=%s",
                    notification_id, client, action_id)

        if action.get("command"):
            # Legacy Hub command: the answering client runs it, then reports the outcome.
            return 200, {"status": "claimed", "execute": "command", "command": action["command"]}

        code, payload = self._route(action["service"], action["path"],
                                    _replace_client(action.get("body"), client),
                                    method=action.get("method", "POST"), timeout=15,
                                    trace_id=notification_id)
        if code == 409:
            return self._finish(notification_id, answer, "already_handled",
                                _outcome_text(payload, "Già gestita"), http=409)
        if 200 <= code < 300:
            return self._finish(notification_id, answer, "done",
                                _outcome_text(payload, f"{action.get('label')} ✓"),
                                resolves=bool(action.get("resolves")))
        # Module failed: release the claim so the user can try again.
        self.archive.patch_outbound_event(
            notification_id, "seen", only_if_states=["answered"],
            payload_merge={"answer": {**answer, "status": "error"}},
            detail=f"action failed: {code}")
        logger.warning("[🔄] event=notification_action_failed notification_id=%s service=%s status=%s",
                       notification_id, action.get("service"), code)
        return 502, {"status": "error", "detail": _outcome_text(payload, f"errore {code}")}

    def submit_secret(self, notification_id: str, values: dict[str, Any], client: str) -> tuple[int, dict[str, Any]]:
        """Cindy 4: the owner's values go to the module that asked, through the Hub. Never stored, never logged
        (only the field names are). First answer wins, like an action."""
        row = self.archive.get_outbound_event(notification_id)
        if not row:
            return 404, {"status": "not_found"}
        secret = ((row.get("payload") or {}).get("notification") or {}).get("secret") or {}
        names = [f["name"] for f in secret.get("fields") or []]
        if not names:
            return 404, {"status": "no_secret_form"}
        clean = {n: str(values.get(n)) for n in names if values.get(n) not in (None, "")}
        if len(clean) != len(names):
            return 400, {"status": "missing_fields", "fields": [n for n in names if n not in clean]}
        answer = {"action_id": "secret", "label": "Inviato", "by": client, "at": _now(), "status": "pending"}
        status, current = self.archive.patch_outbound_event(
            notification_id, "answered", only_if_states=ANSWERABLE_STATES,
            payload_merge={"answer": answer}, detail=f"secret form sent by {client}")
        if status == 409:
            return 409, {"status": "already_handled"}
        if status != 200:
            return 503, {"status": "error", "detail": "archive unavailable"}
        code, payload = self._route(secret["service"], secret["path"], {"values": clean, "client": client},
                                    timeout=15, trace_id=notification_id)
        clean.clear()
        logger.info("event=notification_secret_forwarded notification_id=%s service=%s fields=%s status=%s",
                    notification_id, secret["service"], ",".join(names), code)
        if 200 <= code < 300:
            return self._finish(notification_id, answer, "done", _outcome_text(payload, "Ricevuto"))
        self.archive.patch_outbound_event(
            notification_id, "seen", only_if_states=["answered"],
            payload_merge={"answer": {**answer, "status": "error"}}, detail=f"secret form failed: {code}")
        return 502, {"status": "error", "detail": _outcome_text(payload, f"errore {code}")}

    def remind_pending(self, now: datetime | None = None) -> dict[str, int]:
        """Cindy 5: one grouped reminder for what still waits for an answer after ``hermes.attesa.richiamo_ore``;
        each notification is recalled once (``reminded_at``). The reminder replaces the previous one."""
        now = now or datetime.now(timezone.utc)
        after = timedelta(hours=float(settings.get(PENDING_REMIND_HOURS) or 4))
        rows = self.archive.get_outbound_events({
            "channel": CHANNEL, "lifecycle_states": ",".join(ANSWERABLE_STATES),
            "created_after": (now - timedelta(days=7)).isoformat(), "limit": 200})
        due = []
        for row in rows:
            v = view(row)
            stored = row.get("payload") or {}
            created = _parse_ts(row.get("created_at"))
            if not v["pending"] or stored.get("reminded_at") or row.get("event_type") == "assistant.pending_reminder":
                continue
            if created and now - created >= after:
                due.append((row, v))
        if not due:
            return {"reminded": 0}
        for row, _ in due:
            self.archive.patch_outbound_event(str(row["outbound_event_id"]), str(row.get("lifecycle_state")),
                                              payload_merge={"reminded_at": now.isoformat()})
        import html
        lines = [f"• {html.escape(v['title'] or v['message'][:80])}" for _, v in due[:8]]
        more = len(due) - len(lines)
        message = ("Aspettano ancora una tua risposta:\n" + "\n".join(lines)
                   + (f"\n…e altre {more}." if more > 0 else ""))
        self.publish(message=message, event_type="assistant.pending_reminder", domain="assistant",
                     title=f"Da decidere: {len(due)}", level="info", source="hermes",
                     replaces="hermes.pending_reminder",
                     link={"module": "hermes", "page": "notifiche", "params": {"filter": "pending"}})
        logger.info("event=notification_pending_reminded count=%d", len(due))
        return {"reminded": len(due)}

    def report_outcome(self, notification_id: str, client: str, ok: bool, text: str) -> dict[str, Any]:
        row = self.archive.get_outbound_event(notification_id) or {}
        answer = (row.get("payload") or {}).get("answer") or {"by": client}
        if ok:
            actions = ((row.get("payload") or {}).get("notification") or {}).get("actions") or []
            resolves = any(a.get("id") == answer.get("action_id") and a.get("resolves") for a in actions)
            _, result = self._finish(notification_id, answer, "done", text or f"{answer.get('label', '')} ✓",
                                     resolves=resolves)
            return result
        self.archive.patch_outbound_event(
            notification_id, "seen", only_if_states=["answered"],
            payload_merge={"answer": {**answer, "status": "error", "outcome_text": text}})
        return {"status": "error"}

    def _finish(self, notification_id: str, answer: dict, status: str, text: str,
                http: int = 200, resolves: bool = False) -> tuple[int, dict[str, Any]]:
        final = {**answer, "status": status, "outcome_text": text}
        merge: dict[str, Any] = {"answer": final}
        if resolves:
            merge["repeat_resolved"] = True
        code, row = self.archive.patch_outbound_event(notification_id, "answered", payload_merge=merge)
        if code == 200 and isinstance(row, dict):
            self._broadcast(row, {"state": "answered", "answer": final})
        return http, {"status": status, "answer": final}

    # ── Closed by the asking module (e.g. Themis proposal decided/expired) ──

    def close(self, dedupe_key: str, decision: str, outcome_text: str, by: str) -> int:
        rows = self.archive.get_outbound_events({"channel": CHANNEL, "dedupe_key": dedupe_key, "limit": 20})
        resolving = str(decision or "").lower() in RESOLVING_DECISIONS
        closed = 0
        touched: set[str] = set()
        for row in rows:
            if row.get("lifecycle_state") in CLOSED_STATES and row.get("lifecycle_state") != "answered":
                continue
            stored = row.get("payload") or {}
            previous = stored.get("answer") or {}
            if previous.get("status") == "done":
                continue  # already closed by an answer through Hermes
            state = "expired" if decision in ("expired", "expire") else "answered"
            final = {"action_id": previous.get("action_id"), "label": previous.get("label"),
                     "by": previous.get("by") or by, "at": _now(), "status": decision or "closed",
                     "outcome_text": outcome_text}
            merge: dict[str, Any] = {"answer": final}
            if resolving:
                merge["repeat_resolved"] = True
            code, updated = self.archive.patch_outbound_event(
                str(row.get("outbound_event_id")), state, payload_merge=merge)
            if code == 200 and isinstance(updated, dict):
                closed += 1
                touched.add(str(row.get("outbound_event_id")))
                self._broadcast(updated, {"state": state, "answer": final})
        if resolving and rows:
            # Ends the repeat chain even when the latest occurrence was already handled (e.g. «Salta»).
            latest = max(rows, key=lambda r: str(r.get("created_at") or ""))
            if str(latest.get("outbound_event_id")) not in touched:
                self.archive.patch_outbound_event(
                    str(latest.get("outbound_event_id")), str(latest.get("lifecycle_state")),
                    only_if_states=[str(latest.get("lifecycle_state"))], payload_merge={"repeat_resolved": True})
        logger.info("event=notification_closed dedupe_key=%s decision=%s closed=%d", dedupe_key, decision, closed)
        return closed

    # ── Inbox (WebUI page) ──────────────────────────────────────────────────

    def inbox(self, *, filter_: str = "all", source: str = "", before: str = "", limit: int = 50,
              client: str = "") -> dict[str, Any]:
        query: dict[str, Any] = {"channel": CHANNEL, "order_by": "created", "limit": max(1, min(limit, 200)),
                                 "lifecycle_states": ",".join(LISTED_STATES)}
        if filter_ == "unread":
            query["lifecycle_states"] = ",".join(UNREAD_STATES)
        elif filter_ == "pending":
            query["lifecycle_states"] = ",".join(ANSWERABLE_STATES)
        if source:
            query["payload_source"] = source
        if before:
            query["created_before"] = before
        rows = [view(r, client) for r in self.archive.get_outbound_events(query)]
        if filter_ == "pending":
            rows = [r for r in rows if r["pending"]]
        return {"items": rows, "counts": self.counts(client)}

    def counts(self, client: str = "") -> dict[str, int]:
        rows = self.archive.get_outbound_events({
            "channel": CHANNEL, "lifecycle_states": ",".join(ANSWERABLE_STATES), "limit": 200})
        views = [view(r, client) for r in rows]
        return {"unread": sum(1 for v in views if not v["read"]),
                "pending": sum(1 for v in views if v["pending"])}

    def recap(self, day: str) -> dict[str, Any]:
        """Facts for the daily recap (docs/work/2026-10-20-recap-giornaliero): how many notifications ``day``
        brought (the important ones named) and which are still waiting for an answer. The recap itself is left out."""
        rows = self.archive.get_outbound_events({"channel": CHANNEL, "order_by": "created", "limit": 200,
                                                 "lifecycle_states": ",".join(LISTED_STATES)})
        rows = [r for r in rows if r.get("dedupe_key") != "athena.recap"]
        views = [view(r) for r in rows]

        def local_day(v: dict) -> str:
            ts = _parse_ts(v.get("created_at"))
            return ts.astimezone().date().isoformat() if ts else ""

        todays = [v for v in views if local_day(v) == day]
        done, missed = [], []
        if todays:
            important = [v["title"] for v in todays if v["level"] in ("warning", "error") and v["title"]]
            text = f"{len(todays)} notific{'a' if len(todays) == 1 else 'he'}"
            if important:
                text += " · importanti: " + ", ".join(dict.fromkeys(important[:3]))
            done.append({"text": text})
        waiting = [v["title"] or v["message"][:60] for v in views if v["pending"]]
        if waiting:
            missed.append({"text": "In attesa di una tua risposta: " + ", ".join(dict.fromkeys(waiting[:4]))
                                   + (f" e altre {len(waiting) - 4}" if len(waiting) > 4 else ""),
                           "tone": "warning"})
        return {"done": done, "missed": missed}

    # ── Resilience: per-client retry; retract stale messages ────────────────

    def retry_failed(self) -> dict[str, int]:
        since = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        max_attempts = int(settings.get(DELIVERY_MAX_ATTEMPTS))
        rows = self.archive.get_outbound_events({
            "channel": CHANNEL, "lifecycle_states": ",".join(UNREAD_STATES + ["seen"]),
            "created_after": since, "limit": 100})
        retried = recovered = 0
        for row in rows:
            stored = row.get("payload") or {}
            deliveries = dict(stored.get("deliveries") or {})
            if not deliveries and row.get("lifecycle_state") == "failed":
                # No client was known at publish time (Hub down): try every client now.
                deliveries = {c.name: {"state": "failed", "attempts": 1} for c in self.clients.clients()}
            failing = [name for name, d in deliveries.items()
                       if (d or {}).get("state") == "failed" and int((d or {}).get("attempts") or 1) < max_attempts]
            dead = [name for name, d in deliveries.items()
                    if (d or {}).get("state") == "failed" and name not in failing]
            if not failing and not dead:
                continue
            spec = stored.get("notification") or {}
            fresh = self._fan_out(str(row["outbound_event_id"]), spec, stored.get("event_payload"), only=failing) \
                if failing else {}
            for name in failing:
                attempts = int((deliveries.get(name) or {}).get("attempts") or 1) + 1
                deliveries[name] = {**fresh.get(name, {"state": "failed"}), "attempts": attempts}
                retried += 1
                recovered += int(deliveries[name].get("state") == "delivered")
            for name in dead:
                deliveries[name] = {**(deliveries.get(name) or {}), "state": "dead"}
            state = str(row.get("lifecycle_state"))
            if state == "failed" and any(d.get("state") == "delivered" for d in deliveries.values()):
                state = "delivered"
            elif state == "failed" and not any(d.get("state") == "failed" for d in deliveries.values()):
                state = "dead"
            self.archive.patch_outbound_event(
                str(row["outbound_event_id"]), state, only_if_states=[str(row.get("lifecycle_state"))],
                payload_merge={"deliveries": deliveries})
        if retried:
            logger.info("[🔄] event=notification_retry_pass retried=%d recovered=%d", retried, recovered)
        return {"retried": retried, "recovered": recovered}

    def release_held(self, level: str = "") -> dict[str, int]:
        """The assistant presence opened the notification level again (e.g. woke up): send the
        notifications held meanwhile as ONE digest, still unread ones only (the inbox has them all)."""
        level = level or self.presence.effect("notify.level", "all")
        since = (datetime.now(timezone.utc) - timedelta(seconds=DIGEST_WINDOW_SECONDS)).isoformat()
        rows = self.archive.get_outbound_events({
            "channel": CHANNEL, "lifecycle_states": ",".join(UNREAD_STATES + ["seen"]),
            "created_after": since, "limit": 200})
        released = []
        for row in rows:
            stored = row.get("payload") or {}
            spec = stored.get("notification") or {}
            if not spec.get("held") or stored.get("held_released"):
                continue
            if presence_holds(level, spec.get("level", "info"), spec.get("actions") or [],
                              stored.get("event_payload")):
                continue   # still held under the new level
            released.append(row)
        if not released:
            return {"released": 0}
        for row in released:
            self.archive.patch_outbound_event(str(row["outbound_event_id"]), str(row.get("lifecycle_state")),
                                              payload_merge={"held_released": _now()})
        unread = [r for r in released if r.get("lifecycle_state") in UNREAD_STATES]
        if unread:
            import html
            lines = []
            for row in unread[:10]:
                spec = (row.get("payload") or {}).get("notification") or {}
                title = spec.get("title") or str(spec.get("message") or "")[:80] or row.get("event_type") or ""
                source = spec.get("source") or ""
                lines.append(f"• {html.escape(str(title))}" + (f" <i>({html.escape(str(source))})</i>" if source else ""))
            more = len(unread) - len(lines)
            message = (f"<b>{len(unread)} notific{'a' if len(unread) == 1 else 'he'}</b> mentre riposavo:\n"
                       + "\n".join(lines) + (f"\n…e altre {more} nella posta." if more > 0 else ""))
            self.publish(message=message, event_type="assistant.digest", domain="assistant",
                         title="Mentre riposavo", level="info", source="hermes",
                         event_payload={"_urgent": True, "count": len(unread)})
        logger.info("event=notification_held_released released=%d digest=%d level=%s",
                    len(released), len(unread), level)
        return {"released": len(released), "digest": len(unread)}

    def retract_stale(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        retract_after = min(float(settings.get(RETRACT_AFTER)) * 3600, RETRACT_WINDOW_SECONDS - 3600)
        rows = self.archive.get_outbound_events({
            "channel": CHANNEL, "lifecycle_states": "seen,answered,expired,dismissed",
            "created_after": (now - timedelta(seconds=RETRACT_WINDOW_SECONDS)).isoformat(),
            "updated_before": (now - timedelta(seconds=retract_after)).isoformat(),
            "limit": 200})
        retracted = 0
        clients = {c.name: c for c in self.clients.clients()}
        for row in rows:
            stored = row.get("payload") or {}
            spec = stored.get("notification") or {}
            if row.get("lifecycle_state") == "seen" and spec.get("actions"):
                continue  # still waiting for an answer: never removed
            deliveries = dict(stored.get("deliveries") or {})
            changed = False
            for name, d in deliveries.items():
                if not d or d.get("state") != "delivered" or not d.get("ref") or d.get("retracted"):
                    continue
                client = clients.get(name)
                if not client:
                    continue
                code, _ = self._route(name, client.endpoint, {
                    "kind": "retract", "notification_id": row.get("outbound_event_id"), "ref": d.get("ref")},
                    timeout=6)
                if 200 <= code < 300:
                    deliveries[name] = {**d, "retracted": _now()}
                    changed = True
                    retracted += 1
            if changed:
                self.archive.patch_outbound_event(
                    str(row["outbound_event_id"]), str(row.get("lifecycle_state")),
                    payload_merge={"deliveries": deliveries})
        if retracted:
            logger.info("event=notification_retract_pass retracted=%d", retracted)
        return {"retracted": retracted}


def _outcome_text(payload: Any, default: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "outcome_text", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
            if isinstance(value, dict):
                nested = value.get("message") or value.get("status")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()[:300]
    return default
