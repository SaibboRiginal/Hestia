import os
from typing import Any
import logging

import requests


logger = logging.getLogger("hestia_hermes.dispatch")


class DispatchService:
    def __init__(self):
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")

    def send(self, channel: str, target: str, payload: dict[str, Any] | None = None, message: str | None = None, domain: str = "", entity_id: str = "", subscription_id: int | None = None, metadata: dict[str, Any] | None = None) -> tuple[bool, str]:
        normalized = (channel or "").strip().lower()
        if normalized == "telegram":
            return self._send_telegram_via_service(target, payload=payload, message=message, domain=domain, entity_id=entity_id, subscription_id=subscription_id)

        return False, f"unsupported channel: {channel}"

    def _send_telegram_via_service(self, chat_id: str, payload: dict[str, Any] | None = None, message: str | None = None, domain: str = "", entity_id: str = "", subscription_id: int | None = None) -> tuple[bool, str]:
        """Route to Telegram service's control API for message dispatch via Hub"""
        endpoint = f"{self.hub_api_url}/route/telegram/api/dispatch/send"
        dispatch_body = {
            "target": str(chat_id),
        }
        if payload is not None:
            dispatch_body["payload"] = payload
            dispatch_body["domain"] = domain
            dispatch_body["entity_id"] = entity_id
            dispatch_body["subscription_id"] = subscription_id
        elif message:
            dispatch_body["message"] = message

        try:
            response = requests.post(
                endpoint,
                json={
                    "method": "POST",
                    "headers": {},
                    "query": {},
                    "body": dispatch_body,
                    "timeout_seconds": 8,
                },
                timeout=9,
            )
            if response.status_code != 200:
                detail = response.text[:250]
                logger.warning(
                    "Telegram route via Hub failed | chat_id=%s status=%s detail=%s",
                    chat_id,
                    response.status_code,
                    detail,
                )
                return False, detail

            routed = response.json() or {}
            routed_status = int(routed.get("status_code", 500) or 500)
            if routed_status >= 400:
                detail = str(routed.get("payload", ""))[:250]
                logger.warning(
                    "Telegram service rejected dispatch | chat_id=%s status=%s detail=%s",
                    chat_id,
                    routed_status,
                    detail,
                )
                return False, detail

            return True, "sent"
        except requests.RequestException as error:
            logger.warning(
                "Telegram service request failed | chat_id=%s error=%s",
                chat_id,
                error,
            )
            return False, f"telegram service error: {error}"
