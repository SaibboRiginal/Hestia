# Build from the repo root (docker-compose.global.yml: context ".") so the
# shared hestia_common package and the WebUI SDK are available.

# ── UI bundle (plugin contract): Hestia-Iris/ui → /ui/dist/webui/iris.js («Email» page) ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Iris/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/iris.js

FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Iris/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Iris/app /code
# Outside /code: a compose dev mount of app/ must not hide the bundle.
COPY --from=ui-build /ui/dist /ui/dist
ENV IRIS_UI_DIST=/ui/dist

ENV PYTHONPATH=/code
ENV PYTHONUNBUFFERED=1

EXPOSE 19012

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19012"]
