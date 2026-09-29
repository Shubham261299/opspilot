# Built from the repo root (see docker-compose.yml and .dockerignore).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so this layer stays cached until requirements change.
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ .
# Reference data for seeding: only these two files (never answer_key.json).
COPY sample_data/suppliers.csv sample_data/product_master.csv ./seed_data/
ENV SEED_DATA_DIR=/app/seed_data

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
# On start: apply pending migrations, add missing reference data, then serve.
# `exec` hands the process over to uvicorn so it receives Docker's stop signal.
CMD ["sh", "-c", "alembic upgrade head && python -m app.db.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
