import re
from collections import Counter
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from app.api.deps import SessionDep, SettingsDep, TodayDep
from app.api.errors import ApiError
from app.api.schemas import PoNoteOut, StockUploadOut, UploadOut
from app.db.audit import OWNER
from app.intake.stock_import import import_stock_register

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post(
    "/stock",
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"description": "The file is over the size limit"},
        415: {"description": "Not an .xlsx file"},
        422: {"description": "Empty, unreadable, or no header row (recorded as a failed upload)"},
    },
)
async def upload_stock_register(
    file: Annotated[UploadFile, File(description="The stock register, as an Excel .xlsx file")],
    session: SessionDep,
    settings: SettingsDep,
    today: TodayDep,
) -> StockUploadOut:
    """Upload the godown stock register. Clean counts are saved; every problem becomes an issue."""
    filename = _plain_name(file.filename)
    if not filename.lower().endswith(".xlsx"):
        raise ApiError(
            415, "unsupported_file_type", "Upload the stock register as an Excel .xlsx file."
        )
    limit = settings.max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if not content:
        raise ApiError(422, "empty_file", "The uploaded file is empty.")
    if len(content) > limit:
        raise ApiError(
            413, "file_too_large", f"The file is larger than the {settings.max_upload_mb} MB limit."
        )

    imported = await import_stock_register(
        session, filename=filename, content=content, today=today, actor=OWNER
    )
    issues = imported.result.issues
    return StockUploadOut(
        upload=UploadOut.model_validate(imported.upload),
        issues_by_severity={
            level: sum(1 for issue in issues if issue.severity == level)
            for level in ("error", "warning", "info")
        },
        issues_by_type=dict(Counter(issue.issue_type.value for issue in issues)),
        po_notes=[PoNoteOut(**asdict(note)) for note in imported.result.po_notes],
    )


def _plain_name(filename: str | None) -> str:
    """Just the file name: some browsers send a whole path such as C:\\fakepath\\stock.xlsx."""
    return re.split(r"[\\/]", filename or "")[-1].strip()
