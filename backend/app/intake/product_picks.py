"""Matching product words to the catalogue: code first, the language model only for the rest.

Used by both the WhatsApp reader and the invoice reader. The model's picks are never trusted
as they are: a pick it isn't sure of, no pick, an SKU that doesn't exist, or a pick for words
it wasn't asked about is dropped, and the line stays unmatched for a human.
"""

from collections.abc import Iterable
from typing import Protocol

from pydantic import BaseModel

from app.domain.catalog import Catalog
from app.llm.client import LlmError, complete_structured
from app.llm.whatsapp import Message, ProductPicks, pick_products_messages


class Ask(Protocol):
    """Send messages to the model and get back an instance of `schema`."""

    async def __call__[T: BaseModel](
        self, messages: list[Message], schema: type[T], purpose: str
    ) -> T: ...


async def ask_llm[T: BaseModel](messages: list[Message], schema: type[T], purpose: str) -> T:
    """The real model, through app/llm."""
    return (await complete_structured(messages, schema, purpose=purpose)).value


async def pick_products(
    written: Iterable[str], catalog: Catalog, ask: Ask, purpose: str
) -> dict[str, str]:
    """{written words: SKU} for the picks the model is sure of and code could verify."""
    wanted = list(dict.fromkeys(written))  # unique, in order
    if not wanted:
        return {}
    try:
        picks = await ask(
            pick_products_messages(wanted, catalog.products.values()), ProductPicks, purpose
        )
    except LlmError:
        return {}  # every leftover stays unmatched instead
    return {
        pick.written: pick.sku
        for pick in picks.picks
        if pick.sure and pick.sku in catalog.products and pick.written in wanted
    }
