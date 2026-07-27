"""Tests for the shared greedy line-item alignment helper.

The property that matters: a single extra or missing row must not cascade into
marking every row unmatched. Greedy best-first matching by normalized-description
similarity keeps the shared rows aligned and isolates the odd one out.
"""

from __future__ import annotations

from receipts.extract.lineitem_align import align_line_items
from receipts.extract.schema import LineItem


def li(position: int, description_raw: str) -> LineItem:
    return LineItem(position=position, description_raw=description_raw)


def test_identical_lists_align_one_to_one():
    a = [li(0, "RICE 5KG"), li(1, "OIL 1L"), li(2, "SUGAR 2KG")]
    b = [li(0, "RICE 5KG"), li(1, "OIL 1L"), li(2, "SUGAR 2KG")]
    assert align_line_items(a, b) == [(0, 0), (1, 1), (2, 2)]


def test_extra_item_in_b_isolated_as_single_unmatched():
    """The key case: one extra row on the b side must NOT unmatch everything."""
    a = [li(0, "RICE 5KG"), li(1, "OIL 1L"), li(2, "SUGAR 2KG")]
    b = [li(0, "RICE 5KG"), li(1, "OIL 1L"), li(2, "SUGAR 2KG"), li(3, "SALT 500G")]
    assert align_line_items(a, b) == [(0, 0), (1, 1), (2, 2), (None, 3)]


def test_item_missing_from_b_shows_as_unmatched_a():
    a = [li(0, "RICE 5KG"), li(1, "OIL 1L"), li(2, "SUGAR 2KG")]
    b = [li(0, "RICE 5KG"), li(1, "SUGAR 2KG")]
    result = align_line_items(a, b)
    assert (1, None) in result
    assert result == [(0, 0), (2, 1), (1, None)]


def test_both_empty_returns_empty():
    assert align_line_items([], []) == []


def test_empty_a_marks_all_b_unmatched():
    b = [li(0, "RICE 5KG"), li(1, "OIL 1L")]
    assert align_line_items([], b) == [(None, 0), (None, 1)]


def test_empty_b_marks_all_a_unmatched():
    a = [li(0, "RICE 5KG"), li(1, "OIL 1L")]
    assert align_line_items(a, []) == [(0, None), (1, None)]


def test_does_not_mutate_inputs():
    a = [li(0, "RICE 5KG"), li(1, "OIL 1L")]
    b = [li(0, "RICE 5KG"), li(1, "SUGAR 2KG"), li(2, "OIL 1L")]
    before_a = [item.model_dump_json() for item in a]
    before_b = [item.model_dump_json() for item in b]
    align_line_items(a, b)
    assert [item.model_dump_json() for item in a] == before_a
    assert [item.model_dump_json() for item in b] == before_b
