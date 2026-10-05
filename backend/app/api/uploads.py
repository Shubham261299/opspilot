import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile, status

from app.api.deps import SessionDep, SettingsDep, TodayDep
from app.api.errors import ApiError
from app.api.schemas import (
    CustomersUploadOut,
    DuesUploadOut,
    PoNoteOut,
    SalesUploadOut,
    StockUploadOut,
    UploadOut,
    UploadsOut,
)
from app.config import Settings
from app.db.audit import OWNER
from app.db.queries import recent_uploads
from app.intake.customers_import import import_customers
from app.intake.dues_import import import_outstanding_dues
from app.intake.issues import IssueRecord
from app.intake.sales_import import import_sales_history
from app.intake.stock_import import import_stock_register

router = APIRouter(prefix="/uploads", tags=["uploads"])
PAISE = Decimal("0.01")

_XLSX_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"description": "The file is over the size limit"},
    415: {"description": "Not an .xlsx file"},
    422: {"description": "Empty, unreadable, or no header row (recorded as a failed upload)"},
}


@router.get("")
async def list_uploads(session: SessionDep) -> UploadsOut:
    """The most recent uploads of every kind, newest first."""
    return UploadsOut(items=[UploadOut.model_validate(u) for u in await recent_uploads(session)])


@router.post("/stock", status_code=status.HTTP_201_CREATED, responses=_XLSX_RESPONSES)
async def upload_stock_register(
    file: Annotated[UploadFile, File(description="The stock register, as an Excel .xlsx file")],
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
) -> StockUploadOut:
    """Upload the godown stock register. Clean counts are saved; every problem becomes an issue."""
    filename, content = await _read_xlsx(file, settings, "the stock register")
    imported = await import_stock_register(
        session, filename=filename, content=content, today=today, actor=OWNER
    )
    return StockUploadOut(
        upload=UploadOut.model_validate(imported.upload),
        **_issue_counts(imported.result.issues),
        po_notes=[PoNoteOut(**asdict(note)) for note in imported.result.po_notes],
    )


@router.post("/customers", status_code=status.HTTP_201_CREATED, responses=_XLSX_RESPONSES)
async def upload_customers(
    file: Annotated[UploadFile, File(description="The customers list, as an Excel .xlsx file")],
    session: SessionDep,
    settings: SettingsDep,
) -> CustomersUploadOut:
    """Upload the customer list. New codes are added; existing customers are updated."""
    filename, content = await _read_xlsx(file, settings, "the customers list")
    imported = await import_customers(session, filename=filename, content=content, actor=OWNER)
    return CustomersUploadOut(
        upload=UploadOut.model_validate(imported.upload),
        **_issue_counts(imported.result.issues),
        added=imported.added,
        updated=imported.updated,
    )


@router.post("/dues", status_code=status.HTTP_201_CREATED, responses=_XLSX_RESPONSES)
async def upload_outstanding_dues(
    file: Annotated[UploadFile, File(description="Unpaid customer bills, as an Excel .xlsx file")],
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
) -> DuesUploadOut:
    """Upload the outstanding dues sheet. Needs the customers file to be uploaded first."""
    filename, content = await _read_xlsx(file, settings, "the outstanding dues sheet")
    imported = await import_outstanding_dues(
        session, filename=filename, content=content, today=today, actor=OWNER
    )
    bills = imported.result.bills
    return DuesUploadOut(
        upload=UploadOut.model_validate(imported.upload),
        **_issue_counts(imported.result.issues),
        bills_loaded=len(bills),
        total_balance=sum((bill.balance for bill in bills), start=Decimal(0)).quantize(PAISE),
    )


@router.post(
    "/sales",
    status_code=status.HTTP_201_CREATED,
    responses={**_XLSX_RESPONSES, 415: {"description": "Not a .csv file"}},
)
async def upload_sales_history(
    file: Annotated[UploadFile, File(description="The 90-day sales export, as a .csv file")],
    session: SessionDep,
    settings: SettingsDep,
) -> SalesUploadOut:
    """Upload the sales history used for average daily sales. Needs the customers first."""
    filename, content = await _read_file(file, settings, "the sales history", ".csv", "a .csv file")
    imported = await import_sales_history(session, filename=filename, content=content, actor=OWNER)
    return SalesUploadOut(
        upload=UploadOut.model_validate(imported.upload),
        **_issue_counts(imported.result.issues),
        lines_loaded=len(imported.result.sales),
        last_sale=imported.result.last_sale,
    )


async def _read_xlsx(file: UploadFile, settings: Settings, what: str) -> tuple[str, bytes]:
    return await _read_file(file, settings, what, ".xlsx", "an Excel .xlsx file")


async def _read_file(
    file: UploadFile, settings: Settings, what: str, extension: str, described: str
) -> tuple[str, bytes]:
    """The file's name and bytes, after checking its type, that it isn't empty, and its size."""
    filename = _plain_name(file.filename)
    if not filename.lower().endswith(extension):
        raise ApiError(415, "unsupported_file_type", f"Upload {what} as {described}.")
    limit = settings.max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if not content:
        raise ApiError(422, "empty_file", "The uploaded file is empty.")
    if len(content) > limit:
        raise ApiError(
            413, "file_too_large", f"The file is larger than the {settings.max_upload_mb} MB limit."
        )
    return filename, content


def _issue_counts(issues: Iterable[IssueRecord]) -> dict[str, Any]:
    issues = list(issues)
    return {
        "issues_by_severity": {
            level: sum(1 for issue in issues if issue.severity == level)
            for level in ("error", "warning", "info")
        },
        "issues_by_type": dict(Counter(issue.issue_type.value for issue in issues)),
    }


def _plain_name(filename: str | None) -> str:
    """Just the file name: some browsers send a whole path such as C:\\fakepath\\stock.xlsx."""
    return re.split(r"[\\/]", filename or "")[-1].strip()
