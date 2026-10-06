"""WhatsApp chat -> customer orders, enquiries and issues.

Who does what:
- code (intake/whatsapp.py) splits the export into messages and one thread per customer;
- the model reads each thread: what was ordered as written, with corrections applied,
  plus enquiries and anything unclear (app/llm/whatsapp.py);
- code matches each product: exact name or alias, then the same words in another order;
- only for what's left does the model pick from the catalogue, and code checks every SKU it
  returns. A pick the model isn't sure of, or no pick, is NOT guessed: the line stays in the
  order without a product and is reported for a human to fix.

The model is passed in (`ask`), so tests use a fake one and the app uses the real one.
"""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from app.domain.catalog import Catalog
from app.domain.matching import match_product_by_words, normalise_name
from app.domain.units import normalise_unit
from app.intake.issues import IssueRecord, IssueType
from app.intake.whatsapp import Chat, Thread
from app.llm.client import LlmError, complete_structured
from app.llm.whatsapp import (
    Message,
    ProductPicks,
    ThreadReading,
    pick_products_messages,
    read_thread_messages,
)

logger = logging.getLogger(__name__)

MatchedOn = Literal["name", "alias", "same words", "model"]


class Ask(Protocol):
    """Send messages to the model and get back an instance of `schema`."""

    async def __call__[T: BaseModel](
        self, messages: list[Message], schema: type[T], purpose: str
    ) -> T: ...


async def ask_llm[T: BaseModel](messages: list[Message], schema: type[T], purpose: str) -> T:
    """The real model, through app/llm."""
    return (await complete_structured(messages, schema, purpose=purpose)).value


@dataclass(frozen=True)
class ParsedLine:
    written: str  # the product words as the customer wrote them
    qty: int
    unit_written: str | None
    sku: str | None  # None = not matched; a human must choose the product
    matched_on: MatchedOn | None


@dataclass(frozen=True)
class ParsedOrder:
    sender: str
    customer_code: str | None  # None = the sender isn't a known customer
    lines: tuple[ParsedLine, ...]
    unclear: tuple[str, ...]  # requests to ask the customer about (policy 3.2)
    first_sent_at: datetime
    source_lines: tuple[int, ...]  # line numbers of the customer's messages in the export

    @property
    def needs_review(self) -> bool:
        return (
            self.customer_code is None
            or bool(self.unclear)
            or any(line.sku is None for line in self.lines)
        )


@dataclass(frozen=True)
class Enquiry:
    sender: str
    customer_code: str | None
    text: str
    source_line: int


@dataclass
class OrdersReading:
    orders: list[ParsedOrder] = field(default_factory=list)
    enquiries: list[Enquiry] = field(default_factory=list)
    no_order: list[str] = field(default_factory=list)  # senders whose thread had no order
    issues: list[IssueRecord] = field(default_factory=list)
    model_calls: int = 0
    seconds: float = 0.0


async def read_whatsapp_orders(
    chat: Chat, catalog: Catalog, customers: Mapping[str, str], ask: Ask = ask_llm
) -> OrdersReading:
    """`customers` maps party code -> shop name; senders are matched to it exactly."""
    started = time.perf_counter()
    reading = OrdersReading()
    codes_by_name = {normalise_name(name): code for code, name in customers.items()}
    for thread in chat.threads:
        await _read_thread(thread, catalog, codes_by_name, ask, reading)
    reading.seconds = time.perf_counter() - started
    logger.info(
        "whatsapp orders read",
        extra={
            "threads": len(chat.threads),
            "orders": len(reading.orders),
            "model_calls": reading.model_calls,
        },
    )
    return reading


async def _read_thread(
    thread: Thread,
    catalog: Catalog,
    codes_by_name: Mapping[str, str],
    ask: Ask,
    reading: OrdersReading,
) -> None:
    own = [m for m in thread.messages if not m.from_shop]
    first_line = own[0].line
    raw = {"sender": thread.sender, "lines": [m.line for m in own]}
    code = codes_by_name.get(normalise_name(thread.sender))
    if code is None:
        reading.issues.append(
            IssueRecord(
                IssueType.UNKNOWN_CUSTOMER,
                f"'{thread.sender}' is not a known customer, so their messages were read but "
                "nothing was linked to a customer. Add them to the customers file.",
                first_line,
                raw=raw,
            )
        )
    try:
        reading.model_calls += 1
        result = await ask(
            read_thread_messages(thread.transcript()), ThreadReading, "whatsapp_read"
        )
    except LlmError as error:
        reading.issues.append(
            IssueRecord(
                IssueType.THREAD_NOT_READ,
                f"The language model couldn't read {thread.sender}'s messages ({error.message}). "
                "Read them yourself; nothing was created from them.",
                first_line,
                raw=raw,
                customer_code=code,
            )
        )
        return

    for text in result.enquiries:
        reading.enquiries.append(Enquiry(thread.sender, code, text, first_line))
    if not result.order_lines and not result.unclear:
        reading.no_order.append(thread.sender)
        return

    lines = await _match_lines(result, catalog, ask, reading, first_line, raw, code)
    for request in result.unclear:
        reading.issues.append(
            IssueRecord(
                IssueType.NEEDS_CLARIFICATION,
                f"Ask {thread.sender}: '{request}' can't be read without them (policy 3.2: "
                "don't guess).",
                first_line,
                raw=raw,
                customer_code=code,
            )
        )
    reading.orders.append(
        ParsedOrder(
            sender=thread.sender,
            customer_code=code,
            lines=tuple(lines),
            unclear=tuple(result.unclear),
            first_sent_at=own[0].sent_at,
            source_lines=tuple(m.line for m in own),
        )
    )


async def _match_lines(
    result: ThreadReading,
    catalog: Catalog,
    ask: Ask,
    reading: OrdersReading,
    first_line: int,
    raw: dict[str, object],
    code: str | None,
) -> list[ParsedLine]:
    matched: dict[str, tuple[str, MatchedOn]] = {}
    # The words to look up: without a quantity the model copied in ("regulator 10" -> "regulator").
    lookup = {
        line.product: _without_qty(line.product, line.qty) or line.product
        for line in result.order_lines
    }
    for written, words_ in lookup.items():
        match = match_product_by_words(written, catalog) or match_product_by_words(words_, catalog)
        if match is not None:
            matched[written] = (match.sku, match.matched_on)
    leftovers = {lookup[w]: w for w in lookup if w not in matched}  # looked-up words -> written
    if leftovers:
        picks = await _pick(list(leftovers), catalog, ask, reading)
        for looked_up, sku in picks.items():
            written = leftovers[looked_up]
            matched[written] = (sku, "model")
            product = catalog.products[sku]
            reading.issues.append(
                IssueRecord(
                    IssueType.PRODUCT_MATCHED_BY_LLM,
                    f"'{written}' was matched to {sku} '{product.name}' by the language model; "
                    "check it when confirming the order.",
                    first_line,
                    sku,
                    raw=raw,
                    customer_code=code,
                )
            )

    lines = []
    for line in result.order_lines:
        sku, how = matched.get(line.product, (None, None))
        if sku is None:
            reading.issues.append(
                IssueRecord(
                    IssueType.UNMATCHED_PRODUCT,
                    f"'{line.product}' (qty {line.qty}) matches no product for sure, so it was "
                    "not guessed. Choose the product, or log it as an enquiry if we don't "
                    "stock it.",
                    first_line,
                    raw=raw,
                    customer_code=code,
                )
            )
        elif (
            line.unit and (unit := normalise_unit(line.unit)) and unit != catalog.products[sku].unit
        ):
            product = catalog.products[sku]
            reading.issues.append(
                IssueRecord(
                    IssueType.UNIT_WRITTEN_DIFFERENTLY,
                    f"'{line.qty} {line.unit} {line.product}' is counted as {line.qty} "
                    f"{product.unit}(s) of {sku}; check it when confirming.",
                    first_line,
                    sku,
                    raw=raw,
                    customer_code=code,
                )
            )
        lines.append(ParsedLine(line.product, line.qty, line.unit, sku, how))
    return lines


async def _pick(
    written: list[str], catalog: Catalog, ask: Ask, reading: OrdersReading
) -> dict[str, str]:
    """SKUs the model is sure of, checked against the catalogue. Anything else is left out."""
    try:
        reading.model_calls += 1
        picks = await ask(
            pick_products_messages(written, catalog.products.values()),
            ProductPicks,
            "whatsapp_match",
        )
    except LlmError:
        return {}  # every leftover becomes an "unmatched product" issue instead
    wanted = set(written)
    return {
        pick.written: pick.sku
        for pick in picks.picks
        if pick.sure and pick.sku in catalog.products and pick.written in wanted
    }


def _without_qty(written: str, qty: int) -> str | None:
    """The product words without the quantity, when the model copied it in: "regulator 10"
    with qty 10 -> "regulator". Only that exact number at the start or end is removed, so
    a size like "rccb 40" (qty 2) is left alone."""
    tokens = written.split()
    if len(tokens) < 2:
        return None
    if tokens[-1] == str(qty):
        return " ".join(tokens[:-1])
    if tokens[0] == str(qty):
        return " ".join(tokens[1:])
    return None
