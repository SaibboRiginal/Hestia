from datetime import datetime, timezone
import json
import logging
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


class HermesService:
    def __init__(self):
        self.archive = ArchiveClient()
        self.dispatch = DispatchService()

    def process_event(self, event_type: str, domain: str, entity_id: str, payload: dict):
        subscriptions = self.archive.get_active_subscriptions(
            domain=domain, event_type=event_type)
        logger.debug(
            "Loaded active subscriptions | domain=%s event_type=%s count=%s",
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
                    "Subscription not matched | subscription_id=%s filters=%s",
                    subscription_id,
                    subscription.get("filters") or {},
                )
                continue

            matched += 1
            channels = subscription.get("channels") or []
            logger.info(
                "Subscription matched | subscription_id=%s channels=%s",
                subscription_id,
                channels,
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
                dedupe_anchor = question_id or brief_id or f"{event_type}:{domain}:{entity_id}"
                dedupe_key = f"{dedupe_anchor}:{subscription_id}"

                existing = self.archive.find_active_outbound_event(dedupe_key)
                if existing and str(existing.get("outbound_event_id")) != outbound_event_id:
                    existing_id = str(existing.get("outbound_event_id"))
                    logger.info(
                        "Dispatch deduped | dedupe_key=%s existing_outbound_event_id=%s skipped_outbound_event_id=%s question_id=%s brief_id=%s",
                        dedupe_key,
                        existing_id,
                        outbound_event_id,
                        question_id,
                        brief_id,
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
                self.archive.update_outbound_event_state(
                    outbound_event_id,
                    "queued",
                    detail="dispatch queued",
                )
                ok, detail = self.dispatch.send(
                    channel=channel_type,
                    target=str(channel_target),
                    message=_preformatted,
                    payload=None if _preformatted else payload,
                    domain=domain,
                    entity_id=entity_id,
                    subscription_id=subscription.get("id"),
                )
                if ok:
                    self.archive.update_outbound_event_state(
                        outbound_event_id,
                        "delivered",
                        detail=detail,
                    )
                else:
                    self.archive.update_outbound_event_state(
                        outbound_event_id,
                        "failed",
                        detail=detail,
                    )
                logger.info(
                    "Dispatch attempted | subscription_id=%s channel=%s target=%s success=%s outbound_event_id=%s question_id=%s brief_id=%s detail=%s",
                    subscription_id,
                    channel_type,
                    channel_target,
                    ok,
                    outbound_event_id,
                    question_id,
                    brief_id,
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

        return {
            "subscriptions_checked": len(subscriptions),
            "subscriptions_matched": matched,
            "deliveries": delivered,
        }

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
