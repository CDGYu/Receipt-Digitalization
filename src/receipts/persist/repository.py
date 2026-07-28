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
  * **Only ever store the last four card digits** (§18). Two independent
    defences: :func:`_last4` on the way into ``receipts.card_last4``, and
    :func:`redact_pan` over everything written to
    ``extraction_runs.raw_response``.
"""

from __future__ import annotations

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
from sqlalchemy import select
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
    "get_receipt",
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
#: usual 4-4-4-N grouping, and Amex's 4-6-5. Two deliberate design choices keep
#: it from firing on things that merely look numeric:
#:
#:   * separators must be *consistent* (the backreference), so a run of small
#:     space-separated numbers -- ``"2 18.00 3 20.00 ..."`` -- is not swept up;
#:   * the lookarounds refuse a match that continues into more digits or into a
#:     decimal fraction, so ``1234567890123.45`` stays a number and a longer
#:     digit run is not partially masked.
_PAN_RE = re.compile(
    r"""
    (?<![\d.])                                              # not mid-number, not a fraction
    (?:
        \d{4}(?P<sep>[ -])\d{4}(?P=sep)\d{4}(?P=sep)\d{1,4} # 4-4-4-N (Visa, Mastercard, ...)
      | \d{4}(?P<amex>[ -])\d{6}(?P=amex)\d{5}              # 4-6-5 (Amex)
      | \d{13,19}                                           # unseparated
    )
    (?!\d)(?!\.\d)                                          # ... and not the integer part
    """,
    re.VERBOSE,
)


def _mask_pan(match: re.Match[str]) -> str:
    """Replace a matched PAN with a mask that keeps only the last four digits."""
    digits = re.sub(r"\D", "", match.group(0))
    if not _PAN_MIN_DIGITS <= len(digits) <= _PAN_MAX_DIGITS:
        return match.group(0)
    return "*" * (len(digits) - 4) + digits[-4:]


def redact_pan(value: Any) -> Any:
    """Strip full card numbers out of ``value``, keeping only the last four.

    Pure and recursive: walks ``dict`` values, ``list``/``tuple`` items, and
    strings, returning new containers and never mutating the input. Non-string
    scalars pass through unchanged, except ``int``, which is masked when its
    digits look like a PAN (a model that emitted the card number as a JSON
    number would otherwise slip past).

    What it deliberately does *not* touch, because a rule that fires when it
    should not is worse than no rule: money (``1234.56``), a 4-digit
    ``card_last4``, a 16-character hash, dates, and phone-style numbers -- all
    are shorter than :data:`_PAN_MIN_DIGITS` digits or fail the separator
    grouping. The one accepted false positive is a 13-19 digit *all-numeric*
    identifier, which is indistinguishable from a PAN by inspection.
    """
    if isinstance(value, str):
        return _PAN_RE.sub(_mask_pan, value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        text = str(value)
        masked = _PAN_RE.sub(_mask_pan, text)
        return masked if masked != text else value
    if isinstance(value, dict):
        return {key: redact_pan(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_pan(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_pan(item) for item in value)
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

    Flushes (so ``id`` and the child rows exist) and returns the ORM object
    without committing -- the caller owns the transaction.
    """
    receipt_meta = extraction.receipt
    txn_date = _parse_iso_date(receipt_meta.date)
    date_raw = receipt_meta.date_raw
    if txn_date is None and not date_raw and receipt_meta.date:
        # Nothing is silently dropped: an unparseable date is kept verbatim.
        date_raw = receipt_meta.date

    receipt = Receipt(
        id=job.id,
        merchant_id=merchant_id,
        merchant_name_raw=extraction.merchant.name,
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
        payment_method=extraction.payment.method,
        card_last4=_last4(extraction.payment.card_last4),
        is_handwritten=extraction.meta.is_handwritten,
        legibility=extraction.meta.legibility,
        confidence=confidence,
        status=status,
        image_key=job.image_key,
        image_phash=image_phash,
        receipt_is_inconsistent=extraction.meta.receipt_is_inconsistent,
    )
    receipt.line_items = _build_line_items(extraction)

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
# Corrections
# --------------------------------------------------------------------------- #


def _coerce_text(value: Any) -> str:
    """A required text column: ``None`` becomes ``""`` rather than a NOT NULL error."""
    return "" if value is None else str(value)


def _coerce_optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _coerce_money(value: Any) -> Decimal | None:
    """A ``Numeric`` column value, as ``Decimal``.

    ``float`` is refused outright (ADR-0001 / §18): ``0.1`` is not one tenth, and
    a reviewer's "correction" that silently lands 0.0000001 off would fail the
    validator's cent-bounded tolerances later and look like a model error. Pass a
    ``Decimal`` or the printed string.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(
            f"money must be a Decimal or a string, not {type(value).__name__} ({value!r}); "
            "a float cannot represent an exact amount"
        )
    if isinstance(value, int):
        return Decimal(value)
    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a decimal amount: {value!r}") from exc


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
    "receipt.currency": ("currency", _coerce_optional_text),
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

        # Phase 2 -- apply, log, commit.
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
    except Exception:
        session.rollback()
        raise

    return receipt
