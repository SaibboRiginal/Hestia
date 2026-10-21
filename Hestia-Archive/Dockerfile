# Build from the repo root (docker-compose.global.yml: context ".") so the
# shared hestia_common package and the WebUI SDK are available.

# ── UI bundle (plugin contract): Hestia-Archive/ui → /ui/dist/webui/archive.js (Backup panel in the settings) ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Archive/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/archive.js

FROM python:3.12-slim

# pg_dump / pg_restore for the backup (docs/work/2026-10-20-backup-drive): PGDG clients for the server majors
# Hestia may run (ankane/pgvector = 15); Archive picks the one matching the server. Where apt.postgresql.org
# cannot be reached (restricted build networks), the distribution's own client is installed instead.
ARG PG_CLIENTS="15 16 17"
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
 && install -d /usr/share/postgresql-common/pgdg \
 && . /etc/os-release \
 && if curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
      && apt-get update \
      && apt-get install -y --no-install-recommends $(for v in $PG_CLIENTS; do echo postgresql-client-$v; done); \
    then echo "pg clients: PGDG $PG_CLIENTS"; \
    else rm -f /etc/apt/sources.list.d/pgdg.list && apt-get update \
      && apt-get install -y --no-install-recommends postgresql-client && echo "[fallback] pg clients: distribution"; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY Hestia-Archive/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Archive/app /code/app
# Outside /code: the compose dev mount ./Hestia-Archive/app:/code/app must not hide the bundle.
COPY --from=ui-build /ui/dist /ui/dist
ENV ARCHIVE_UI_DIST=/ui/dist

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19002"]
