"""Pydantic envelopes for the review API's read routes (P4.T4, spec §14.9).

A receipt's own payload -- ``receipt_summary`` / ``receipt_detail`` in
:mod:`receipts.review.serializers` -- is typed here only as
``dict[str, Any]``. Its real shape (line items, findings, ``totals``) is
proven by ``tests/test_api_read.py`` against the actual serializer output;
redeclaring every field as a second, parallel Pydantic model would only be
one more place for the two to drift apart, and the drift would be silent
until a field disagreed.

The envelopes *around* a receipt -- the list page, the metrics document, the
error body -- are typed in full, and deliberately: every ratio and amount
that reaches JSON does so as a ``str`` (ADR-0001, ``money()``), and giving
``auto_approval_rate`` the type ``str | None`` here means a future bug that
lets a ``Decimal`` or a ``float`` leak into it fails loudly as a
``ResponseValidationError`` instead of silently shipping a JSON number.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = [
    "ErrorBody",
    "ErrorDetail",
    "HealthStatus",
    "MetricsResponse",
    "QueueStatsOut",
    "ReceiptListResponse",
    "ThresholdsOut",
]


class HealthStatus(BaseModel):
    """``GET /health`` -- liveness only, nothing about the deployment."""

    status: str


class ErrorDetail(BaseModel):
    message: str


class ErrorBody(BaseModel):
    """The one error shape every handler in ``_install_error_handlers`` uses."""

    error: ErrorDetail


class ReceiptListResponse(BaseModel):
    """One page of :func:`receipt_summary` rows (``GET /receipts``).

    ``has_more`` is read off the extra row a ``limit + 1`` fetch returns, not
    a ``COUNT(*)`` -- see ``_install_read_routes``.
    """

    items: list[dict[str, Any]]
    has_more: bool


class QueueStatsOut(BaseModel):
    """:class:`receipts.review.queue.QueueStats`, reshaped for JSON."""

    open: int
    in_progress: int
    done: int
    total: int
    by_priority: dict[int, int]


class ThresholdsOut(BaseModel):
    """The two routing thresholds (:mod:`receipts.score.thresholds`), as strings."""

    auto_approve: str
    review: str


class MetricsResponse(BaseModel):
    """``GET /metrics``.

    ``auto_approval_rate`` is ``None`` when no receipt has reached a terminal
    routing outcome yet (``auto_approved + needs_review + reviewed == 0``) --
    an undefined rate, not a ``0`` or a ``1.0`` masquerading as one. See the
    module docstring on why that null is load-bearing.
    """

    counts_by_status: dict[str, int]
    auto_approval_rate: str | None
    queue: QueueStatsOut
    thresholds: ThresholdsOut
