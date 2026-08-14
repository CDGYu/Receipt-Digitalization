"""The merchant registry: the only module that touches the `merchants` table.

In-memory SQLite with FK enforcement, mirroring `tests/test_dedupe_db.py`.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from receipts.merchants.registry import lookup
from receipts.persist import Merchant
from receipts.persist.models import Base


@pytest.fixture()
def engine() -> sa.Engine:
    eng = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


def _merchant(session: Session, name: str, **kw) -> Merchant:
    merchant = Merchant(canonical_name=name, **kw)
    session.add(merchant)
    session.flush()
    return merchant


def test_lookup_matches_the_canonical_name_exactly(engine: sa.Engine) -> None:
    with Session(engine) as session:
        stored = _merchant(session, "METRO OIL SUBIC INC.")

        found = lookup(session, "METRO OIL SUBIC INC.")

        assert found is not None
        assert found.id == stored.id


def test_lookup_folds_case_punctuation_and_legal_suffix(engine: sa.Engine) -> None:
    """`normalize_merchant_name` is what makes these the same merchant."""
    with Session(engine) as session:
        stored = _merchant(session, "METRO OIL SUBIC INC.")

        found = lookup(session, "Metro Oil Subic Inc")

        assert found is not None
        assert found.id == stored.id


def test_lookup_matches_a_known_variant(engine: sa.Engine) -> None:
    with Session(engine) as session:
        stored = _merchant(
            session, "METRO OIL SUBIC INC.", name_variants=["METRO OIL SUBIC BAY"]
        )

        found = lookup(session, "metro oil subic bay")

        assert found is not None
        assert found.id == stored.id


def test_lookup_does_not_guess(engine: sa.Engine) -> None:
    """No fuzzy matching (spec D2): a near miss is a miss."""
    with Session(engine) as session:
        _merchant(session, "METRO OIL SUBIC INC.")

        assert lookup(session, "METRO 0IL SUBIC") is None


@pytest.mark.parametrize("guess", [None, "", "   ", "Inc."])
def test_lookup_returns_none_for_an_empty_guess(engine: sa.Engine, guess) -> None:
    """`"Inc."` normalizes to the empty string -- it is all legal suffix."""
    with Session(engine) as session:
        _merchant(session, "METRO OIL SUBIC INC.")

        assert lookup(session, guess) is None
