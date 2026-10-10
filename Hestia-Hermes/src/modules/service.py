import logging
import os
import time
from typing import Any
from uuid import uuid4

from .archive_client import ArchiveClient
from .entity_batch_dispatcher import (
    BATCHED_DOMAINS,
    BATCHED_EVENT_TYPES,
    enqueue_entity,
    set_publisher as set_batch_publisher,
)
from .matcher import subscription_matches
from .notifications import NotificationCenter
from .oracle_client import narrate

logger = logging.getLogger("hestia_hermes.service")

# Event types whose dedup is time-limited.  Once the previous delivery
# exceeds this age it is treated as stale, letting a fresh notification
# through.  Default 3600 s (1 hour) — matches the Hecate entity_id
# hourly scoping so a persistent auth failure gets at most one alert per
# hour regardless of restarts.
_RECURRING_EVENT_MAX_AGE_SECONDS = float(
    os.getenv("HERMES_RECURRING_EVENT_MAX_AGE_SECONDS", "3600"))
_RECURRING_EVENT_TYPES: frozenset[str] = frozenset(
    e.strip() for e in os.getenv(
        "HERMES_RECURRING_EVENT_TYPES",
        "service.action_required,service.health",
    ).split(",") if e.strip()
)


def _dedupe_anchor(payload, question_id, brief_id, event_type, domain, entity_id) -> str:
    """What makes two events "the same notification".

    Explicit ``payload.dedupe_key`` wins, then question/brief ids.  For
    pre-formatted messages (system alerts, Forge, recoveries) the text is part
    of the key: a fixed entity_id like "argus-batch" used to dedupe EVERY later
    alert against the first delivered one, so the user only ever got one.
    Domain entities without a message keep entity-level dedupe (no repeat
    notification for the same listing).
    """
    import hashlib

    if isinstance(payload, dict) and str(payload.get("dedupe_key") or "").strip():
        return str(payload["dedupe_key"]).strip()
    if question_id or brief_id:
        return str(question_id or brief_id)
    base = f"{event_type}:{domain}:{entity_id}"
    message = payload.get("_message") if isinstance(payload, dict) else None
    if message:
        return f"{base}:{hashlib.sha1(str(message).encode()).hexdigest()[:12]}"
    return base


def subscription_audience(channels: list[dict[str, Any]]) -> tuple[str, dict | None]:
    """Subscription channels → audience (SPEC §5.2/§5.6).

    ``{"type": "all"}`` (and legacy ``{"type": "telegram"}``, which only meant
    "the one channel that existed") → global. ``{"type": "client", "client": X,
    "target": session}`` → only that client (the others keep it in the inbox).
    """
    origin = None
    for ch in channels or [{"type": "all"}]:
        if not isinstance(ch, dict):
            continue
        if str(ch.get("type") or "all").lower() == "client" and ch.get("client"):
            origin = origin or {"client": str(ch["client"]), "session_id": str(ch.get("target") or "owner")}
        else:
            return "global", None
    return ("origin", origin) if origin else ("global", None)


def payload_origin(payload: dict[str, Any]) -> dict | None:
    """``_origin: {client, session_id}`` set by a module answering a session request."""
    raw = payload.get("_origin") if isinstance(payload, dict) else None
    if isinstance(raw, dict) and raw.get("client"):
        return {"client": str(raw["client"]), "session_id": str(raw.get("session_id") or "owner")}
    return None


def _entity_message(payload: dict[str, Any], domain: str) -> str:
    """One narration for every client (SPEC §5.5): Oracle, else a plain fallback."""
    from html import escape

    title = str(payload.get("title") or payload.get("summary") or "").strip()
    facts = "\n".join(f"{k}: {v}" for k, v in payload.items()
                      if not str(k).startswith("_") and isinstance(v, (str, int, float)) and str(v).strip())[:1500]
    text = narrate(
        f"Scrivi una notifica breve in italiano per l'utente su questo elemento ({domain}). "
        f"Solo HTML semplice (<b>, <a href>), niente saluti, inizia dall'informazione.\n\n{facts}")
    if text:
        return text
    url = str(payload.get("url") or "").strip()
    label = escape(title or domain or "Aggiornamento")
    if url:
        return f'🔔 <a href="{escape(url, quote=True)}"><b>{label}</b></a>'
    return f"🔔 <b>{label}</b>"


class HermesService:
    def __init__(self):
        self.archive = ArchiveClient()
        self.notifications = NotificationCenter(self.archive)
        set_batch_publisher(self._publish_batch)

    def _publish_batch(self, subscription_id, audience_key: str, domain: str, text: str) -> bool:
        audience, origin = ("global", None)
        if audience_key.startswith("client:"):
            _, client, session = (audience_key.split(":", 2) + ["owner"])[:3]
            audience, origin = "origin", {"client": client, "session_id": session}
        result = self.notifications.publish(
            message=text, event_type="entity.upserted", domain=domain, source=domain,
            audience=audience, origin=origin, subscription_id=subscription_id)
        return bool(result.get("deliveries"))

    def process_event(self, event_type: str, domain: str, entity_id: str, payload: dict):
        t0 = time.perf_counter()
        payload = payload if isinstance(payload, dict) else {}
        event_trace_id = str(payload.get("trace_id") or payload.get("x_trace_id") or "").strip()
        logger.info(
            "event=event_ingestion_start domain=%s event_type=%s entity_id=%s trace_id=%s",
            domain, event_type, entity_id, event_trace_id,
        )

        # A module closing its own notification (e.g. Themis proposal decided elsewhere).
        closes = str(payload.get("closes") or "").strip()
        if closes:
            closed = self.notifications.close(
                closes, str(payload.get("decision") or "closed"),
                str(payload.get("outcome_text") or ""), by=str(payload.get("_source") or domain))
            if not payload.get("_message"):
                return {"subscriptions_checked": 0, "subscriptions_matched": 0, "deliveries": 0,
                        "closed": closed}

        subscriptions = self.archive.get_active_subscriptions(domain=domain, event_type=event_type)
        matched_subs = [s for s in subscriptions if subscription_matches(s, payload)]
        if not matched_subs:
            logger.info(
                "event=event_processed ms=%d domain=%s event_type=%s entity_id=%s subscriptions=%d matched=0 deliveries=0",
                int((time.perf_counter() - t0) * 1000), domain, event_type, entity_id, len(subscriptions))
            return {"subscriptions_checked": len(subscriptions), "subscriptions_matched": 0, "deliveries": 0}

        question_id = str(payload.get("question_id", "")).strip() or None
        brief_id = str(payload.get("brief_id", "")).strip() or None
        anchor = _dedupe_anchor(payload, question_id, brief_id, event_type, domain, entity_id)
        max_age = _RECURRING_EVENT_MAX_AGE_SECONDS if event_type in _RECURRING_EVENT_TYPES else None

        # Batched domains: one narrated message per subscription after a settling window.
        if domain in BATCHED_DOMAINS and event_type in BATCHED_EVENT_TYPES:
            queued = 0
            for subscription in matched_subs:
                sub_id = subscription.get("id")
                dedupe_key = f"{anchor}:{sub_id}"
                if self.archive.find_active_outbound_event(dedupe_key, max_age_seconds=max_age):
                    continue
                self.archive.upsert_outbound_event({
                    "outbound_event_id": str(uuid4()), "dedupe_key": dedupe_key,
                    "lifecycle_state": "queued", "event_type": event_type, "domain": domain,
                    "entity_id": entity_id, "subscription_id": str(sub_id), "channel": "batch",
                    "target": "*", "source_service": "hermes", "detail": "queued in entity batch",
                    "payload": {"event_payload": payload},
                })
                audience, origin = subscription_audience(subscription.get("channels") or [])
                audience_key = (f"client:{origin['client']}:{origin['session_id']}"
                                if audience == "origin" and origin else "all")
                enqueue_entity(subscription_id=sub_id, channel_type=audience_key, channel_target="",
                               domain=domain, entity_id=entity_id, payload=payload,
                               filters=subscription.get("filters") or {})
                queued += 1
            return {"subscriptions_checked": len(subscriptions),
                    "subscriptions_matched": len(matched_subs), "deliveries": queued}

        # One notification per event, whatever the number of matching subscriptions.
        origin = payload_origin(payload)
        if origin:
            audience = "origin"
        else:
            audiences = [subscription_audience(s.get("channels") or []) for s in matched_subs]
            audience, origin = next((a for a in audiences if a[0] == "global"), audiences[0])

        message = payload.get("_message")
        if not message:
            message = _entity_message(payload, domain)
        result = self.notifications.publish(
            message=str(message),
            title=str(payload.get("_title") or payload.get("title") or ""),
            level=str(payload.get("_level") or payload.get("level") or ""),
            source=str(payload.get("_source") or ""),
            event_type=event_type, domain=domain, entity_id=entity_id,
            actions=payload.get("_actions"), audience=audience, origin=origin,
            dedupe_key=anchor, dedupe_max_age=max_age, event_payload=payload,
            subscription_id=str(matched_subs[0].get("id")),
        )
        logger.info(
            "event=event_processed ms=%d domain=%s event_type=%s entity_id=%s subscriptions=%d matched=%d deliveries=%d",
            int((time.perf_counter() - t0) * 1000), domain, event_type, entity_id,
            len(subscriptions), len(matched_subs), result.get("deliveries", 0))
        return {
            "subscriptions_checked": len(subscriptions),
            "subscriptions_matched": len(matched_subs),
            "deliveries": result.get("deliveries", 0),
            "notification_id": result.get("notification_id"),
            "deduped": result.get("deduped", False),
        }

    def send_direct(self, channel: str, target: str, message: str, metadata: dict | None = None,
                    actions: Any = None) -> tuple[bool, str]:
        """Legacy ``/api/dispatch/send``: ``target`` owner (or empty) → every client;
        a concrete target on a known client (e.g. Forge requester's chat) → that client only."""
        target = str(target or "").strip()
        channel = str(channel or "").strip().lower()
        origin = None
        if target and target != "owner" and channel and self.notifications.clients.get(channel):
            origin = {"client": channel, "session_id": target}
        meta = metadata if isinstance(metadata, dict) else {}
        result = self.notifications.publish(
            message=message, event_type=str(meta.get("type") or "direct.message"), domain="system",
            source=str(meta.get("source") or ""), actions=actions,
            audience="origin" if origin else "global", origin=origin)
        ok = bool(result.get("deliveries"))
        return ok, "sent" if ok else "no client reached"

    def retry_failed_deliveries(self, limit: int = 50) -> dict:
        """Resilience rule 7: failed client deliveries are retried per client."""
        return self.notifications.retry_failed()

    def update_outbound_event_state(
        self,
        outbound_event_id: str,
        lifecycle_state: str,
        detail: str | None = None,
        superseded_by: str | None = None,
    ) -> bool:
        """External state transition hook (seen/answered/dismissed/superseded)."""
        return self.archive.update_outbound_event_state(
            outbound_event_id=outbound_event_id,
            lifecycle_state=lifecycle_state,
            detail=detail,
            superseded_by=superseded_by,
        )
