# OpsPilot

An AI back office for a small distributor. OpsPilot turns messy WhatsApp orders, an Excel stock
sheet and PDF supplier invoices into clean data. Agents then propose actions (reorders, payment
reminders, anomaly flags), and the owner approves every action before anything happens.

The customer is fictional: **Sharma Traders**, an electrical and hardware parts distributor in
Pune with 60 products, 25 shop-owner customers and 6 suppliers. Every name, number and record in
this repo is invented.

> **Status:** building v0.1 in public, week 1 of 12. Only features marked ✅ work today.

## What works so far

| Feature | Status |
| --- | --- |
| API skeleton: health check, structured JSON logs, Docker Compose | ✅ |
| Database schema with migrations; 6 suppliers and 60 products loaded on start-up | ✅ |
| Upload the Excel stock register → clean products and stock levels in Postgres | 🚧 week 1 |
| Issues page: every data problem listed, nothing silently dropped | 🚧 week 1 |
| CI: lint and tests on every push | 🚧 week 1 |

## Run it locally

Requires Docker Desktop.

```bash
docker compose up --build
```

On start the API applies database migrations and loads the reference data, then serves:

- API docs: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>
- Database shell: `docker compose exec db psql -U opspilot` (Postgres is published on host port
  5433, so it doesn't clash with a locally installed Postgres)

## Run the tests

```bash
docker compose up -d db          # tests use their own opspilot_test database on this server
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest                           # unit tests + database tests
ruff check . && ruff format --check .
```

## Stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic · PostgreSQL 16 ·
Docker Compose. More pieces arrive as the features that need them ship.

## Design decisions

Each real design choice, with the options considered, is recorded in
[docs/decisions.md](docs/decisions.md).
