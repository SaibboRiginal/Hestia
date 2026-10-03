# Use a lightweight Python image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /code

# Install system dependencies required for psycopg2 (Postgres client).
# Optional Claude Code CLI for the "code" use case (Forge engine `claude`,
# Claude Pro/Max subscription). Default on; ORACLE_INSTALL_CLAUDE_CODE=0 in the root .env to skip.
ARG INSTALL_CLAUDE_CODE=1
RUN apt-get update && apt-get install -y libpq-dev gcc git curl ca-certificates \
    && if [ "$INSTALL_CLAUDE_CODE" = "1" ]; then \
         curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
         && apt-get install -y --no-install-recommends nodejs \
         && npm install -g @anthropic-ai/claude-code; \
       fi \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cached independently of code changes)
COPY Hestia-Oracle/requirements.txt /code/requirements.txt

# Install dependencies (cached independently of code changes)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Claude Code (Forge engine `claude`) runs every service's pytest suite from here:
# install the union of the services' light deps, and trust the repo mounted from
# the host (otherwise git refuses it: "dubious ownership").
COPY Hestia-Hephaestus/requirements-forge-tests.txt /code/requirements-forge-tests.txt
RUN if [ "$INSTALL_CLAUDE_CODE" = "1" ]; then \
      pip install --no-cache-dir -r /code/requirements-forge-tests.txt; fi \
    && git config --system --add safe.directory '*'

# Copy all application code last (this layer changes frequently)
COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Oracle/app/ /code/

# Expose the API port
EXPOSE 19004

# Start the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19004"]