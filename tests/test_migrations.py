"""Alembic migration tests for the seven-table schema (spec §6).

Everything here *executes* against a **temp-file SQLite database** -- no
Postgres, no psycopg, no network. The migrations are deliberately written with
portable types (``sa.Uuid``, ``sa.Numeric``, ``sa.JSON``), so the same revision
applies to both backends; SQLite is what we can actually run offline. The one
exception is the Postgres rendering guard below, which uses Alembic's *offline*
renderer and therefore needs neither a server nor a driver.

Five things are pinned down:

  * ``upgrade head`` builds all seven tables.
  * ``downgrade base`` removes them again (the downgrade is real, not a stub).
  * **The migrated schema matches ``Base.metadata`` exactly** -- Alembic's own
    autogenerate comparison finds nothing left to do. This is the drift guard:
    if someone edits a model and forgets the migration, this fails.
  * **Every revision applies to a database whose tables already hold rows**, and
    no ``NOT NULL`` column is ``NULL`` afterwards. Every other test here upgrades
    an *empty* database and so cannot see the single most common migration
    failure -- ``ADD COLUMN ... NOT NULL`` with no default, which both backends
    refuse the moment a table holds a row.
  * **The chain renders as valid Postgres, not just valid SQLite.** Autogenerate
    runs against SQLite here and will happily freeze a SQLite-only literal into a
    revision that then fails in production.

The last two are properties over *all* revisions rather than assertions about
one, so neither needs re-pointing when a revision is added.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
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

#: A URL that is never connected to. Alembic's ``--sql`` (offline) mode resolves
#: the dialect from the URL and renders DDL without opening a socket, so this
#: works with no Postgres server *and no psycopg installed* -- which is the
#: normal state of a dev checkout (ADR-0004).
POSTGRES_URL = "postgresql://user:password@localhost:5432/receipts"

#: Alembic's bookkeeping table. Not part of the schema under test, and it is the
#: one table a migration is *supposed* to write to.
ALEMBIC_BOOKKEEPING = "alembic_version"


def _revision_chain() -> list[tuple[str, str | None]]:
    """``(revision, down_revision)`` for every revision in the chain, oldest first.

    Read from the script directory rather than hardcoded, so a new revision joins
    the properties below automatically instead of when someone remembers.
    """
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    script = ScriptDirectory.from_config(cfg)
    # walk_revisions() yields head -> base; reverse it so a failure reads in the
    # order the migrations actually run.
    chain: list[tuple[str, str | None]] = []
    for revision in reversed(list(script.walk_revisions())):
        down = revision.down_revision
        # Merge revisions carry a tuple; none exist today, and a tuple would make
        # "upgrade to the predecessor" ambiguous, so say so rather than guess.
        assert not isinstance(down, tuple), (
            f"{revision.revision} is a merge revision; the populated-database "
            "property needs a single predecessor to seed at"
        )
        chain.append((revision.revision, down))
    return chain


REVISION_CHAIN = _revision_chain()


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


# --------------------------------------------------------------------------- #
# Seeding an arbitrary schema, for the populated-database property
#
# These work off *reflection*, not off Base.metadata, because they run against
# whatever schema existed at some earlier revision -- a metadata that describes
# today's columns would ask for columns the database does not have yet.
# --------------------------------------------------------------------------- #


def _seed_value(column: sa.Column[Any]) -> Any:
    """A plausible non-NULL value for ``column``, chosen from its reflected type.

    SQLite reflection erases the finer types (``sa.Uuid`` comes back ``CHAR(32)``,
    the enums come back ``VARCHAR``), so this dispatches on what reflection
    actually returns. The enums need no special case: SQLAlchemy's
    ``Enum.create_constraint`` defaults to False, so there is no CHECK constraint
    on SQLite for an arbitrary string to violate.
    """
    type_ = column.type
    if isinstance(type_, sa.Boolean):
        return False
    if isinstance(type_, sa.Integer):
        return 1
    if isinstance(type_, sa.Numeric):
        return Decimal("1")
    if isinstance(type_, sa.DateTime):
        return datetime.now(UTC)
    if isinstance(type_, sa.Date):
        return date.today()
    if isinstance(type_, sa.Time):
        return time(0, 0)
    if isinstance(type_, sa.JSON):
        return {}
    # Text-ish. 32 hex chars doubles as a UUID primary key; truncate for the
    # narrow ones (currency is String(3), card_last4 is String(4)).
    filler = uuid.uuid4().hex
    length = getattr(type_, "length", None)
    return filler[:length] if length else filler


def _seed_row(table: sa.Table, parent_keys: dict[str, Any]) -> dict[str, Any]:
    """Values for one row of ``table``: every NOT NULL column, and FKs resolved.

    Nullable columns are deliberately left out, so the row exercises the NULL
    path too -- and so the "no NOT NULL column is NULL" assertion afterwards is
    checking something rather than restating how the row was built.
    """
    values: dict[str, Any] = {}
    for column in table.columns:
        foreign_key = next(iter(column.foreign_keys), None)
        if foreign_key is not None:
            parent = foreign_key.column.table.name
            if parent in parent_keys:
                values[column.name] = parent_keys[parent]
            elif not column.nullable:
                raise AssertionError(
                    f"{table.name}.{column.name} is NOT NULL and references "
                    f"{parent}, which has not been seeded yet -- the FK sort order "
                    "is wrong"
                )
            # else: nullable and unseeded, e.g. the receipts.duplicate_of
            # self-reference. Leave it NULL.
            continue
        if column.nullable:
            continue
        values[column.name] = _seed_value(column)
    return values


def _seed_every_table(url: str) -> None:
    """Insert one row into every table that exists.

    Tables are filled parent-first (``sorted_tables`` is FK-topological) and each
    table's primary key is remembered so its children can point at a real row.
    """
    engine = create_engine(url)
    try:
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        parent_keys: dict[str, Any] = {}
        with engine.begin() as connection:
            for table in metadata.sorted_tables:
                if table.name == ALEMBIC_BOOKKEEPING:
                    continue
                values = _seed_row(table, parent_keys)
                connection.execute(table.insert().values(**values))
                primary_key = list(table.primary_key.columns)
                if len(primary_key) == 1 and primary_key[0].name in values:
                    parent_keys[table.name] = values[primary_key[0].name]
    finally:
        engine.dispose()


def _table_contents(url: str) -> dict[str, list[dict[str, Any]]]:
    """Every row of every table, as plain dicts.

    Read back from the database on both sides of the upgrade rather than
    remembering what was inserted, so the comparison is unaffected by how a type
    round-trips (SQLite hands back naive datetimes, for instance) and any
    difference that shows up is a difference the migration made.
    """
    engine = create_engine(url)
    try:
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        with engine.connect() as connection:
            return {
                table.name: [
                    dict(row) for row in connection.execute(sa.select(table)).mappings().all()
                ]
                for table in metadata.sorted_tables
                if table.name != ALEMBIC_BOOKKEEPING
            }
    finally:
        engine.dispose()


def _not_null_columns_holding_null(url: str) -> list[str]:
    """Every ``table.column`` that is NOT NULL yet contains a NULL.

    Deliberately written over *all* tables and *all* columns rather than the ones
    a given revision touches: this is the half of the property that keeps working
    as the schema grows.
    """
    engine = create_engine(url)
    offenders: list[str] = []
    try:
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        with engine.connect() as connection:
            for table in metadata.sorted_tables:
                if table.name == ALEMBIC_BOOKKEEPING:
                    continue
                for column in table.columns:
                    if column.nullable:
                        continue
                    nulls = connection.execute(
                        sa.select(sa.func.count())
                        .select_from(table)
                        .where(column.is_(None))
                    ).scalar_one()
                    if nulls:
                        offenders.append(f"{table.name}.{column.name} ({nulls} row(s))")
        return offenders
    finally:
        engine.dispose()


def _offline_ddl(url: str) -> str:
    """Render the whole chain as DDL for ``url``'s dialect, without connecting.

    ``--sql`` mode resolves the dialect from the URL string and never opens a
    connection, which is what lets this check Postgres from a machine that has
    neither a server nor a driver. Note it does *not* work for SQLite here:
    batch mode needs a live connection to reflect the table it rebuilds, and
    Alembic raises ``CommandError`` saying so. SQLite is covered by every other
    test in this module, which run against a real database.
    """
    buffer = io.StringIO()
    cfg = Config(str(ALEMBIC_INI), output_buffer=buffer)
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "base:head", sql=True)
    return buffer.getvalue()


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


@pytest.mark.parametrize(
    ("revision", "down_revision"),
    REVISION_CHAIN,
    ids=[revision for revision, _ in REVISION_CHAIN],
)
def test_every_revision_applies_to_a_populated_database(
    alembic_cfg: Config, revision: str, down_revision: str | None
) -> None:
    """Every revision must survive a database that already holds rows.

    Two properties, both over the whole schema rather than the table a given
    revision happens to touch:

      * no row is lost -- every table that had rows still has exactly as many;
      * **no NOT NULL column holds a NULL afterwards.**

    This is the failure mode from-scratch tests structurally cannot see.
    ``ADD COLUMN ... NOT NULL`` with no default fails on both SQLite and
    Postgres the moment the table holds a row, because there is nothing to
    backfill existing rows with. It is not hypothetical: a1c4d2f80b31 shipped
    exactly that bug on ``validation_findings.created_at``, and every other test
    in this module upgraded an empty file and stayed green.

    It also covers a shape that is easy to miss -- on SQLite a ``server_default``
    that is a ``ClauseElement`` (``sa.false()``, ``sa.func.now()``) makes batch
    mode *rebuild the table and copy every row* rather than ALTER it, so these
    revisions are exercising the riskiest operation Alembic has on tables that
    are not empty.

    The first revision has no predecessor, so its case seeds nothing and asserts
    nothing beyond "it applies" -- kept in the parametrisation for uniformity,
    and because that changes the day a revision is inserted before it.
    """
    url = alembic_cfg.get_main_option("sqlalchemy.url") or ""

    if down_revision is not None:
        command.upgrade(alembic_cfg, down_revision)
        _seed_every_table(url)
    before = _table_contents(url)

    if down_revision is not None:
        assert before, (
            f"nothing was seeded at {down_revision}, so this case would pass "
            "vacuously without ever testing a populated database"
        )

    # The line that raises if a NOT NULL column arrives without a default.
    command.upgrade(alembic_cfg, revision)

    after = _table_contents(url)

    for table, rows in before.items():
        assert table in after, f"{revision} dropped the table {table}"
        assert len(after[table]) == len(rows), (
            f"{revision} changed the row count of {table}: "
            f"{len(rows)} before, {len(after[table])} after"
        )
        # Columns that existed before must still hold what they held. A batch
        # rebuild does not ALTER the table, it recreates it and copies every row
        # across, so "the rows are still there" and "the rows are still correct"
        # are genuinely different claims.
        for old, new in zip(rows, after[table], strict=True):
            preserved = {name: value for name, value in new.items() if name in old}
            assert preserved == old, (
                f"{revision} altered an existing row of {table}: "
                f"{old} became {preserved}"
            )

    offenders = _not_null_columns_holding_null(url)
    assert offenders == [], (
        f"{revision} left NULLs in NOT NULL columns (a missing server_default "
        f"on a table that already had rows): {offenders}"
    )


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


def test_the_revision_chain_renders_as_valid_postgres_ddl() -> None:
    """The chain must render for Postgres, not only for the SQLite we run on.

    Autogenerate runs against SQLite here (ADR-0004: SQLite in dev, Postgres in
    production), so it reflects SQLite's spelling of a value and can freeze it
    into a revision. That is not a hypothetical either -- f3ae0f86e0e6 was
    generated with ``server_default=sa.text("0")``, SQLite's spelling of
    ``false``. It renders ``BOOLEAN DEFAULT 0`` on Postgres, which Postgres
    rejects: an integer default on a boolean column. The revision would have
    applied in dev and tests and failed in production.

    The property asserted is the class, not that instance: **a boolean column's
    default must be a boolean literal in the Postgres rendering.**

    Note what does *not* close this hole. ``compare_server_default=True`` on the
    drift guard above cannot: it runs on SQLite, where ``sa.text("0")`` and
    ``sa.false()`` render identically, so it reports no difference between the
    broken and the fixed revision. This test reads the Postgres rendering, which
    is the only place the two differ.

    No server and no driver are involved -- see :func:`_offline_ddl`.
    """
    ddl = _offline_ddl(POSTGRES_URL)
    assert ddl.strip(), "the offline renderer produced no SQL to check"

    boolean_literals = {"true", "false", "null"}
    offenders = [
        match.group(0)
        for match in re.finditer(r"BOOLEAN\s+DEFAULT\s+(\S+)", ddl, re.IGNORECASE)
        if match.group(1).rstrip(",;").lower() not in boolean_literals
    ]

    assert offenders == [], (
        "a boolean column is given a non-boolean default in the Postgres "
        f"rendering, which Postgres rejects: {offenders}"
    )


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
