# Hestia-Archive Project

## Overview
Archive is Hestia's single persistence gateway. Every service reads/writes data through Archive APIs only.

## Responsibilities
- generic storage and retrieval
- hybrid entity search
- chat history + long-term memory storage
- subscription persistence for proactive notifications
- dispatch outcome logs for auditing

## Current API Groups
- `/api/archive`
- `/api/entities`
- `/api/chat/history`
- `/api/memory`
- `/api/subscriptions`
- `/api/dispatch/logs`

## Run
```bash
docker-compose up --build -d
```