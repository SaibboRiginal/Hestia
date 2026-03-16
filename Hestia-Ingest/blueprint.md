# Hestia-Ingest Blueprint

## Mission
Provide generic connector registration and raw fetch execution for modules.

## Structure
```
Hestia-Ingest/
├── hestia-ingest.md
├── blueprint.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py
    ├── core/
    └── fetchers/
```

## Contracts
- register connector
- trigger fetch
- return raw data only