FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Athena/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Athena/app /code/app

EXPOSE 19009

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19009"]
