# Build from the repo root (docker-compose.global.yml: context ".") so the
# shared hestia_common package and the WebUI SDK are available.

# ── UI bundle (plugin contract): Hestia-Hub/ui → /ui/dist/webui/hub.js (Mappa page, Servizi online widget) ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Hub/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/hub.js

FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Hub/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hub/src /code/src
# Outside /code: the compose dev mount ./Hestia-Hub/src:/code/src must not hide the bundle.
COPY --from=ui-build /ui/dist /ui/dist
ENV HUB_UI_DIST=/ui/dist

EXPOSE 19001

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "19001"]
