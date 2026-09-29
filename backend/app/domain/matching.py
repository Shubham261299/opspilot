"""Matching free text to products and suppliers.

Rule: never guess. A match is returned only when it is exact (ignoring case and extra
spaces) and points to exactly one product or supplier. Anything else returns None, and
the caller reports an issue so a human decides.
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.catalog import Catalog


def normalise_name(text: str) -> str:
    """Case- and whitespace-insensitive form used to compare names: "  GI box 8 " -> "gi box 8"."""
    return " ".join(text.casefold().split())


@dataclass(frozen=True)
class ProductMatch:
    sku: str
    matched_on: Literal["name", "alias"]


def match_product_by_name(name: str, catalog: Catalog) -> ProductMatch | None:
    """Find the one product whose name, or failing that whose alias, equals `name`."""
    key = normalise_name(name)
    if not key:
        return None
    by_name = [p.sku for p in catalog.products.values() if normalise_name(p.name) == key]
    if len(by_name) == 1:
        return ProductMatch(by_name[0], "name")
    by_alias = [
        p.sku
        for p in catalog.products.values()
        if key in {normalise_name(alias) for alias in p.aliases}
    ]
    if len(by_alias) == 1:
        return ProductMatch(by_alias[0], "alias")
    return None


@dataclass(frozen=True)
class SupplierMatch:
    code: str
    exact: bool  # False when resolved from a short name like "Volta"


def resolve_supplier(text: str, catalog: Catalog) -> SupplierMatch | None:
    """Resolve a supplier written as its full name, its code, or a short name.

    A short name must be the first word(s) of exactly one supplier's name:
    "Volta" -> "Volta Switchgear". "Volt" matches nothing (it stops mid-word).
    """
    key = normalise_name(text)
    if not key:
        return None
    for supplier in catalog.suppliers.values():
        if key in (normalise_name(supplier.name), supplier.code.casefold()):
            return SupplierMatch(supplier.code, exact=True)
    candidates = [
        supplier.code
        for supplier in catalog.suppliers.values()
        if normalise_name(supplier.name).startswith(key + " ")
    ]
    if len(candidates) == 1:
        return SupplierMatch(candidates[0], exact=False)
    return None
