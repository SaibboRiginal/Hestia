# Hestia-Hecate Blueprint

## Mission
Provide provider gateway ownership (auth + CRUD) plus connector-based fetch execution for modules.

## Structure
```
Hestia-Hecate/
├── hestia-hecate.md
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
- expose provider gateway APIs
- mirror calendar sync items to Archive