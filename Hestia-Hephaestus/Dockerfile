FROM python:3.12-slim

WORKDIR /code

# git: Forge works in git worktrees. (Claude Code lives in Oracle, the LLM core.)
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY Hestia-Hephaestus/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
# Forge runs any service's tests: union of the services' light deps.
COPY Hestia-Hephaestus/requirements-forge-tests.txt /code/requirements-forge-tests.txt
RUN pip install --no-cache-dir -r /code/requirements-forge-tests.txt \
    && git config --system --add safe.directory '*'

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hephaestus/app /code/app

EXPOSE 19010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19010"]
