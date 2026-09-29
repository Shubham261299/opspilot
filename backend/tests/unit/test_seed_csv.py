from decimal import Decimal
from pathlib import Path

import pytest

from app.db.seed import ProductRow, SeedDataError, SupplierRow, read_csv_rows


def test_reads_all_six_suppliers(sample_data_dir: Path) -> None:
    suppliers = read_csv_rows(sample_data_dir / "suppliers.csv", SupplierRow)

    assert [s.code for s in suppliers] == [f"SUP0{n}" for n in range(1, 7)]
    volta = suppliers[1]
    assert (volta.name, volta.lead_time_days, volta.payment_terms) == (
        "Volta Switchgear",
        7,
        "45 days",
    )


def test_reads_all_sixty_products_with_aliases_and_exact_prices(sample_data_dir: Path) -> None:
    products = read_csv_rows(sample_data_dir / "product_master.csv", ProductRow)

    assert len(products) == 60
    assert len({p.sku for p in products}) == 60
    wall_plug = next(p for p in products if p.sku == "ST-0051")
    assert wall_plug.aliases == ["gitti", "wall plug", "rawl plug"]
    assert wall_plug.cost_price == Decimal("35")
    assert wall_plug.supplier_code == "SUP06"
    assert {p.unit for p in products} == {"coil", "box", "piece", "length", "roll", "packet", "kg"}


def test_invalid_row_stops_with_its_row_number(tmp_path: Path) -> None:
    bad_csv = tmp_path / "suppliers.csv"
    bad_csv.write_text(
        "id,name,phone,email,lead_time_days,payment_terms,categories\n"
        "SUP01,Good Supplier,,,5,30 days,Wires\n"
        "SUP02,Bad Supplier,,,-3,30 days,Wires\n",
        encoding="utf-8",
    )

    with pytest.raises(SeedDataError, match="suppliers.csv row 3"):
        read_csv_rows(bad_csv, SupplierRow)


def test_blank_optional_cells_become_none(tmp_path: Path) -> None:
    csv_file = tmp_path / "suppliers.csv"
    csv_file.write_text(
        "id,name,phone,email,lead_time_days,payment_terms,categories\nSUP09,Quiet Supplier,,,4,,\n",
        encoding="utf-8",
    )

    (supplier,) = read_csv_rows(csv_file, SupplierRow)

    assert supplier.phone is None
    assert supplier.payment_terms is None
