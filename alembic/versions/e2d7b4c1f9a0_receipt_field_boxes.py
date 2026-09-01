"""receipt field boxes

Revision ID: e2d7b4c1f9a0
Revises: 8b2f0c9d4e11
Create Date: 2026-09-01 00:00:00.000000

``receipts.field_boxes`` -- where receipt-LEVEL fields sit on the image, as
JSON keyed by the dotted correction path the review UI edits them under
(``{"merchant.name": [x0, y0, x1, y1], ...}``), normalised 0-1, the same
convention as ``line_items.bbox``. Filled by the OCR grounding pass
(``pipeline.py``) for the fields it can place unambiguously, so the review
screen can highlight a field's location on the photo when a reviewer focuses it.

Added ``NOT NULL`` with a ``server_default`` of ``'{}'``, matching
``line_items.is_template_row`` in ``f3ae0f86e0e6``: both SQLite and Postgres
refuse ``ADD COLUMN ... NOT NULL`` with no default the moment the table holds a
row, and there is nothing to backfill an existing receipt WITH -- grounding
never ran for it, so an empty map is the truthful state. The server default
only backfills; going forward the ORM's Python-side ``default=dict`` supplies
``{}`` for every row it writes (see ``receipts.persist.models.Receipt``). The
literal ``'{}'`` is valid JSON on both backends, so no per-dialect spelling is
needed the way ``sa.false()`` was for the boolean columns.

**THERE IS NO BACKFILL, AND NONE IS POSSIBLE**, for the same reason the tax
bands revision (``d5b8c31e7a04``) records: the geometry was never produced for
a receipt processed before this column existed. Every existing receipt gets an
empty ``{}``, which is the honest state rather than a gap, and a receipt only
gains boxes when it is re-run with OCR grounding enabled.

Hand-written, matching ``d5b8c31e7a04``'s conventions: a single
``batch_alter_table`` add-column with an explicit portable ``server_default``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2d7b4c1f9a0"
down_revision: str | Sequence[str] | None = "8b2f0c9d4e11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``receipts.field_boxes`` (JSON, NOT NULL, default empty map)."""
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "field_boxes",
                sa.JSON(),
                server_default="{}",
                nullable=False,
            )
        )


def downgrade() -> None:
    """Drop ``receipts.field_boxes``.

    Reversible in the schema sense; lossy in the data sense -- it discards
    whatever boxes the grounding pass had placed. The upgrade cannot put them
    back (see the no-backfill note above).
    """
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.drop_column("field_boxes")
