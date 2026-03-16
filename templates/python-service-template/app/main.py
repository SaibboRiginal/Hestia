import os

from fastapi import FastAPI

from .core.service_contract import HestiaServiceBase, ServiceDescriptor


class TemplateService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, str]:
        return {
            "health_check": "/health",
        }


SERVICE_NAME = os.getenv("SERVICE_NAME", "template_service")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://template_service:8099")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "integration")
SERVICE_TAGS = [
    tag.strip().lower()
    for tag in os.getenv("SERVICE_TAGS", SERVICE_TYPE).split(",")
    if tag.strip()
]

service = TemplateService(
    ServiceDescriptor(
        name=SERVICE_NAME,
        base_url=SERVICE_BASE_URL,
        service_type=SERVICE_TYPE,
        service_version=SERVICE_VERSION,
        tags=SERVICE_TAGS,
    )
)

app = FastAPI(title="Hestia Template Service", version=SERVICE_VERSION)


@app.on_event("startup")
def register_on_hub_startup():
    try:
        service.register_to_hub(timeout_seconds=4)
    except Exception:
        pass


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "service_type": service.descriptor.service_type,
        "tags": service.descriptor.tags,
    }
