from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeConfig:
    service_name: str
    service_base_url: str
    service_version: str
    service_type: str
    service_tags: list[str]
    service_topology_tags: list[str]
    hub_api_url: str
    hephaestus_notify_target: str
    hephaestus_baseline_ref: str
    hephaestus_execution_timeout_seconds: float
    hephaestus_require_approval_for_mutation: bool
    hephaestus_allow_auto_approve_non_prod: bool
    hephaestus_maintenance_paths: list[str]


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _parse_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def load_runtime_config() -> RuntimeConfig:
    service_type = os.getenv("SERVICE_TYPE", "core")
    return RuntimeConfig(
        service_name=os.getenv("SERVICE_NAME", "hephaestus"),
        service_base_url=os.getenv(
            "SERVICE_BASE_URL", "http://hestia_hephaestus:19010"),
        service_version=os.getenv("SERVICE_VERSION", "1.0.0"),
        service_type=service_type,
        service_tags=[
            tag.strip().lower()
            for tag in os.getenv("SERVICE_TAGS", service_type).split(",")
            if tag.strip()
        ],
        service_topology_tags=[
            tag.strip().lower()
            for tag in os.getenv(
                "SERVICE_TOPOLOGY_TAGS",
                "layer:cognition,domain:remediation,status:beta",
            ).split(",")
            if tag.strip()
        ],
        hub_api_url=os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/"),
        hephaestus_notify_target=os.getenv(
            "HEPHAESTUS_NOTIFY_TARGET", "").strip(),
        hephaestus_baseline_ref=os.getenv("HEPHAESTUS_BASELINE_REF", "HEAD"),
        hephaestus_execution_timeout_seconds=max(
            5.0, _parse_float_env("HEPHAESTUS_EXECUTION_TIMEOUT_SECONDS", 25.0)),
        hephaestus_require_approval_for_mutation=_parse_bool_env(
            "HEPHAESTUS_REQUIRE_APPROVAL_FOR_MUTATION", True),
        hephaestus_allow_auto_approve_non_prod=_parse_bool_env(
            "HEPHAESTUS_ALLOW_AUTO_APPROVE_NON_PROD", False),
        hephaestus_maintenance_paths=[
            path.strip()
            for path in os.getenv(
                "HEPHAESTUS_MAINTENANCE_PATHS",
                "/api/module/maintenance/reconcile,/api/maintenance/reconcile,/api/$service/maintenance/reconcile",
            ).split(",")
            if path.strip()
        ],
    )
