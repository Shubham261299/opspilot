"""The WhatsApp order reader with a fake model: what code does with the model's answers."""

from typing import Any

import pytest
from pydantic import BaseModel

from app.domain.catalog import Catalog
from app.domain.matching import match_product_by_words, words
from app.intake.issues import IssueType
from app.intake.whatsapp import parse_chat
from app.intake.whatsapp_orders import read_whatsapp_orders
from app.llm.client import LlmError
from app.llm.whatsapp import OrderLine, ProductPick, ProductPicks, ThreadReading

CUSTOMERS = {"CUS001": "Ramesh Electricals", "CUS003": "Om Sai Hardware"}


class FakeModel:
    """Returns the prepared answer for each purpose in turn, and records what was asked."""

    def __init__(self, **answers: list[BaseModel | Exception]) -> None:
        self.answers = answers
        self.asked: list[tuple[str, list[dict[str, str]]]] = []

    async def __call__(
        self, messages: list[dict[str, str]], schema: type[Any], purpose: str
    ) -> Any:
        self.asked.append((purpose, messages))
        answer = self.answers[purpose].pop(0)
        if isinstance(answer, Exception):
            raise answer
        assert isinstance(answer, schema)
        return answer


def chat(*lines: str) -> Any:
    return parse_chat("\n".join(lines), "Sharma Traders")


RAMESH = chat(
    "22/09/26, 9:13 am - Ramesh Electricals: 20 box 1.5mm wire, 10 pkt gitti aur 3 jn box",
    "22/09/26, 4:48 pm - Ramesh Electricals: 1.5 wala 20 nahi 15 karo",
)


@pytest.mark.parametrize(
    ("written", "sku", "how"),
    [
        ("gitti", "ST-0051", "alias"),
        ("FR PVC Wire 1.5 sqmm 90m", "ST-0002", "name"),
        ("plate 3m", "ST-0041", "same words"),
        ("MCB 16 amp", "ST-0010", "same words"),
        ("clip", "ST-0052", "same words"),  # alias "clips"
    ],
)
def test_products_are_matched_exactly_or_by_the_same_words(
    catalog: Catalog, written: str, sku: str, how: str
) -> None:
    match = match_product_by_words(written, catalog)
    assert match is not None and (match.sku, match.matched_on) == (sku, how)


@pytest.mark.parametrize("written", ["panel", "jn box", "wire", ""])
def test_vague_words_are_not_matched_by_code(catalog: Catalog, written: str) -> None:
    assert match_product_by_words(written, catalog) is None


def test_words_ignore_order_case_spacing_and_plurals() -> None:
    assert words("Flood 50W") == words("50w flood") == {"flood", "50", "w"}
    assert words("cable clips") == words("Cable Clip")


async def test_an_order_with_exact_and_model_matched_products(catalog: Catalog) -> None:
    model = FakeModel(
        whatsapp_read=[
            ThreadReading(
                order_lines=[
                    OrderLine(product="1.5mm wire", qty=15, unit="box"),
                    OrderLine(product="gitti", qty=10, unit="pkt"),
                    OrderLine(product="jn box", qty=3),
                ],
                enquiries=[],
                unclear=[],
            )
        ],
        whatsapp_match=[
            ProductPicks(picks=[ProductPick(written="jn box", sku="ST-0029", sure=True)])
        ],
    )

    reading = await read_whatsapp_orders(RAMESH, catalog, CUSTOMERS, model)

    [order] = reading.orders
    assert order.customer_code == "CUS001" and not order.needs_review
    assert [(line.sku, line.qty, line.matched_on) for line in order.lines] == [
        ("ST-0002", 15, "alias"),
        ("ST-0051", 10, "alias"),
        ("ST-0029", 3, "model"),
    ]
    assert order.source_lines == (1, 2)
    # Only the leftover went to the model for matching.
    assert model.asked[1][1][-1]["content"].endswith('Written items: ["jn box"]')
    assert {i.issue_type for i in reading.issues} == {
        IssueType.PRODUCT_MATCHED_BY_LLM,  # jn box: shown for checking
        IssueType.UNIT_WRITTEN_DIFFERENTLY,  # "15 box" of wire, counted as coils
    }


@pytest.mark.parametrize(
    "pick",
    [
        ProductPick(written="jn box", sku="ST-0029", sure=False),  # not sure
        ProductPick(written="jn box", sku=None, sure=True),  # nothing fits
        ProductPick(written="jn box", sku="ST-9999", sure=True),  # an SKU that doesn't exist
        ProductPick(written="something else", sku="ST-0029", sure=True),  # not what was asked
    ],
)
async def test_a_doubtful_model_pick_is_never_used(catalog: Catalog, pick: ProductPick) -> None:
    model = FakeModel(
        whatsapp_read=[
            ThreadReading(
                order_lines=[OrderLine(product="jn box", qty=3)], enquiries=[], unclear=[]
            )
        ],
        whatsapp_match=[ProductPicks(picks=[pick])],
    )
    [order] = (await read_whatsapp_orders(RAMESH, catalog, CUSTOMERS, model)).orders
    assert order.lines[0].sku is None and order.needs_review


async def test_enquiries_and_unclear_requests(catalog: Catalog) -> None:
    model = FakeModel(
        whatsapp_read=[
            ThreadReading(
                order_lines=[OrderLine(product="gitti", qty=10)],
                enquiries=["do you have smart wifi bulbs?"],
                unclear=["ye wala panel bhi 20 (refers to a photo)"],
            )
        ]
    )
    reading = await read_whatsapp_orders(RAMESH, catalog, CUSTOMERS, model)
    assert [e.text for e in reading.enquiries] == ["do you have smart wifi bulbs?"]
    assert reading.orders[0].needs_review
    assert [i.issue_type for i in reading.issues] == [IssueType.NEEDS_CLARIFICATION]


async def test_a_thread_without_an_order(catalog: Catalog) -> None:
    model = FakeModel(
        whatsapp_read=[ThreadReading(order_lines=[], enquiries=["rate list?"], unclear=[])]
    )
    reading = await read_whatsapp_orders(RAMESH, catalog, CUSTOMERS, model)
    assert (reading.orders, reading.no_order) == ([], ["Ramesh Electricals"])


async def test_an_unknown_sender_is_reported_and_the_order_needs_review(catalog: Catalog) -> None:
    stranger = chat("22/09/26, 9:13 am - Sunrise Electric: gitti 10")
    model = FakeModel(
        whatsapp_read=[
            ThreadReading(
                order_lines=[OrderLine(product="gitti", qty=10)], enquiries=[], unclear=[]
            )
        ]
    )
    reading = await read_whatsapp_orders(stranger, catalog, CUSTOMERS, model)
    assert reading.orders[0].customer_code is None and reading.orders[0].needs_review
    assert reading.issues[0].issue_type == IssueType.UNKNOWN_CUSTOMER


async def test_when_the_model_fails_the_thread_is_reported_not_guessed(catalog: Catalog) -> None:
    model = FakeModel(whatsapp_read=[LlmError("unavailable", "Ollama is not running")])
    reading = await read_whatsapp_orders(RAMESH, catalog, CUSTOMERS, model)
    assert reading.orders == []
    [issue] = reading.issues
    assert (issue.issue_type, issue.customer_code) == (IssueType.THREAD_NOT_READ, "CUS001")


async def test_a_quantity_copied_into_the_product_words_is_removed(catalog: Catalog) -> None:
    model = FakeModel(
        whatsapp_read=[
            ThreadReading(
                order_lines=[
                    OrderLine(product="regulator 10", qty=10),  # the model copied the qty in
                    OrderLine(product="rccb 40", qty=2),  # 40 is the rating, not the qty
                ],
                enquiries=[],
                unclear=[],
            )
        ]
    )
    [order] = (await read_whatsapp_orders(RAMESH, catalog, CUSTOMERS, model)).orders
    assert [(line.sku, line.qty) for line in order.lines] == [("ST-0039", 10), ("ST-0012", 2)]


async def test_the_model_is_asked_about_the_words_without_the_copied_quantity(
    catalog: Catalog,
) -> None:
    model = FakeModel(
        whatsapp_read=[
            ThreadReading(
                order_lines=[OrderLine(product="bend 200", qty=200)], enquiries=[], unclear=[]
            )
        ],
        whatsapp_match=[
            ProductPicks(picks=[ProductPick(written="bend", sku="ST-0028", sure=True)])
        ],
    )
    [order] = (await read_whatsapp_orders(RAMESH, catalog, CUSTOMERS, model)).orders
    assert model.asked[1][1][-1]["content"].endswith('Written items: ["bend"]')
    assert (order.lines[0].written, order.lines[0].sku, order.lines[0].qty) == (
        "bend 200",
        "ST-0028",
        200,
    )
