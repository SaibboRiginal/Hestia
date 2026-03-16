# Use a lightweight Python image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /code

# Install system dependencies required for psycopg2 (Postgres client)
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cached independently of code changes)
COPY requirements.txt /code/requirements.txt

# Install Python dependencies (cached independently of code changes)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy application code last (this layer changes frequently)
COPY ./app /code/app

# Start the FastAPI server
CMD ["python", "app/main.py"]