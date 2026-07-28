"""Persistence layer: SQLAlchemy ORM for the seven-table data model (spec §6).

Portable across PostgreSQL (production) and SQLite (development/tests). Import
:class:`Base` for metadata operations and the seven model classes for queries.

The repository functions (spec §14.8) are the read/write API over those tables;
each takes an explicit :class:`~sqlalchemy.orm.Session`, and the caller owns the
transaction (:func:`apply_corrections` is the documented exception -- it is
transactional itself). :mod:`receipts.persist.session` builds the engine and
session factory.

**The models are imported eagerly; the repository and session helpers are not.**
:mod:`receipts.persist.models` needs nothing but SQLAlchemy, while the repository
reaches :mod:`receipts.ingest.dedupe` and through it numpy and Pillow -- which
live in the optional ``pipeline`` extra. Loading those on ``import
receipts.persist.models`` would mean a base install could not run ``alembic
upgrade head``, so the heavier names are resolved on first attribute access
(:pep:`562`). ``from receipts.persist import save_extraction`` still works
exactly as before, and imports the same module it always did -- just later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import (
    Base,
    Correction,
    ExtractionRun,
    LineItem,
    Merchant,
    PassName,
    Receipt,
    ReviewState,
    ReviewTask,
    User,
    ValidationFinding,
)

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from .repository import (
        apply_corrections,
        create_pending_receipt,
        find_duplicate_by_content,
        find_duplicate_by_phash,
        get_findings,
        get_receipt,
        mark_duplicate,
        query_receipts,
        redact_pan,
        save_extraction,
        save_extraction_run,
        save_findings,
    )
    from .session import DEFAULT_URL, make_engine, make_session_factory

#: Lazily re-exported name -> the submodule that defines it.
_LAZY: dict[str, str] = {
    "apply_corrections": "repository",
    "create_pending_receipt": "repository",
    "find_duplicate_by_content": "repository",
    "find_duplicate_by_phash": "repository",
    "get_findings": "repository",
    "get_receipt": "repository",
    "mark_duplicate": "repository",
    "query_receipts": "repository",
    "redact_pan": "repository",
    "save_extraction": "repository",
    "save_extraction_run": "repository",
    "save_findings": "repository",
    "DEFAULT_URL": "session",
    "make_engine": "session",
    "make_session_factory": "session",
}

__all__ = [
    "DEFAULT_URL",
    "Base",
    "Correction",
    "ExtractionRun",
    "LineItem",
    "Merchant",
    "PassName",
    "Receipt",
    "ReviewState",
    "ReviewTask",
    "User",
    "ValidationFinding",
    "apply_corrections",
    "create_pending_receipt",
    "find_duplicate_by_content",
    "find_duplicate_by_phash",
    "get_findings",
    "get_receipt",
    "make_engine",
    "make_session_factory",
    "mark_duplicate",
    "query_receipts",
    "redact_pan",
    "save_extraction",
    "save_extraction_run",
    "save_findings",
]


def __getattr__(name: str) -> Any:
    """Resolve a repository/session name on first use (:pep:`562`)."""
    from importlib import import_module

    # ``receipts.persist.repository`` as an *attribute* still resolves, so no
    # caller that relied on the previous eager import has to change.
    if name in {"repository", "session"}:
        return import_module(f".{name}", __name__)

    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(import_module(f".{module_name}", __name__), name)
    globals()[name] = value  # cache it: the lookup happens once per process
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
