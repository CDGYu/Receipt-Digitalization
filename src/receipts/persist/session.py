"""Engine and session factories (the only place that opens a connection).

Two tiny functions, deliberately: the repository takes an explicit
:class:`~sqlalchemy.orm.Session`, so nothing else in the package needs to know
where the database lives. Nothing here connects at import time -- no module-level
engine, no global session -- so importing :mod:`receipts.persist` stays free and
tests can build throwaway in-memory engines.

URL precedence mirrors ``alembic/env.py`` so the app and the migrations always
agree: an explicit argument, then ``DATABASE_URL`` read through
:class:`config.settings.Settings`, then a local SQLite file (ADR-0004: Postgres
in production, SQLite in dev and tests, no driver to install).
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings

#: Local fallback when nothing is configured -- same value as
#: ``alembic/env.py``'s ``DEFAULT_URL``, so ``alembic upgrade head`` and the
#: application point at the same database on a fresh checkout.
DEFAULT_URL = "sqlite:///receipts.db"


def make_engine(url: str | None = None) -> Engine:
    """Build an :class:`~sqlalchemy.Engine` for ``url`` (or the configured one).

    On SQLite a ``connect`` listener issues ``PRAGMA foreign_keys=ON``: SQLite
    ignores foreign keys -- and therefore ``ON DELETE CASCADE`` -- unless that
    pragma is set on every connection, which would silently leave orphaned
    ``line_items`` behind in development while production cascaded correctly.
    """
    resolved = url or Settings().database_url or DEFAULT_URL
    engine = create_engine(resolved)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """A ``sessionmaker`` bound to ``engine``.

    Defaults are left alone (``expire_on_commit=True``) so a committed object is
    re-read rather than served stale. Callers own the transaction boundary --
    ``with factory() as session:`` then ``session.commit()``.
    """
    return sessionmaker(bind=engine)
