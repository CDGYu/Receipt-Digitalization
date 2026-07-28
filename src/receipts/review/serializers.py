"""JSON serializers for the review API's read routes (P4.T4, spec §14.9).

Two rules from the data model carry straight into these functions:

  * **Money and confidence are strings, never JSON numbers** (ADR-0001). A
    ``Decimal`` that crossed the wire as a JSON float would reintroduce
    exactly the representation drift the validator exists to catch, so
    :func:`money` is the one place that conversion happens -- every other
    function here calls it rather than doing its own ``str()``.
  * **``confidence_reasons`` is nullable, and the null is meaningful**
    (see ``Receipt.confidence_reasons`` in :mod:`receipts.persist.models`):
    ``None`` means "this receipt's score was never explained" (a row written
    before the column existed, or a run that failed before scoring), while
    ``[]`` means "nothing lowered the score" -- a genuinely clean receipt.
    Collapsing the two into ``[]`` would tell a reviewer "no reasons" about a
    receipt that never captured any -- a confident wrong answer of exactly
    the kind this project has already shipped once (an eval artifact
    claiming 100% precision on zero receipts). :func:`receipt_detail` passes
    the column through verbatim.
"""

from __future__ import annotations

from datetime import date as date_cls
from decimal import Decimal
from typing import Any

from ..persist.models import LineItem, Receipt, ValidationFinding

__all__ = ["money", "receipt_detail", "receipt_summary"]


def money(value: Decimal | None) -> str | None:
    """A money (or confidence, or ratio) column as a string.

    ``None`` in, ``None`` out -- never rewritten to ``"0"`` or ``"0.00"``: an
    amount that was never recorded is not the same fact as a recorded zero.
    A JSON number is a float (ADR-0001), so every ``Decimal`` this API
    returns passes through here first.
    """
    return None if value is None else str(value)


def _iso_date(value: date_cls | None) -> str | None:
    return None if value is None else value.isoformat()


def receipt_summary(receipt: Receipt) -> dict[str, Any]:
    """One row of the receipts list (``GET /receipts``).

    Deliberately light -- just enough for a reviewer to triage a queue --
    rather than pulling line items and findings for every row on the page;
    :func:`receipt_detail` is what a reviewer opens next.
    """
    return {
        "id": str(receipt.id),
        "status": receipt.status.value,
        "confidence": money(receipt.confidence),
        "merchant_name_raw": receipt.merchant_name_raw,
        "txn_date": _iso_date(receipt.txn_date),
        "currency": receipt.currency,
        "total": money(receipt.total),
        "created_at": receipt.created_at.isoformat(),
    }


def _line_item(item: LineItem) -> dict[str, Any]:
    return {
        "position": item.position,
        "description_raw": item.description_raw,
        "sku": item.sku,
        "qty": money(item.qty),
        "unit": item.unit,
        "unit_price": money(item.unit_price),
        "line_total": money(item.line_total),
        "modifiers": item.modifiers,
        "bbox": item.bbox,
        "line_confidence": money(item.line_confidence),
    }


def _finding(finding: ValidationFinding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity.value,
        "message": finding.message,
        "context": finding.context,
        "resolved_by_repair": finding.resolved_by_repair,
    }


def receipt_detail(receipt: Receipt, findings: list[ValidationFinding]) -> dict[str, Any]:
    """The full receipt (``GET /receipts/{id}``), findings included.

    ``findings`` is passed in rather than re-read off ``receipt`` because the
    caller already has it from
    :func:`receipts.persist.repository.get_findings` (oldest first) --
    fetching it again here would be a second query for data the caller was
    going to load anyway.

    Every money column lives under ``totals``, named after
    :class:`receipts.extract.schema.Totals` (``subtotal``, ``tax``,
    ``discount``, ``total``, ``tender``, ``change``) rather than the
    ``receipts`` table's own column names (``tax_total``, ``tender_amount``,
    ...), so a client already speaking the extraction schema's vocabulary
    does not have to learn a second one.
    """
    return {
        "id": str(receipt.id),
        "status": receipt.status.value,
        "confidence": money(receipt.confidence),
        "confidence_reasons": receipt.confidence_reasons,  # verbatim: None stays None
        "merchant_name_raw": receipt.merchant_name_raw,
        "txn_date": _iso_date(receipt.txn_date),
        "date_raw": receipt.date_raw,
        "currency": receipt.currency,
        "created_at": receipt.created_at.isoformat(),
        "card_last4": receipt.card_last4,
        "is_handwritten": receipt.is_handwritten,
        "legibility": receipt.legibility.value,
        "duplicate_of": None if receipt.duplicate_of is None else str(receipt.duplicate_of),
        "receipt_is_inconsistent": receipt.receipt_is_inconsistent,
        "totals": {
            "subtotal": money(receipt.subtotal),
            "tax": money(receipt.tax_total),
            "discount": money(receipt.discount_total),
            "total": money(receipt.total),
            "tender": money(receipt.tender_amount),
            "change": money(receipt.change_amount),
        },
        "line_items": [_line_item(item) for item in receipt.line_items],
        "findings": [_finding(finding) for finding in findings],
    }
