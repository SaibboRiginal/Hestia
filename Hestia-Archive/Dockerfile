FROM python:3.12-slim
WORKDIR /code
COPY Hestia-Archive/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-Archive/app /code/app
# Start the FastAPI server on port 19002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19002"]