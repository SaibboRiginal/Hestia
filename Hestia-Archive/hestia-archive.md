# Hestia-Archive 🗄️

**Role:** Generic Storage + Query Gateway
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · PostgreSQL + pgvector · Docker

---

## Responsibility

Archive is the only database access service in Hestia.
It stores and serves all persistent state through generic APIs.

---

## Data Areas

- Raw records (`/api/archive`)
- Processed entities (`/api/entities`)
- Chat sessions (`/api/chat/history`)
- User memory/preferences (`/api/memory`)
- **Alert subscriptions** (`/api/subscriptions`) for proactive dispatch
- **Dispatch delivery log** (`/api/dispatch/logs`) for auditing and dedupe

---

## API Highlights

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/entities` | Upsert one entity |
| `POST` | `/api/entities/search` | Generic hybrid search |
| `GET` | `/api/memory/active` | Active preferences |
| `POST` | `/api/subscriptions` | Create/update subscription |
| `GET` | `/api/subscriptions/active` | List active subscriptions |
| `POST` | `/api/dispatch/logs` | Write delivery result |
| `GET` | `/health` | Archive health |

---

## Constraints

- No domain-specific ranking/business rules.
- No notification dispatch decisions.
- No module-specific parsing.
