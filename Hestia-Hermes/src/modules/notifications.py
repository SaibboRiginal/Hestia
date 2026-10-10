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
- Hermes keeps no domain logic: it delivers, claims answers, forwards them and
  tells every client what happened (``update``) or to drop a stale message
  (``retract``).
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from .clients import ClientRegistry, NotifyClient
from .hermes_settings import DELIVERY_MAX_ATTEMPTS, RETRACT_AFTER, settings
from hestia_common.presence_client import PresenceClient   # path set up by hermes_settings

logger = logging.getLogger("hestia_hermes.notifications")

CHANNEL = "notification"
UNREAD_STATES = ["created", "queued", "delivered", "failed"]
ANSWERABLE_STATES = ["created", "queued", "delivered", "seen", "failed"]
CLOSED_STATES = ["answered", "dismissed", "expired", "superseded", "dead"]
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
        actions.append(item)
    return actions


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


def view(row: dict[str, Any], client: str = "") -> dict[str, Any]:
    """Client-facing shape of a stored notification (WebUI inbox)."""
    stored = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    n = stored.get("notification") if isinstance(stored.get("notification"), dict) else {}
    deliveries = stored.get("deliveries") if isinstance(stored.get("deliveries"), dict) else {}
    state = str(row.get("lifecycle_state") or "")
    actions = n.get("actions") or []
    origin = n.get("origin") if isinstance(n.get("origin"), dict) else None
    return {
        "id": row.get("outbound_event_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "state": state,
        "read": state not in UNREAD_STATES,
        "pending": bool(actions) and state in ANSWERABLE_STATES,
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
    }


class NotificationCenter:
    def __init__(self, archive, clients: ClientRegistry | None = None, hub_api_url: str | None = None):
        self.archive = archive
        self.clients = clients or ClientRegistry(hub_api_url)
        self.hub_api_url = (hub_api_url or os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="hermes-notify")
        self.presence = PresenceClient("hermes", self.hub_api_url)

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
    ) -> dict[str, Any]:
        """Store one notification and fan it out to every client."""
        if dedupe_key:
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
        if held:
            spec["held"] = notify_level
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
                    "clients=%s delivered=%d", notification_id, event_type, audience, spec.get("held") or "-",
                    ",".join(f"{k}:{v.get('state')}" for k, v in deliveries.items()) or "-", delivered)
        return {"notification_id": notification_id, "deduped": False, "deliveries": delivered}

    def _client_body(self, notification_id: str, spec: dict, client: str,
                     event_payload: dict | None) -> dict[str, Any]:
        origin = spec.get("origin") or {}
        is_origin = bool(origin) and origin.get("client") == client
        return {
            "kind": "notification",
            "notification_id": notification_id,
            "target": str(origin.get("session_id") or "owner") if is_origin else "owner",
            "silent": (spec.get("audience") == "origin" and not is_origin) or bool(spec.get("held")),
            "title": spec.get("title", ""),
            "message": spec.get("message", ""),
            "level": spec.get("level", "info"),
            "source": spec.get("source", ""),
            "created_at": spec.get("created_at"),
            "actions": public_actions(spec.get("actions") or []),
            "origin": origin or None,
            "payload": event_payload or {},
        }

    def _fan_out(self, notification_id: str, spec: dict, event_payload: dict | None,
                 only: list[str] | None = None) -> dict[str, dict]:
        clients = [c for c in self.clients.clients() if only is None or c.name in only]
        futures = {c.name: self._pool.submit(
            self._deliver, c, self._client_body(notification_id, spec, c.name, event_payload))
            for c in clients}
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
                                _outcome_text(payload, f"{action.get('label')} ✓"))
        # Module failed: release the claim so the user can try again.
        self.archive.patch_outbound_event(
            notification_id, "seen", only_if_states=["answered"],
            payload_merge={"answer": {**answer, "status": "error"}},
            detail=f"action failed: {code}")
        logger.warning("[🔄] event=notification_action_failed notification_id=%s service=%s status=%s",
                       notification_id, action.get("service"), code)
        return 502, {"status": "error", "detail": _outcome_text(payload, f"errore {code}")}

    def report_outcome(self, notification_id: str, client: str, ok: bool, text: str) -> dict[str, Any]:
        row = self.archive.get_outbound_event(notification_id) or {}
        answer = (row.get("payload") or {}).get("answer") or {"by": client}
        if ok:
            _, result = self._finish(notification_id, answer, "done", text or f"{answer.get('label', '')} ✓")
            return result
        self.archive.patch_outbound_event(
            notification_id, "seen", only_if_states=["answered"],
            payload_merge={"answer": {**answer, "status": "error", "outcome_text": text}})
        return {"status": "error"}

    def _finish(self, notification_id: str, answer: dict, status: str, text: str,
                http: int = 200) -> tuple[int, dict[str, Any]]:
        final = {**answer, "status": status, "outcome_text": text}
        code, row = self.archive.patch_outbound_event(
            notification_id, "answered", payload_merge={"answer": final})
        if code == 200 and isinstance(row, dict):
            self._broadcast(row, {"state": "answered", "answer": final})
        return http, {"status": status, "answer": final}

    # ── Closed by the asking module (e.g. Themis proposal decided/expired) ──

    def close(self, dedupe_key: str, decision: str, outcome_text: str, by: str) -> int:
        rows = self.archive.get_outbound_events({"channel": CHANNEL, "dedupe_key": dedupe_key, "limit": 20})
        closed = 0
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
            code, updated = self.archive.patch_outbound_event(
                str(row.get("outbound_event_id")), state, payload_merge={"answer": final})
            if code == 200 and isinstance(updated, dict):
                closed += 1
                self._broadcast(updated, {"state": state, "answer": final})
        logger.info("event=notification_closed dedupe_key=%s decision=%s closed=%d", dedupe_key, decision, closed)
        return closed

    # ── Inbox (WebUI page) ──────────────────────────────────────────────────

    def inbox(self, *, filter_: str = "all", source: str = "", before: str = "", limit: int = 50,
              client: str = "") -> dict[str, Any]:
        query: dict[str, Any] = {"channel": CHANNEL, "order_by": "created", "limit": max(1, min(limit, 200))}
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
