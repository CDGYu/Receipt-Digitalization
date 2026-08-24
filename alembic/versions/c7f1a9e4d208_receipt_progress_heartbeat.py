"""receipt progress heartbeat

Revision ID: c7f1a9e4d208
Revises: f3ae0f86e0e6
Create Date: 2026-08-24 00:00:00.000000

Two nullable columns on ``receipts`` recording when a run was last known alive
and what it was doing:

* ``receipts.progress_stage`` -- a member of ``receipts.pipeline.STAGES``,
  written on stage entry and once per model call inside extract.
* ``receipts.progress_at`` -- when that write happened.

Both nullable and both without a server default, deliberately. NULL is
meaningful here: it means no run has ever reported on this receipt, which
``receipts.sweep`` treats as a different failure mode from "started and went
cold" on a different timescale. A backfill would erase exactly the distinction
the sweep depends on, and a ``NOT NULL`` column would need one.

Because both are nullable, this needs no ``server_default`` and therefore none
of the portability care ``f3ae0f86e0e6`` documents for its boolean.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7f1a9e4d208"
down_revision: str | Sequence[str] | None = "f3ae0f86e0e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``receipts.progress_stage`` and ``receipts.progress_at``."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("progress_stage", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("progress_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Drop both columns, newest first."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.drop_column("progress_at")
        batch_op.drop_column("progress_stage")
