import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass
class ServiceDescriptor:
    name: str
    base_url: str
    health_endpoint: str = "/health"
    service_type: str = "integration"
    service_version: str = "1.0.0"
    tags: list[str] = field(default_factory=lambda: ["integration"])


class HestiaServiceBase(ABC):
    def __init__(self, descriptor: ServiceDescriptor):
        self.descriptor = descriptor
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://localhost:19001/api").rstrip("/")

    @abstractmethod
    def build_capabilities(self) -> dict[str, Any]:
        raise NotImplementedError

    def registration_payload(self) -> dict[str, Any]:
        return {
            "name": self.descriptor.name,
            "base_url": self.descriptor.base_url,
            "health_endpoint": self.descriptor.health_endpoint,
            "service_type": self.descriptor.service_type,
            "service_version": self.descriptor.service_version,
            "tags": self.descriptor.tags,
            "capabilities": self.build_capabilities(),
        }

    def register_to_hub(self, timeout_seconds: int = 4) -> None:
        response = requests.post(
            f"{self.hub_api_url}/registry/register",
            json=self.registration_payload(),
            timeout=timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = (response.text or "").strip()
            raise RuntimeError(
                f"Hub registration failed HTTP {response.status_code}: {detail}") from exc
