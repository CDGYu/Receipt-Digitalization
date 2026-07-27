"""Persistence layer: SQLAlchemy ORM for the seven-table data model (spec §6).

Portable across PostgreSQL (production) and SQLite (development/tests). Import
:class:`Base` for metadata operations and the seven model classes for queries.
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

__all__ = [
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
]
