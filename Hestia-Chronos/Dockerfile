# Build from the repo root (docker-compose.global.yml: context ".") so the
# shared hestia_common package and the WebUI SDK are available.

# ── UI bundle (plugin contract): Hestia-Chronos/ui → /ui/dist/webui/chronos.js (Esecuzioni page) ──
# Plain JS output: the node stage builds on the Raspberry Pi (arm) the same way.
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Chronos/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/chronos.js

FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Chronos/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy app contents directly to /code so flat imports resolve correctly
COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Chronos/app /code
# Outside /code: the compose dev mount ./Hestia-Chronos/app:/code must not hide the bundle.
COPY --from=ui-build /ui/dist /ui/dist
ENV CHRONOS_UI_DIST=/ui/dist

EXPOSE 19007

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19007"]
