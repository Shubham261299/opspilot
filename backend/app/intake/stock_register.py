"""Stock register intake: the godown's messy Excel stock sheet -> clean stock counts.

parse_stock_register() is pure: the file's bytes and the catalog go in, a result comes
out, and no database is touched. Every row that is skipped, corrected or rejected becomes
an IssueRecord, so nothing is dropped silently. The rules and why they were chosen are
in docs/decisions.md.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.domain.catalog import Catalog, CatalogProduct
from app.domain.dates import find_date
from app.domain.matching import match_product_by_name, normalise_name, resolve_supplier
from app.domain.units import normalise_unit
from app.intake.errors import IntakeError
from app.intake.excel import (
    Header,
    Sheet,
    SheetRow,
    column_letter,
    find_header,
    json_safe,
    read_workbook,
)
from app.intake.excel import parse_money as _parse_money
from app.intake.excel import rupees as _rupees
from app.intake.issues import IssueRecord, IssueType

# Column titles (compared after normalise_label) that mean each field.
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "code": ("item code", "code", "sku", "product code", "item no"),
    "name": ("item name", "item", "name", "product", "product name", "description"),
    "unit": ("unit", "uom", "units"),
    "qty": ("qty in stock", "qty", "quantity", "stock", "closing stock", "qty on hand"),
    "purchase_rate": ("rate purchase", "purchase rate", "cost price", "cost", "rate"),
    "sale_rate": ("mrp sale rate", "sale rate", "mrp", "selling price", "sale price"),
    "supplier": ("supplier", "vendor", "supplier name"),
    "remarks": ("remarks", "remark", "notes", "note", "comments"),
}

# A quantity typed as text: "395 pcs", "1,200", "-4"
_QTY_TEXT = re.compile(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*([a-z][a-z.]*)?", re.IGNORECASE)
_TOTALS = re.compile(r"\btotal\b", re.IGNORECASE)

# A remark about an order that was placed ("ordered", "on order", "PO"), unlike
# "order urgent", which asks for one.
_MENTIONS_ORDER = re.compile(r"\b(ordered|on order|po)\b", re.IGNORECASE)
_QTY = r"(?P<qty>\d[\d,]*)"
_UNIT = r"(?:\s*(?P<unit>[a-z][a-z.]*))?"
_FROM = r"(?:\s+from\s+(?P<supplier>.+?))?"
_ON = r"(?:\s+on\s+(?P<date>\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?))?"
_ORDER_REMARKS = (
    # "40 pcs ordered from Brightline on 22/9"
    re.compile(rf"{_QTY}{_UNIT}\s+(?:ordered|on order){_FROM}{_ON}\s*\.?", re.IGNORECASE),
    # "ordered 40 pcs from Brightline on 22/9"
    re.compile(rf"ordered\s+{_QTY}{_UNIT}{_FROM}{_ON}\s*\.?", re.IGNORECASE),
)


@dataclass(frozen=True)
class StockRow:
    sku: str
    qty_on_hand: int
    source_row: int
    remarks: str | None


@dataclass(frozen=True)
class PoNote:
    """A purchase order placed outside the app, read from a remark."""

    sku: str
    supplier_code: str | None
    qty: int
    ordered_on: date | None
    note: str  # the remark exactly as written
    source_row: int


@dataclass(frozen=True)
class StockRegisterResult:
    sheet_name: str
    header_row: int
    as_of: date  # the count date
    rows_read: int  # item rows found (titles, headings, totals and blank rows excluded)
    stock_rows: tuple[StockRow, ...]
    po_notes: tuple[PoNote, ...]
    issues: tuple[IssueRecord, ...]


def parse_stock_register(content: bytes, catalog: Catalog, today: date) -> StockRegisterResult:
    """Read a stock register workbook. `today` fills in the year for dates written without one."""
    sheets = read_workbook(content)
    for sheet in sheets:
        header = find_header(sheet, HEADER_SYNONYMS, required=("qty",), any_of=("code", "name"))
        if header is not None:
            others = [other for other in sheets if other is not sheet]
            return _StockSheetReader(sheet, header, catalog, today).read(others)
    raise IntakeError(
        "header_not_found",
        "No header row found. The stock sheet needs a quantity column (like 'Qty In Stock') "
        "and an 'Item Code' or 'Item Name' column.",
    )


@dataclass(frozen=True)
class _Count:
    """The latest row seen for one product."""

    row_number: int
    qty_as_written: Any
    stock_row: StockRow | None  # None when this row's count couldn't be loaded


class _StockSheetReader:
    def __init__(self, sheet: Sheet, header: Header, catalog: Catalog, today: date) -> None:
        self.sheet = sheet
        self.header = header
        self.catalog = catalog
        self.today = today
        self.as_of = today
        self.rows_read = 0
        self.counts: dict[str, _Count] = {}  # SKU -> its latest row
        self.po_notes: list[PoNote] = []
        self.issues: list[IssueRecord] = []
        self.unit_spellings: dict[tuple[str, str], list[int]] = defaultdict(list)

    def read(self, other_sheets: list[Sheet]) -> StockRegisterResult:
        header_row = self.header.row_number
        self._read_title_rows([row for row in self.sheet.rows if row.number < header_row])
        for row in self.sheet.rows:
            if row.number > header_row:
                self._read_row(row)
        self._report_unit_spellings()
        self._report_missing_products()
        self._report_other_sheets(other_sheets)

        stock_rows = sorted(
            (count.stock_row for count in self.counts.values() if count.stock_row is not None),
            key=lambda stock_row: stock_row.source_row,
        )
        issues = sorted(self.issues, key=lambda i: (i.source_row is None, i.source_row or 0))
        return StockRegisterResult(
            sheet_name=self.sheet.name,
            header_row=header_row,
            as_of=self.as_of,
            rows_read=self.rows_read,
            stock_rows=tuple(stock_rows),
            po_notes=tuple(self.po_notes),
            issues=tuple(issues),
        )

    # Rows above the header -------------------------------------------------------

    def _read_title_rows(self, rows: list[SheetRow]) -> None:
        date_found = False
        for row in rows:
            if row.is_blank():
                continue
            detail = f"Title row above the header, not imported: '{row.text()}'."
            if not date_found and (found := find_date(row.text(), self.today)) is not None:
                self.as_of, date_found = found, True
                detail += f" The count date {found:%d %b %Y} was read from it."
            self._issue(IssueType.SKIPPED_ROW, detail, row)
        if not date_found:
            self._issue(
                IssueType.COUNT_DATE_MISSING,
                "No count date found above the header, so the upload date "
                f"{self.today:%d %b %Y} is used as the count date.",
            )

    # Rows below the header -------------------------------------------------------

    def _read_row(self, row: SheetRow) -> None:
        if row.is_blank():
            return  # nothing in it, so nothing is lost
        cells = self._cells(row)
        filled = row.filled()
        first = str(filled[0][1])
        if cells.get("code") is None and not self._is_product_name(first):
            if _TOTALS.search(first):
                self._issue(IssueType.SKIPPED_ROW, f"Totals row, not an item: '{row.text()}'.", row)
                return
            if len(filled) == 1 and isinstance(filled[0][1], str):
                self._issue(IssueType.SKIPPED_ROW, f"Section heading, not an item: '{first}'.", row)
                return
        self.rows_read += 1
        self._read_item(row, cells)

    def _read_item(self, row: SheetRow, cells: dict[str, Any]) -> None:
        product, usable = self._identify(row, cells)
        if product is None:
            return
        stock_row = None
        if usable:
            self._check_name_format(row, product)
            qty = self._read_qty(row, cells, product)
            unit_ok = self._check_unit(row, cells, product)
            self._check_rates(row, cells, product)
            self._check_supplier(row, cells, product)
            remarks = _as_text(cells.get("remarks"))
            if remarks is not None:
                self._read_order_remark(row, remarks, product)
            if qty is not None and unit_ok:
                stock_row = StockRow(product.sku, qty, row.number, remarks)
        self._record_count(row, product, cells.get("qty"), stock_row)

    def _identify(self, row: SheetRow, cells: dict[str, Any]) -> tuple[CatalogProduct | None, bool]:
        """Which product is this row about? Returns (product, whether the row can be used)."""
        code, name = _as_text(cells.get("code")), _as_text(cells.get("name"))
        if code is not None:
            product = self.catalog.products.get(code.upper())
            if product is None:
                self._issue(
                    IssueType.UNKNOWN_ITEM,
                    f"Item code '{code}' is not in the product master, so this row was not loaded.",
                    row,
                )
                return None, False
            if name is not None and not _is_name_of(name, product):
                self._issue(
                    IssueType.CODE_NAME_MISMATCH,
                    f"Item code {product.sku} is '{product.name}' in the product master, but this "
                    f"row says '{name}'. Not loaded, because it's unclear which one is right.",
                    row,
                    product.sku,
                )
                return product, False
            return product, True

        if name is None:
            self._issue(
                IssueType.UNKNOWN_ITEM,
                "The row has neither an item code nor an item name, so it was not loaded.",
                row,
            )
            return None, False
        match = match_product_by_name(name, self.catalog)
        if match is None:
            discontinued = (
                " It is marked discontinued." if "discontinued" in name.casefold() else ""
            )
            self._issue(
                IssueType.UNKNOWN_ITEM,
                f"'{name}' has no item code and matches no product in the product master, "
                f"so it was not loaded.{discontinued}",
                row,
            )
            return None, False
        product = self.catalog.products[match.sku]
        if "code" in self.header.columns:  # a sheet without a code column identifies by name
            self._issue(
                IssueType.BLANK_CODE,
                f"Item code is blank; matched to {product.sku} '{product.name}' "
                f"by its exact {match.matched_on}.",
                row,
                product.sku,
            )
        return product, True

    def _check_name_format(self, row: SheetRow, product: CatalogProduct) -> None:
        """Report a name that matches the master's only after fixing spaces or capitals."""
        col = self.header.columns.get("name")
        written = row.original[col] if col is not None and col < len(row.original) else None
        if not isinstance(written, str) or written == product.name:
            return
        tidy = " ".join(written.split())
        if normalise_name(tidy) != normalise_name(product.name):
            return  # a different name, such as an alias; not a formatting problem
        differences = []
        if tidy != written:
            differences.append("extra spaces")
        if tidy != product.name:
            differences.append("capital letters")
        self._issue(
            IssueType.NAME_FORMAT,
            f"Name '{written}' differs from the product master's '{product.name}' only in "
            f"{' and '.join(differences)}.",
            row,
            product.sku,
        )

    def _read_qty(
        self, row: SheetRow, cells: dict[str, Any], product: CatalogProduct
    ) -> int | None:
        """The counted quantity, or None (with an issue) when it can't be trusted."""
        raw = cells.get("qty")
        sku = product.sku
        if raw is None:
            self._issue(
                IssueType.INVALID_QTY, "Quantity is blank, so this count was not loaded.", row, sku
            )
            return None
        if isinstance(raw, bool) or not isinstance(raw, int | float | str):
            self._issue(
                IssueType.INVALID_QTY,
                f"Quantity '{raw}' is not a number, so this count was not loaded.",
                row,
                sku,
            )
            return None

        if isinstance(raw, str):
            match = _QTY_TEXT.fullmatch(raw)
            if match is None:
                self._issue(
                    IssueType.INVALID_QTY,
                    f"Quantity '{raw}' is not a number, so this count was not loaded.",
                    row,
                    sku,
                )
                return None
            number_text, unit_text = match.groups()
            if unit_text is not None and not self._qty_unit_ok(row, raw, unit_text, product):
                return None
            number = Decimal(number_text.replace(",", ""))
        else:
            number = Decimal(str(raw))

        if number != number.to_integral_value():
            self._issue(
                IssueType.INVALID_QTY,
                f"Quantity {raw} is not a whole number, so this count was not loaded.",
                row,
                sku,
            )
            return None
        qty = int(number)
        if qty < 0:
            self._issue(
                IssueType.NEGATIVE_QTY,
                f"Quantity is {qty}. A stock count can't be negative, so it was not loaded; "
                f"{sku} needs a recount.",
                row,
                sku,
            )
            return None
        if isinstance(raw, str):
            self._issue(
                IssueType.QTY_AS_TEXT,
                f"Quantity was typed as text '{raw}'; read as {qty}.",
                row,
                sku,
            )
        return qty

    def _qty_unit_ok(
        self, row: SheetRow, raw: str, unit_text: str, product: CatalogProduct
    ) -> bool:
        """A unit typed inside the quantity ("395 pcs") must be the product's unit."""
        unit = normalise_unit(unit_text)
        if unit is None:
            self._issue(
                IssueType.INVALID_QTY,
                f"Quantity '{raw}' has an unknown unit '{unit_text}', "
                "so this count was not loaded.",
                row,
                product.sku,
            )
            return False
        if unit != product.unit:
            self._issue(
                IssueType.UNIT_MISMATCH,
                f"Quantity '{raw}' is in {_plural(unit)}, but {product.sku} is counted in "
                f"{_plural(product.unit)} in the product master. Not loaded, because converting "
                "would be a guess.",
                row,
                product.sku,
            )
            return False
        return True

    def _check_unit(self, row: SheetRow, cells: dict[str, Any], product: CatalogProduct) -> bool:
        """The unit must be the product's unit; returns False if the count can't be used."""
        if "unit" not in self.header.columns:
            return True  # a sheet without a unit column counts in the master's units
        raw = _as_text(cells.get("unit"))
        sku = product.sku
        if raw is None:
            self._issue(
                IssueType.BLANK_UNIT,
                f"Unit is blank; assumed the product master's unit '{product.unit}'.",
                row,
                sku,
            )
            return True
        unit = normalise_unit(raw)
        if unit is None:
            self._issue(
                IssueType.UNKNOWN_UNIT,
                f"Unit '{raw}' is not a known unit, so the quantity can't be trusted and was not "
                "loaded.",
                row,
                sku,
            )
            return False
        if unit != product.unit:
            self._issue(
                IssueType.UNIT_MISMATCH,
                f"Counted in '{raw}' ({_plural(unit)}), but {sku} is counted in "
                f"{_plural(product.unit)} in the product master. Not loaded, because converting "
                "would be a guess.",
                row,
                sku,
            )
            return False
        if raw != unit:
            self.unit_spellings[(raw, unit)].append(row.number)
        return True

    def _check_rates(self, row: SheetRow, cells: dict[str, Any], product: CatalogProduct) -> None:
        """Compare the sheet's rates with the product master. The master is never changed."""
        rates = (
            ("purchase_rate", "Purchase rate", product.cost_price),
            ("sale_rate", "Sale rate", product.sell_price),
        )
        blank = []
        for field, label, master in rates:
            if field not in self.header.columns:
                continue  # this sheet has no such column
            raw = cells.get(field)
            if raw is None:
                blank.append((label, master))
                continue
            value = _parse_money(raw)
            if value is None:
                self._issue(
                    IssueType.INVALID_RATE,
                    f"{label} '{raw}' is not a number; the product master's price "
                    f"{_rupees(master)} is kept.",
                    row,
                    product.sku,
                )
            elif value != master:
                self._issue(
                    IssueType.RATE_MISMATCH,
                    f"{label} {_rupees(value)} differs from the product master "
                    f"({_rupees(master)}); the master price is kept.",
                    row,
                    product.sku,
                )
        if len(blank) == 1:
            label, master = blank[0]
            detail = f"{label} is blank; the product master's price {_rupees(master)} is kept."
        elif blank:
            detail = (
                "Purchase rate and sale rate are blank; the product master's prices "
                f"{_rupees(product.cost_price)} and {_rupees(product.sell_price)} are kept."
            )
        else:
            return
        self._issue(IssueType.BLANK_RATE, detail, row, product.sku)

    def _check_supplier(
        self, row: SheetRow, cells: dict[str, Any], product: CatalogProduct
    ) -> None:
        """Compare the sheet's supplier with the product master. The master is never changed."""
        raw = _as_text(cells.get("supplier"))
        if raw is None:
            return
        master = self.catalog.suppliers.get(product.supplier_code)
        master_label = f"{master.name} ({master.code})" if master else product.supplier_code
        match = resolve_supplier(raw, self.catalog)
        if match is None:
            self._issue(
                IssueType.UNKNOWN_SUPPLIER,
                f"Supplier '{raw}' matches no known supplier; the product master's supplier "
                f"{master_label} is kept.",
                row,
                product.sku,
            )
            return
        found = self.catalog.suppliers[match.code]
        if match.code != product.supplier_code:
            self._issue(
                IssueType.SUPPLIER_MISMATCH,
                f"Supplier on this row is {found.name} ({found.code}), but the product master "
                f"says {master_label}; the master is kept.",
                row,
                product.sku,
            )
        elif not match.exact:
            self._issue(
                IssueType.SUPPLIER_SHORT_NAME,
                f"Supplier '{raw}' read as {found.name} ({found.code}).",
                row,
                product.sku,
            )

    def _read_order_remark(self, row: SheetRow, remark: str, product: CatalogProduct) -> None:
        """Record "40 pcs ordered from Brightline on 22/9" as an open purchase order."""
        if not _MENTIONS_ORDER.search(remark):
            return
        match = next((m for p in _ORDER_REMARKS if (m := p.fullmatch(remark))), None)
        unit = None
        if match is not None:
            unit = normalise_unit(match["unit"]) if match["unit"] else product.unit
        if match is None or unit != product.unit or int(match["qty"].replace(",", "")) <= 0:
            self._issue(
                IssueType.UNCLEAR_PO_REMARK,
                f"Remark '{remark}' mentions an order, but its quantity or unit is unclear, so "
                "nothing was counted as on order.",
                row,
                product.sku,
            )
            return

        qty = int(match["qty"].replace(",", ""))
        supplier_text = match["supplier"]
        supplier = resolve_supplier(supplier_text, self.catalog) if supplier_text else None
        ordered_on = find_date(match["date"], self.as_of) if match["date"] else None
        self.po_notes.append(
            PoNote(
                sku=product.sku,
                supplier_code=supplier.code if supplier else None,
                qty=qty,
                ordered_on=ordered_on,
                note=remark,
                source_row=row.number,
            )
        )
        parts = [f"{_quantity(qty, product.unit)} of {product.sku}"]
        if supplier is not None:
            found = self.catalog.suppliers[supplier.code]
            parts.append(f"from {found.name} ({found.code})")
        elif supplier_text:
            parts.append(f"from '{supplier_text}' (supplier not recognised)")
        if ordered_on is not None:
            parts.append(f"ordered {ordered_on:%d %b %Y}")
        self._issue(
            IssueType.OPEN_PO_NOTE,
            f"Remark '{remark}' recorded as an open purchase order: {', '.join(parts)}.",
            row,
            product.sku,
        )

    def _record_count(
        self,
        row: SheetRow,
        product: CatalogProduct,
        qty_as_written: Any,
        stock_row: StockRow | None,
    ) -> None:
        """Remember this row as the product's count; if the product appeared before, it wins."""
        previous = self.counts.get(product.sku)
        if previous is not None:
            if stock_row is not None:
                remark = f", remark '{stock_row.remarks}'" if stock_row.remarks else ""
                kept = f"This later row is kept (qty {stock_row.qty_on_hand}{remark})."
            else:
                kept = (
                    "This later row counts, but its quantity couldn't be loaded, so the product "
                    "needs a recount."
                )
            self._issue(
                IssueType.DUPLICATE_ROW,
                f"{product.sku} is listed twice: first on row {previous.row_number} "
                f"(qty {previous.qty_as_written}), again here. {kept} "
                f"Row {previous.row_number} was not loaded.",
                row,
                product.sku,
            )
        self.counts[product.sku] = _Count(row.number, qty_as_written, stock_row)

    # Whole-file checks -----------------------------------------------------------

    def _report_unit_spellings(self) -> None:
        if not self.unit_spellings:
            return
        ordered = sorted(self.unit_spellings.items(), key=lambda item: (-len(item[1]), item[0]))
        summary = ", ".join(
            f"{raw} → {unit} ({len(rows)} {'row' if len(rows) == 1 else 'rows'})"
            for (raw, unit), rows in ordered
        )
        self._issue(
            IssueType.UNITS_NORMALISED,
            f"Unit spellings were changed to the product master's units: {summary}.",
            raw={f"{raw} → {unit}": rows for (raw, unit), rows in ordered},
        )

    def _report_missing_products(self) -> None:
        for sku, product in self.catalog.products.items():
            if sku not in self.counts:
                self._issue(
                    IssueType.MISSING_FROM_REGISTER,
                    f"{sku} '{product.name}' is not in this stock count, "
                    "so it shows as not counted.",
                    sku=sku,
                )

    def _report_other_sheets(self, sheets: list[Sheet]) -> None:
        for sheet in sheets:
            lines = [row.text() for row in sheet.rows if not row.is_blank()]
            if not lines:
                continue
            shown = " / ".join(f"'{line}'" for line in lines[:5])
            if len(lines) > 5:
                shown += f" / … ({len(lines) - 5} more lines)"
            self._issue(
                IssueType.OTHER_SHEET,
                f"Sheet '{sheet.name}' was not imported. It says: {shown}",
                raw={"sheet": sheet.name, "lines": lines[:50]},
            )

    # Helpers -----------------------------------------------------------------------

    def _cells(self, row: SheetRow) -> dict[str, Any]:
        """The row's values by field name ("qty", "code", ...)."""
        return {
            field: row.values[col]
            for field, col in self.header.columns.items()
            if col < len(row.values)
        }

    def _is_product_name(self, text: str) -> bool:
        return match_product_by_name(text, self.catalog) is not None

    def _issue(
        self,
        issue_type: IssueType,
        detail: str,
        row: SheetRow | None = None,
        sku: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        if raw is None and row is not None:
            raw = {
                self.header.labels.get(col, column_letter(col)): json_safe(row.original[col])
                for col, _ in row.filled()
            }
        source_row = row.number if row is not None else None
        self.issues.append(IssueRecord(issue_type, detail, source_row, sku, raw))


def _as_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _is_name_of(name: str, product: CatalogProduct) -> bool:
    key = normalise_name(name)
    return key == normalise_name(product.name) or key in {
        normalise_name(alias) for alias in product.aliases
    }


def _plural(unit: str) -> str:
    if unit == "kg":
        return unit
    return f"{unit}es" if unit.endswith("x") else f"{unit}s"


def _quantity(qty: int, unit: str) -> str:
    """(40, "piece") -> "40 pieces"; (1, "box") -> "1 box"."""
    return f"{qty} {unit if qty == 1 else _plural(unit)}"
