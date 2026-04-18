FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy app contents directly to /code so flat imports resolve correctly
COPY ./app /code

EXPOSE 19007

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19007"]
