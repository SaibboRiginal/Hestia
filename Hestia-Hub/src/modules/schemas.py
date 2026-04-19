import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ALLOWED_TAGS = {
    "core",
    "module",
    "storage",
    "connector",
    "chat",
    "dispatch",
    "real_estate",
    "integration",
    "messaging",
    "monitoring",
}


class RegisterServiceRequest(BaseModel):
    name: str
    base_url: str
    health_endpoint: str = "/health"
    service_type: Literal["core", "module", "integration"] = "core"
    service_version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("name is required")
        if not re.fullmatch(r"[a-z0-9_-]{2,40}", normalized):
            raise ValueError(
                "name must match [a-z0-9_-]{2,40} (lowercase, numbers, - and _)"
            )
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("base_url must start with http:// or https://")
        return normalized

    @field_validator("health_endpoint")
    @classmethod
    def validate_health_endpoint(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("/"):
            raise ValueError("health_endpoint must start with '/'")
        return normalized

    @field_validator("service_version")
    @classmethod
    def validate_service_version(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+", normalized):
            raise ValueError(
                "service_version must follow semver major.minor.patch")
        return normalized

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        normalized = []
        for tag in values:
            item = str(tag).strip().lower()
            if not item:
                continue
            if item not in ALLOWED_TAGS:
                raise ValueError(
                    f"Unsupported tag '{item}'. Allowed: {sorted(ALLOWED_TAGS)}")
            normalized.append(item)
        return sorted(set(normalized))

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, item in (value or {}).items():
            normalized_key = str(key).strip().lower()
            if not re.fullmatch(r"[a-z0-9_]+", normalized_key):
                raise ValueError(
                    "capabilities keys must use snake_case [a-z0-9_]"
                )
            cleaned[normalized_key] = item
        return cleaned

    @model_validator(mode="after")
    def validate_type_tag_alignment(self):
        if self.service_type not in self.tags:
            raise ValueError(
                f"tags must include service_type '{self.service_type}'"
            )
        return self


class DeregisterServiceRequest(BaseModel):
    name: str
    base_url: str | None = None


class RouteRequest(BaseModel):
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None
    timeout_seconds: float = 8.0
