# DB hardening after public-repo secret scan

| Version | Source | Status |
|---|---|---|
| 1.0 | user via external chat (Marko, "si fallo") | done |

## Goal
Repo is public. Secret scan (gitleaks + targeted grep, all branches, full history) found no real secrets.
Only weak point: Postgres default password hardcoded in compose + port 5432 published on all interfaces.

## Scope
- `docker-compose.global.yml`, `Hestia-Archive/docker-compose.yml`: password from `${HESTIA_DB_PASSWORD:-super_secret_local_password}`
  (same default → existing volume keeps working); port bound to `127.0.0.1:5432`.
- Root `.env.example` documenting `HESTIA_DB_PASSWORD` and how to rotate it on an existing volume.

## Acceptance
- `docker compose config` resolves the default and an override; DB port has `host_ip: 127.0.0.1`.
- No behaviour change for containers (they reach the DB over `hestia_net`, not the host port).

## Out of scope
History rewrite (nothing to remove). `docker-compose.rpi.yml` already takes `ARCHIVE_DATABASE_URL` from env.
