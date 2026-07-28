"""Persistence layer: SQLAlchemy ORM for the seven-table data model (spec §6).

Portable across PostgreSQL (production) and SQLite (development/tests). Import
:class:`Base` for metadata operations and the seven model classes for queries.

The repository functions (spec §14.8) are the read/write API over those tables;
each takes an explicit :class:`~sqlalchemy.orm.Session`, and the caller owns the
transaction (:func:`apply_corrections` is the documented exception -- it is
transactional itself). :mod:`receipts.persist.session` builds the engine and
session factory.
"""

from __future__ import annotations

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
    ValidationFinding,
)
from .repository import (
    apply_corrections,
    get_receipt,
    query_receipts,
    redact_pan,
    save_extraction,
    save_extraction_run,
    save_findings,
)
from .session import DEFAULT_URL, make_engine, make_session_factory

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
    "ValidationFinding",
    "apply_corrections",
    "get_receipt",
    "make_engine",
    "make_session_factory",
    "query_receipts",
    "redact_pan",
    "save_extraction",
    "save_extraction_run",
    "save_findings",
]
