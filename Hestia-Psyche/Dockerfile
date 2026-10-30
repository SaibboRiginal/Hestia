# Build from the repo root (docker-compose.global.yml: context ".") so the shared hestia_common package is available.

# ── UI bundle (plugin contract): Hestia-Psyche/ui → /ui/dist/webui/psyche.js ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Psyche/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/psyche.js

FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Psyche/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Psyche/app /code/app
COPY --from=ui-build /ui/dist /code/ui/dist

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/code

EXPOSE 19029

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19029"]
