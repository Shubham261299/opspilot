"""Customers and outstanding dues, end to end: upload -> Postgres -> GET endpoints."""

from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Customer, CustomerBill, SalesLine, Upload
from tests.integration.test_api import count, upload_form, workbook


@pytest.fixture
def customers_file(sample_data_dir: Path) -> bytes:
    return (sample_data_dir / "customers.xlsx").read_bytes()


@pytest.fixture
def dues_file(sample_data_dir: Path) -> bytes:
    return (sample_data_dir / "outstanding_dues.xlsx").read_bytes()


async def test_customers_upload_adds_25_customers(
    client: AsyncClient, db_session: AsyncSession, customers_file: bytes
) -> None:
    response = await client.post("/uploads/customers", files=upload_form("c.xlsx", customers_file))

    assert response.status_code == 201
    body = response.json()
    assert (body["upload"]["kind"], body["upload"]["rows_loaded"]) == ("customers", 25)
    assert len(body["added"]) == 25 and body["updated"] == []
    assert body["issues_by_type"] == {"duplicate_customer": 1, "phones_normalised": 1}
    assert await count(db_session, Customer) == 25


async def test_uploading_customers_again_updates_details_but_never_the_hold(
    client: AsyncClient, db_session: AsyncSession, customers_file: bytes
) -> None:
    await client.post("/uploads/customers", files=upload_form("c.xlsx", customers_file))
    customer = await db_session.scalar(select(Customer).where(Customer.code == "CUS001"))
    assert customer is not None
    customer.on_hold, customer.hold_reason = True, "approved hold"
    await db_session.commit()

    header = ["Party Code", "Shop Name", "Mobile", "Credit Limit", "Credit Days"]
    changed = ["CUS001", "Ramesh Electricals", "9895822412", 60000, 15]
    response = await client.post(
        "/uploads/customers", files=upload_form("c2.xlsx", workbook(header, changed))
    )

    assert response.json()["updated"] == ["CUS001"]
    await db_session.refresh(customer)
    assert (customer.credit_limit, customer.on_hold) == (Decimal(60000), True)
    audit = await db_session.scalar(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
    assert audit is not None and audit.after is not None
    assert audit.after["updated"]["CUS001"]["credit_limit"] == ["50000.00", "60000"]


async def test_dues_need_the_customers_first(
    client: AsyncClient, db_session: AsyncSession, dues_file: bytes
) -> None:
    response = await client.post("/uploads/dues", files=upload_form("d.xlsx", dues_file))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_customers"
    upload = await db_session.scalar(select(Upload))
    assert upload is not None and (upload.kind, upload.status) == ("outstanding_dues", "failed")


async def test_dues_upload_saves_bills_and_customers_show_balances(
    client: AsyncClient, db_session: AsyncSession, customers_file: bytes, dues_file: bytes
) -> None:
    await client.post("/uploads/customers", files=upload_form("c.xlsx", customers_file))

    response = await client.post("/uploads/dues", files=upload_form("d.xlsx", dues_file))

    assert response.status_code == 201
    body = response.json()
    assert (body["bills_loaded"], body["total_balance"]) == (55, "1134000.00")
    assert body["issues_by_severity"] == {"error": 0, "warning": 0, "info": 3}
    assert await count(db_session, CustomerBill) == 55

    customers = (await client.get("/customers")).json()
    assert customers["dues_upload_id"] == body["upload"]["id"]
    om_sai = next(c for c in customers["items"] if c["code"] == "CUS003")
    assert (om_sai["balance"], om_sai["open_bills"], om_sai["oldest_bill_date"]) == (
        "102500.00",
        4,
        "2026-07-24",
    )
    assert om_sai["phone"] == "+919828728463"


async def test_issues_name_the_customer_they_concern(
    client: AsyncClient, customers_file: bytes
) -> None:
    upload = (
        await client.post("/uploads/customers", files=upload_form("c.xlsx", customers_file))
    ).json()["upload"]

    issues = (await client.get("/issues", params={"upload_id": upload["id"]})).json()["items"]

    duplicate = next(i for i in issues if i["issue_type"] == "duplicate_customer")
    assert (duplicate["customer_code"], duplicate["customer_name"], duplicate["sku"]) == (
        "CUS001",
        "Ramesh Electricals",
        None,
    )


async def test_uploads_are_listed_newest_first(
    client: AsyncClient, customers_file: bytes, dues_file: bytes
) -> None:
    await client.post("/uploads/customers", files=upload_form("c.xlsx", customers_file))
    await client.post("/uploads/dues", files=upload_form("d.xlsx", dues_file))

    items = (await client.get("/uploads")).json()["items"]

    assert [u["kind"] for u in items] == ["outstanding_dues", "customers"]


async def test_customer_upload_refuses_other_file_types(client: AsyncClient) -> None:
    response = await client.post("/uploads/customers", files=upload_form("c.csv", b"a,b"))
    assert response.status_code == 415


@pytest.mark.usefixtures("seeded")
async def test_sales_upload_loads_the_90_day_export(
    client: AsyncClient, db_session: AsyncSession, customers_file: bytes, sample_data_dir: Path
) -> None:
    await client.post("/uploads/customers", files=upload_form("c.xlsx", customers_file))
    sales = (sample_data_dir / "sales_history_90d.csv").read_bytes()

    response = await client.post(
        "/uploads/sales", files={"file": ("sales_history_90d.csv", sales, "text/csv")}
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["lines_loaded"], body["last_sale"], body["upload"]["as_of"]) == (
        8331,
        "2026-09-24",
        "2026-09-24",
    )
    assert await count(db_session, SalesLine) == 8331


async def test_sales_upload_refuses_excel_files(client: AsyncClient) -> None:
    response = await client.post("/uploads/sales", files=upload_form("s.xlsx", b"x"))
    assert response.status_code == 415
