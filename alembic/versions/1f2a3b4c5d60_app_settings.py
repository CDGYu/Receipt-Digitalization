"""app_settings

Revision ID: 1f2a3b4c5d60
Revises: 9c1e7a4b2d30
Create Date: 2026-09-02 00:00:00.000000

One addition: the ``app_settings`` table, a ``(key, value)`` store for
operator-editable runtime knobs. The first and only key today is
``processing_mode`` (local / cloud / hybrid), which decides whether the extract
ladder runs a pure-local rung, a pure-cloud rung, or the local-primary +
cloud-fallback ladder.

``value`` is ``Text`` and there is no DB ENUM, matching ``users.role``: the
migration drift guard (``tests/test_migrations.py``) runs on SQLite only and
cannot see a new ENUM member, so an ENUM here would pass locally and fail on
Postgres. The meaning of each key is validated in
``receipts.persist.app_settings``.

``updated_at`` carries a ``server_default`` of ``now()`` for the same reason
every other timestamp column in this schema does: the ORM's Python-side default
still supplies the value for rows it writes, and the server default only
backfills.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f2a3b4c5d60"
down_revision: str | Sequence[str] | None = "9c1e7a4b2d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the ``app_settings`` key/value table."""
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Drop the ``app_settings`` table."""
    op.drop_table("app_settings")
