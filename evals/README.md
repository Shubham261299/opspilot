# Evals

An **eval** scores the app's AI-dependent code against known answers
(`sample_data/answer_key.json`, read only here and in tests, never by the app).

| Suite | What it reads | Scored on |
| --- | --- | --- |
| `whatsapp` | the sample WhatsApp chat | every order line: product, quantity; non-orders; lines sent to review |
| `invoices` | the 4 sample supplier invoice PDFs | invoice number, supplier, date, every line's product/qty/rate, totals to the paisa, duplicate mark |
| `policy` | `company_policy.pdf` and 18 questions (15 English, 3 Hinglish) | is the right rule the closest one (hit@1) or among the closest three (hit@3)? It runs the real import and the real pgvector search |

The policy questions were written by hand before the first run and not changed to suit its
results, so with only 18 of them each question is worth about 5 points: treat the numbers as
rough.

## Two ways to run

**With the real model** (Ollama running; from the repo root). This is the quality measurement,
and its numbers are the ones quoted in the README:

```bash
python evals/run.py all                       # LLM_MODEL from .env (default qwen2.5:7b)
LLM_MODEL=ollama_chat/qwen2.5:14b python evals/run.py all
```

Results are saved to `evals/results/<suite>_<model>.json`. With Langfuse keys in `.env`, these
runs also show up as traces. The `policy` suite needs Postgres with pgvector
(`docker compose up -d db`) and `ollama pull nomic-embed-text`.

**From the tapes, with no model** (what CI runs; from `backend/`):

```bash
docker compose up -d db   # only the policy suite needs it; CI has a Postgres service for it
python -m pytest ../evals
```

A *tape* (`evals/recordings/<suite>.json`) holds every answer the real model gave when the suite
was last recorded (for `policy`: the embedding vectors, rounded to 5 decimals). Replaying it runs
everything except the model for real: reading the chat and the PDFs, matching products, the
arithmetic checks, the search in Postgres, the scoring. The test passes when the score equals the
one recorded. It catches broken code, not a worse model.

The `policy` suite empties and re-migrates the `_test` database it uses (`TEST_DATABASE_URL`,
default `opspilot_test`, the one the integration tests use). It refuses a database whose name does
not end in `_test`.

## When a test says "the tape is out of date"

A prompt, an output schema, the policy file, a question, or the embedding prefix changed, so a
request no longer matches any recorded answer. Record again with the real model and commit the
new tapes:

```bash
LLM_MODEL=ollama_chat/qwen2.5:14b python evals/run.py all --record
```

If the score changed, check why before committing: that is the eval doing its job.
