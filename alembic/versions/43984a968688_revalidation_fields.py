"""fields the review-time re-validation needs

Revision ID: 43984a968688
Revises: f3ae0f86e0e6
Create Date: 2026-08-24 00:00:00.000000

Three ``receipts`` columns, each read by a validation rule and carried by no
column until now. Without them a receipt rebuilt from this table validates
DIFFERENTLY from the one that was extracted, with no reviewer edit involved:

* ``is_refund`` -- R040 ("the total is positive unless the document is a
  refund"). Measured 2026-08-24: a refund that validated clean at extraction
  produced ``R040/ERROR`` after a round trip, because the rebuild had no column
  to read and assumed a sale. NOT NULL with ``server_default=sa.false()``,
  matching ``line_items.is_template_row``: both engines refuse ``ADD COLUMN ...
  NOT NULL`` with no default once the table holds a row, and ``false`` is what
  every existing row was already rebuilt as, so nothing stored changes meaning.
* ``prices_include_tax`` -- R020/R024. NULL is a real value ("the document does
  not state a convention") and the common one, so the column is nullable and
  needs no default. A lost ``True`` does not fail loudly; it loosens the check.
* ``tax_breakdown`` -- R025. Nullable following ``receipts.confidence_reasons``:
  NULL means "not recorded" (a row written before this column existed), ``[]``
  means "the model read no bands".

Portability (ADR-0004): ``sa.false()``, never ``sa.text("0")`` -- SQLite's
spelling of false frozen into a migration, which Postgres rejects on a BOOLEAN
column. Same edit ``f3ae0f86e0e6`` documents.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "43984a968688"
down_revision: str | Sequence[str] | None = "f3ae0f86e0e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Add the three ``receipts`` columns the review-time re-validation reads."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_refund", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(sa.Column("prices_include_tax", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("tax_breakdown", _JSON, nullable=True))


def downgrade() -> None:
    """Drop the three columns."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.drop_column("tax_breakdown")
        batch_op.drop_column("prices_include_tax")
        batch_op.drop_column("is_refund")
