from decimal import Decimal

import pytest

from app.domain.catalog import Catalog, CatalogProduct, CatalogSupplier
from app.domain.matching import (
    ProductMatch,
    SupplierMatch,
    match_product_by_name,
    normalise_name,
    resolve_supplier,
)


def _product(sku: str, name: str, *aliases: str) -> CatalogProduct:
    return CatalogProduct(sku, name, aliases, "piece", Decimal("1"), Decimal("2"), "SUP01")


CATALOG = Catalog.build(
    products=[
        _product("ST-0031", "GI Box 3 Module", "3m box", "gi box 3"),
        _product("ST-0041", "Plate 3 Module White", "3m plate"),
        _product("ST-0047", "PVC Insulation Tape Black", "tape"),
        _product("ST-0048", "PVC Insulation Tape Red", "tape"),  # shares the alias "tape"
    ],
    suppliers=[
        CatalogSupplier("SUP02", "Volta Switchgear"),
        CatalogSupplier("SUP03", "Brightline LED Co."),
        CatalogSupplier("SUP08", "Sai Conduits & Pipes"),
        CatalogSupplier("SUP09", "Sai Electricals"),
    ],
)


def test_normalise_name_ignores_case_and_extra_spaces() -> None:
    assert normalise_name("  GI  box 8 MODULE ") == "gi box 8 module"


def test_product_matches_its_exact_name_ignoring_case_and_spacing() -> None:
    assert match_product_by_name("  gi box 3 module ", CATALOG) == ProductMatch("ST-0031", "name")


def test_product_matches_a_unique_alias() -> None:
    assert match_product_by_name("3M BOX", CATALOG) == ProductMatch("ST-0031", "alias")


def test_alias_shared_by_two_products_is_not_guessed() -> None:
    assert match_product_by_name("tape", CATALOG) is None


@pytest.mark.parametrize("name", ["GI Box", "Tube light 36W", "", "   "])
def test_partial_or_unknown_names_do_not_match(name: str) -> None:
    assert match_product_by_name(name, CATALOG) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Volta Switchgear", SupplierMatch("SUP02", exact=True)),
        ("  volta   switchgear ", SupplierMatch("SUP02", exact=True)),
        ("SUP03", SupplierMatch("SUP03", exact=True)),
        ("Volta", SupplierMatch("SUP02", exact=False)),
        ("Brightline", SupplierMatch("SUP03", exact=False)),
        ("brightline led", SupplierMatch("SUP03", exact=False)),
    ],
)
def test_supplier_resolves_from_full_name_code_or_short_name(
    text: str, expected: SupplierMatch
) -> None:
    assert resolve_supplier(text, CATALOG) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Volt",  # stops mid-word
        "Sai",  # the start of two suppliers' names
        "Kiran Cables",  # not a supplier here
        "",
    ],
)
def test_supplier_is_not_guessed(text: str) -> None:
    assert resolve_supplier(text, CATALOG) is None
