# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /code

# Install tzdata for timezone support (required for OAuth token timestamp validation)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cached independently of code changes)
COPY Hestia-Hecate/requirements.txt /code/requirements.txt

# Install dependencies (cached independently of code changes)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# The Google app that comes with Hestia (release images only, from GitHub secrets; a local build has none and the card
# asks for your own client). Outside /code, which compose mounts over. The client ID is public anyway (it is in every
# consent link) and is a build arg so a new client rebuilds this layer; the secret is a BuildKit secret.
ARG GOOGLE_CLIENT_ID=""
RUN --mount=type=secret,id=google_client_secret,required=false \
    mkdir -p /opt/hestia && if [ -n "$GOOGLE_CLIENT_ID" ] && [ -s /run/secrets/google_client_secret ]; then \
      python -c "import json,sys; print(json.dumps({'client_id': sys.argv[1], 'client_secret': open('/run/secrets/google_client_secret').read().strip()}))" \
        "$GOOGLE_CLIENT_ID" > /opt/hestia/google_client.json; fi

# Copy all application code last (this layer changes frequently)
COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hecate/app/ /code/

# Start the Factory on port 19003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19003"]