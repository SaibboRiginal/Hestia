FROM python:3.12-slim

WORKDIR /code

# Copy requirements first (cached independently of code changes)
COPY Hestia-Ingest/requirements.txt /code/requirements.txt

# Install dependencies (cached independently of code changes)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy all application code last (this layer changes frequently)
COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Ingest/app/ /code/

# Start the Factory on port 19003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19003"]