from typing import Annotated, cast

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.api.schemas import IssueOut, IssuesOut, Severity, UploadOut
from app.db.queries import get_upload, issues_for_upload, latest_upload

router = APIRouter(tags=["issues"])


@router.get("/issues")
async def list_issues(
    session: SessionDep,
    upload_id: Annotated[int | None, Query(ge=1, description="Default: the latest upload")] = None,
) -> IssuesOut:
    """Every issue found in one upload, in file order."""
    if upload_id is None:
        upload = await latest_upload(session)
    else:
        upload = await get_upload(session, upload_id)
        if upload is None:
            raise ApiError(404, "upload_not_found", f"There is no upload with id {upload_id}.")
    if upload is None:
        return IssuesOut(upload=None, items=[])

    rows = await issues_for_upload(session, upload.id)
    return IssuesOut(
        upload=UploadOut.model_validate(upload),
        items=[
            IssueOut(
                id=row.issue.id,
                source_file=row.issue.source_file,
                source_row=row.issue.source_row,
                issue_type=row.issue.issue_type,
                severity=cast(Severity, row.issue.severity),  # the DB allows only these three
                detail=row.issue.detail,
                sku=row.sku,
                product_name=row.product_name,
                raw=row.issue.raw,
                resolved=row.issue.resolved,
            )
            for row in rows
        ],
    )
