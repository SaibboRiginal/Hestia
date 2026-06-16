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

# Start the Factory on port 19003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19003"]