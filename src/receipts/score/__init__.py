"""Confidence scoring and routing (spec §12).

Folds the validation report plus the triage and self-consistency signals into a
single confidence ``Decimal`` and routes it to a review status/priority.
"""

from __future__ import annotations

from .confidence import (
    ReceiptStatus,
    explain_confidence,
    route,
    score_confidence,
)

__all__ = [
    "ReceiptStatus",
    "explain_confidence",
    "route",
    "score_confidence",
]
