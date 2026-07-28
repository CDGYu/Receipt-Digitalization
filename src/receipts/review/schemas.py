"""Pydantic envelopes for the review API's read and write routes (P4.T4/T5, spec §14.9).

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

``CorrectionPatch`` (P4.T5, ``PATCH /receipts/{id}``) is the one write-side
exception to the "type only the envelope" rule above: every money field it
declares is typed ``str | int | None`` specifically so a JSON *number* fails
request validation before it ever reaches
:func:`receipts.persist.repository.apply_corrections` -- see its docstring.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictInt

__all__ = [
    "CorrectionPatch",
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


# --------------------------------------------------------------------------- #
# Write routes (P4.T5)
# --------------------------------------------------------------------------- #


def _reject_json_float(value: Any) -> Any:
    """Refuse a JSON *number* on a money field before FastAPI's own union
    validation runs (ADR-0001).

    ``json.loads`` renders any number written with a decimal point as a
    Python ``float`` -- ``1234.56`` in the request body arrives here as
    ``1234.56`` the float, not the string ``"1234.56"``. Without this guard
    the ``str | int | None`` union below would simply fail with pydantic's
    generic "no branch matched" error, which still rejects the float (a
    ``float`` satisfies neither ``str`` nor ``StrictInt``) but never says
    *why* it must be a string. Running this ``mode="before"`` gives the
    caller one explicit, correctly-worded reason instead of the losing
    union branch's generic message.

    ``_coerce_money`` in :mod:`receipts.persist.repository` refuses a float
    too -- it is the last line of defence for any correction that reaches it
    by a path this model does not type (a dotted top-level key such as
    ``"line_items[5].qty"`` bypasses the nested models below and is not
    protected by this validator). This function is the *first* line of
    defence, catching the documented, nested shape before the request is
    even accepted.
    """
    if isinstance(value, float):
        raise ValueError(
            "send money as a string; a JSON number is a float and cannot "
            "represent an exact amount"
        )
    return value


#: A money field on the PATCH body: a string amount, a whole-dollar int, or
#: absent -- never a JSON float. ``StrictInt`` (not plain ``int``) so a
#: whole-number float such as ``1234.0`` cannot slip through lax-mode int
#: coercion and defeat the guard above.
MoneyPatch = Annotated[str | StrictInt | None, BeforeValidator(_reject_json_float)]

#: Every nested patch model uses ``extra="allow"``: an unrecognised field is
#: not this layer's problem to reject. It passes through to
#: :func:`receipts.persist.repository.apply_corrections`, whose closed
#: ``_RECEIPT_FIELDS``/``_LINE_ITEM_FIELDS`` maps raise ``ValueError`` (400)
#: for a path that cannot be applied -- one error currency for "unknown
#: field", not two (422 here, 400 there) depending on nesting depth.
_PATCH_MODEL_CONFIG = ConfigDict(extra="allow")


class _MerchantPatch(BaseModel):
    model_config = _PATCH_MODEL_CONFIG

    name: str | None = None


class _ReceiptMetaPatch(BaseModel):
    model_config = _PATCH_MODEL_CONFIG

    number: str | None = None
    date: str | None = None
    date_raw: str | None = None
    time: str | None = None
    currency: str | None = None


class _TotalsPatch(BaseModel):
    model_config = _PATCH_MODEL_CONFIG

    subtotal: MoneyPatch = None
    tax: MoneyPatch = None
    discount: MoneyPatch = None
    total: MoneyPatch = None
    tender: MoneyPatch = None
    change: MoneyPatch = None


class _PaymentPatch(BaseModel):
    model_config = _PATCH_MODEL_CONFIG

    method: str | None = None
    card_last4: str | None = None


class _MetaPatch(BaseModel):
    model_config = _PATCH_MODEL_CONFIG

    is_handwritten: bool | None = None
    legibility: str | None = None
    receipt_is_inconsistent: bool | None = None


class _LineItemPatch(BaseModel):
    model_config = _PATCH_MODEL_CONFIG

    position: int | None = None
    description_raw: str | None = None
    sku: str | None = None
    qty: MoneyPatch = None
    unit: str | None = None
    unit_price: MoneyPatch = None
    line_total: MoneyPatch = None


class CorrectionPatch(BaseModel):
    """The ``PATCH /receipts/{id}`` body: a nested patch, dotted or not.

    Mirrors the shape :func:`receipts.persist.repository.flatten` already
    understands (nested dicts and lists, or dotted paths) and the closed set
    of correctable paths in ``_RECEIPT_FIELDS``/``_LINE_ITEM_FIELDS`` --
    ``merchant.name``, ``receipt.*``, ``totals.*``, ``payment.*``,
    ``meta.*``, and ``line_items[i].*``. A field this model does not name
    (an unmapped one, or a dotted top-level key like
    ``"totals.total"``) is not rejected here: ``extra="allow"`` at every
    level lets it through unchanged, and
    :func:`~receipts.persist.repository.apply_corrections` is the one place
    that decides whether a field path is known, raising ``ValueError`` (400)
    for one it cannot map. That keeps "unknown field" a single error
    currency instead of a 422 for some shapes and a 400 for others.

    The route reads the patch with
    ``patch.model_dump(exclude_unset=True, mode="json")`` -- ``exclude_unset``
    so a field a client never mentioned is not confused with one explicitly
    set to ``null``, and so an all-default body (nothing set) becomes ``{}``,
    which ``apply_corrections`` accepts as "no changes, still mark
    reviewed" rather than raising.
    """

    model_config = _PATCH_MODEL_CONFIG

    merchant: _MerchantPatch | None = None
    receipt: _ReceiptMetaPatch | None = None
    totals: _TotalsPatch | None = None
    payment: _PaymentPatch | None = None
    meta: _MetaPatch | None = None
    line_items: list[_LineItemPatch] | None = None
