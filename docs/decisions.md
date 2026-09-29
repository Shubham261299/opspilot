# Design decisions

One entry per real design choice: the context, the options considered, what was chosen and why.
Newest entries at the bottom. Useful ideas that are out of scope for the current phase are parked
under [Ideas](#ideas).

---

## 001 · PostgreSQL, not MongoDB (2026-09-25)

**Context:** The data is relational. Products belong to suppliers, orders have lines, approved
proposals become purchase orders, and every approval writes an audit row in the same transaction.
**Options:** PostgreSQL · MongoDB.
**Choice:** PostgreSQL 16.
**Why:** Foreign keys and transactions fit both the data and the approval flow. pgvector adds
vector search later (policy retrieval in v0.4) without a second database.

## 002 · Code calculates, the LLM explains (2026-09-25)

**Context:** Agents will propose reorder quantities, overdue amounts and anomaly flags. A wrong
number in a purchase order costs real money.
**Options:** Let the LLM compute quantities and amounts · compute them in plain Python and use the
LLM to extract, match, classify and explain.
**Choice:** Pure functions in `backend/app/domain/` compute every quantity, amount, date and
threshold. The LLM never does arithmetic.
**Why:** Numbers stay exact and unit-tested. The LLM does what it is good at: messy text,
matching and explanations.

## 003 · File uploads before live integrations (2026-09-25)

**Context:** The live WhatsApp Cloud API needs Meta developer setup and a test number. That
shouldn't block the core pipeline.
**Options:** Start with live webhooks · start with file uploads (chat export, Excel, PDF).
**Choice:** Every source works by file upload first. Live WhatsApp follows in week 6.
**Why:** Nothing blocks on external approvals, and the same parsers serve both paths later.

## 004 · API image built from the repo root with an allow-list (2026-09-28)

**Context:** The API seeds suppliers and products from two CSVs in `sample_data/`, outside
`backend/`. The same folder holds `answer_key.json`, which the app must never read.
**Options:** Mount `sample_data/` as a volume · copy the CSVs into `backend/` · build from the
repo root and copy in only the two CSVs.
**Choice:** Build from the repo root. `.dockerignore` excludes everything except `backend/` and
the two seed CSVs.
**Why:** One copy of the data, a self-contained image that also works on a hosting platform (no
volume needed), and the answer key cannot end up in the image.

## 005 · Configuration from environment variables, no database default in code (2026-09-28)

**Context:** The same code runs locally, in Docker, in CI and later on a hosting platform.
**Options:** Local defaults hard-coded in `config.py` · everything from environment variables.
**Choice:** `pydantic-settings` reads environment variables (plus a gitignored `.env` in
development). `DATABASE_URL` is required, with no default in code. Local-only defaults live in
`docker-compose.yml` and `.env.example`.
**Why:** A missing setting fails at startup with a clear message instead of quietly connecting to
the wrong database.

## 006 · JSON logs with the standard library (2026-09-28)

**Context:** Every log line needs a `request_id` (later also `upload_id`, `proposal_id`) so one
request can be traced end to end.
**Options:** structlog · python-json-logger · a small formatter on the standard `logging` module.
**Choice:** A short `JsonFormatter` plus a `ContextVar` holding the request id, set by middleware.
**Why:** No extra dependency, and the whole mechanism fits in one readable file. Revisit if
logging needs grow.

---

## Ideas

Out of scope for the current phase; pick up when the phase allows.

- (none yet)
