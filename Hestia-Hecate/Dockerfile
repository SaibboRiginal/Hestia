# ── UI bundle (plugin contract): Hestia-Hecate/ui → /ui/dist/webui/hecate.js («Dispositivi» page) ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Hecate/ui/ /ui/
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/hecate.js

FROM python:3.12-slim

WORKDIR /code

# Install tzdata for timezone support (required for OAuth token timestamp validation)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cached independently of code changes)
COPY Hestia-Hecate/requirements.txt /code/requirements.txt

# Install dependencies (cached independently of code changes)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy all application code last (this layer changes frequently)
COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hecate/app/ /code/
# Outside /code: a compose dev mount of app/ must not hide the bundle.
COPY --from=ui-build /ui/dist /ui/dist
ENV HECATE_UI_DIST=/ui/dist

# Start the Factory on port 19003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19003"]