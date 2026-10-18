# Build from the repo root (docker-compose.global.yml: context ".") so the
# shared hestia_common package and the WebUI SDK are available.

# ── UI bundle (plugin contract): Hestia-Hercules/ui → /ui/dist/webui/hercules.js ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Hercules/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/hercules.js

FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Hercules/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hercules/app /code/app
COPY --from=ui-build /ui/dist /code/ui/dist

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/code
ENV HERCULES_UI_DIST=/code/ui/dist

EXPOSE 19019

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19019"]
