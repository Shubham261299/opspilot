"""The reference data (suppliers and products) as plain objects.

Parsers and business rules receive a Catalog instead of a database session, so they
stay pure and can be tested with no database at all.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Self


@dataclass(frozen=True)
class CatalogSupplier:
    code: str  # "SUP02"
    name: str  # "Volta Switchgear"


@dataclass(frozen=True)
class CatalogProduct:
    sku: str
    name: str
    aliases: tuple[str, ...]
    unit: str
    cost_price: Decimal
    sell_price: Decimal
    supplier_code: str


@dataclass(frozen=True)
class Catalog:
    products: Mapping[str, CatalogProduct]  # by SKU
    suppliers: Mapping[str, CatalogSupplier]  # by code

    @classmethod
    def build(
        cls, products: Iterable[CatalogProduct], suppliers: Iterable[CatalogSupplier]
    ) -> Self:
        return cls(
            products={product.sku: product for product in products},
            suppliers={supplier.code: supplier for supplier in suppliers},
        )
