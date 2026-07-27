"""Normalization layer: SAFE canonicalization of a ``ReceiptExtraction``.

By the time we hold a ``ReceiptExtraction``, money fields are ALREADY
``Decimal`` (json_io parsed them). Therefore :func:`normalize` must never alter,
re-quantize, or round money values -- :func:`quantize_money` is display-only.

Guarantees (spec §9), enforced here and in tests:

  * Reformats values but never invents one. Null in -> null out.
  * Never applies character-confusion fixes to numeric fields.
  * Never resolves an ambiguous date by guessing.
  * Pure: returns a deep copy and never mutates ``raw``.
"""

from __future__ import annotations

from ..extract.schema import ReceiptExtraction
from .dates import expand_two_digit_year, parse_date, parse_time
from .numbers import detect_decimal_convention, parse_money, quantize_money
from .text import clean_text, normalize_currency, normalize_merchant_name

__all__ = [
    "clean_text",
    "detect_decimal_convention",
    "expand_two_digit_year",
    "normalize",
    "normalize_currency",
    "normalize_merchant_name",
    "parse_date",
    "parse_money",
    "parse_time",
    "quantize_money",
]


def normalize(raw: ReceiptExtraction) -> ReceiptExtraction:
    """Return a deep copy of ``raw`` with only safe canonicalization applied.

    In order: (1) ``clean_text`` on text fields; (2) resolve the currency;
    (3) canonicalize a raw/ambiguous date without guessing; (4) fill missing
    line-item positions by printed order and sort by position. Money ``Decimal``
    values are never touched. ``raw`` is never mutated.
    """
    result = raw.model_copy(deep=True)

    # (1) clean text on NON-numeric fields only (no OCR-confusion swaps).
    if result.merchant.name is not None:
        result.merchant.name = clean_text(result.merchant.name)
    if result.merchant.address is not None:
        result.merchant.address = clean_text(result.merchant.address)
    for item in result.line_items:
        item.description_raw = clean_text(item.description_raw)

    # (2) resolve currency. normalize() has no merchant/system defaults to
    # offer, so this keeps an explicit ISO code and drops an ambiguous symbol.
    result.receipt.currency = normalize_currency(result.receipt.currency, None, None)

    # (3) canonicalize the date only when unambiguous; otherwise leave it null
    # and preserve the verbatim string. Never guess a DD/MM vs MM/DD order.
    if result.receipt.date is not None:
        parsed, ambiguous = parse_date(result.receipt.date)
        if parsed is not None:
            result.receipt.date = parsed.isoformat()
        elif ambiguous:
            if not result.receipt.date_raw:
                result.receipt.date_raw = result.receipt.date
            result.receipt.date = None
        # Unparseable but not ambiguous: leave untouched for the validator (R030).

    # (4) fill missing positions by order, then sort by position.
    items = result.line_items
    positions = [item.position for item in items]
    if sorted(positions) != list(range(len(items))):
        for index, item in enumerate(items):
            item.position = index
    else:
        items.sort(key=lambda item: item.position)

    return result
