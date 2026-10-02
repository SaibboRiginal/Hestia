# Build from the repo root (docker-compose.global.yml: context ".") so the
# shared hestia_common package is available, like every other service.
FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Metis/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Metis/app /code/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/code

EXPOSE 19014

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19014"]
