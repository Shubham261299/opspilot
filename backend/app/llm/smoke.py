"""Check that the configured model answers, through the same path the app uses.

python -m app.llm.smoke                         (from backend/, against your Ollama)
docker compose exec api python -m app.llm.smoke (from inside the API container)
"""

import asyncio
import json

from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm.client import LlmError, complete_structured
from app.llm.tracing import flush_tracing, setup_tracing

MESSAGE = "20 box 1.5mm wire, 10 pkt gitti aur 50 black tape bhejo aaj"


class Line(BaseModel):
    product_text: str = Field(description="The product as the customer wrote it, without the qty")
    qty: int


class Lines(BaseModel):
    lines: list[Line]


async def main() -> int:
    settings = get_settings()
    print(f"Model: {settings.llm_model} at {settings.llm_base_url}")
    print(f"Message: {MESSAGE!r}")
    print(f"Tracing to Langfuse: {'on' if setup_tracing(settings) else 'off (no keys set)'}")
    try:
        result = await complete_structured(
            [
                {"role": "system", "content": "Extract the order lines from the message."},
                {"role": "user", "content": MESSAGE},
            ],
            Lines,
            purpose="smoke_test",
        )
    except LlmError as error:
        print(f"FAILED ({error.code}): {error.message}")
        await flush_tracing()
        return 1
    await flush_tracing()  # this script ends right away; send the trace before it does
    print(f"OK in {result.latency_ms} ms, {result.attempts} attempt(s):")
    print(json.dumps(result.value.model_dump(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
