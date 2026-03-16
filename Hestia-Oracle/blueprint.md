# Hestia-Oracle Blueprint

## Mission
Conversational reasoning service with generic routing, compact context building, and memory/subscription extraction.

## Structure
```
Hestia-Oracle/
├── hestia-oracle.md
├── blueprint.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── app/
	├── main.py
	├── agents/
	└── core/
		└── services/
```

## Contracts
- Reads/writes memory + sessions via Archive only
- Discovers module tools via Hub
- Compiles proactive subscriptions to Archive