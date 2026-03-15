FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl bash \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x /app/scripts/manage.sh

CMD ["sh", "-c", "uvicorn app.main:app --host ${SMARTLIFE_APP_HOST:-0.0.0.0} --port ${SMARTLIFE_APP_PORT:-18089}"]
