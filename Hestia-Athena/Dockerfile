# Build from the repo root (docker-compose.global.yml: context ".") so the shared hestia_common package and the
# WebUI SDK are available.

# ── UI bundle (plugin contract): Hestia-Athena/ui → /ui/dist/webui/athena.js (page Pensieri, widget) ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Athena/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/athena.js

FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Athena/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Athena/app /code/app
# Outside /code/app: the compose dev mount ./Hestia-Athena/app:/code/app must not hide the bundle.
COPY --from=ui-build /ui/dist /ui/dist
ENV ATHENA_UI_DIST=/ui/dist

EXPOSE 19009

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19009"]
