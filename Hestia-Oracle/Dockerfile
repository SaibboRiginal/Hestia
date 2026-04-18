# Use a lightweight Python image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /code

# Install system dependencies required for psycopg2 (Postgres client)
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements first (cached independently of code changes)
COPY requirements.txt /code/requirements.txt

# Install dependencies (cached independently of code changes)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy all application code last (this layer changes frequently)
COPY ./app/ /code/

# Expose the API port
EXPOSE 19004

# Start the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "19004"]