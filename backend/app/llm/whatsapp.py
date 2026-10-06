"""Prompts and output schemas for reading WhatsApp orders.

The model does two kinds of job here, and only these:
1. read one customer's thread and list what they want, as they wrote it, with later
   corrections applied (ThreadReading);
2. for product words the code couldn't match exactly, pick the catalogue product they most
   likely mean, or say none / not sure (ProductPicks).
Code does everything else: matching names and aliases exactly, checking every SKU the model
returns, and deciding what needs a human.
"""

import json
from collections.abc import Iterable

from pydantic import BaseModel, Field

from app.domain.catalog import CatalogProduct

Message = dict[str, str]


# 1. Reading a thread -------------------------------------------------------------------


class OrderLine(BaseModel):
    product: str = Field(description="The product words only, exactly as written, no quantity")
    qty: int = Field(gt=0, description="The final quantity, after any later correction")
    unit: str | None = Field(default=None, description="The unit word written, e.g. box, pkt")


class ThreadReading(BaseModel):
    order_lines: list[OrderLine]
    enquiries: list[str] = Field(description="Questions about price, stock or other products")
    unclear: list[str] = Field(description="Requests that need the customer to explain")


_READ_SYSTEM = """You read WhatsApp messages sent to Sharma Traders, an electrical and hardware \
distributor in Pune. Customers write in English, Hindi or Hinglish. You get ONE customer's \
messages, with the shop's replies for context. Return JSON with:

- order_lines: what the customer wants delivered. One line per product, with the FINAL \
quantity: a later message like "1.5 wala 20 nahi 15 karo" changes that product's 20 to 15. \
"product" is only the product words, copied as written, without the quantity or unit. Sizes \
and ratings are part of the product, never the quantity or unit: "3m" (3 module), "1 inch", \
"6a", "16 amp", "2.5", "rccb 40", "changeover 63". In "isolator 63 - 2" the quantity is 2. Do \
not translate, correct or rename products. "unit" is the unit word if one was written (box, pkt, \
coil, nos, pcs, kg, length), else null.
- enquiries: questions about prices, a rate list, stock, or products the shop may not sell, \
copied as written.
- unclear: requests that can't be understood without asking the customer, for example \
"ye wala" (this one) right after a [photo].

Ignore greetings, thanks and talk about payments. A thread with no order gets an empty \
order_lines list. Never invent products or quantities."""

_EXAMPLE_THREAD = """[21 Sep 10:00] Customer: Namaste, 5 coil 4mm wire aur 12 nos 6a mcb bhejna
[21 Sep 10:02] Customer: mcb 12 nahi 18 karo
[21 Sep 10:03] Customer: [photo]
[21 Sep 10:03] Customer: ye wala switch bhi 10
[21 Sep 10:05] Customer: LED panel ka rate bhejo
[21 Sep 10:06] Customer: isolator 63 - 2, 8m plate 5"""

_EXAMPLE_READING = ThreadReading(
    order_lines=[
        OrderLine(product="4mm wire", qty=5, unit="coil"),
        OrderLine(product="6a mcb", qty=18, unit="nos"),
        OrderLine(product="isolator 63", qty=2),
        OrderLine(product="8m plate", qty=5),
    ],
    enquiries=["LED panel ka rate bhejo"],
    unclear=["ye wala switch bhi 10 (refers to a photo)"],
)


def read_thread_messages(transcript: str) -> list[Message]:
    """The conversation sent to the model: instructions, one worked example, the thread."""
    return [
        {"role": "system", "content": _READ_SYSTEM},
        {"role": "user", "content": _EXAMPLE_THREAD},
        {"role": "assistant", "content": _EXAMPLE_READING.model_dump_json()},
        {"role": "user", "content": transcript},
    ]


# 2. Picking products the code couldn't match ----------------------------------------------


class ProductPick(BaseModel):
    written: str = Field(description="The product words exactly as given")
    sku: str | None = Field(description="The one catalogue SKU meant, or null if none fits")
    sure: bool = Field(description="True only if this is clearly the product meant")


class ProductPicks(BaseModel):
    picks: list[ProductPick]


_PICK_SYSTEM = """You match product words written by a shop's customers to the shop's \
catalogue. For each written item, give the SKU of the ONE catalogue product it means. Use \
the names and aliases; customers abbreviate ("jn box" = junction box) and leave out sizes. \
If no product fits, or the words could mean two different products, give sku null or set \
sure to false. Never pick a product just because it is similar."""


def pick_products_messages(
    written: Iterable[str], catalogue: Iterable[CatalogProduct]
) -> list[Message]:
    lines = "\n".join(
        f"{p.sku} | {p.name} | aliases: {', '.join(p.aliases) or '-'}" for p in catalogue
    )
    items = json.dumps(list(written), ensure_ascii=False)
    return [
        {"role": "system", "content": _PICK_SYSTEM},
        {"role": "user", "content": f"Catalogue:\n{lines}\n\nWritten items: {items}"},
    ]
