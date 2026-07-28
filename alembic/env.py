"""Alembic environment for the seven-table receipt schema (spec §6).

The database URL is **resolved at runtime and never hardcoded**, in this order:

1. an explicit override -- ``-x db_url=...`` on the command line, or
   ``sqlalchemy.url`` set in ``alembic.ini`` / programmatically (this is how the
   test suite points migrations at a throwaway SQLite file);
2. ``DATABASE_URL`` from the environment, read through
   :class:`config.settings.Settings` so the app and the migrations agree;
3. ``sqlite:///receipts.db`` -- a local file, so a fresh checkout can run
   ``alembic upgrade head`` with no configuration and **no Postgres driver
   installed** (ADR-0004: Postgres in production, SQLite in dev/tests).

``render_as_batch`` is enabled for SQLite: SQLite cannot ``ALTER`` a column in
place, so batch mode recreates the table instead and future migrations keep
working on both backends. ``compare_type`` is on so autogenerate notices type
changes -- in particular a money column drifting away from ``Numeric``.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from config.settings import Settings

# Straight from ``models``, never from the ``receipts.persist`` package surface:
# the schema is all a migration needs, and this module imports nothing beyond
# SQLAlchemy and the project's own enums. The package surface would reach the
# repository layer and, through it, the image stack (numpy, Pillow) that lives in
# the optional ``pipeline`` extra -- so ``pip install -e .`` followed by
# ``alembic upgrade head`` would fail on an import that has nothing to do with
# the schema. ``tests/test_migrations.py`` pins both halves of this.
from receipts.persist.models import Base

#: Local fallback when nothing else is configured. Deliberately SQLite: no
#: driver to install, and no chance of a migration hitting a real database by
#: accident.
DEFAULT_URL = "sqlite:///receipts.db"

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: env.py is also imported in-process by the
    # test suite, and silencing pytest's loggers would be a nasty side effect.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def resolve_url() -> str:
    """Return the database URL, following the precedence documented above."""
    override = context.get_x_argument(as_dictionary=True).get("db_url")
    if not override:
        override = config.get_main_option("sqlalchemy.url", None)
    if override:
        return override
    return Settings().database_url or DEFAULT_URL


def run_migrations_offline() -> None:
    """Emit the migration as SQL to stdout (``alembic upgrade head --sql``)."""
    url = resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=url.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migration against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=connection.dialect.name == "sqlite",
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Release the file handle promptly: on Windows an open SQLite
        # connection blocks the test's tmp_path cleanup.
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
