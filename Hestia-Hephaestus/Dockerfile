FROM python:3.12-slim

WORKDIR /code

# git: Forge works in git worktrees. (Claude Code lives in Oracle, the LLM core.)
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY Hestia-Hephaestus/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hephaestus/app /code/app

EXPOSE 19010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19010"]
