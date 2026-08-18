"""Tests for the canonical extraction schema (src/receipts/extract/schema.py).

These pin the *shapes* the VLM contract promises, not the extract path that
fills them: that a sub-model is always present rather than sometimes absent,
that a default is the conservative one, and that a value survives
``model_dump`` -> ``model_validate``. Round-tripping matters because the
pipeline persists and re-loads extractions between stages, so a field that
serializes but does not re-validate would be silently lost.
"""

from __future__ import annotations

from receipts.extract.schema import Buyer, LineItem, ReceiptExtraction


def test_a_new_extraction_has_an_empty_buyer_rather_than_no_buyer() -> None:
    """The buyer is always present as a structure, even when unread.

    A missing `buyer` attribute and a `Buyer` with null fields are different
    states; downstream rules distinguish 'not read' from 'read and empty'.
    """
    extraction = ReceiptExtraction()
    assert extraction.buyer.name is None
    assert extraction.buyer.tax_id is None


def test_a_line_item_is_not_a_template_row_unless_it_says_so() -> None:
    assert LineItem().is_template_row is False


def test_a_template_row_round_trips_through_the_model() -> None:
    item = LineItem(description_raw="MaxiPower", is_template_row=True)
    assert LineItem.model_validate(item.model_dump()).is_template_row is True


def test_buyer_survives_a_round_trip() -> None:
    extraction = ReceiptExtraction(buyer=Buyer(name="IDEAL SOURCE", tax_id=None))
    assert ReceiptExtraction.model_validate(extraction.model_dump()).buyer.name == "IDEAL SOURCE"
