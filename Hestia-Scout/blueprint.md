# Hestia-Scout Blueprint

## Mission
Domain module for real-estate extraction, retrieval tools, and event publishing.

## Structure
```
Hestia-Scout/
├── hestia-scout.md
├── blueprint.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py
    ├── core/
    ├── tools/
    └── worker/
```

## Contracts
- Uses Ingest for raw fetch
- Uses Archive for persistence
- Registers module tools in Hub
- Publishes `entity.upserted` events for Hermes