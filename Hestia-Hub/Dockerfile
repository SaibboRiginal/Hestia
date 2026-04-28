FROM python:3.12-slim

WORKDIR /code

COPY Hestia-Hub/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Hub/src /code/src

EXPOSE 19001

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "19001"]
