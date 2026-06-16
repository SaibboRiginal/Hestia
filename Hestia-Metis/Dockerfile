FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 19014

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "19014"]
