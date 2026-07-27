"""Tests for the minimal XLSX export (Receipts + LineItems sheets).

Export is a terminal DISPLAY boundary, so money lands in cells as numeric
floats with a display ``number_format``. These tests reopen the saved workbook
with openpyxl and assert structure (sheets, header/data row counts, frozen
header) and a few spot-checked values, including that a null money field
(discount) stays an empty cell rather than the string "None".
"""

from __future__ import annotations

from decimal import Decimal

import pytest

openpyxl = pytest.importorskip("openpyxl")

from receipts.export import export_workbook  # noqa: E402
from receipts.extract.schema import (  # noqa: E402
    LineItem,
    Merchant,
    Payment,
    ReceiptExtraction,
    ReceiptMeta,
    Totals,
)


def _receipt_one() -> ReceiptExtraction:
    return ReceiptExtraction(
        merchant=Merchant(name="Total Wine Co"),
        receipt=ReceiptMeta(date="2024-01-15", currency="USD"),
        line_items=[
            LineItem(
                position=1,
                description_raw="TOTAL WINE CO MERLOT",
                qty=Decimal("1"),
                unit_price=Decimal("12.00"),
                line_total=Decimal("12.00"),
            ),
            LineItem(
                position=2,
                description_raw="CHARDONNAY",
                qty=Decimal("2"),
                unit_price=Decimal("5.00"),
                line_total=Decimal("10.00"),
            ),
        ],
        totals=Totals(
            subtotal=Decimal("22.00"),
            tax=Decimal("1.76"),
            discount=Decimal("2.00"),
            total=Decimal("21.76"),
        ),
        payment=Payment(method="card"),
    )


def _receipt_two() -> ReceiptExtraction:
    # discount is None on purpose: it must export as an empty cell, not "None".
    return ReceiptExtraction(
        merchant=Merchant(name="Corner Store"),
        receipt=ReceiptMeta(date="2024-02-20", currency="USD"),
        line_items=[
            LineItem(
                position=1,
                description_raw="MILK 1L",
                qty=Decimal("3"),
                unit_price=Decimal("1.50"),
                line_total=Decimal("4.50"),
            ),
        ],
        totals=Totals(
            subtotal=Decimal("4.50"),
            tax=Decimal("0.36"),
            discount=None,
            total=Decimal("4.86"),
        ),
        payment=Payment(method="cash"),
    )


def test_export_workbook_builds_two_sheets(tmp_path):
    receipts = [_receipt_one(), _receipt_two()]
    out = tmp_path / "book.xlsx"

    returned = export_workbook(receipts, out_path=out, ids=["r1", "r2"])

    assert returned == out
    assert out.exists()

    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Receipts", "LineItems"]


def test_receipts_sheet_rows_and_values(tmp_path):
    receipts = [_receipt_one(), _receipt_two()]
    out = tmp_path / "book.xlsx"
    export_workbook(receipts, out_path=out, ids=["r1", "r2"])

    ws = openpyxl.load_workbook(out)["Receipts"]

    # 1 header row + 2 data rows.
    assert ws.max_row == 3

    # receipt_id column carries the provided ids.
    assert ws["A2"].value == "r1"
    assert ws["A3"].value == "r2"

    # total column (H) for r1 equals the expected number.
    assert ws["H2"].value == pytest.approx(21.76)

    # merchant and payment_method spot checks.
    assert ws["B2"].value == "Total Wine Co"
    assert ws["I3"].value == "cash"

    # a null money field (discount, column G) is an empty cell, not "None".
    assert ws["G3"].value is None


def test_lineitems_sheet_row_count_and_spot_check(tmp_path):
    receipts = [_receipt_one(), _receipt_two()]
    out = tmp_path / "book.xlsx"
    export_workbook(receipts, out_path=out, ids=["r1", "r2"])

    ws = openpyxl.load_workbook(out)["LineItems"]

    # 3 line items total (2 + 1) plus a header row.
    total_items = sum(len(r.line_items) for r in receipts)
    assert total_items == 3
    assert ws.max_row == total_items + 1

    # First data row is r1's first item.
    assert ws["A2"].value == "r1"
    assert ws["C2"].value == "TOTAL WINE CO MERLOT"
    assert ws["D2"].value == pytest.approx(1)
    assert ws["F2"].value == pytest.approx(12.00)

    # Last data row is r2's only item.
    assert ws["A4"].value == "r2"
    assert ws["C4"].value == "MILK 1L"
    assert ws["D4"].value == pytest.approx(3)
    assert ws["F4"].value == pytest.approx(4.50)


def test_headers_are_frozen_on_both_sheets(tmp_path):
    receipts = [_receipt_one(), _receipt_two()]
    out = tmp_path / "book.xlsx"
    export_workbook(receipts, out_path=out, ids=["r1", "r2"])

    wb = openpyxl.load_workbook(out)
    assert wb["Receipts"].freeze_panes == "A2"
    assert wb["LineItems"].freeze_panes == "A2"


def test_receipt_id_falls_back_to_index_when_ids_absent(tmp_path):
    receipts = [_receipt_one(), _receipt_two()]
    out = tmp_path / "book.xlsx"
    export_workbook(receipts, out_path=out)

    ws = openpyxl.load_workbook(out)["Receipts"]
    # 1-based index fallback.
    assert ws["A2"].value == 1
    assert ws["A3"].value == 2
