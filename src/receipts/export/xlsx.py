"""Minimal XLSX export: a ``Receipts`` sheet and a ``LineItems`` sheet.

Export is the terminal DISPLAY boundary of the pipeline (the database is the
source of truth; see SPEC §13.1-13.2). Money is ``Decimal`` everywhere on the
internal money path, but a spreadsheet cell is a display value, so here -- and
only here -- each amount is written as ``float(value)`` together with a numeric
``number_format`` so Excel treats it as a number rather than text. This float
conversion is deliberately confined to this cell-writing boundary; nothing
downstream reads these cells (exports read from the database, never the sheet).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from openpyxl import Workbook
from openpyxl.styles import Font

if TYPE_CHECKING:
    from receipts.extract.schema import ReceiptExtraction

# Display format for numeric cells (money and quantity). Format is presentation
# only; it does not change the stored value.
_NUMBER_FORMAT = "#,##0.00"

_RECEIPT_HEADERS = [
    "receipt_id",
    "merchant",
    "date",
    "currency",
    "subtotal",
    "tax",
    "discount",
    "total",
    "payment_method",
]

_LINEITEM_HEADERS = [
    "receipt_id",
    "position",
    "description",
    "qty",
    "unit_price",
    "line_total",
]


def _write_header(ws, headers: list[str]) -> None:
    """Write the bold header row and freeze it so it stays visible on scroll."""
    bold = Font(bold=True)
    for col, name in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=name)
        cell.font = bold
    ws.freeze_panes = "A2"


def _num_cell(ws, row: int, col: int, value: Decimal | None) -> None:
    """Write a numeric value (money or qty) at the display boundary.

    Values are ``Decimal`` on the internal path; a cell is terminal display, so
    we convert to ``float`` here (and only here) with a numeric format. ``None``
    is left as an empty cell -- never the string "None".
    """
    if value is None:
        return
    cell = ws.cell(row=row, column=col, value=float(value))
    cell.number_format = _NUMBER_FORMAT


def export_workbook(
    receipts: list[ReceiptExtraction],
    out_path: Path,
    *,
    ids: list[str] | None = None,
) -> Path:
    """Export receipts to a two-sheet workbook and return the written path.

    ``ids[i]`` supplies the ``receipt_id`` for each receipt when provided;
    otherwise the 1-based index is used. Missing values become empty cells --
    nothing is invented.
    """
    wb = Workbook()

    receipts_ws = wb.active
    receipts_ws.title = "Receipts"
    _write_header(receipts_ws, _RECEIPT_HEADERS)

    lineitems_ws = wb.create_sheet("LineItems")
    _write_header(lineitems_ws, _LINEITEM_HEADERS)

    receipt_row = 1  # row 1 is the header on each sheet
    lineitem_row = 1
    for i, receipt in enumerate(receipts):
        receipt_id: str | int = ids[i] if ids is not None else i + 1

        receipt_row += 1
        receipts_ws.cell(row=receipt_row, column=1, value=receipt_id)
        receipts_ws.cell(row=receipt_row, column=2, value=receipt.merchant.name)
        receipts_ws.cell(row=receipt_row, column=3, value=receipt.receipt.date)
        receipts_ws.cell(row=receipt_row, column=4, value=receipt.receipt.currency)
        _num_cell(receipts_ws, receipt_row, 5, receipt.totals.subtotal)
        _num_cell(receipts_ws, receipt_row, 6, receipt.totals.tax)
        _num_cell(receipts_ws, receipt_row, 7, receipt.totals.discount)
        _num_cell(receipts_ws, receipt_row, 8, receipt.totals.total)
        receipts_ws.cell(row=receipt_row, column=9, value=receipt.payment.method)

        for item in receipt.line_items:
            lineitem_row += 1
            lineitems_ws.cell(row=lineitem_row, column=1, value=receipt_id)
            lineitems_ws.cell(row=lineitem_row, column=2, value=item.position)
            lineitems_ws.cell(row=lineitem_row, column=3, value=item.description_raw)
            _num_cell(lineitems_ws, lineitem_row, 4, item.qty)
            _num_cell(lineitems_ws, lineitem_row, 5, item.unit_price)
            _num_cell(lineitems_ws, lineitem_row, 6, item.line_total)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path
