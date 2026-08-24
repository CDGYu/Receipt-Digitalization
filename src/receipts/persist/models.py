"""SQLAlchemy 2.0 ORM for the seven-table data model (spec §6).

One declarative model per table, written to be portable across the two
databases the system targets:

  * **PostgreSQL** in production -- native ``UUID`` primary keys, ``JSONB``
    document columns, native ``ENUM`` types.
  * **SQLite** in development and tests -- the same schema, degraded gracefully:
    ``UUID`` becomes ``CHAR(32)``, ``JSONB`` becomes ``JSON`` (text), and enums
    become ``VARCHAR``.

Portability is achieved with two mechanisms and no per-backend branching in the
models themselves:

  * :class:`sqlalchemy.Uuid` for every id / foreign key -- native on Postgres,
    ``CHAR`` elsewhere.
  * :func:`_jsonb` -- ``JSON`` with a ``JSONB`` variant registered for the
    ``postgresql`` dialect, so document columns are ``JSONB`` on Postgres and
    plain ``JSON`` on SQLite.

Load-bearing rule for this project: **money is ``Numeric``/``Decimal``, never
``Float``.** Every monetary and ratio column below is ``Numeric(..., asdecimal=
True)``; a companion test walks ``Base.metadata`` and fails if any column is a
``Float``.

Enum columns persist the enum *value* (the stable lowercase token from the spec
that is stored in the DB and shown in the review UI), not the Python member
name -- see :func:`_token_enum`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..extract.schema import Legibility
from ..score.confidence import ReceiptStatus
from ..validate.report import Severity

# --------------------------------------------------------------------------- #
# New enums (the reused ones -- ReceiptStatus, Severity, Legibility -- are
# imported above; their values are NOT redefined here).
# --------------------------------------------------------------------------- #


class PassName(str, Enum):
    """Which model pass produced an :class:`ExtractionRun` audit row (§6.4)."""

    TRIAGE = "triage"
    EXTRACT = "extract"
    REPAIR = "repair"
    CONSISTENCY = "consistency"


class ReviewState(str, Enum):
    """Lifecycle of a :class:`ReviewTask` (§6.7)."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"


# --------------------------------------------------------------------------- #
# Portable column-type helpers
# --------------------------------------------------------------------------- #


def _jsonb() -> sa.types.TypeEngine[Any]:
    """A JSON column that is ``JSONB`` on Postgres and ``JSON`` on SQLite."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _token_enum(python_enum: type[Enum], *, name: str) -> sa.Enum:
    """A DB enum that persists each member's ``.value`` (the spec token).

    SQLAlchemy defaults to persisting the enum member *name*; the values in this
    system (``auto_approved``, ``error``, ``good`` ...) are stable, stored in the
    DB, and shown in the review UI, so we persist ``.value`` instead. Native
    ``ENUM`` on Postgres, ``VARCHAR`` on SQLite.
    """
    return sa.Enum(
        python_enum,
        name=name,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )


#: Money / ratio column types. Centralised so the precision is defined once and
#: it is obvious at a glance that the money path is Decimal, never float.
_MONEY = sa.Numeric(14, 4, asdecimal=True)
_QTY = sa.Numeric(12, 4, asdecimal=True)
_RATIO = sa.Numeric(4, 3, asdecimal=True)
_COST = sa.Numeric(10, 6, asdecimal=True)
#: A printed tax RATE, and deliberately wider than ``_RATIO``.
#:
#: **The upstream convention is unstated**, which is why this is its own type
#: rather than a reuse. :class:`receipts.extract.schema.TaxBand` declares
#: ``rate: Decimal | None`` with no description, and the prompt asks only for
#: "rate bands" -- so a 12% band may arrive as ``12`` or as ``0.12`` depending on
#: what the model reads off the paper, and nothing tells it which to send.
#: ``_RATIO`` is ``Numeric(4, 3)`` and would OVERFLOW on ``12``; this holds both
#: readings. Nothing computes from this column -- R-rules reconcile bands by
#: ``amount`` -- so storing what was printed, unconverted, loses nothing and
#: inventing a convention here would silently rewrite the document.
_RATE = sa.Numeric(7, 4, asdecimal=True)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in this package."""


# --------------------------------------------------------------------------- #
# 6.1 merchants
# --------------------------------------------------------------------------- #


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tax_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    name_variants: Mapped[Any] = mapped_column(_jsonb(), nullable=False, default=list)
    address: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    default_currency: Mapped[str | None] = mapped_column(sa.String(3), nullable=True)
    hints: Mapped[Any] = mapped_column(_jsonb(), nullable=False, default=list)
    receipt_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    receipts: Mapped[list[Receipt]] = relationship(back_populates="merchant")


# --------------------------------------------------------------------------- #
# 6.2 receipts (the head table)
# --------------------------------------------------------------------------- #


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, ForeignKey("merchants.id"), nullable=True
    )
    merchant_name_raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Who the receipt was issued TO -- the "Sold To" / "Registered Name" block,
    #: mirroring :class:`receipts.extract.schema.Buyer`. Distinct from the
    #: merchant columns above, which are who *issued* it: a BIR sales invoice
    #: carries both names and both TINs, and they are different numbers.
    #:
    #: Both nullable, deliberately. Most receipts name no buyer at all, and every
    #: receipt in the golden set leaves the buyer TIN blank; NOT NULL here would
    #: turn an ordinary receipt into a persist-stage failure. There is no
    #: ``buyer_address``: the forms print a Business Address line for the buyer
    #: and it is blank throughout the golden set (see ``Buyer``'s docstring).
    buyer_name_raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    buyer_tax_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    receipt_number: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    txn_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    txn_time: Mapped[time | None] = mapped_column(sa.Time, nullable=True)
    date_raw: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(sa.String(3), nullable=True)

    subtotal: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    tax_total: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    discount_total: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    total: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    tender_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    change_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: Whether the line-item amounts already include tax, as the DOCUMENT states
    #: it -- not a computed fact. ``true`` means the amounts sum to ``total``
    #: (the usual case on a Philippine BIR sales invoice, where ``subtotal`` is
    #: the net-of-VAT base); ``false`` means they sum to ``subtotal``; ``NULL``
    #: means the receipt does not say, which is the ordinary reading.
    #:
    #: R020 and R024 read it to decide which figure the lines are expected to
    #: sum to. Until this column existed it was extracted, used in memory by
    #: those rules, and then dropped -- so a re-run of the rules against a
    #: persisted receipt could not reach the convention the first run had.
    prices_include_tax: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)

    payment_method: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    card_last4: Mapped[str | None] = mapped_column(sa.String(4), nullable=True)

    is_handwritten: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    legibility: Mapped[Legibility] = mapped_column(
        _token_enum(Legibility, name="legibility"), nullable=False, default=Legibility.GOOD
    )
    confidence: Mapped[Decimal] = mapped_column(_RATIO, nullable=False, default=Decimal("0"))
    #: The (reason, penalty) pairs that produced ``confidence``, as JSON:
    #: ``[{"reason": "poor legibility", "penalty": "-0.20"}]``. Penalties are
    #: strings so Decimal survives the round trip (ADR-0001).
    #:
    #: Nullable on purpose: NULL means "not recorded" (a row written before this
    #: column existed, or a run that failed before scoring), while ``[]`` means
    #: "nothing lowered the score" -- a genuinely clean receipt. Collapsing the
    #: two would let the review UI tell a reviewer "no reasons" about a row that
    #: never captured them.
    confidence_reasons: Mapped[Any | None] = mapped_column(_jsonb(), nullable=True, default=None)
    status: Mapped[ReceiptStatus] = mapped_column(
        _token_enum(ReceiptStatus, name="receipt_status"),
        nullable=False,
        default=ReceiptStatus.PENDING,
    )

    image_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    processed_image_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    image_phash: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, ForeignKey("receipts.id"), nullable=True
    )
    receipt_is_inconsistent: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False
    )
    #: Whether the document is a refund / credit note. **R040 reads it**
    #: ("the total is positive unless the document is a refund"), and until
    #: 2026-08-24 it was a column on nothing -- so a receipt rebuilt from this
    #: table always looked like a sale, and a refund re-validated as an ERROR
    #: its extraction run never produced. Measured; see the design's section 1.
    #:
    #: NOT NULL with a server default, matching ``LineItem.is_template_row``:
    #: both engines refuse ``ADD COLUMN ... NOT NULL`` with no default once the
    #: table holds a row, and ``false`` is exactly what every existing row was
    #: already being rebuilt as, so no stored receipt changes behaviour.
    is_refund: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    #: The document's stated tax convention: ``True`` = the line amounts include
    #: tax, ``False`` = they exclude it, ``NULL`` = the document does not say.
    #: **R020/R024 read it** to choose what the line sum may equal; NULL accepts
    #: either reading, so a lost ``True`` does not fail loudly -- it silently
    #: LOOSENS the arithmetic check. Nullable because NULL is a real value here
    #: and the common one, not a placeholder.
    prices_include_tax: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    #: Per-band tax breakdown as the model emitted it, e.g.
    #: ``[{"label": "VATable", "base": "500.00", "rate": "0.12", "amount": "60.00"}]``.
    #: Amounts are strings so ``Decimal`` survives the round trip (ADR-0001).
    #: **R025 reads it** and skips on an empty list, so a lost breakdown
    #: disables that rule rather than failing it.
    #:
    #: Nullable on purpose, following ``confidence_reasons``: NULL means "not
    #: recorded" (a row written before this column existed), ``[]`` means "the
    #: model read no tax bands". Collapsing the two would claim a reading
    #: nothing made.
    tax_breakdown: Mapped[Any | None] = mapped_column(_jsonb(), nullable=True, default=None)

    #: What the run was doing when it was last known alive, and when that was.
    #: Written by the heartbeat sink on every stage entry and once per model
    #: call inside extract, so the largest gap between two writes is one model
    #: call -- which is what lets a sweep tell a slow receipt from a stranded
    #: one.
    #:
    #: NULL means no run has ever reported on this receipt. That is a
    #: *different* failure mode from "started and went cold", on a different
    #: timescale, and `receipts.sweep` must not collapse the two: a receipt
    #: queued behind a backlog is healthy and has no heartbeat either.
    progress_stage: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    progress_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    merchant: Mapped[Merchant | None] = relationship(back_populates="receipts")
    line_items: Mapped[list[LineItem]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="LineItem.position",
    )
    tax_bands: Mapped[list[TaxBand]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="TaxBand.position",
    )

    __table_args__ = (
        Index("ix_receipts_merchant_id_txn_date", "merchant_id", "txn_date"),
        Index("ix_receipts_status", "status"),
        Index("ix_receipts_image_phash", "image_phash"),
        Index("ix_receipts_merchant_id_txn_date_total", "merchant_id", "txn_date", "total"),
    )


# --------------------------------------------------------------------------- #
# 6.3 line_items
# --------------------------------------------------------------------------- #


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    description_raw: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    sku: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    qty: Mapped[Decimal | None] = mapped_column(_QTY, nullable=True)
    unit: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    line_total: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    modifiers: Mapped[Any] = mapped_column(_jsonb(), nullable=False, default=list)
    bbox: Mapped[Any | None] = mapped_column(_jsonb(), nullable=True, default=None)
    line_confidence: Mapped[Decimal] = mapped_column(_RATIO, nullable=False, default=Decimal("0"))
    #: A pre-printed product row left blank on the form -- transcribed so nothing
    #: on the paper is lost, but NOT a purchase (mirrors
    #: :attr:`receipts.extract.schema.LineItem.is_template_row`).
    #:
    #: Carries *both* a Python-side ``default`` and a ``server_default``, for the
    #: same reason as ``validation_findings.created_at`` above: ``ALTER TABLE ...
    #: ADD COLUMN ... NOT NULL`` with no default fails on both SQLite and
    #: Postgres once the table holds a row, and ``line_items`` holds one per line
    #: of every processed receipt. The server default only ever backfills; the
    #: ORM supplies ``False`` for every row it writes itself.
    is_template_row: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )

    receipt: Mapped[Receipt] = relationship(back_populates="line_items")

    __table_args__ = (
        UniqueConstraint("receipt_id", "position", name="uq_line_items_receipt_position"),
    )


# --------------------------------------------------------------------------- #
# 6.3b tax_bands (the printed tax breakdown)
# --------------------------------------------------------------------------- #


class TaxBand(Base):
    """One printed band of a receipt's tax breakdown.

    The VATABLE SALES / VAT-EXEMPT SALES / zero-rated block a Philippine BIR
    sales invoice prints beneath its items grid, one row per band.

    **A child table rather than a JSONB column on ``receipts``, and the reason
    is correctability.** ``line_items.modifiers`` and ``line_items.bbox`` are
    JSONB and are deliberately absent from ``_LINE_ITEM_FIELDS`` -- "they are
    documents, not scalars, and a reviewer edits them through the item they
    belong to". A reviewer must be able to correct a misread band, and
    ``extract/paths.py`` already documents ``totals.tax_breakdown[0].amount`` as
    valid path grammar, so each figure has to be addressable on its own. JSONB
    would put those paths out of reach by exactly the reasoning that keeps
    ``modifiers`` out.

    **And the bands are arithmetic, not decoration.** R-rules reconcile
    ``sum(band.amount) == totals.tax``; a band is also the only independent
    check on a misread total. Measured on this project's own data: a model read
    ``total = 2.0000`` from a receipt printing 2,000, on a page that also
    printed ``Amount: Net of VAT 1785.71`` and ``Add: VAT 214.29`` -- which sum
    to exactly 2,000. A rule can only make that comparison if the bands are
    scalars it can reach.

    Every column is nullable but ``position``: a band may print a label and an
    amount with no base, or a base with no rate. Nothing here is computed --
    "Do not compute bands that are not printed" is the prompt's own rule.
    """

    __tablename__ = "tax_bands"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    #: Printed order, top to bottom. Also the index in the correction path
    #: ``totals.tax_breakdown[i].<field>``, exactly as ``LineItem.position`` is
    #: the index in ``line_items[i].<field>``.
    position: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: The band's printed name -- "VATable Sales", "VAT-Exempt Sales",
    #: "Zero-Rated". Text as printed; nothing maps it to an enum, because the
    #: wording varies by printer and an unrecognised label must survive.
    label: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    base: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(_RATE, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)

    receipt: Mapped[Receipt] = relationship(back_populates="tax_bands")

    __table_args__ = (
        UniqueConstraint("receipt_id", "position", name="uq_tax_bands_receipt_position"),
    )


# --------------------------------------------------------------------------- #
# 6.4 extraction_runs (immutable audit log)
# --------------------------------------------------------------------------- #


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    pass_name: Mapped[PassName] = mapped_column(
        _token_enum(PassName, name="pass_name"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    model_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    raw_response: Mapped[Any] = mapped_column(_jsonb(), nullable=False, default=dict)
    latency_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(_COST, nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


# --------------------------------------------------------------------------- #
# 6.5 validation_findings
# --------------------------------------------------------------------------- #


class ValidationFinding(Base):
    __tablename__ = "validation_findings"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    severity: Mapped[Severity] = mapped_column(
        _token_enum(Severity, name="finding_severity"), nullable=False
    )
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    context: Mapped[Any] = mapped_column(_jsonb(), nullable=False, default=dict)
    resolved_by_repair: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    #: Not part of the original spec §6.5 table -- added so :func:`get_findings`
    #: (P4.T3) can return findings in the order they were written. Carries
    #: *both* a Python-side ``default`` and a ``server_default``, deliberately:
    #:
    #:   * ``default`` wins for every ORM-issued INSERT -- SQLAlchemy computes it
    #:     once per row as the unit of work processes them, in insertion order,
    #:     which is what makes two findings from the same ``save_findings`` call
    #:     sort in write order. A pure server-side default would tie them:
    #:     Postgres freezes ``now()`` for the whole transaction, and SQLite's
    #:     ``CURRENT_TIMESTAMP`` has only whole-second resolution.
    #:   * ``server_default`` is what lets ``ALTER TABLE ... ADD COLUMN ...
    #:     NOT NULL`` backfill existing rows when this column is added to a
    #:     table that already has data (see migration a1c4d2f80b31) -- both
    #:     SQLite and Postgres refuse a NOT NULL column addition with no
    #:     default when the table is non-empty. It is otherwise inert: it never
    #:     fires for a row the ORM writes, only for rows written directly in SQL.
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        default=lambda: datetime.now(UTC),
    )


# --------------------------------------------------------------------------- #
# 6.6 corrections (training data)
# --------------------------------------------------------------------------- #


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    value_before: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    value_after: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    corrected_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


# --------------------------------------------------------------------------- #
# 6.7 review_tasks
# --------------------------------------------------------------------------- #


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    assigned_to: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    state: Mapped[ReviewState] = mapped_column(
        _token_enum(ReviewState, name="review_state"), nullable=False, default=ReviewState.OPEN
    )
    opened_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- #
# 6.8 users (added with the review API, P4.T3)
# --------------------------------------------------------------------------- #


class User(Base):
    """A person who can sign in to the review service.

    Exists so ``corrections.corrected_by`` names a real account: a shared key
    cannot attribute a correction to a reviewer, which would hollow out the one
    audit trail the review UI depends on.

    ``role`` is deliberately a ``String`` and **not** a database ENUM. The
    migration drift guard runs on SQLite only and cannot see a new ENUM member,
    so an ENUM here would pass locally and fail on Postgres. Validation lives in
    :mod:`receipts.persist.users`, next to the role constants the API guards use.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
