# Hestia Python Service Template

This template enforces a consistent startup, health contract, and Hub registration shape.

## Goals
- Standard `/health` endpoint response
- Standard Hub registration payload (`service_type`, `service_version`, normalized tags)
- OOP service class with explicit extension points

## Files
- `app/main.py`: FastAPI app + startup registration + health endpoint
- `app/core/service_contract.py`: reusable base class and DTOs

## How to use
1. Copy this folder into a new service repository.
2. Rename `TemplateService` and set `SERVICE_NAME`.
3. Implement `build_capabilities()` and domain routes.
4. Keep `service_type` and `tags` aligned.

## Registration Contract
Must include:
- `name`
- `base_url`
- `health_endpoint`
- `service_type` in: `core|module|integration`
- `service_version` in semver format (`x.y.z`)
- `tags` from allowed set and containing `service_type`
- `capabilities` with snake_case keys
