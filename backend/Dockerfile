FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Bogota

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN mkdir -p /app/storage/media/inbound

EXPOSE 8000

# app.start waits for the database, applies migrations, seeds if empty and launches Uvicorn.
CMD ["python", "-m", "app.start"]
