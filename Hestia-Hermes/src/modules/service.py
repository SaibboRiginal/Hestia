from datetime import datetime, timezone
import json
import logging

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
        logger.info(
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
                logger.info(
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

                if use_batch:
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
                ok, detail = self.dispatch.send(
                    channel=channel_type,
                    target=str(channel_target),
                    message=_preformatted,
                    payload=None if _preformatted else payload,
                    domain=domain,
                    entity_id=entity_id,
                    subscription_id=subscription.get("id"),
                )
                logger.info(
                    "Dispatch attempted | subscription_id=%s channel=%s target=%s success=%s detail=%s",
                    subscription_id,
                    channel_type,
                    channel_target,
                    ok,
                    detail,
                )
                if ok:
                    delivered += 1

                self.archive.write_dispatch_log(
                    {
                        "subscription_id": str(subscription.get("id")),
                        "event_type": event_type,
                        "domain": domain,
                        "entity_id": entity_id,
                        "channel": channel_type,
                        "target": str(channel_target),
                        "success": ok,
                        "detail": detail,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        return {
            "subscriptions_checked": len(subscriptions),
            "subscriptions_matched": matched,
            "deliveries": delivered,
        }
