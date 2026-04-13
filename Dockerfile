FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create necessary directories for volumes
RUN mkdir -p /app/data /app/credentials

EXPOSE 9000

ENV APP_HOST=0.0.0.0 \
    APP_PORT=9000 \
    LOG_LEVEL=DEBUG

CMD ["python", "main.py"]
