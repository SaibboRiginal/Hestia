# Hestia-Hermes Blueprint

## Mission
Enable proactive, event-driven alerts in a generic and modular way.

## Scope (MVP)
- Generic event ingest endpoint
- Subscription matching against Archive data
- Dispatch adapters (Telegram first)
- Delivery audit logging in Archive

## Event Envelope
```json
{
  "event_type": "entity.upserted",
  "domain": "real_estate",
  "entity_id": "...",
  "payload": {"...": "..."},
  "event_ts": "2026-03-07T00:00:00Z"
}
```

## Subscription Contract (stored in Archive)
```json
{
  "subscription_id": "...",
  "owner": "telegram_main",
  "domain": "real_estate",
  "event_type": "entity.upserted",
  "filters": {"city": "Gussago", "max_price": 350000},
  "channels": [{"type": "telegram", "target": "<chat_id>"}],
  "is_active": true
}
```

## Non-Goals
- No domain extraction/parsing
- No long-running workflow engine
- No custom rule language in MVP
