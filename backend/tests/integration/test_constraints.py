"""Rules the database enforces on its own, whatever the application code does."""

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Customer, Product, Proposal, Upload


async def _product_id(session: AsyncSession, sku: str) -> int:
    product_id = await session.scalar(select(Product.id).where(Product.sku == sku))
    assert product_id is not None
    return product_id


async def _customer_id(session: AsyncSession) -> int:
    customer = Customer(
        code="CUS001", shop_name="Ramesh Electricals", credit_limit=Decimal(50000), credit_days=15
    )
    session.add(customer)
    await session.flush()
    return customer.id


def _proposal(**fields: Any) -> Proposal:
    return Proposal(numbers={}, basis={}, reason="test", **fields)


async def _expect_rejected(session: AsyncSession, row: object) -> None:
    session.add(row)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_only_one_pending_proposal_per_product_and_kind(
    db_session: AsyncSession, seeded: None
) -> None:
    product_id = await _product_id(db_session, "ST-0002")
    db_session.add(_proposal(kind="reorder", product_id=product_id))
    await db_session.flush()

    await _expect_rejected(db_session, _proposal(kind="reorder", product_id=product_id))


async def test_decided_proposals_dont_block_a_new_pending_one(
    db_session: AsyncSession, seeded: None
) -> None:
    product_id = await _product_id(db_session, "ST-0002")
    db_session.add_all(
        [
            _proposal(kind="reorder", product_id=product_id, status="rejected"),
            _proposal(kind="reorder", product_id=product_id, status="superseded"),
            _proposal(kind="reorder", product_id=product_id),
        ]
    )
    await db_session.flush()  # no error


async def test_only_one_pending_proposal_per_customer_and_kind(
    db_session: AsyncSession, seeded: None
) -> None:
    customer_id = await _customer_id(db_session)
    db_session.add_all(
        [
            _proposal(kind="payment_reminder", customer_id=customer_id),
            _proposal(kind="hold_orders", customer_id=customer_id),  # a different kind is fine
        ]
    )
    await db_session.flush()

    await _expect_rejected(db_session, _proposal(kind="hold_orders", customer_id=customer_id))


async def test_a_proposal_is_about_exactly_one_product_or_customer(
    db_session: AsyncSession, seeded: None
) -> None:
    product_id = await _product_id(db_session, "ST-0002")
    customer_id = await _customer_id(db_session)
    await db_session.commit()

    await _expect_rejected(db_session, _proposal(kind="reorder"))
    await _expect_rejected(
        db_session, _proposal(kind="reorder", product_id=product_id, customer_id=customer_id)
    )


@pytest.mark.parametrize(
    "fields",
    [{"kind": "launch_rocket"}, {"status": "done"}],
    ids=["unknown kind", "unknown status"],
)
async def test_unknown_proposal_kind_or_status_is_rejected(
    db_session: AsyncSession, seeded: None, fields: dict[str, str]
) -> None:
    product_id = await _product_id(db_session, "ST-0002")
    await _expect_rejected(
        db_session, _proposal(**({"kind": "reorder", "product_id": product_id} | fields))
    )


async def test_unknown_upload_kind_is_rejected(db_session: AsyncSession) -> None:
    await _expect_rejected(db_session, Upload(kind="photos", filename="x.jpg", status="processed"))
