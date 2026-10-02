FROM python:3.12-slim

WORKDIR /code

# git: Forge works in git worktrees. Node + Claude Code CLI are optional
# (build with --build-arg INSTALL_CLAUDE_CODE=1 to use a Claude subscription/API key).
ARG INSTALL_CLAUDE_CODE=0
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl \
    && if [ "$INSTALL_CLAUDE_CODE" = "1" ]; then \
         curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
         && apt-get install -y --no-install-recommends nodejs \
         && npm install -g @anthropic-ai/claude-code; \
       fi \
    && rm -rf /var/lib/apt/lists/*

COPY Hestia-Hephaestus/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hephaestus/app /code/app

EXPOSE 19010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19010"]
