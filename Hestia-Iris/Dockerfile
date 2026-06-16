FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Iris/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Iris/app /code

ENV PYTHONPATH=/code
ENV PYTHONUNBUFFERED=1

EXPOSE 19012

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19012"]
