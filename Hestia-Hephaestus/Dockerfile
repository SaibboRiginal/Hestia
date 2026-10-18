# Build from the repo root (docker-compose.global.yml: context ".") so the
# shared hestia_common package and the WebUI SDK are available.

# ── UI bundle (plugin contract): Hestia-Hephaestus/ui → /ui/dist/webui/hephaestus.js (Riparazioni, widget Forge) ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Hephaestus/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/hephaestus.js

FROM python:3.12-slim

WORKDIR /code

# git: Forge works in git worktrees. (Claude Code lives in Oracle, the LLM core.)
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY Hestia-Hephaestus/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
# Forge runs any service's tests: union of the services' light deps.
COPY Hestia-Hephaestus/requirements-forge-tests.txt /code/requirements-forge-tests.txt
RUN pip install --no-cache-dir -r /code/requirements-forge-tests.txt \
    && git config --system --add safe.directory '*'

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hephaestus/app /code/app
# Outside /code: the compose dev mount ./Hestia-Hephaestus/app:/code/app must not hide the bundle.
COPY --from=ui-build /ui/dist /ui/dist
ENV HEPHAESTUS_UI_DIST=/ui/dist

EXPOSE 19010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19010"]
