"""Alembic migration tests for the seven-table schema (spec §6).

Everything here runs against a **temp-file SQLite database** -- no Postgres, no
psycopg, no network. The migration itself is deliberately written with portable
types (``sa.Uuid``, ``sa.Numeric``, ``sa.JSON``), so the same revision applies to
both backends; SQLite is what we can actually exercise offline.

Three things are pinned down:

  * ``upgrade head`` builds all seven tables.
  * ``downgrade base`` removes them again (the downgrade is real, not a stub).
  * **The migrated schema matches ``Base.metadata`` exactly** -- Alembic's own
    autogenerate comparison finds nothing left to do. This is the drift guard:
    if someone edits a model and forgets the migration, this fails.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

# `from alembic import command` sorts with the first-party imports: the repo-root
# alembic/ directory shadows the package name for the import sorter. Leave it here.
from alembic import command
from receipts.persist import Base

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
ALEMBIC_DIR = REPO_ROOT / "alembic"

EXPECTED_TABLES = {
    "merchants",
    "receipts",
    "line_items",
    "extraction_runs",
    "validation_findings",
    "corrections",
    "review_tasks",
    # Added with the review API (P4.T3); not part of the original seven.
    "users",
}


@pytest.fixture()
def alembic_cfg(tmp_path: Path) -> Config:
    """Alembic config pointed at a throwaway SQLite file in ``tmp_path``.

    ``sqlalchemy.url`` set here is the explicit override branch of ``env.py``'s
    URL resolution, so the test never touches ``DATABASE_URL`` or any real DB.
    """
    assert ALEMBIC_INI.is_file(), f"missing alembic.ini at {ALEMBIC_INI}"
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    return cfg


def _table_names(cfg: Config) -> set[str]:
    """Reflect table names, disposing the engine (Windows keeps file locks)."""
    engine = create_engine(cfg.get_main_option("sqlalchemy.url") or "")
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_head_creates_all_seven_tables(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")

    tables = _table_names(alembic_cfg)
    assert EXPECTED_TABLES <= tables
    # Nothing beyond the seven tables plus Alembic's own bookkeeping table.
    assert tables - EXPECTED_TABLES == {"alembic_version"}


def test_downgrade_base_drops_all_seven_tables(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, "head")
    assert EXPECTED_TABLES <= _table_names(alembic_cfg)

    command.downgrade(alembic_cfg, "base")
    assert _table_names(alembic_cfg) & EXPECTED_TABLES == set()


def test_migration_schema_matches_orm_metadata(alembic_cfg: Config) -> None:
    """No pending autogenerate diffs: the migration *is* the ORM (drift guard)."""
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(alembic_cfg.get_main_option("sqlalchemy.url") or "")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "target_metadata": Base.metadata}
            )
            diffs = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diffs == [], f"migration has drifted from the ORM models: {diffs}"


def test_migration_metadata_imports_without_the_image_stack() -> None:
    """``alembic upgrade head`` must work on a *base* install.

    ``env.py`` needs nothing but the schema, so the module it takes
    ``Base.metadata`` from must not drag in the optional ``pipeline`` extra
    (numpy, Pillow, and the ``receipts.ingest`` chain that imports them). Checked
    in a subprocess because this test session has already imported them.
    """
    probe = (
        "import sys; import receipts.persist.models as m; "
        "assert m.Base.metadata.tables, 'no tables on the metadata'; "
        "heavy = [n for n in ('numpy', 'PIL', 'cv2', 'receipts.ingest.dedupe') "
        "if n in sys.modules]; "
        "assert not heavy, heavy"
    )
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)]),
    }
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=120,
    )

    assert result.returncode == 0, (
        "importing the migration's metadata pulled optional pipeline "
        f"dependencies:\n{result.stdout}\n{result.stderr}"
    )


def test_env_py_imports_metadata_from_the_light_module() -> None:
    """The import in ``env.py`` is the load-bearing half of the fix above."""
    source = (ALEMBIC_DIR / "env.py").read_text(encoding="utf-8")
    assert "from receipts.persist.models import Base" in source
    assert "from receipts.persist import Base" not in source


def test_line_items_fk_cascades_and_position_is_unique(alembic_cfg: Config) -> None:
    """Constraints autogenerate does not compare: ON DELETE CASCADE and the pair unique."""
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(alembic_cfg.get_main_option("sqlalchemy.url") or "")
    try:
        inspector = sa.inspect(engine)
        fks = inspector.get_foreign_keys("line_items")
        uniques = inspector.get_unique_constraints("line_items")
    finally:
        engine.dispose()

    receipt_fk = next(fk for fk in fks if fk["constrained_columns"] == ["receipt_id"])
    assert receipt_fk["referred_table"] == "receipts"
    assert (receipt_fk.get("options") or {}).get("ondelete") == "CASCADE"

    assert any(uc["column_names"] == ["receipt_id", "position"] for uc in uniques)
