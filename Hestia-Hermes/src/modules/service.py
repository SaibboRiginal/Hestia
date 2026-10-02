from datetime import datetime, timezone
import json
import logging
import os
import time
from uuid import uuid4

from .archive_client import ArchiveClient
from .dispatch import DispatchService
from .entity_batch_dispatcher import (
    BATCHED_DOMAINS,
    BATCHED_EVENT_TYPES,
    enqueue_entity,
)
from .matcher import subscription_matches

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


MAX_DELIVERY_ATTEMPTS = int(__import__("os").getenv("HERMES_MAX_DELIVERY_ATTEMPTS", "6"))


class HermesService:
    def __init__(self):
        self.archive = ArchiveClient()
        self.dispatch = DispatchService()

    def process_event(self, event_type: str, domain: str, entity_id: str, payload: dict):
        t0 = time.perf_counter()
        event_trace_id = ""
        if isinstance(payload, dict):
            event_trace_id = str(payload.get("trace_id")
                                 or payload.get("x_trace_id") or "").strip()
        logger.info(
            "event=event_ingestion_start domain=%s event_type=%s entity_id=%s trace_id=%s",
            domain,
            event_type,
            entity_id,
            event_trace_id,
        )
        subscriptions = self.archive.get_active_subscriptions(
            domain=domain, event_type=event_type)
        logger.debug(
            "event=loaded_active_subscriptions_domain_event_type Loaded active subscriptions | domain=%s event_type=%s count=%s",
            domain,
            event_type,
            len(subscriptions),
        )
        matched = 0
        delivered = 0

        for subscription in subscriptions:
            subscription_id = subscription.get("id")
            matches = subscription_matches(subscription, payload)
            if not matches:
                logger.debug(
                    "event=subscription_matched_subscription_id_filters Subscription not matched | subscription_id=%s filters=%s",
                    subscription_id,
                    subscription.get("filters") or {},
                )
                continue

            matched += 1
            channels = subscription.get("channels") or []
            logger.info(
                "event=subscription_matched_subscription_id_channels Subscription matched | subscription_id=%s channels=%s trace_id=%s",
                subscription_id,
                channels,
                event_trace_id,
            )

            # Route batched domains (e.g. real_estate) through the batch dispatcher
            # so multiple entities arriving in a burst are narrated as one message.
            use_batch = (
                domain in BATCHED_DOMAINS
                and event_type in BATCHED_EVENT_TYPES
            )

            for channel in channels:
                channel_type = channel.get("type", "")
                channel_target = channel.get("target", "")
                question_id = str(payload.get(
                    "question_id", "")).strip() or None
                brief_id = str(payload.get("brief_id", "")).strip() or None
                inbound_outbound_id = str(payload.get(
                    "outbound_event_id", "")).strip()
                outbound_event_id = inbound_outbound_id or str(uuid4())
                dedupe_anchor = _dedupe_anchor(payload, question_id, brief_id, event_type, domain, entity_id)
                dedupe_key = f"{dedupe_anchor}:{subscription_id}"

                max_age = (
                    _RECURRING_EVENT_MAX_AGE_SECONDS
                    if event_type in _RECURRING_EVENT_TYPES
                    else None
                )
                existing = self.archive.find_active_outbound_event(
                    dedupe_key,
                    max_age_seconds=max_age,
                )
                if existing and str(existing.get("outbound_event_id")) != outbound_event_id:
                    existing_id = str(existing.get("outbound_event_id"))
                    existing_state = str(existing.get("lifecycle_state", "")).strip().lower()
                    logger.info(
                        "event=dispatch_deduped_dedupe_key_existing_outbound_event_id_skipp Dispatch deduped | dedupe_key=%s existing_outbound_event_id=%s skipped_outbound_event_id=%s existing_state=%s question_id=%s brief_id=%s trace_id=%s",
                        dedupe_key,
                        existing_id,
                        outbound_event_id,
                        existing_state,
                        question_id,
                        brief_id,
                        event_trace_id,
                    )
                    self.archive.upsert_outbound_event(
                        {
                            "outbound_event_id": outbound_event_id,
                            "dedupe_key": dedupe_key,
                            "lifecycle_state": "superseded",
                            "event_type": event_type,
                            "domain": domain,
                            "entity_id": entity_id,
                            "subscription_id": str(subscription_id),
                            "channel": channel_type,
                            "target": str(channel_target),
                            "question_id": question_id,
                            "brief_id": brief_id,
                            "source_service": "hermes",
                            "superseded_by": existing_id,
                            "detail": "deduped against active outbound event",
                            "payload": {"event_payload": payload or {}},
                        }
                    )
                    continue

                self.archive.upsert_outbound_event(
                    {
                        "outbound_event_id": outbound_event_id,
                        "dedupe_key": dedupe_key,
                        "lifecycle_state": "created",
                        "event_type": event_type,
                        "domain": domain,
                        "entity_id": entity_id,
                        "subscription_id": str(subscription_id),
                        "channel": channel_type,
                        "target": str(channel_target),
                        "question_id": question_id,
                        "brief_id": brief_id,
                        "source_service": "hermes",
                        "payload": {"event_payload": payload or {}},
                    }
                )

                if use_batch:
                    self.archive.update_outbound_event_state(
                        outbound_event_id,
                        "queued",
                        detail="queued in entity batch dispatcher",
                    )
                    enqueue_entity(
                        subscription_id=subscription.get("id"),
                        channel_type=channel_type,
                        channel_target=str(channel_target),
                        domain=domain,
                        entity_id=entity_id,
                        payload=payload,
                        filters=subscription.get("filters") or {},
                    )
                    delivered += 1
                    continue

                # If the payload carries a pre-formatted message, send it as
                # direct text (skips Oracle narration on the Telegram side).
                _preformatted = payload.get(
                    "_message") if isinstance(payload, dict) else None
                _actions = payload.get(
                    "_actions") if isinstance(payload, dict) else None
                self.archive.update_outbound_event_state(
                    outbound_event_id,
                    "queued",
                    detail="dispatch queued",
                )
                trace_id = str(payload.get("trace_id") or payload.get(
                    "x_trace_id") or outbound_event_id or "").strip()
                ok, detail = self.dispatch.send(
                    channel=channel_type,
                    target=str(channel_target),
                    message=_preformatted,
                    actions=_actions
                    if isinstance(_actions, list)
                    else None,
                    payload=None if _preformatted else payload,
                    domain=domain,
                    entity_id=entity_id,
                    subscription_id=subscription.get("id"),
                    metadata={"trace_id": trace_id},
                )
                if ok:
                    self.archive.update_outbound_event_state(
                        outbound_event_id,
                        "delivered",
                        detail=detail,
                    )
                else:
                    updated = self.archive.update_outbound_event_state(
                        outbound_event_id,
                        "failed",
                        detail=detail,
                    )
                    if not updated:
                        logger.warning(
                            "event=outbound_state_update_failed "
                            "outbound_event_id=%s target_state=failed",
                            outbound_event_id,
                        )
                logger.info(
                    "event=dispatch_attempted_subscription_id_channel_target Dispatch attempted | subscription_id=%s channel=%s target=%s success=%s outbound_event_id=%s question_id=%s brief_id=%s trace_id=%s detail=%s",
                    subscription_id,
                    channel_type,
                    channel_target,
                    ok,
                    outbound_event_id,
                    question_id,
                    brief_id,
                    trace_id,
                    detail,
                )
                if ok:
                    delivered += 1

                ref_detail = (
                    f"outbound_event_id={outbound_event_id};question_id={question_id or ''};brief_id={brief_id or ''}"
                )
                detail_with_refs = f"{detail} | {ref_detail}" if detail else ref_detail

                self.archive.write_dispatch_log(
                    {
                        "subscription_id": str(subscription.get("id")),
                        "event_type": event_type,
                        "domain": domain,
                        "entity_id": entity_id,
                        "channel": channel_type,
                        "target": str(channel_target),
                        "success": ok,
                        "detail": detail_with_refs,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        logger.info(
            "event=event_processed ms=%d domain=%s event_type=%s entity_id=%s subscriptions=%d matched=%d deliveries=%d",
            int((time.perf_counter() - t0) * 1000),
            domain,
            event_type,
            entity_id,
            len(subscriptions),
            matched,
            delivered,
        )
        return {
            "subscriptions_checked": len(subscriptions),
            "subscriptions_matched": matched,
            "deliveries": delivered,
        }

    def retry_failed_deliveries(self, limit: int = 50) -> dict:
        """Resilience rule 7: a failed delivery is retried on every pass until it
        succeeds or reaches HERMES_MAX_DELIVERY_ATTEMPTS (then marked "dead")."""
        rows = self.archive.get_outbound_events({"lifecycle_state": "failed", "limit": limit})
        retried = delivered = dead = 0
        for row in rows:
            channel, target = row.get("channel"), row.get("target")
            stored = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            event_payload = stored.get("event_payload") if isinstance(stored.get("event_payload"), dict) else {}
            attempts = int(stored.get("attempts") or 1)
            if not channel or not target:
                continue
            if attempts >= MAX_DELIVERY_ATTEMPTS:
                self.archive.update_outbound_event_state(
                    row["outbound_event_id"], "dead", detail=f"gave up after {attempts} attempts")
                dead += 1
                continue
            message = event_payload.get("_message")
            ok, detail = self.dispatch.send(
                channel=channel, target=str(target),
                message=message, payload=None if message else event_payload,
                domain=row.get("domain", ""), entity_id=row.get("entity_id", ""),
                subscription_id=row.get("subscription_id"),
                metadata={"trace_id": row["outbound_event_id"]},
            )
            retried += 1
            delivered += int(ok)
            updated = {k: row.get(k) for k in (
                "outbound_event_id", "dedupe_key", "event_type", "domain", "entity_id",
                "subscription_id", "channel", "target", "question_id", "brief_id",
                "source_service", "superseded_by")}
            updated.update({
                "lifecycle_state": "delivered" if ok else "failed",
                "detail": f"retry {attempts + 1}: {detail}"[:500],
                "payload": {**stored, "attempts": attempts + 1},
            })
            self.archive.upsert_outbound_event(updated)
        if retried or dead:
            logger.info("[🔄] event=hermes_retry_pass retried=%d delivered=%d dead=%d", retried, delivered, dead)
        return {"retried": retried, "delivered": delivered, "dead": dead}

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
