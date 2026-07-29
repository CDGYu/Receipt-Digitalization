"""Reads and writes over the seven-table model (spec §14.8).

Every function takes an explicit :class:`~sqlalchemy.orm.Session` as its first
argument. That is dependency injection, not ceremony: it keeps this layer unit
testable against an in-memory SQLite database, and it keeps the transaction
boundary where it belongs -- with the caller. **The caller commits.** The one
documented exception is :func:`apply_corrections`, which is specified as
transactional (spec §14.8) and therefore commits or rolls back itself.

Three rules from the spec are load-bearing here:

  * **Money is ``Decimal``, never ``float``** (ADR-0001, §18). Amounts are copied
    from the extraction to the ``Numeric`` columns untouched, and a reviewer's
    correction that arrives as a ``float`` is *refused* rather than quietly
    converted.
  * **Never invent a date.** An ISO ``receipt.date`` becomes ``txn_date``; a
    missing or unparseable one leaves ``txn_date`` NULL and keeps the printed
    string in ``date_raw``, because a wrong date is worse than a missing one.
  * **Only ever store the last four card digits** (§18). Three independent
    defences: :func:`_last4` on the way into ``receipts.card_last4``,
    :func:`redact_pan` over everything written to
    ``extraction_runs.raw_response``, and :func:`redact_pan` again over every
    free-text value on its way into a column -- whether the model produced it
    (:func:`save_extraction`) or a reviewer typed it (:func:`_plan_change`,
    which also covers the ``corrections`` audit copy).
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime
from datetime import time as time_cls
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..extract.clients.base import VLMResponse
from ..extract.paths import flatten
from ..extract.schema import Legibility, ReceiptExtraction
from ..ingest.ingest import ReceiptJob
from ..score.confidence import ReceiptStatus
from ..validate.report import ValidationReport
from .models import (
    Correction,
    ExtractionRun,
    LineItem,
    PassName,
    Receipt,
    ValidationFinding,
)

__all__ = [
    "apply_corrections",
    "create_pending_receipt",
    "find_duplicate_by_content",
    "find_duplicate_by_phash",
    "get_findings",
    "get_receipt",
    "mark_duplicate",
    "query_receipts",
    "redact_pan",
    "save_extraction",
    "save_extraction_run",
    "save_findings",
]

# --------------------------------------------------------------------------- #
# PAN redaction (§18: "Only ever store the last four digits")
# --------------------------------------------------------------------------- #

#: A card number is 13-19 digits. Anything shorter is not a PAN -- a 4-digit
#: ``card_last4``, a money amount, a year -- and must be left alone.
_PAN_MIN_DIGITS = 13
_PAN_MAX_DIGITS = 19

#: Matches a PAN in the three shapes a model actually emits: unseparated, the
#: usual 4-4-4-N grouping, and Amex's 4-6-5. Separators may be any mix of spaces
#: and hyphens, because OCR of a worn thermal print reads one of them
#: differently from the rest (``4111 1111-1111 1111``). Three deliberate design
#: choices keep it from firing on things that merely look numeric:
#:
#:   * every group in a separated shape is 4-6 digits wide, so a run of small
#:     space-separated numbers -- ``"2 18.00 3 20.00 ..."`` -- matches nothing,
#:     and :func:`_mask_pan` re-checks the total digit count either way;
#:   * ``(?<!\d)`` refuses a match that starts mid-number, and ``(?<!\d\.)``
#:     refuses one that starts just after a *decimal point*, so the fraction of
#:     ``0.4111111111111111`` is not mistaken for a card number. A period that is
#:     **not** preceded by a digit is label punctuation, not a decimal point --
#:     ``CARD NO.``, ``ACCT NO.``, ``REF.`` is exactly what a receipt prints, and
#:     the PAN behind it must still be masked;
#:   * the trailing lookaheads refuse a match that continues into more digits or
#:     into a decimal fraction, so ``1234567890123.45`` stays a number and a
#:     longer digit run is never partially masked.
_PAN_RE = re.compile(
    r"""
    (?<!\d)(?<!\d\.)                          # not mid-number, not a decimal fraction
    (?:
        \d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,4}    # 4-4-4-N (Visa, Mastercard, ...)
      | \d{4}[ -]\d{6}[ -]\d{5}               # 4-6-5 (Amex)
      | \d{13,19}                             # unseparated
    )
    (?!\d)(?!\.\d)                            # ... and not the integer part
    """,
    re.VERBOSE,
)


def _mask_pan(match: re.Match[str]) -> str:
    """Replace a matched PAN with a mask that keeps only the last four digits."""
    digits = re.sub(r"\D", "", match.group(0))
    if not _PAN_MIN_DIGITS <= len(digits) <= _PAN_MAX_DIGITS:
        return match.group(0)
    return "*" * (len(digits) - 4) + digits[-4:]


def _redact_number(value: int | float, text: str) -> Any:
    """Mask a numeric scalar whose *digits* look like a PAN, else return it as is.

    A model that emitted the card number as a JSON number would otherwise slip
    past. The original object is returned untouched when nothing matched, so an
    ordinary amount keeps its type as well as its value.
    """
    masked = _PAN_RE.sub(_mask_pan, text)
    return masked if masked != text else value


def redact_pan(value: Any) -> Any:
    """Strip full card numbers out of ``value``, keeping only the last four.

    Pure and recursive: walks ``dict`` **keys and values**, ``list``/``tuple``
    items, ``set``/``frozenset`` members, and strings, returning new containers
    and never mutating the input. Container types are preserved. Numeric scalars
    are inspected too -- an ``int``, or a ``float`` holding a whole number, is
    masked when its digits look like a PAN -- and every other scalar passes
    through unchanged.

    What it deliberately does *not* touch, because a rule that fires when it
    should not is worse than no rule: money (``1234.56``, and any ``float`` with
    a fractional part), a 4-digit ``card_last4``, a 16-character hash, dates, and
    phone-style numbers -- all are shorter than :data:`_PAN_MIN_DIGITS` digits,
    fail the separator grouping, or sit behind a decimal point. The one accepted
    false positive is a 13-19 digit *all-numeric* identifier, which is
    indistinguishable from a PAN by inspection.
    """
    if isinstance(value, str):
        return _PAN_RE.sub(_mask_pan, value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return _redact_number(value, str(value))
    if isinstance(value, float):
        # ``4111111111111111.0`` is a PAN that made a detour through a float;
        # ``1234.56`` is money and must survive untouched, so only a whole
        # number is inspected -- and a non-finite float has no digits at all.
        if not math.isfinite(value) or not value.is_integer():
            return value
        return _redact_number(value, str(int(value)))
    if isinstance(value, dict):
        return {redact_pan(key): redact_pan(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_pan(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_pan(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(redact_pan(item) for item in value)
    if isinstance(value, set):
        return {redact_pan(item) for item in value}
    return value


# --------------------------------------------------------------------------- #
# Small conversions
# --------------------------------------------------------------------------- #


def _json_safe(value: Any) -> Any:
    """Coerce ``value`` into something the JSON/JSONB columns can store.

    ``Decimal`` becomes a string (lossless, and it keeps money out of JSON's
    float representation); dates, times, and enums become their canonical text;
    pydantic models are dumped in JSON mode; anything else unrecognised falls
    back to ``str``. Run *before* :func:`redact_pan`, so redaction sees the final
    text of an object whose ``repr`` might contain a card number.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, (datetime, date_cls, time_cls)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _last4(value: str | None) -> str | None:
    """The last four digits of ``value``, or ``None`` when it holds no digits.

    The column is ``char(4)`` and §18 allows nothing more, so a model that put a
    full PAN in ``payment.card_last4`` loses everything but the tail here.
    """
    if value is None:
        return None
    digits = re.sub(r"\D", "", value)
    return digits[-4:] if digits else None


def _parse_iso_date(value: str | None) -> date_cls | None:
    """ISO ``YYYY-MM-DD`` to a ``date``; ``None`` when absent or unparseable.

    Returning ``None`` rather than guessing is the point: an ambiguous date must
    stay in ``date_raw`` (§18 -- a wrong date is worse than a missing one).
    """
    if not value:
        return None
    try:
        return date_cls.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_iso_time(value: str | None) -> time_cls | None:
    """``HH:MM`` to a ``time``; ``None`` when absent or unparseable."""
    if not value:
        return None
    try:
        return time_cls.fromisoformat(value.strip())
    except ValueError:
        return None


def _as_text(value: Any) -> str | None:
    """Render a column value for the ``corrections`` audit trail."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (datetime, date_cls, time_cls)):
        return value.isoformat()
    return str(value)


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


#: Statuses whose values a **human** owns. :func:`save_extraction` refuses to
#: write over a row in one of these, because a machine run that did would drop
#: the reviewer's correction, revert the receipt to a machine value the reviewer
#: had already rejected (and re-label it ``auto_approved``, so it exports as an
#: approved transaction), and leave the ``corrections`` audit trail contradicting
#: the row it describes -- three §18 violations from one silent overwrite.
#: ``REJECTED`` is deliberately absent: that state is the pipeline's own
#: duplicate marking, not a human decision.
_HUMAN_OWNED_STATUSES = frozenset({ReceiptStatus.REVIEWED})


def _reasons_json(pairs: list[tuple[str, Decimal]] | None) -> list[dict[str, str]] | None:
    """Encode explain_confidence pairs for the JSON column.

    Penalties are stored as strings: a JSON number is a float, and this column
    sits next to a Decimal score that a reviewer reads as an explanation of it.
    """
    if pairs is None:
        return None
    return [{"reason": reason, "penalty": str(penalty)} for reason, penalty in pairs]


def save_extraction(
    session: Session,
    job: ReceiptJob,
    extraction: ReceiptExtraction,
    report: ValidationReport,
    confidence: Decimal,
    status: ReceiptStatus,
    *,
    image_phash: str = "",
    merchant_id: uuid.UUID | None = None,
    confidence_reasons: list[tuple[str, Decimal]] | None = None,
) -> Receipt:
    """Map one extraction onto a ``receipts`` row plus its ``line_items`` rows.

    The row id is ``job.id`` -- the same id the image key was minted from -- so
    the blob, the receipt, and every audit row share one identifier. Money is
    copied across as ``Decimal`` without arithmetic; ``txn_date`` is filled only
    from a genuinely parseable ISO date, and the printed string is preserved in
    ``date_raw`` otherwise; ``card_last4`` keeps four digits at most.

    ``report`` is part of the §14.8 contract and is passed by the pipeline, but
    findings are deliberately *not* written here: they live in their own table so
    a repair pass can append its own and flag which of the originals it resolved.
    Call :func:`save_findings` next.

    **Update-or-insert on ``job.id``.** An upload writes a ``pending`` row via
    :func:`create_pending_receipt` before the worker ever runs, and a retried job
    may already have persisted a previous attempt; either way a row with this id
    can already exist, and re-inserting would collide on the primary key and lose
    the receipt on the way to recording it. The column values are built once and
    applied to whichever branch runs, so the insert and update paths cannot drift
    apart.

    **A row a human has already reviewed is never updated.** Since ``POST
    /upload`` writes the ``pending`` row before queueing, a reviewer can re-key a
    receipt off the paper while the queue is still backed up; the worker then
    arrives holding a machine extraction of the same id. Applying it would
    overwrite the reviewer's numbers, re-label the receipt ``auto_approved``, and
    leave the ``corrections`` rows describing values no longer in the row -- so
    this raises ``ValueError`` instead (ADR-0006's error currency), naming what
    the machine run produced. The pipeline turns that into a review task against
    the row it declined to touch, which is how the attempt stays visible without
    anything being silently dropped. This covers a reprocess trigger too, for the
    same reason and at the same place.

    Flushes (so ``id`` and the child rows exist) and returns the ORM object
    without committing -- the caller owns the transaction.
    """
    receipt_meta = extraction.receipt
    txn_date = _parse_iso_date(receipt_meta.date)
    date_raw = receipt_meta.date_raw
    if txn_date is None and not date_raw and receipt_meta.date:
        # Nothing is silently dropped: an unparseable date is kept verbatim.
        date_raw = receipt_meta.date

    fields: dict[str, Any] = dict(
        merchant_id=merchant_id,
        # §18: a PAN the model read off the card line and put in a free-text
        # field must not reach a column either. ``redact_pan`` keeps the last
        # four and is silent on everything that merely looks numeric.
        merchant_name_raw=redact_pan(extraction.merchant.name),
        receipt_number=receipt_meta.number,
        txn_date=txn_date,
        txn_time=_parse_iso_time(receipt_meta.time),
        date_raw=date_raw,
        currency=receipt_meta.currency,
        subtotal=extraction.totals.subtotal,
        tax_total=extraction.totals.tax,
        discount_total=extraction.totals.discount,
        total=extraction.totals.total,
        tender_amount=extraction.totals.tender,
        change_amount=extraction.totals.change,
        payment_method=redact_pan(extraction.payment.method),
        card_last4=_last4(extraction.payment.card_last4),
        is_handwritten=extraction.meta.is_handwritten,
        legibility=extraction.meta.legibility,
        confidence=confidence,
        status=status,
        image_key=job.image_key,
        image_phash=image_phash,
        receipt_is_inconsistent=extraction.meta.receipt_is_inconsistent,
    )

    existing = session.get(Receipt, job.id)
    if existing is None:
        receipt = Receipt(id=job.id, **fields)
    elif existing.status in _HUMAN_OWNED_STATUSES:
        raise ValueError(
            f"receipt {job.id} has already been reviewed by a human "
            f"(status {existing.status.value}) and a machine run must not "
            f"overwrite it; this run produced status={status.value}, "
            f"total={extraction.totals.total}, merchant={extraction.merchant.name!r}"
        )
    else:
        # A PENDING row written at upload, or a retry of a job that already
        # persisted. Update in place: re-inserting would collide on the primary
        # key and lose the receipt on the way to recording it.
        receipt = existing
        for column, value in fields.items():
            setattr(receipt, column, value)
        # The previous line items must actually be gone before the new ones are
        # inserted: cascade="all, delete-orphan" queues them for deletion, but a
        # single flush does not guarantee the DELETEs precede the new INSERTs,
        # and a new item can legitimately reuse a position an old item still
        # occupies -- which would collide against
        # ``uq_line_items_receipt_position`` if both landed in one flush.
        receipt.line_items = []
        session.flush()

    receipt.confidence_reasons = _reasons_json(confidence_reasons)
    receipt.line_items = _build_line_items(extraction)

    session.add(receipt)
    session.flush()
    return receipt


def create_pending_receipt(session: Session, job: ReceiptJob) -> Receipt:
    """Write the ``pending`` row an upload creates before the worker runs.

    The receipt is visible and queryable the moment it is accepted, so a job the
    queue loses (an evicted Redis entry, a worker killed before it persisted)
    shows up as a stuck ``pending`` row instead of leaving a blob on disk and
    nothing in the database -- the vanished job §18 forbids.

    ``image_phash`` is empty: the perceptual hash is computed in the worker's
    preprocess stage, and inventing one here would be a value nothing read off
    the image. :func:`find_duplicate_by_phash` skips empty hashes, so a pending
    row can never become the original a later upload is marked a duplicate of.

    Flushes; does not commit. ``ValueError`` if the id is already taken.
    """
    if session.get(Receipt, job.id) is not None:
        raise ValueError(f"a receipt with id {job.id} already exists")
    receipt = Receipt(
        id=job.id,
        image_key=job.image_key,
        image_phash="",
        status=ReceiptStatus.PENDING,
        confidence=Decimal("0"),
    )
    session.add(receipt)
    session.flush()
    return receipt


def _build_line_items(extraction: ReceiptExtraction) -> list[LineItem]:
    """Child rows for one extraction, with collision-free positions.

    ``(receipt_id, position)`` is unique, so a model that never emitted positions
    (every item at the default ``0``) would otherwise make the whole insert fail
    and lose the receipt. When the emitted positions are not distinct we fall
    back to list order; R061 already reports the malformed positions, and a
    receipt that reaches review is far better than one that vanishes.
    """
    positions = [item.position for item in extraction.line_items]
    use_list_order = len(set(positions)) != len(positions)

    return [
        LineItem(
            position=index if use_list_order else item.position,
            description_raw=item.description_raw,
            sku=item.sku,
            qty=item.qty,
            unit=item.unit,
            unit_price=item.unit_price,
            line_total=item.line_total,
            modifiers=[modifier.model_dump(mode="json") for modifier in item.modifiers],
            bbox=list(item.bbox) if item.bbox is not None else None,
        )
        for index, item in enumerate(extraction.line_items)
    ]


def save_extraction_run(
    session: Session,
    receipt_id: uuid.UUID,
    pass_name: PassName | str,
    attempt: int,
    response: VLMResponse,
    prompt_hash: str,
) -> ExtractionRun:
    """Append the immutable audit row for one model call (§6.4).

    Records what was asked (``pass_name``, ``attempt``, ``model_id``,
    ``prompt_hash``) and what it cost (tokens, latency, ``cost_usd`` as
    ``Decimal``), alongside the raw response so a bad extraction can be
    diagnosed months later.

    **The stored response is redacted first.** §18: if a full PAN appears in a
    raw model response it must never reach ``raw_response``. See
    :func:`redact_pan`.

    Flushes; does not commit.
    """
    payload = {
        "raw": _json_safe(response.raw),
        "parsed": _json_safe(response.parsed),
        "parse_error": response.parse_error,
    }

    run = ExtractionRun(
        receipt_id=receipt_id,
        pass_name=PassName(pass_name),
        attempt=attempt,
        model_id=response.model_id,
        prompt_hash=prompt_hash,
        raw_response=redact_pan(payload),
        latency_ms=response.latency_ms,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )
    session.add(run)
    session.flush()
    return run


def save_findings(
    session: Session, receipt_id: uuid.UUID, report: ValidationReport
) -> list[ValidationFinding]:
    """Write one ``validation_findings`` row per finding, in report order.

    Rule ids are stored **verbatim** -- they are stable identifiers (R001,
    R021, ...) shown in the review UI and joined on in eval, so they are never
    renumbered or normalised here. Rows are appended, never replaced: a repair
    pass adds its own findings and marks which earlier ones it resolved.

    Flushes; does not commit.
    """
    rows = [
        ValidationFinding(
            receipt_id=receipt_id,
            rule_id=finding.rule_id,
            severity=finding.severity,
            message=finding.message,
            context=_json_safe(finding.context),
            resolved_by_repair=finding.resolved_by_repair,
        )
        for finding in report.findings
    ]
    if rows:
        session.add_all(rows)
        session.flush()
    return rows


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


def get_receipt(session: Session, receipt_id: uuid.UUID) -> Receipt | None:
    """One receipt by id, or ``None``. Line items load on access."""
    return session.get(Receipt, receipt_id)


def get_findings(session: Session, receipt_id: uuid.UUID) -> list[ValidationFinding]:
    """Every finding written for a receipt, oldest first.

    Ordered by ``created_at`` then ``id`` -- a total order, so two findings
    written in the same transaction still come back in a stable sequence.
    """
    return list(
        session.scalars(
            select(ValidationFinding)
            .where(ValidationFinding.receipt_id == receipt_id)
            .order_by(ValidationFinding.created_at, ValidationFinding.id)
        )
    )


def query_receipts(
    session: Session,
    *,
    status: ReceiptStatus | None = None,
    merchant_id: uuid.UUID | None = None,
    date_from: date_cls | None = None,
    date_to: date_cls | None = None,
    min_confidence: Decimal | None = None,
    limit: int = 1000,
    offset: int = 0,
) -> list[Receipt]:
    """Receipts matching every supplied filter (they compose with AND).

    Ordered by ``created_at`` then ``id`` -- a total order, so ``limit`` and
    ``offset`` page through the result set without repeating or skipping a row
    when two receipts share a timestamp.

    Note that a date filter excludes receipts whose ``txn_date`` is NULL (SQL
    three-valued logic). That is the intended reading of "receipts in this
    period": a receipt with no date is not known to be in it.
    """
    query = select(Receipt)
    if status is not None:
        query = query.where(Receipt.status == status)
    if merchant_id is not None:
        query = query.where(Receipt.merchant_id == merchant_id)
    if date_from is not None:
        query = query.where(Receipt.txn_date >= date_from)
    if date_to is not None:
        query = query.where(Receipt.txn_date <= date_to)
    if min_confidence is not None:
        query = query.where(Receipt.confidence >= min_confidence)

    query = query.order_by(Receipt.created_at, Receipt.id).limit(limit).offset(offset)
    return list(session.scalars(query))


# --------------------------------------------------------------------------- #
# Duplicate detection (§14.1)
#
# The *decisions* -- how close two hashes must be, what makes two receipts the
# same purchase -- stay in the pure helpers in ``receipts.ingest.dedupe``, which
# take injected candidates and are unit tested without a database. What lives
# here is only the part that needs a session: loading the candidate set and
# turning a matched id back into a row. SQL narrows on the cheap indexed columns;
# the pure helper makes the call.
#
# **Those helpers are imported inside the three functions that call them, never
# at module top.** ``receipts.ingest.dedupe`` needs numpy and Pillow, which live
# in the optional ``pipeline`` extra -- ADR-0009 named this exact chain
# (``receipts.persist`` -> ``repository`` -> ``receipts.ingest.dedupe`` ->
# numpy/Pillow) and made ``persist/__init__`` lazy so a base install could run
# ``alembic upgrade head``. It stopped one module short: ``receipts.cli``
# imports ``persist.repository`` *directly* for ``get_receipt``/
# ``query_receipts``/``create_pending_receipt``, none of which have anything to
# do with dedupe, so a module-top import here still made every ``receipts``
# command require Pillow. Same decision, one level deeper.
# --------------------------------------------------------------------------- #


def find_duplicate_by_phash(
    session: Session,
    phash: str,
    *,
    threshold: int = 5,
    exclude_id: uuid.UUID | None = None,
) -> Receipt | None:
    """The first receipt whose stored hash is within ``threshold`` bits, or ``None``.

    Feeds ``(id, image_phash)`` pairs to
    :func:`~receipts.ingest.dedupe.find_near_duplicate_image`. Rows with an empty
    ``image_phash`` are skipped (an unhashed receipt is not comparable, and
    ``int("", 16)`` would raise), as is ``exclude_id`` -- pass the receipt's own
    id so it cannot be reported as its own duplicate.

    ``exclude_id`` also drops every row **already marked a duplicate of it**, for
    the same reason one step further out: those rows hold a copy of this very
    image, so a re-run of the original would match its own duplicate and be
    marked a duplicate of it. That closes an ``A -> B -> A`` cycle, empties the
    original's amounts, and drops *both* rows out of the default export -- the
    transaction disappears from the ledger with nothing left pointing at it.

    An empty ``phash`` argument matches nothing rather than raising: a receipt we
    could not hash must not be declared a duplicate of anything.

    Candidates are ordered by ``created_at`` then ``id``, so "the first match"
    is the oldest receipt and the same query always returns the same answer.
    """
    from ..ingest.dedupe import find_near_duplicate_image

    if not phash:
        return None

    query = select(Receipt.id, Receipt.image_phash).where(Receipt.image_phash != "")
    if exclude_id is not None:
        query = query.where(Receipt.id != exclude_id).where(
            # ``!=`` alone is NULL (and so excluding) for every row that
            # duplicates nothing, which is nearly all of them.
            or_(Receipt.duplicate_of.is_(None), Receipt.duplicate_of != exclude_id)
        )
    query = query.order_by(Receipt.created_at, Receipt.id)

    candidates = session.execute(query).tuples().all()
    match_id = find_near_duplicate_image(phash, candidates, threshold)
    return session.get(Receipt, match_id) if match_id is not None else None


def find_duplicate_by_content(
    session: Session,
    merchant_id: uuid.UUID | None,
    txn_date: date_cls | None,
    total: Decimal | None,
    *,
    exclude_id: uuid.UUID | None = None,
) -> Receipt | None:
    """A receipt with the same merchant *and* date *and* total, or ``None``.

    Delegates the match to
    :func:`~receipts.ingest.dedupe.find_semantic_duplicate`.

    **Insufficient keys match nothing.** With no ``total`` or no ``txn_date``
    there is no identifying key left, and matching on what remains would make
    every undated or unpriced receipt a "duplicate" of every other -- silently
    merging unrelated purchases, which is far worse than missing a re-upload. A
    NULL ``merchant_id`` *is* allowed: an unresolved merchant then only matches
    other receipts whose merchant is equally unresolved.

    The ``merchant_id`` and ``txn_date`` equality is pushed into SQL (they are
    indexed together, per §6.2). The ``total`` comparison deliberately is not: it
    stays in Python so the match is one exact ``Decimal`` equality on every
    backend, independent of how each one gives numeric affinity and scale to a
    ``Numeric`` bind parameter. (Both backends do round-trip a
    ``Numeric(14, 4)`` faithfully -- the scale fits inside float64's exactly
    representable range and the result processor re-quantizes -- so this is about
    keeping one comparison with one documented semantics, not about correcting a
    lossy backend.)
    """
    from ..ingest.dedupe import find_semantic_duplicate

    if total is None or txn_date is None:
        return None

    query = select(Receipt.id, Receipt.merchant_id, Receipt.txn_date, Receipt.total).where(
        Receipt.txn_date == txn_date
    )
    # ``= NULL`` is never true in SQL, so an unresolved merchant needs IS NULL.
    if merchant_id is None:
        query = query.where(Receipt.merchant_id.is_(None))
    else:
        query = query.where(Receipt.merchant_id == merchant_id)
    if exclude_id is not None:
        query = query.where(Receipt.id != exclude_id)
    query = query.order_by(Receipt.created_at, Receipt.id)

    candidates = [dict(row) for row in session.execute(query).mappings()]
    match_id = find_semantic_duplicate(merchant_id, txn_date, total, candidates)
    return session.get(Receipt, match_id) if match_id is not None else None


def _reject_cycle(session: Session, new_id: uuid.UUID, existing_id: uuid.UUID) -> None:
    """Raise ``ValueError`` if pointing ``new_id`` at ``existing_id`` closes a cycle.

    Walks the existing ``duplicate_of`` chain forwards from ``existing_id``. The
    walk is bounded by ``seen`` rather than by trusting the data, so a cycle that
    a pre-fix row already contains ends the loop instead of hanging the worker.
    """
    seen: set[uuid.UUID] = {existing_id}
    cursor: uuid.UUID | None = existing_id
    while cursor is not None:
        row = session.get(Receipt, cursor)
        cursor = None if row is None else row.duplicate_of
        if cursor == new_id:
            raise ValueError(
                f"receipt {new_id} cannot be a duplicate of {existing_id}: "
                f"{existing_id} already resolves back to {new_id}, and a cycle "
                "would leave both rows rejected with nothing left to follow"
            )
        if cursor in seen:
            return
        if cursor is not None:
            seen.add(cursor)


def mark_duplicate(session: Session, new_id: uuid.UUID, existing_id: uuid.UUID) -> Receipt:
    """Record that ``new_id`` duplicates ``existing_id`` and return the new row.

    The link is one-way and points at the receipt that was already there:
    ``receipts.duplicate_of`` on the *new* row. Both ids must exist -- a
    dangling self-FK would be accepted by SQLite with foreign keys off -- and
    **the chain must stay acyclic**. Either case raises ``ValueError`` before
    anything is written.

    Self-reference is only the one-hop case of the cycle rule; the general one is
    checked by walking ``duplicate_of`` from ``existing_id``. An ``A -> B -> A``
    pair is not a harmless loop: both rows are ``rejected``, so both drop out of
    the default export and the transaction leaves the ledger with no un-rejected
    row left to follow the chain to. Refusing the link keeps the original intact
    for the caller to report instead.

    Flushes; does not commit.
    """
    from ..ingest.dedupe import link_duplicate

    if new_id == existing_id:
        raise ValueError(f"receipt {new_id} cannot be a duplicate of itself")

    new_receipt = session.get(Receipt, new_id)
    if new_receipt is None:
        raise ValueError(f"no receipt with id {new_id}")
    if session.get(Receipt, existing_id) is None:
        raise ValueError(f"no receipt with id {existing_id}")
    _reject_cycle(session, new_id, existing_id)

    _linked_new, linked_existing = link_duplicate(new_id, existing_id)
    new_receipt.duplicate_of = linked_existing
    session.flush()
    return new_receipt


# --------------------------------------------------------------------------- #
# Corrections
# --------------------------------------------------------------------------- #


def _coerce_text(value: Any) -> str:
    """A required text column: ``None`` becomes ``""`` rather than a NOT NULL error."""
    return "" if value is None else str(value)


def _coerce_optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _bounded_optional_text(column_name: str) -> Callable[[Any], str | None]:
    """A coercion for a length-bounded ``String(n)`` column on ``receipts``.

    The limit is read from the model column rather than repeated here, so widening
    ``currency`` to ``String(4)`` needs no change in this module. Overlong text is
    a ``ValueError`` because the backends disagree about it: Postgres raises a
    ``DataError`` and SQLite stores it anyway, so without this check a reviewer's
    edit that works in development fails in production.
    """
    limit: int | None = getattr(Receipt.__table__.c[column_name].type, "length", None)

    def coerce(value: Any) -> str | None:
        text = _coerce_optional_text(value)
        if text is not None and limit is not None and len(text) > limit:
            raise ValueError(
                f"{column_name} holds at most {limit} characters, got {len(text)} ({text!r})"
            )
        return text

    return coerce


def _coerce_money(value: Any) -> Decimal | None:
    """A ``Numeric`` column value, as a **finite** ``Decimal``.

    ``float`` is refused outright (ADR-0001 / §18): ``0.1`` is not one tenth, and
    a reviewer's "correction" that silently lands 0.0000001 off would fail the
    validator's cent-bounded tolerances later and look like a model error. Pass a
    ``Decimal`` or the printed string.

    ``NaN`` and ``Infinity`` are refused too, and for a sharper reason: they are
    *legal* ``Decimal``s, so ``"nan"`` parses, passes the float guard, and reaches
    the column -- where SQLite stores NULL (the amount is destroyed with no error
    and no flag) while the ``corrections`` row still records ``NaN``, leaving the
    audit trail disagreeing with the row it describes. On Postgres it persists and
    poisons every later comparison and sum. A money column holds an amount or
    nothing; it never holds "not a number".
    """
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(
            f"money must be a Decimal or a string, not {type(value).__name__} ({value!r}); "
            "a float cannot represent an exact amount"
        )
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    else:
        try:
            amount = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal amount: {value!r}") from exc

    if not amount.is_finite():
        raise ValueError(
            f"money must be a finite amount, not {value!r}; "
            "a non-finite value would destroy the stored amount and make the "
            "corrections audit row disagree with the column"
        )
    return amount


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not an integer: {value!r}") from exc


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ValueError(f"not a boolean: {value!r}")


def _coerce_date(value: Any) -> date_cls | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    try:
        return date_cls.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"not an ISO 8601 date (YYYY-MM-DD): {value!r}") from exc


def _coerce_time(value: Any) -> time_cls | None:
    if value is None or value == "":
        return None
    if isinstance(value, time_cls):
        return value
    try:
        return time_cls.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"not an ISO 8601 time (HH:MM): {value!r}") from exc


def _coerce_legibility(value: Any) -> Legibility:
    if isinstance(value, Legibility):
        return value
    return Legibility(str(value).strip().lower())


#: Dotted extraction path -> (``receipts`` column, coercion). The mapping is
#: explicit and closed: an unlisted path is a ``ValueError``, never a silent
#: no-op, because a reviewer's edit that vanishes is a data-integrity bug.
_RECEIPT_FIELDS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "merchant.name": ("merchant_name_raw", _coerce_optional_text),
    "receipt.number": ("receipt_number", _coerce_optional_text),
    "receipt.date": ("txn_date", _coerce_date),
    "receipt.date_raw": ("date_raw", _coerce_optional_text),
    "receipt.time": ("txn_time", _coerce_time),
    "receipt.currency": ("currency", _bounded_optional_text("currency")),
    "totals.subtotal": ("subtotal", _coerce_money),
    "totals.tax": ("tax_total", _coerce_money),
    "totals.discount": ("discount_total", _coerce_money),
    "totals.total": ("total", _coerce_money),
    "totals.tender": ("tender_amount", _coerce_money),
    "totals.change": ("change_amount", _coerce_money),
    "payment.method": ("payment_method", _coerce_optional_text),
    "payment.card_last4": ("card_last4", _last4),
    "meta.is_handwritten": ("is_handwritten", _coerce_bool),
    "meta.legibility": ("legibility", _coerce_legibility),
    "meta.receipt_is_inconsistent": ("receipt_is_inconsistent", _coerce_bool),
}

#: Field of ``line_items[i].<field>`` -> (``line_items`` column, coercion).
#: ``modifiers`` and ``bbox`` are intentionally absent: they are documents, not
#: scalars, and a reviewer edits them through the item they belong to.
_LINE_ITEM_FIELDS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "position": ("position", _coerce_int),
    "description_raw": ("description_raw", _coerce_text),
    "sku": ("sku", _coerce_optional_text),
    "qty": ("qty", _coerce_money),
    "unit": ("unit", _coerce_optional_text),
    "unit_price": ("unit_price", _coerce_money),
    "line_total": ("line_total", _coerce_money),
}

_LINE_ITEM_PATH = re.compile(r"^line_items\[(\d+)\]\.([A-Za-z_][A-Za-z0-9_]*)$")


@dataclass(frozen=True)
class _PlannedChange:
    """One resolved, coerced edit -- computed before anything is mutated."""

    field_path: str
    target: Any
    column: str
    before: Any
    after: Any


def _plan_change(
    receipt: Receipt, items_by_position: dict[int, LineItem], field_path: str, raw_value: Any
) -> _PlannedChange | None:
    """Resolve one dotted path to a column and coerce its value.

    Returns ``None`` when the value is already what is stored (no correction row
    for a no-op), and raises ``ValueError`` when the path cannot be mapped.

    **Coerced text goes through :func:`redact_pan` first** (§18). Only
    ``payment.card_last4`` is narrowed by :func:`_last4`; every other text path
    -- ``payment.method`` above all, which is where a reviewer types "VISA
    4111111111111111" off the slip -- would otherwise land a full card number in
    ``receipts.payment_method`` *and* in ``corrections.value_after``, and the
    audit trail is precisely the copy nothing later scrubs. Redacting here rather
    than at each coercion is what makes the rule hold for every text path at
    once, including any added later. Non-text values (money, dates, booleans,
    the legibility enum) are handed on untouched.
    """
    target: Receipt | LineItem
    match = _LINE_ITEM_PATH.match(field_path)
    if match:
        position, field = int(match.group(1)), match.group(2)
        if field not in _LINE_ITEM_FIELDS:
            raise ValueError(f"cannot apply a correction to unknown field path {field_path!r}")
        item = items_by_position.get(position)
        if item is None:
            raise ValueError(
                f"cannot apply a correction to {field_path!r}: "
                f"receipt {receipt.id} has no line item at position {position}"
            )
        target = item
        column, coerce = _LINE_ITEM_FIELDS[field]
    elif field_path in _RECEIPT_FIELDS:
        target = receipt
        column, coerce = _RECEIPT_FIELDS[field_path]
    else:
        raise ValueError(f"cannot apply a correction to unknown field path {field_path!r}")

    after = coerce(raw_value)
    if isinstance(after, str):
        after = redact_pan(after)
    before = getattr(target, column)
    if before == after:
        return None
    return _PlannedChange(
        field_path=field_path, target=target, column=column, before=before, after=after
    )


def apply_corrections(
    session: Session, receipt_id: uuid.UUID, patch: dict, corrected_by: str
) -> Receipt:
    """Apply a reviewer's edits, log each one, and mark the receipt reviewed.

    ``patch`` may be dotted (``{"totals.total": Decimal("761.61")}``), nested
    (``{"totals": {"total": ...}}``), or a mix -- both are flattened through
    :func:`receipts.extract.paths.flatten`, the same path grammar the corrections
    log, the consistency diff, and the eval harness already speak.
    ``line_items[i]`` addresses the item at *position* ``i``.

    Exactly one ``corrections`` row is written per **changed** field path, with
    the before and after rendered as text; a path whose value already matches
    writes nothing. Status becomes ``reviewed`` either way -- a reviewer
    confirming an already-correct receipt is still a review.

    Transactional, and the one function here that owns its transaction: every
    path is resolved and coerced *before* anything is mutated, so an unmappable
    path raises ``ValueError`` with the offending path and the database is left
    exactly as it was. Any failure rolls back.

    **Every rejected patch raises ``ValueError``**, including one that only the
    database can refuse -- swapping two ``line_items[i].position`` values trips
    the non-deferrable ``uq_line_items_receipt_position`` at flush time, and a
    caller told to expect ``ValueError`` should not have to catch
    ``IntegrityError`` as well. The database error is chained as ``__cause__``.
    """
    try:
        receipt = get_receipt(session, receipt_id)
        if receipt is None:
            raise ValueError(f"no receipt with id {receipt_id}")

        items_by_position = {item.position: item for item in receipt.line_items}

        # Phase 1 -- resolve and validate everything. No mutation yet, so a bad
        # path cannot leave a half-applied patch behind.
        planned: list[_PlannedChange] = []
        for field_path, raw_value in sorted(flatten(patch).items()):
            change = _plan_change(receipt, items_by_position, field_path, raw_value)
            if change is not None:
                planned.append(change)

        # Phase 2 -- apply, log, commit. A constraint the plan cannot see is
        # reported in the documented currency: ValueError, not IntegrityError.
        try:
            for change in planned:
                setattr(change.target, change.column, change.after)
            session.add_all(
                [
                    Correction(
                        receipt_id=receipt.id,
                        field_path=change.field_path,
                        value_before=_as_text(change.before),
                        value_after=_as_text(change.after),
                        corrected_by=corrected_by,
                    )
                    for change in planned
                ]
            )
            receipt.status = ReceiptStatus.REVIEWED
            session.commit()
        except SQLAlchemyError as exc:
            raise ValueError(
                f"could not apply corrections to receipt {receipt_id}: "
                f"the database refused the patch ({type(exc).__name__})"
            ) from exc
    except Exception:
        session.rollback()
        raise

    return receipt
