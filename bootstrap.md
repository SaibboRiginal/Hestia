## Bootstrap

```bash
docker network create hestia_net
```

## Suggested startup order

1. `Hestia-Hub`
2. `Hestia-Archive`
3. `Hestia-Hecate`
4. `Hestia-Hermes`
5. `Hestia-Oracle`
6. `Hestia-Scout`
7. `Hestia-Telegram`

## One-command orchestration

### Full stack (all services)

```bash
docker compose -f docker-compose.global.yml up --build -d
```

### Raspberry deployment (always-on core services)

Set `ARCHIVE_DATABASE_URL` first (cloud DB or remote DB), then run:

```bash
docker compose -f docker-compose.rpi.yml up --build -d
```

## New service scaffolding

Use the shared generator to create a service that already follows the Hub contract:

```bash
create-service.bat <name> [core|module|integration] [port]
```

Example:

```bash
create-service.bat Markets module 8012
```