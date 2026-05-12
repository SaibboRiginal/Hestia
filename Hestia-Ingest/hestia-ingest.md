# Hestia-Ingest 📥

**Role:** Dynamic Data Fetcher — Connector Runtime
**Node:** Raspberry Pi (Always-On)
**Stack:** Python · FastAPI · Docker

---

## Responsibility

A generic runtime that executes data fetch operations on behalf of other services. Modules register connectors dynamically at runtime and request fetches on demand. Ingest returns raw data only — no processing, no storage.

Ingest registers itself into Hub and remains discoverable as a generic fetch runtime.

---

## Core Features

### Dynamic Connector Registry
- Modules register a connector on startup by providing: `connector_type`, `config` (credentials, parameters), and `owner` (the registering module's name).
- Connectors are deregistered automatically when the owning module deregisters or becomes unavailable (tracked via Hub).
- Multiple modules can register the same connector type with different configs.

### On-Demand Fetching
- A module calls Ingest with a `connector_id` and optional fetch parameters.
- Ingest runs the connector, collects raw data, and returns it directly in the response.
- Ingest does **not** store, cache, or modify the data in any way.

### Connector Interface
All connectors implement a common interface:
```
connect() → establishes connection / authenticates
fetch(params) → returns list of raw items
disconnect() → cleans up
```
Adding a new data source = implementing this interface and registering the connector type.

**Current Connectors:**

| Connector | Type Key | Description |
|---|---|---|
| `GmailIMAPFetcher` | `gmail_imap` | Fetches emails via IMAP from a Gmail account |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/connectors/register` | Register a connector instance |
| `DELETE` | `/connectors/{connector_id}` | Deregister a connector |
| `GET` | `/connectors` | List active connectors (and owner) |
| `POST` | `/connectors/{connector_id}/fetch` | Trigger a fetch, returns raw data |
| `GET` | `/health` | Service health |

---

## Constraints

- Ingest never writes to Archive or any database.
- Ingest never processes, transforms, or interprets fetched data.
- Connector credentials/config are passed at registration time and held in memory only — never persisted by Ingest.
- Ingest has no knowledge of what the fetched data will be used for.
- Ingest does not publish notifications and does not call Hermes.


## Documentation Synchronization (Required)

1. Any behavior, command, or contract change must update this service document in the same change set.
2. If API routes, methods, schemas, or Hub-routed command contracts change, update Hestia-Swagger/swagger.yml in the same change.
3. Ensure command metadata exposed to Hub discovery is complete and accurate (service, method, path, arguments/templates) so Oracle and clients can execute deterministically.
4. Keep canonical payloads rich at source; client-facing detail level is controlled by client rendering policy (minimal/compact/rich), not by deleting upstream semantics.
