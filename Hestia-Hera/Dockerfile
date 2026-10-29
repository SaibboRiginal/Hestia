# Build from the repo root (docker-compose.global.yml: context ".") so the shared hestia_common package is available.
# The WebUI plugin bundle (ui/) arrives with wave 7 of docs/work/2026-10-24-tutto-brainstorm-cindy.

FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Hera/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hera/app /code/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/code

EXPOSE 19025

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19025"]
