from fastapi import APIRouter

from app.api.deps import SessionDep
from app.api.schemas import CustomerOut, CustomersOut
from app.db.queries import OUTSTANDING_DUES, current_upload, customers_with_dues

router = APIRouter(tags=["customers"])


@router.get("/customers")
async def list_customers(session: SessionDep) -> CustomersOut:
    """Every customer with credit terms, hold status and unpaid balance (current dues file)."""
    upload = await current_upload(session, OUTSTANDING_DUES)
    rows = await customers_with_dues(session, upload.id if upload else None)
    return CustomersOut(
        dues_upload_id=upload.id if upload else None,
        dues_as_of=upload.as_of if upload else None,
        items=[
            CustomerOut(
                code=row.customer.code,
                shop_name=row.customer.shop_name,
                contact_person=row.customer.contact_person,
                phone=row.customer.phone,
                area=row.customer.area,
                credit_limit=row.customer.credit_limit,
                credit_days=row.customer.credit_days,
                on_hold=row.customer.on_hold,
                hold_reason=row.customer.hold_reason,
                balance=row.balance,
                open_bills=row.open_bills,
                oldest_bill_date=row.oldest_bill_date,
            )
            for row in rows
        ],
    )
