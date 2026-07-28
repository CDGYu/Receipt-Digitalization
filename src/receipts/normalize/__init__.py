"""Normalization layer: SAFE canonicalization of a ``ReceiptExtraction``.

By the time we hold a ``ReceiptExtraction``, money fields are ALREADY
``Decimal`` (json_io parsed them). Therefore :func:`normalize` must never alter,
re-quantize, or round money values -- :func:`quantize_money` is display-only.

Guarantees (spec §9), enforced here and in tests:

  * Reformats values but never invents one. Null in -> null out. The one value
    that may be *supplied* rather than read is the currency, and only from the
    explicit §9 chain (merchant default, then system default) -- never guessed
    from a symbol or from language.
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


def normalize(
    raw: ReceiptExtraction,
    *,
    merchant_default_currency: str | None = None,
    system_default_currency: str | None = None,
) -> ReceiptExtraction:
    """Return a deep copy of ``raw`` with only safe canonicalization applied.

    In order: (1) ``clean_text`` on text fields; (2) resolve the currency;
    (3) canonicalize a raw/ambiguous date without guessing; (4) fill missing
    line-item positions by printed order and sort by position. Money ``Decimal``
    values are never touched. ``raw`` is never mutated.

    Currency resolves by the full §9 precedence: an explicit ISO 4217 code on
    the receipt -> ``merchant_default_currency`` (the merchant's stored
    ``default_currency``) -> ``system_default_currency`` (``DEFAULT_CURRENCY``)
    -> ``None``. Both defaults are optional, so a caller with no context still
    gets code-or-null behaviour. A bare symbol like ``"$"`` is not a recognised
    code and is discarded rather than guessed at; an unrecognised code is
    treated the same way. Nothing here ever invents a currency.
    """
    result = raw.model_copy(deep=True)

    # (1) clean text on NON-numeric fields only (no OCR-confusion swaps).
    if result.merchant.name is not None:
        result.merchant.name = clean_text(result.merchant.name)
    if result.merchant.address is not None:
        result.merchant.address = clean_text(result.merchant.address)
    for item in result.line_items:
        item.description_raw = clean_text(item.description_raw)

    # (2) resolve currency by the §9 precedence: explicit ISO code on the
    # receipt -> merchant default -> system default -> null. An ambiguous symbol
    # is dropped, never guessed from.
    result.receipt.currency = normalize_currency(
        result.receipt.currency,
        merchant_default_currency,
        system_default_currency,
    )

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
