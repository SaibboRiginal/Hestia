# Hestia-Telegram Blueprint

## Mission
Channel relay between user and Oracle, plus optional proactive delivery adapter target.

## Structure
```
Hestia-Telegram/
├── hestia-telegram.md
├── blueprint.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── app/
    └── main.py
```

## Contracts
- forward chat to Oracle
- clear Oracle session
- channel-level formatting only
