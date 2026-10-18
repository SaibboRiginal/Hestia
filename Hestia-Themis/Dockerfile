# Build from the repo root (docker-compose.global.yml: context ".") so the
# shared hestia_common package and the WebUI SDK are available, like every other service.

# ── UI bundle (plugin contract): Hestia-Themis/ui → /ui/dist/webui/themis.js (Registro page) ──
# Plain JS output: the node stage builds on the Raspberry Pi (arm) the same way.
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Themis/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/themis.js

FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Themis/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Themis/app /code/app
# Outside /code: the compose dev mount ./Hestia-Themis/app:/code/app must not hide the bundle.
COPY --from=ui-build /ui/dist /ui/dist

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/code
ENV THEMIS_UI_DIST=/ui/dist

EXPOSE 19016

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19016"]
