"""One concept, two modules: the purchase predicate cannot split silently.

`export/xlsx.py::_purchases` and `validate/rules.py::_purchased` both answer
"which line items are purchases". **They are two copies on purpose** -- ADR-0010
keeps `export` from importing `persist` or `validate`, and ISSUE-008's entry is
explicit that they must not be merged for tidiness. The duplication is the
design; the risk is drift.

Each copy is already pinned inside its own module's suite -- `test_xlsx.py`'s
`test_a_template_row_is_not_exported_as_a_purchase` on one side, `test_rules.py`'s
`test_R020s_finding_counts_only_the_purchases` on the other -- so changing one
alone reddens. **Nothing caught the same change reaching only one of them**,
because no test imported both. If "purchase" grows a second condition and one
side gets it, both suites stay green while the workbook and the arithmetic
quietly stop agreeing about what was bought.

This file is the binding ISSUE-008 asks for, and it lives in neither module's
suite deliberately: a property about two modules belongs to neither of them.

**What it catches and what it cannot.** The rows below vary every field a
purchase predicate could plausibly key on today -- the flag itself, whether the
row carries amounts, whether it carries a description -- so a second condition
on any of those makes the two answers differ and reddens this file. A condition
on a field nobody reads today would need a row shape that does not exist yet,
and no fixture can anticipate that. The property is "these two agree over the
shapes we can build", not "these two are the same function".
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from receipts.extract.schema import LineItem, ReceiptExtraction
from receipts.validate.rules import _purchased

# `export/xlsx.py` imports openpyxl at module top -- the optional `pipeline`
# extra -- so this file skips without it, exactly as `tests/test_xlsx.py` does.
pytest.importorskip("openpyxl")

from receipts.export.xlsx import _purchases  # noqa: E402


def _every_row_shape() -> ReceiptExtraction:
    """One receipt holding every row shape the two predicates could differ on."""
    rows: list[LineItem] = []
    position = 0
    for is_template in (True, False):
        for amounts in (True, False):
            for described in (True, False):
                rows.append(
                    LineItem(
                        position=position,
                        description_raw="RICE 5KG" if described else "",
                        qty=D("1") if amounts else None,
                        unit_price=D("100.00") if amounts else None,
                        line_total=D("100.00") if amounts else None,
                        is_template_row=is_template,
                    )
                )
                position += 1
    # The flag omitted entirely, which is how a row from a model that never
    # mentions it arrives. It defaults to False, so it is a purchase -- and a
    # predicate that started reading the field as tri-state would split here.
    rows.append(
        LineItem(position=position, description_raw="OIL 1L", line_total=D("50.00"))
    )
    return ReceiptExtraction(line_items=rows)


def test_the_two_purchase_predicates_answer_identically() -> None:
    receipt = _every_row_shape()

    from_export = _purchases(receipt)
    from_rules = _purchased(receipt)

    # Positions first: a mismatch names the row that split rather than dumping
    # two lists of models at whoever broke it.
    assert [row.position for row in from_export] == [row.position for row in from_rules]
    assert from_export == from_rules


def test_the_agreement_is_not_vacuous() -> None:
    """Both predicates must actually exclude something.

    Two functions that each return every row agree perfectly and guard nothing,
    so the test above would pass on a pair that had both stopped filtering.
    """
    receipt = _every_row_shape()
    kept = _purchases(receipt)

    assert 0 < len(kept) < len(receipt.line_items)
    assert all(not row.is_template_row for row in kept)
    assert any(row.is_template_row for row in receipt.line_items)


def test_they_agree_that_a_receipt_with_no_rows_has_no_purchases() -> None:
    empty = ReceiptExtraction()
    assert _purchases(empty) == _purchased(empty) == []
