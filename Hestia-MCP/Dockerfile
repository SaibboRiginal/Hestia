FROM python:3.12-slim
WORKDIR /code
COPY Hestia-MCP/requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt
COPY Hestia-Shared/hestia_common /code/hestia_common
COPY Hestia-MCP/app/ /code/
EXPOSE 19013
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19013"]
