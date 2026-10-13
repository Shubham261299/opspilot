# Evals

An **eval** scores the app's AI-dependent code against known answers
(`sample_data/answer_key.json`, read only here and in tests, never by the app).

| Suite | What it reads | Scored on |
| --- | --- | --- |
| `whatsapp` | the sample WhatsApp chat | every order line: product, quantity; non-orders; lines sent to review |
| `invoices` | the 4 sample supplier invoice PDFs | invoice number, supplier, date, every line's product/qty/rate, totals to the paisa, duplicate mark |

## Two ways to run

**With the real model** (Ollama running; from the repo root). This is the quality measurement,
and its numbers are the ones quoted in the README:

```bash
python evals/run.py all                       # LLM_MODEL from .env (default qwen2.5:7b)
LLM_MODEL=ollama_chat/qwen2.5:14b python evals/run.py all
```

Results are saved to `evals/results/<suite>_<model>.json`. With Langfuse keys in `.env`, these
runs also show up as traces.

**From the tapes, with no model** (what CI runs; from `backend/`):

```bash
python -m pytest ../evals
```

A *tape* (`evals/recordings/<suite>.json`) holds every answer the real model gave when the suite
was last recorded. Replaying it runs everything except the model for real: reading the chat and
the PDFs, matching products, the arithmetic checks, the scoring. The test passes when the score
equals the one recorded. It catches broken code, not a worse model.

## When a test says "the tape is out of date"

A prompt or an output schema changed, so a request no longer matches any recorded answer. Record
again with the real model and commit the new tapes:

```bash
LLM_MODEL=ollama_chat/qwen2.5:14b python evals/run.py all --record
```

If the score changed, check why before committing: that is the eval doing its job.
