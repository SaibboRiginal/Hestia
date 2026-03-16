FROM python:3.12-slim

WORKDIR /code

# Copy requirements first (cached independently of code changes)
COPY requirements.txt /code/requirements.txt

# Install Python dependencies (cached independently of code changes)
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy all application code last (this layer changes frequently)
COPY ./app/ /code/

# Run the endless background worker
CMD ["python", "main.py"]