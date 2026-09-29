"""The HTTP API end to end: FastAPI + the stock register importer + a real Postgres."""

from io import BytesIO
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Issue, OpenPoNote, StockLevel, Upload

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload_form(filename: str, content: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"file": (filename, content, XLSX_TYPE)}


def workbook(*rows: list[Any]) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def register(sample_data_dir: Path) -> bytes:
    return (sample_data_dir / "stock_register.xlsx").read_bytes()


async def test_health_reports_the_database_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


# --- POST /uploads/stock ---


@pytest.mark.usefixtures("seeded")
async def test_upload_saves_counts_notes_issues_and_an_audit_row(
    client: AsyncClient, db_session: AsyncSession, register: bytes
) -> None:
    response = await client.post(
        "/uploads/stock",
        files=upload_form("stock_register.xlsx", register),
        headers={"X-Request-ID": "upload-test-1"},
    )

    assert response.status_code == 201
    upload_id = response.json()["upload"]["id"]
    assert await count(db_session, StockLevel) == 59
    assert await count(db_session, OpenPoNote) == 1
    assert await count(db_session, Issue) == 16
    audit = (await db_session.scalars(select(AuditLog))).one()
    assert (audit.actor, audit.action, audit.entity_type, audit.entity_id) == (
        "owner",
        "upload.stock_register",
        "upload",
        str(upload_id),
    )
    assert audit.request_id == "upload-test-1"  # the audit row links to the request's logs
    assert audit.after is not None
    assert audit.after["rows_loaded"] == 59


@pytest.mark.usefixtures("seeded")
async def test_upload_response_summarises_the_result(client: AsyncClient, register: bytes) -> None:
    body = (
        await client.post("/uploads/stock", files=upload_form("stock_register.xlsx", register))
    ).json()

    upload = body["upload"]
    assert (upload["status"], upload["filename"], upload["as_of"]) == (
        "processed",
        "stock_register.xlsx",
        "2026-09-24",
    )
    assert (upload["rows_read"], upload["rows_loaded"], upload["error"]) == (62, 59, None)
    assert body["issues_by_severity"] == {"error": 2, "warning": 4, "info": 10}
    assert body["issues_by_type"]["skipped_row"] == 4
    assert body["po_notes"] == [
        {
            "sku": "ST-0021",
            "supplier_code": "SUP03",
            "qty": 40,
            "ordered_on": "2026-09-22",
            "note": "40 pcs ordered from Brightline on 22/9",
            "source_row": 55,
        }
    ]


@pytest.mark.usefixtures("seeded")
async def test_a_workbook_without_a_header_is_recorded_as_failed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client.post(
        "/uploads/stock", files=upload_form("notes.xlsx", workbook(["just some notes"]))
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "header_not_found"
    upload = await db_session.get(Upload, error["details"]["upload_id"])
    assert upload is not None
    assert (upload.status, upload.filename) == ("failed", "notes.xlsx")
    assert await count(db_session, StockLevel) == 0
    assert await count(db_session, AuditLog) == 1


@pytest.mark.parametrize(
    ("filename", "content", "status", "code"),
    [
        ("stock.csv", b"Item,Qty\nWidget,5\n", 415, "unsupported_file_type"),
        ("stock_register.xlsx", b"", 422, "empty_file"),
    ],
)
async def test_wrong_or_empty_files_are_refused_without_a_record(
    client: AsyncClient,
    db_session: AsyncSession,
    filename: str,
    content: bytes,
    status: int,
    code: str,
) -> None:
    response = await client.post("/uploads/stock", files=upload_form(filename, content))

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert await count(db_session, Upload) == 0


async def test_a_file_over_the_size_limit_is_refused(client: AsyncClient) -> None:
    from app.config import get_settings
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"max_upload_mb": 0}
    )

    response = await client.post("/uploads/stock", files=upload_form("big.xlsx", b"PK\x03\x04"))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


# --- GET /products ---


@pytest.mark.usefixtures("seeded")
async def test_products_before_any_upload_have_no_stock(client: AsyncClient) -> None:
    body = (await client.get("/products")).json()

    assert (body["stock_upload_id"], body["as_of"]) == (None, None)
    assert len(body["items"]) == 60
    assert all(item["qty_on_hand"] is None for item in body["items"])


@pytest.mark.usefixtures("seeded")
async def test_products_show_the_current_count(client: AsyncClient, register: bytes) -> None:
    upload = (
        await client.post("/uploads/stock", files=upload_form("stock_register.xlsx", register))
    ).json()

    body = (await client.get("/products")).json()

    assert (body["stock_upload_id"], body["as_of"]) == (upload["upload"]["id"], "2026-09-24")
    items = {item["sku"]: item for item in body["items"]}
    assert len(items) == 60
    assert sum(item["qty_on_hand"] is not None for item in items.values()) == 59
    assert items["ST-0036"]["qty_on_hand"] == 164  # the recount row wins
    assert items["ST-0040"]["qty_on_hand"] is None  # -4 wasn't loaded: needs a recount
    assert items["ST-0040"]["open_issue_count"] == 1
    assert items["ST-0021"]["on_order_qty"] == 40
    assert items["ST-0047"]["remarks"] == "finished!! order urgent"
    assert items["ST-0001"]["cost_price"] == "1150.00"  # money as exact text
    assert items["ST-0014"]["supplier"] == {"code": "SUP02", "name": "Volta Switchgear"}


@pytest.mark.usefixtures("seeded")
async def test_the_newest_count_becomes_current(client: AsyncClient, register: bytes) -> None:
    form = upload_form("stock_register.xlsx", register)
    first = (await client.post("/uploads/stock", files=form)).json()["upload"]["id"]
    second = (await client.post("/uploads/stock", files=form)).json()["upload"]["id"]

    body = (await client.get("/products")).json()

    assert second > first
    assert body["stock_upload_id"] == second


# --- GET /issues ---


@pytest.mark.usefixtures("seeded")
async def test_issues_list_the_latest_upload_in_file_order(
    client: AsyncClient, register: bytes
) -> None:
    await client.post("/uploads/stock", files=upload_form("stock_register.xlsx", register))

    body = (await client.get("/issues")).json()

    assert body["upload"]["filename"] == "stock_register.xlsx"
    rows = [issue["source_row"] for issue in body["items"]]
    assert len(rows) == 16
    assert rows[:3] == [1, 2, 5]
    negative = next(i for i in body["items"] if i["issue_type"] == "negative_qty")
    assert {key: negative[key] for key in ("source_row", "severity", "sku", "product_name")} == {
        "source_row": 63,
        "severity": "error",
        "sku": "ST-0040",
        "product_name": "Bell Push Modular",
    }
    assert negative["raw"]["Qty In Stock"] == -4
    assert negative["resolved"] is False


async def test_issues_before_any_upload_are_empty(client: AsyncClient) -> None:
    assert (await client.get("/issues")).json() == {"upload": None, "items": []}


async def test_issues_for_an_unknown_upload_is_a_404(client: AsyncClient) -> None:
    response = await client.get("/issues", params={"upload_id": 999})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "upload_not_found"
