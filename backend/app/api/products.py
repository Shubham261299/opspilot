from fastapi import APIRouter

from app.api.deps import SessionDep
from app.api.schemas import ProductOut, ProductsOut, SupplierOut
from app.db.queries import current_stock_upload, products_with_stock

router = APIRouter(tags=["products"])


@router.get("/products")
async def list_products(session: SessionDep) -> ProductsOut:
    """Every product with its current stock: the latest count, quantity on order, open issues."""
    upload = await current_stock_upload(session)
    rows = await products_with_stock(session, upload.id if upload else None)
    return ProductsOut(
        stock_upload_id=upload.id if upload else None,
        as_of=upload.as_of if upload else None,
        items=[
            ProductOut(
                sku=row.product.sku,
                name=row.product.name,
                aliases=row.product.aliases,
                unit=row.product.unit,
                pack_size=row.product.pack_size,
                cost_price=row.product.cost_price,
                sell_price=row.product.sell_price,
                supplier=SupplierOut(code=row.supplier.code, name=row.supplier.name),
                qty_on_hand=row.qty_on_hand,
                on_order_qty=row.on_order_qty,
                remarks=row.remarks,
                open_issue_count=row.open_issue_count,
            )
            for row in rows
        ],
    )
