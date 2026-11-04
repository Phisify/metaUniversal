FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
 && playwright install --with-deps chromium \
 && apt-get update && apt-get install -y --no-install-recommends fonts-inter && rm -rf /var/lib/apt/lists/*

COPY . .
CMD ["python", "-m", "engine.main", "schedule"]
