# Hestia-Hermes Project

## Overview
Hermes is the proactive dispatch core that evaluates events against subscriptions and delivers notifications through channel adapters.

## Responsibilities
- ingest generic domain events
- load active subscriptions from Archive
- run generic matching and dedupe
- dispatch alerts (Telegram first)
- persist dispatch outcomes in Archive

## Run
```bash
docker-compose up --build -d
```
