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

## 007 · Integer ids, with business codes kept unique (2026-09-29)

**Context:** Suppliers and products already have codes people use (`SUP01`, `ST-0051`).
**Options:** Use the codes as primary keys · integer primary keys plus unique code columns.
**Choice:** Every table has an integer `id`; `suppliers.code` and `products.sku` are unique.
**Why:** Foreign keys stay small and stable even if a code is renamed one day, and the unique
constraint still guarantees no duplicate codes.

## 008 · Money is NUMERIC(10,2), never float (2026-09-29)

**Context:** Prices, and later invoice totals, must add up exactly.
**Options:** float · NUMERIC in Postgres with `Decimal` in Python · integer paise.
**Choice:** `NUMERIC(10,2)` / `Decimal`.
**Why:** Floats can't store many decimal amounts exactly (0.1 + 0.2 ≠ 0.3). Decimal keeps rupees
and paise exact and still reads naturally.

## 009 · Reference data is seeded on start-up, insert-only (2026-09-29)

**Context:** Suppliers and products must exist before the first stock upload, and
`docker compose up` alone should give a working app.
**Options:** Put the data inside a migration · a seed script run by hand · a seed that runs on
start-up.
**Choice:** On start the API container runs `alembic upgrade head`, then `python -m app.db.seed`,
then the server. The seed inserts rows whose code or SKU is missing and never overwrites existing
rows (`INSERT … ON CONFLICT DO NOTHING`).
**Why:** Migrations stay about structure, one command gives a working app, and a restart can never
silently undo a change made in the app. Invalid reference data stops start-up with the CSV row
number instead of being guessed at.

## 010 · Stock is kept as per-upload snapshots of valid counts only (2026-09-29)

**Context:** Each stock register is a full godown count on one date. Some rows can't be trusted
(for example a count of −4).
**Options:** One "current stock" row per product, overwritten · one snapshot per upload. For a
bad count: store it, clamp it to 0, or don't store it.
**Choice:** `stock_levels` holds one row per product per upload, and the database enforces
`qty_on_hand >= 0`. Current stock = the snapshot from the processed upload with the latest count
date. A count that can't be trusted is not stored: it becomes an `issues` row and the product
shows "needs recount".
**Why:** History comes for free, an old file uploaded late can't overwrite a newer count, and no
made-up number ever reaches the reorder formula.

## 011 · Purchase orders placed outside the app get their own table (2026-09-29)

**Context:** A remark like "40 pcs ordered from Brightline on 22/9" means stock is already on
order. The week-3 reorder rule needs on-order quantities, and the supplier and date explain when
stock should arrive.
**Options:** An `on_order_qty` column on `stock_levels` · a separate `open_po_notes` table.
**Choice:** `open_po_notes`: product, supplier, qty, ordered-on date, the original remark, and the
upload and row it came from.
**Why:** `stock_levels` stays about what is physically in the godown, and these notes stay separate
from purchase orders created in the app, which only a human approval may create.

## 012 · Migrations are autogenerated, reviewed and checked by tests (2026-09-29)

**Context:** The schema will change every few weeks.
**Options:** Hand-written SQL files · Alembic autogenerate.
**Choice:** Alembic generates each migration from the models, ruff formats it automatically, and a
human reviews it. Two tests guard the process: the models must match the migrations
(`alembic check`), and every migration must downgrade and upgrade cleanly.
**Why:** Less typing and fewer mistakes, and a forgotten migration fails CI instead of production.

## 013 · How the stock register is read (2026-09-29)

**Context:** The sheet has title rows above the header, a section row mid-table, a totals footer
and a second "Notes" sheet. Row numbers in issues must match what the owner sees in Excel.
**Options:** Assume fixed positions (header on row 4) · detect the structure.
**Choice:** pandas reads each sheet as a raw grid (`header=None`, `dtype=object`,
`keep_default_na=False`). The header is the first row whose titles match known synonyms
("Qty In Stock", "Item Code", …). Plain Python then classifies each row: blank rows are ignored;
title, section and totals rows become `skipped_row` info issues; other sheets with content become
an `other_sheet` issue.
**Why:** The same code survives an extra title line or reordered columns. `keep_default_na=False`
matters: by default pandas turns text like "n/a" or "NA" into blank cells, hiding it from every
check.

## 014 · When the sheet disagrees with itself or with the master (2026-09-29)

**Context:** A register row can conflict with another row (duplicates) or with the product
master (code vs name, unit, rates, supplier).
**Options:** Trust the sheet · trust the master · refuse to guess and ask a human.
**Choice:**

- Same product twice: the last row wins (a later line is a correction, e.g. "recount"); the issue
  shows both counts.
- Item code and name that disagree: not loaded.
- Blank code: matched only by an exact name or a unique alias; otherwise not loaded.
- Unit different from the master's: not loaded (converting would be a guess). Spelling variants
  (NOS, Pcs, coils, …) are normalised and listed once per file.
- Rates and supplier: the master is kept; blanks and differences become issues. A stock count
  never changes prices.
- A name that differs only in spaces or capitals: loaded, reported as info.

**Why:** A stock count answers "how many are in the godown", nothing more. Anything uncertain goes
to a human instead of into the numbers.

## 015 · Each issue type has one fixed severity (2026-09-29)

**Context:** The Issues page should show what matters first, and the same problem should always
look the same.
**Options:** Decide severity case by case · fix it per issue type.
**Choice:** error = not loaded; warning = loaded, but check it; info = handled automatically and
listed for transparency. The mapping lives in `app/intake/issues.py`, and a test checks every type
has one.
**Why:** The owner learns what each level means once, and it never changes.

## 016 · Dates written without a year (2026-09-29)

**Context:** People write "24/9" and "22/9"; the year has to come from somewhere.
**Options:** Always assume the current year · the latest such date on or before a reference date.
**Choice:** The latest such date on or before the reference: the upload date for the count date,
the count date for dates inside remarks. Day first, the Indian way.
**Why:** A count uploaded on 5 January saying "28/12" means last December, not the coming one.

## 017 · Built from the data first, then measured against the answer key (2026-09-29)

**Context:** `sample_data/answer_key.json` lists the planted problems. Reading it first invites
special cases that pass the test without being robust.
**Options:** Tune the cleaner using the key · design from the data, then measure.
**Choice:** The cleaner was designed from the spreadsheet alone. The key was opened only to write
`test_stock_register_answer_key.py`. First run: 10 of 11 planted problems reported. The miss was
row 19 ("  gi box 8 module  "), judged harmless because the item code identifies the product. That
contradicted "nothing changes silently", so any name that differs only in spaces or capitals is
now reported as info, as a general rule. Result: 11 of 11, and every error or warning raised is a
planted problem.
**Why:** Measure before claiming. The key checks the design instead of shaping it.

## 018 · One transaction per upload, and failed files are recorded too (2026-09-29)

**Context:** One upload writes to five tables (uploads, stock_levels, open_po_notes, issues,
audit_log). A crash halfway must never leave half a stock count.
**Options:** Save each part as soon as it's ready · one transaction for the whole upload.
**Choice:** One transaction: all five are saved together or not at all. A file that can't be
processed (unreadable, no header row) is still saved as a `failed` upload with its own audit row,
and the API answers 422 with its `upload_id`. A request that isn't a stock file at all (wrong type,
empty, too large) is refused with 415, 422 or 413 and nothing is saved. Parsing runs in a worker
thread so a large file doesn't pause other requests. Until sign-in exists, the audit actor is
`owner`.
**Why:** The Stock page can never show a half-imported count, and even a bad file leaves a record of
what happened and when.

## 019 · Money is sent as text in JSON (2026-09-29)

**Context:** Prices are exact `Decimal`s in Python and NUMERIC in Postgres, but JSON numbers become
floating-point numbers in the browser.
**Options:** Send numbers (`1150.0`) · send strings (`"1150.00"`).
**Choice:** Strings, which is Pydantic's default for `Decimal`. The frontend only formats them for
display and never calculates with them.
**Why:** The value stays exact all the way to the screen, and calculations stay in the backend
(decision 002).

---

## Ideas

Out of scope for the current phase; pick up when the phase allows.

- Make `audit_log` append-only inside the database (a trigger that rejects UPDATE and DELETE).
- A seed option that applies changes from `product_master.csv` to existing products (for example
  new aliases), shown as a diff and applied only after approval.
