"""JSON serializers for the review API's read and write routes (P4.T4/T5, spec §14.9).

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

:func:`build_export_rows` (P4.T5) is the write side's one addition: it turns
persisted ``Receipt`` rows back into the ``(ReceiptExtraction,
ReceiptExportRow)`` pairs :func:`receipts.export.xlsx.export_workbook` wants.
It lives here, not in :mod:`receipts.export.xlsx`, so that module stays
decoupled from the ORM (ADR-0010) -- the serializer sits on the API side of
that boundary.
"""

from __future__ import annotations

import uuid
from datetime import date as date_cls
from datetime import time as time_cls
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..export.xlsx import ReceiptExportRow
from ..extract.schema import Buyer as ExtractBuyer
from ..extract.schema import ExtractionMeta, ReceiptExtraction, ReceiptMeta, Totals
from ..extract.schema import LineItem as ExtractLineItem
from ..extract.schema import Merchant as ExtractMerchant
from ..extract.schema import Modifier as ExtractModifier
from ..extract.schema import Payment as ExtractPayment
from ..persist.models import Correction, LineItem, Receipt, ReviewTask, ValidationFinding
from ..score.confidence import ReceiptStatus
from ..validate.report import Severity
from .signing import sign_url

__all__ = [
    "build_export_rows",
    "correction_summary",
    "money",
    "query_export_receipts",
    "receipt_detail",
    "receipt_summary",
]

#: Receipt statuses ``query_export_receipts`` leaves out unless ``status=``
#: names one of them explicitly (ambiguity resolution #4): a pending row is
#: an upload in flight rather than a transaction, and a rejected one is a
#: duplicate the pipeline deliberately keeps out of exports.
_EXPORT_EXCLUDED_BY_DEFAULT = frozenset({ReceiptStatus.PENDING, ReceiptStatus.REJECTED})


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


def _iso_time(value: time_cls | None) -> str | None:
    """A ``time`` column as ISO text -- ``isoformat()``, not ``"%H:%M"``.

    ``receipt.time`` is one of the paths ``apply_corrections`` accepts
    (``_RECEIPT_FIELDS`` in
    :mod:`receipts.persist.repository`), so whatever this renders is what a
    reviewer's screen sends back through ``PATCH``. ``_coerce_time`` parses it
    with :meth:`datetime.time.fromisoformat`, which reads ``isoformat()``'s
    output exactly -- seconds and microseconds included -- while
    ``strftime("%H:%M")`` (what :func:`_export_extraction` uses, one-way, into
    a spreadsheet cell) silently truncates them. Measured: for
    ``time(14, 30, 45)``, ``_coerce_time(v.isoformat()) == v`` while
    ``_coerce_time(v.strftime("%H:%M")) != v``. A lossy rendering would mean a
    reviewer who merely *confirms* an untouched receipt rewrites its stored
    time and gets a ``corrections`` row for an edit they never made.
    """
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


def correction_summary(correction: Correction) -> dict[str, Any]:
    """One ``corrections`` row as JSON (``GET /receipts/{id}/corrections``).

    ``receipt_id`` is deliberately absent: the route is nested under the
    receipt, so every row on a page shares the id already in the request path.

    ``value_before``/``value_after`` pass through as text and do **not** go
    through :func:`money`. They were rendered by ``_as_text`` at write time and
    the columns are ``Text``; re-parsing a stored string to re-render it would
    invent precision the audit trail never recorded, and most ``field_path``
    values are not money at all. ``None`` means the field had no value on that
    side of the change -- not ``"0"``, not empty (ADR-0027 section 5).
    """
    return {
        "id": str(correction.id),
        "field_path": correction.field_path,
        "value_before": correction.value_before,
        "value_after": correction.value_after,
        "corrected_by": correction.corrected_by,
        "created_at": correction.created_at.isoformat(),
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

    **Every column a reviewer may correct is returned here** (P5.T3b).
    ``_RECEIPT_FIELDS`` in :mod:`receipts.persist.repository` and this
    function are two independently written lists of the same columns, and at
    P5.T3b they had drifted: ``receipt_number``, ``txn_time`` and
    ``payment_method`` were correctable but had no key here at all, so a
    reviewer could overwrite what the machine read without ever being shown
    it. No count is quoted, deliberately -- the pair grows (``buyer.name`` and
    ``buyer.tax_id`` are the most recent additions) and a number here rots
    silently. ``tests/test_api_read.py::
    test_every_correctable_receipt_column_is_readable_in_the_detail`` is what
    binds the two lists together, and it fails on the next unpaired addition.

    ``payment_method`` is redacted on the way *in*. ``save_extraction`` puts
    **every** ``str`` value it writes through ``redact_pan`` in one blanket
    pass rather than an enumerated column list (see its own comment on why the
    enumerated list was abandoned), and ``_plan_change`` redacts every coerced
    text value a reviewer submits, so the correction path is covered too.
    Those are the only two writers of the column under ``src/``
    (``create_pending_receipt``, the sole other ``Receipt(...)`` construction,
    leaves it NULL), so what leaves here is what §18 already permits to be
    stored: a PAN read off the card line reaches this key as
    ``"VISA ************1111"``. Measured 2026-08-18 through
    ``save_extraction``, one PAN seeded per field: ``merchant_name_raw``,
    ``buyer_name_raw``, ``buyer_tax_id``, ``receipt_number``, ``date_raw`` and
    ``payment_method`` all came back masked and none in the clear -- six
    columns, which is why this paragraph no longer names two.

    **That sentence is a claim about every way a card line is written, so the
    measurement behind it is a table rather than an example.** An earlier
    version of this note was measured on the unseparated form alone and
    generalised from it; at the time it was written, a PAN separated by
    anything but a space or a hyphen reached this key whole. Re-measured
    through the route, one fresh receipt per row --
    ``PATCH {"payment": {"method": <sent>}}`` then ``GET /receipts/{id}``:

        '4111111111111111'      -> '************1111'
        '4111 1111 1111 1111'   -> '************1111'
        '4111-1111-1111-1111'   -> '************1111'
        '4111.1111.1111.1111'   -> '************1111'
        '4111_1111_1111_1111'   -> '************1111'
        '4111/1111/1111/1111'   -> '************1111'
        '4111,1111,1111,1111'   -> '************1111'
        '4111 1111-1111.1111'   -> '************1111'
        '3782 822463 10005'     -> '***********0005'
        '3782.822463.10005'     -> '***********0005'
        '411111111111'          -> '411111111111'      (12 digits, not a PAN)

    The ``receipts`` row and ``corrections.value_after`` hold the same string
    as the body in every row above; all three were read, not inferred from one
    another. Asserted at the layer below by
    ``test_save_extraction_redacts_a_pan_the_model_put_in_free_text``,
    ``test_apply_corrections_redacts_a_pan_typed_into_a_free_text_field`` and
    ``test_apply_corrections_redacts_a_pan_on_every_reviewer_typed_text_path``,
    and at this layer by
    ``test_a_dotted_pan_is_masked_in_the_row_the_body_and_the_audit_copy``.

    The guarantee therefore belongs to the repository layer, not to the
    column: a test that seeds a row by constructing ``Receipt(...)`` directly
    bypasses both writers and can put anything it likes in this key.
    """
    return {
        "id": str(receipt.id),
        "status": receipt.status.value,
        "confidence": money(receipt.confidence),
        "confidence_reasons": receipt.confidence_reasons,  # verbatim: None stays None
        "merchant_name_raw": receipt.merchant_name_raw,
        # Nested for the same reason ``totals`` is: the buyer is a schema object
        # (:class:`receipts.extract.schema.Buyer`) and the paths a reviewer's
        # edit comes back on are ``buyer.name``/``buyer.tax_id``, so the key
        # path a client reads is the key path it writes. Always an object, even
        # when both columns are NULL -- the form still has two fields to draw,
        # and a missing key is a client-side crash where ``null`` is a blank.
        "buyer": {"name": receipt.buyer_name_raw, "tax_id": receipt.buyer_tax_id},
        "receipt_number": receipt.receipt_number,
        "txn_date": _iso_date(receipt.txn_date),
        "date_raw": receipt.date_raw,
        "txn_time": _iso_time(receipt.txn_time),
        "currency": receipt.currency,
        "created_at": receipt.created_at.isoformat(),
        "payment_method": receipt.payment_method,
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


# --------------------------------------------------------------------------- #
# Export (P4.T5, ``GET /export/xlsx``)
# --------------------------------------------------------------------------- #


def query_export_receipts(
    session: Session,
    *,
    status: ReceiptStatus | None,
    merchant_id: uuid.UUID | None,
    date_from: date_cls | None,
    date_to: date_cls | None,
    min_confidence: Decimal | None,
    limit: int,
) -> list[Receipt]:
    """Receipts for ``GET /export/xlsx``: the same filters as
    :func:`~receipts.persist.repository.query_receipts`, plus the
    export-only exclusion of ``PENDING``/``REJECTED`` unless ``status``
    names one of them explicitly.

    A dedicated query rather than a call to ``query_receipts`` because that
    function's ``status`` filter is a single equality -- it has no way to
    express "every status except these two" -- and the export exclusion
    needs exactly that. Ordered ``created_at`` then ``id``, matching
    ``query_receipts``, so the two entry points never disagree about paging
    order.

    ``line_items`` and ``merchant`` are eager-loaded with ``selectinload``
    (fix round 1, F3): both are default-lazy relationships
    (:mod:`receipts.persist.models`), and
    :func:`receipts.review.serializers.build_export_rows` touches both for
    every row it builds (line items to reconstruct the extraction, merchant
    for the canonical name). Left lazy, each access is its own SELECT --
    an N+1 that a two- or three-receipt test run never surfaces but that
    turns into 5,000-10,000 round trips at the route's own
    ``_EXPORT_MAX_ROWS`` design point. One batched ``IN`` query per
    relationship, issued here, is what keeps the query count independent of
    how many receipts match.
    """
    query = (
        select(Receipt)
        .options(selectinload(Receipt.line_items), selectinload(Receipt.merchant))
    )
    if status is not None:
        query = query.where(Receipt.status == status)
    else:
        query = query.where(Receipt.status.not_in(_EXPORT_EXCLUDED_BY_DEFAULT))
    if merchant_id is not None:
        query = query.where(Receipt.merchant_id == merchant_id)
    if date_from is not None:
        query = query.where(Receipt.txn_date >= date_from)
    if date_to is not None:
        query = query.where(Receipt.txn_date <= date_to)
    if min_confidence is not None:
        query = query.where(Receipt.confidence >= min_confidence)

    query = query.order_by(Receipt.created_at, Receipt.id).limit(limit)
    return list(session.scalars(query))


def _export_extraction(receipt: Receipt) -> ReceiptExtraction:
    """Rebuild a :class:`~receipts.extract.schema.ReceiptExtraction` from one
    persisted ``Receipt`` (plus its ``line_items``), for
    :func:`receipts.export.xlsx.export_workbook`.

    **Lossy against the full extraction schema.** ``tax_breakdown``,
    ``prices_include_tax``, ``meta.ambiguous_fields``,
    ``meta.unreadable_regions``, ``meta.notes``, and the merchant's
    ``address``/``tax_id``/``phone``/``branch`` are not columns on
    ``receipts`` -- they were never persisted past the extraction run that
    produced them, so there is nothing here to rebuild them from. They are
    left at their schema defaults (``[]``/``None``/``False``), never
    invented.

    **The buyer is the counter-example, and is rebuilt whole.** Reading the
    paragraph above, a merchant whose ``tax_id`` cannot be rebuilt invites the
    assumption that the buyer's cannot either; it can.
    :class:`~receipts.extract.schema.Buyer` has exactly two fields, ``name``
    and ``tax_id``, and both are columns on ``receipts`` -- it deliberately
    carries no ``address``, so there is no third field to lose. Same for
    ``LineItem.is_template_row``, which is a ``line_items`` column and is
    copied straight across: the export needs it to keep a blank pre-printed
    row out of the ledger, and a rebuild that dropped it would leave that
    filter nothing to filter on.

    **Lossless for every column §13 (and this codebase's
    ``export/xlsx.py``) actually writes to a cell**, because the database is
    the source of truth and Excel is output only (ADR-0010): every one of
    ``_RECEIPT_HEADERS`` / ``_LINEITEM_HEADERS`` / ``_REVIEW_HEADERS`` /
    ``_SUMMARY_HEADERS`` in :mod:`receipts.export.xlsx` reads either directly
    off a ``receipts``/``line_items`` column reproduced here, or off the
    :class:`~receipts.export.xlsx.ReceiptExportRow` companion this function's
    caller (:func:`build_export_rows`) builds alongside it.
    """
    return ReceiptExtraction(
        merchant=ExtractMerchant(name=receipt.merchant_name_raw),
        # Rebuilt in full, unlike the merchant: ``Buyer`` has exactly the two
        # fields ``receipts`` stores (it deliberately has no ``address``), so
        # nothing about the buyer is lost here.
        buyer=ExtractBuyer(name=receipt.buyer_name_raw, tax_id=receipt.buyer_tax_id),
        receipt=ReceiptMeta(
            number=receipt.receipt_number,
            date=receipt.txn_date.isoformat() if receipt.txn_date is not None else None,
            date_raw=receipt.date_raw,
            time=receipt.txn_time.strftime("%H:%M") if receipt.txn_time is not None else None,
            currency=receipt.currency,
        ),
        line_items=[
            ExtractLineItem(
                position=item.position,
                description_raw=item.description_raw,
                sku=item.sku,
                qty=item.qty,
                unit=item.unit,
                unit_price=item.unit_price,
                line_total=item.line_total,
                modifiers=[ExtractModifier(**modifier) for modifier in item.modifiers],
                # Without this the export cannot tell a blank pre-printed row
                # from a purchase, and a ledger that lists something nobody
                # bought is a defect no downstream filter can undo.
                is_template_row=item.is_template_row,
            )
            for item in receipt.line_items
        ],
        totals=Totals(
            subtotal=receipt.subtotal,
            tax=receipt.tax_total,
            discount=receipt.discount_total,
            total=receipt.total,
            tender=receipt.tender_amount,
            change=receipt.change_amount,
        ),
        payment=ExtractPayment(method=receipt.payment_method, card_last4=receipt.card_last4),
        meta=ExtractionMeta(
            is_handwritten=receipt.is_handwritten,
            legibility=receipt.legibility,
            receipt_is_inconsistent=receipt.receipt_is_inconsistent,
        ),
    )


def _export_image_url(receipt_id: uuid.UUID, *, secret: str, ttl_s: int) -> str:
    """A signed link to the receipt's original image, valid for ``ttl_s``.

    Same construction as ``GET /receipts/{id}/image`` in ``review/api.py``
    (``sign_url`` over ``"{receipt_id}|{variant}"``, a relative link to the
    unauthenticated blob sub-route) -- deliberately the *original*, not
    ``processed``, since export is a financial record and the original is
    what was actually photographed. Callers who open the workbook get
    ``ttl_s`` (``settings.export_image_url_ttl_s``, a day by default) rather
    than the few minutes the review screen's own links get, because anyone
    holding the file can open the links until they expire -- see the
    export route's docstring.

    ``secret`` may be ``None`` on :func:`build_export_rows` -- this function
    is simply not called in that case. The CLI can be run on a box with no
    ``SESSION_SECRET`` -- it needs no session -- and an unsigned or
    fabricated link would be worse than an empty cell: ``ReceiptExportRow``'s
    contract is that whatever the caller does not know stays empty rather
    than being invented.
    """
    signature, exp = sign_url(f"{receipt_id}|original", secret=secret, ttl_s=ttl_s)
    return f"/receipts/{receipt_id}/image/blob?variant=original&exp={exp}&sig={signature}"


def build_export_rows(
    session: Session,
    receipts: list[Receipt],
    *,
    secret: str | None,
    image_url_ttl_s: int,
) -> tuple[list[ReceiptExtraction], list[ReceiptExportRow]]:
    """The ``(ReceiptExtraction, ReceiptExportRow)`` pairs ``export_workbook`` wants.

    ``receipts[i]`` and the two returned lists' ``i``-th entries always
    describe the same row -- callers must not reorder one list without the
    other.

    Two batched joins run *in this function*, not one query per receipt:

      * ``review_tasks`` -- the ``reason``/``priority`` a receipt was routed
        to review with, keyed by ``receipt_id`` (unique per §6.7, so at most
        one task per receipt). ``None``/``None`` when a receipt was never
        queued (auto-approved, or already reviewed and the task closed and
        never reopened).
      * ``validation_findings`` -- folded into
        :attr:`~receipts.export.xlsx.ReceiptExportRow.has_unresolved_error`,
        true when any ``ERROR``-severity finding for the receipt is not
        ``resolved_by_repair`` (mirrors the ``report.findings`` computation
        :class:`~receipts.export.xlsx.ReceiptExportRow`'s own docstring
        describes, adapted because export has ORM rows, not a
        ``ValidationReport``).

    **This function is not, on its own, the whole batching story (fix
    round 1, F3).** :func:`_export_extraction` also touches
    ``receipt.line_items`` for every receipt, and this function touches
    ``receipt.merchant`` for the canonical name -- both default-lazy
    relationships (:mod:`receipts.persist.models`). Left lazy, those are a
    second and third N+1 that a docstring claiming "two batched joins" was
    papering over. Avoiding them is the *caller's* responsibility: pass in
    ``receipts`` that were already loaded with ``selectinload(Receipt.
    line_items)`` and ``selectinload(Receipt.merchant)``, which is exactly
    what :func:`query_export_receipts` does. This function cannot enforce
    that itself -- it only ever sees the list it is handed, after the query
    already ran.

    Every image link is signed with ``secret``/``image_url_ttl_s`` -- the
    caller passes ``settings.session_secret`` and
    ``settings.export_image_url_ttl_s`` so the links this function mints
    verify against the same secret the blob route checks and expire on the
    export-specific (longer) TTL, not the review screen's.

    ``secret`` may be ``None``. The CLI can be run on a box with no
    ``SESSION_SECRET`` -- it needs no session -- and an unsigned or
    fabricated link would be worse than an empty cell: ``ReceiptExportRow``'s
    contract is that whatever the caller does not know stays empty rather
    than being invented. When ``secret`` is ``None``, :func:`_export_image_url`
    is not called and the row's ``image_url`` stays ``None``.
    """
    if not receipts:
        return [], []

    ids = [receipt.id for receipt in receipts]

    tasks_by_receipt: dict[uuid.UUID, ReviewTask] = {
        task.receipt_id: task
        for task in session.scalars(select(ReviewTask).where(ReviewTask.receipt_id.in_(ids)))
    }

    findings_by_receipt: dict[uuid.UUID, list[ValidationFinding]] = {}
    for finding in session.scalars(
        select(ValidationFinding).where(ValidationFinding.receipt_id.in_(ids))
    ):
        findings_by_receipt.setdefault(finding.receipt_id, []).append(finding)

    extractions: list[ReceiptExtraction] = []
    rows: list[ReceiptExportRow] = []
    for receipt in receipts:
        extractions.append(_export_extraction(receipt))

        task = tasks_by_receipt.get(receipt.id)
        findings = findings_by_receipt.get(receipt.id, [])
        has_unresolved_error = any(
            finding.severity is Severity.ERROR and not finding.resolved_by_repair
            for finding in findings
        )

        rows.append(
            ReceiptExportRow(
                receipt_id=str(receipt.id),
                status=receipt.status,
                confidence=receipt.confidence,
                review_reason=task.reason if task is not None else None,
                review_priority=task.priority if task is not None else None,
                has_unresolved_error=has_unresolved_error,
                image_url=(
                    None
                    if secret is None
                    else _export_image_url(receipt.id, secret=secret, ttl_s=image_url_ttl_s)
                ),
                merchant_name=(
                    receipt.merchant.canonical_name if receipt.merchant is not None else None
                ),
            )
        )

    return extractions, rows
