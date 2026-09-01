"""processed receipts archive

Revision ID: 8b2f0c9d4e11
Revises: 43984a968688
Create Date: 2026-09-01 00:00:00.000000

Create ``processed_receipts``, the durable archive marker written after an
Excel export succeeds. The original ``receipts`` row remains the source of
truth and keeps all child audit rows; this table only records that the receipt
has already left the active Results/export scope.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8b2f0c9d4e11"
down_revision: str | Sequence[str] | None = "43984a968688"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the archive marker table."""
    op.create_table(
        "processed_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("receipt_id", sa.Uuid(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_by", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            name="fk_processed_receipts_receipt_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", name="uq_processed_receipts_receipt_id"),
    )


def downgrade() -> None:
    """Drop the archive marker table."""
    op.drop_table("processed_receipts")
