"""line item handwriting flag

Revision ID: 9c1e7a4b2d30
Revises: e2d7b4c1f9a0
Create Date: 2026-09-02 00:00:00.000000

Add ``line_items.is_handwritten`` so the review grid can distinguish rows whose
values were read from handwriting from rows read from printed text. The column
is nullable on purpose: existing rows have no item-level handwriting judgement
to backfill, and storing ``false`` for them would pretend "printed" where the
system only knows "not recorded".
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c1e7a4b2d30"
down_revision: str | Sequence[str] | None = "e2d7b4c1f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable ``line_items.is_handwritten``."""
    with op.batch_alter_table("line_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_handwritten", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Drop ``line_items.is_handwritten``."""
    with op.batch_alter_table("line_items", schema=None) as batch_op:
        batch_op.drop_column("is_handwritten")
