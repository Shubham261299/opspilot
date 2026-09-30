# OpsPilot

[![CI](https://github.com/Shubham261299/opspilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Shubham261299/opspilot/actions/workflows/ci.yml)

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
| Stock register cleaner: reports all 11 problems planted in the sample file, with no false alarms (measured by the answer-key test) | ✅ |
| API: upload the stock register → clean stock counts, open PO notes and every issue saved in Postgres in one transaction, plus an audit row | ✅ |
| API: products with current stock (`GET /products`) and issues per upload (`GET /issues`) | ✅ |
| Web app: Upload (drag and drop), Stock (table with search), Issues (grouped by type) | ✅ |
| CI on every pull request and push to `main`: lint, tests against a real Postgres, frontend type-check, lint and build | ✅ |

## Run it locally

Requires Docker Desktop.

```bash
docker compose up --build
```

Then open **<http://localhost:3000>** and drop `sample_data/stock_register.xlsx` on the Upload page.

On start the API applies database migrations and loads the reference data. Also available:

- API docs: <http://localhost:8000/docs>. To try the upload there, open `POST /uploads/stock`,
  click *Try it out* and choose `sample_data/stock_register.xlsx`
- Current stock: <http://localhost:8000/products>
- Issues from the latest upload: <http://localhost:8000/issues>
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

Frontend, with instant reload while you edit (needs the API running on port 8000):

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173
npm run typecheck && npm run lint && npm run build
```

## Stack

- **Backend:** Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic · pandas ·
  PostgreSQL 16
- **Frontend:** React 19 · TypeScript · Vite · Tailwind CSS · shadcn/ui · React Router
- **Running it:** Docker Compose (Postgres, API, nginx serving the web app)
- **CI:** GitHub Actions (backend and frontend jobs in parallel, Postgres as a service container)

More pieces arrive as the features that need them ship.

## Design decisions

Each real design choice, with the options considered, is recorded in
[docs/decisions.md](docs/decisions.md).
