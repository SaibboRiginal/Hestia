# ── WebUI plugin bundle (client plugins SPEC §4.4): built with the shared SDK, never committed ──
FROM node:22-alpine AS ui-build
WORKDIR /sdk
COPY Hestia-Shared/webui-sdk/package.json Hestia-Shared/webui-sdk/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY Hestia-Shared/webui-sdk/src ./src
COPY Hestia-Shared/webui-sdk/build.mjs ./
COPY Hestia-Scout/ui/src /ui/src
RUN node build.mjs plugin /ui/src/index.ts /ui/dist/webui/scout.js

FROM python:3.12-slim

WORKDIR /code

# Copy requirements first (cached independently of code changes)
COPY Hestia-Scout/requirements.txt /code/requirements.txt

# Install Python dependencies (cached independently of code changes)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy all application code last (this layer changes frequently)
COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Scout/app/ /code/
# Outside /code: compose mounts ./Hestia-Scout/app over /code, which would hide a bundle baked there.
COPY --from=ui-build /ui/dist /ui/dist
ENV SCOUT_UI_DIST=/ui/dist

# Run the endless background worker
CMD ["python", "main.py"]
