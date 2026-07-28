"""DB-backed duplicate detection: the layer that feeds the pure §14.1 helpers.

Everything here runs on an in-memory SQLite database with ``PRAGMA
foreign_keys=ON`` (the same fixture pattern as ``test_repository.py``) -- no
Postgres, no psycopg, no network.

The pure helpers in :mod:`receipts.ingest.dedupe` already decide *whether* two
receipts are the same; what is pinned down here is the repository layer that
loads candidates for them, and above all the cases where it must stay **silent**:

  * a hash 32 bits away is not a near-duplicate, and a receipt is never its own
    duplicate (``exclude_id``);
  * insufficient key fields -- a NULL ``total`` most of all -- match *nothing*.
    A NULL total that matched every other undated receipt would silently merge
    unrelated purchases, which is far worse than missing a duplicate.

Money comparison stays in ``Decimal`` (ADR-0001): a candidate stored as
``761.6000`` must match a lookup for ``Decimal("761.60")``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from receipts.persist import (
    Merchant,
    Receipt,
    find_duplicate_by_content,
    find_duplicate_by_phash,
    mark_duplicate,
)
from receipts.persist.models import Base
from receipts.score.confidence import ReceiptStatus

#: A reference hash and three neighbours with known Hamming distances, so the
#: threshold behaviour is asserted against exact bit counts rather than vibes:
#:   * ``PHASH_SAME``      -> distance 0
#:   * ``PHASH_ONE_BIT``   -> distance 1 (``f`` -> ``e``): a re-compressed copy
#:   * ``PHASH_FAR``       -> distance 32 (the reference has 32 set bits)
PHASH = "0123456789abcdef"
PHASH_SAME = "0123456789abcdef"
PHASH_ONE_BIT = "0123456789abcdee"
PHASH_FAR = "ffffffffffffffff"


@pytest.fixture()
def engine() -> sa.Engine:
    """In-memory SQLite with FK enforcement on (mirrors ``test_repository.py``)."""
    eng = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(eng)
    return eng


def _receipt(
    session: Session,
    *,
    phash: str = PHASH,
    merchant_id: uuid.UUID | None = None,
    txn_date: date | None = None,
    total: Decimal | None = None,
) -> Receipt:
    """A minimal persisted receipt -- only the columns dedupe reads."""
    receipt_id = uuid.uuid4()
    receipt = Receipt(
        id=receipt_id,
        merchant_id=merchant_id,
        txn_date=txn_date,
        total=total,
        image_key=f"receipts/2026/07/{receipt_id}/original.jpg",
        image_phash=phash,
        status=ReceiptStatus.PENDING,
    )
    session.add(receipt)
    session.flush()
    return receipt


def _merchant(session: Session, name: str = "TOTAL WINE") -> Merchant:
    merchant = Merchant(canonical_name=name)
    session.add(merchant)
    session.flush()
    return merchant


# --------------------------------------------------------------------------- #
# find_duplicate_by_phash
# --------------------------------------------------------------------------- #


def test_find_duplicate_by_phash_finds_the_same_image(engine: sa.Engine) -> None:
    with Session(engine) as session:
        existing = _receipt(session, phash=PHASH)

        found = find_duplicate_by_phash(session, PHASH_SAME)

        assert found is not None
        assert found.id == existing.id


def test_find_duplicate_by_phash_finds_a_recompressed_copy(engine: sa.Engine) -> None:
    with Session(engine) as session:
        existing = _receipt(session, phash=PHASH)

        # One bit apart: the same photo, re-encoded.
        found = find_duplicate_by_phash(session, PHASH_ONE_BIT)

        assert found is not None
        assert found.id == existing.id


def test_find_duplicate_by_phash_returns_none_for_a_far_apart_hash(engine: sa.Engine) -> None:
    with Session(engine) as session:
        _receipt(session, phash=PHASH)

        assert find_duplicate_by_phash(session, PHASH_FAR) is None


def test_find_duplicate_by_phash_respects_a_wider_threshold(engine: sa.Engine) -> None:
    with Session(engine) as session:
        existing = _receipt(session, phash=PHASH)

        assert find_duplicate_by_phash(session, PHASH_FAR, threshold=31) is None
        found = find_duplicate_by_phash(session, PHASH_FAR, threshold=32)
        assert found is not None
        assert found.id == existing.id


def test_find_duplicate_by_phash_excludes_the_receipt_itself(engine: sa.Engine) -> None:
    with Session(engine) as session:
        mine = _receipt(session, phash=PHASH)

        # Without exclude_id the receipt is its own duplicate; with it, nothing.
        assert find_duplicate_by_phash(session, PHASH) is not None
        assert find_duplicate_by_phash(session, PHASH, exclude_id=mine.id) is None


def test_find_duplicate_by_phash_skips_rows_with_no_hash(engine: sa.Engine) -> None:
    with Session(engine) as session:
        _receipt(session, phash="")

        # An empty stored hash is not comparable and must never match.
        assert find_duplicate_by_phash(session, PHASH) is None


def test_find_duplicate_by_phash_returns_none_for_an_empty_lookup_hash(engine: sa.Engine) -> None:
    with Session(engine) as session:
        _receipt(session, phash=PHASH)

        assert find_duplicate_by_phash(session, "") is None


def test_find_duplicate_by_phash_returns_none_on_an_empty_table(engine: sa.Engine) -> None:
    with Session(engine) as session:
        assert find_duplicate_by_phash(session, PHASH) is None


# --------------------------------------------------------------------------- #
# find_duplicate_by_content
# --------------------------------------------------------------------------- #


def test_find_duplicate_by_content_matches_merchant_date_and_total(engine: sa.Engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        existing = _receipt(
            session,
            merchant_id=merchant.id,
            txn_date=date(2026, 7, 27),
            total=Decimal("761.60"),
        )

        # Note the different scale on the way in: the comparison is Decimal
        # equality (ADR-0001), so 761.60 matches a stored 761.6000.
        found = find_duplicate_by_content(
            session, merchant.id, date(2026, 7, 27), Decimal("761.6")
        )

        assert found is not None
        assert found.id == existing.id


def test_find_duplicate_by_content_ignores_a_differing_total(engine: sa.Engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        _receipt(
            session,
            merchant_id=merchant.id,
            txn_date=date(2026, 7, 27),
            total=Decimal("761.60"),
        )

        assert (
            find_duplicate_by_content(
                session, merchant.id, date(2026, 7, 27), Decimal("761.61")
            )
            is None
        )


def test_find_duplicate_by_content_ignores_a_differing_date(engine: sa.Engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        _receipt(
            session,
            merchant_id=merchant.id,
            txn_date=date(2026, 7, 27),
            total=Decimal("761.60"),
        )

        assert (
            find_duplicate_by_content(
                session, merchant.id, date(2026, 7, 28), Decimal("761.60")
            )
            is None
        )


def test_find_duplicate_by_content_ignores_another_merchant(engine: sa.Engine) -> None:
    with Session(engine) as session:
        mine = _merchant(session)
        other = _merchant(session, "COSTCO")
        _receipt(
            session,
            merchant_id=other.id,
            txn_date=date(2026, 7, 27),
            total=Decimal("761.60"),
        )

        assert (
            find_duplicate_by_content(session, mine.id, date(2026, 7, 27), Decimal("761.60"))
            is None
        )


def test_find_duplicate_by_content_returns_none_when_the_total_is_null(engine: sa.Engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        # A stored receipt whose total the model could not read.
        _receipt(session, merchant_id=merchant.id, txn_date=date(2026, 7, 27), total=None)

        # A NULL total is not a key: it must match nothing, not everything.
        assert find_duplicate_by_content(session, merchant.id, date(2026, 7, 27), None) is None


def test_find_duplicate_by_content_returns_none_when_the_date_is_null(engine: sa.Engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        _receipt(session, merchant_id=merchant.id, txn_date=None, total=Decimal("761.60"))

        assert find_duplicate_by_content(session, merchant.id, None, Decimal("761.60")) is None


def test_find_duplicate_by_content_excludes_the_receipt_itself(engine: sa.Engine) -> None:
    with Session(engine) as session:
        merchant = _merchant(session)
        mine = _receipt(
            session,
            merchant_id=merchant.id,
            txn_date=date(2026, 7, 27),
            total=Decimal("761.60"),
        )

        assert (
            find_duplicate_by_content(session, merchant.id, date(2026, 7, 27), Decimal("761.60"))
            is not None
        )
        assert (
            find_duplicate_by_content(
                session,
                merchant.id,
                date(2026, 7, 27),
                Decimal("761.60"),
                exclude_id=mine.id,
            )
            is None
        )


def test_find_duplicate_by_content_matches_two_receipts_with_no_merchant(
    engine: sa.Engine,
) -> None:
    with Session(engine) as session:
        existing = _receipt(
            session, merchant_id=None, txn_date=date(2026, 7, 27), total=Decimal("761.60")
        )

        found = find_duplicate_by_content(session, None, date(2026, 7, 27), Decimal("761.60"))

        assert found is not None
        assert found.id == existing.id


# --------------------------------------------------------------------------- #
# mark_duplicate
# --------------------------------------------------------------------------- #


def test_mark_duplicate_sets_duplicate_of(engine: sa.Engine) -> None:
    with Session(engine) as session:
        existing_id = _receipt(session).id
        new_id = _receipt(session).id

        linked = mark_duplicate(session, new_id, existing_id)
        assert linked.id == new_id
        assert linked.duplicate_of == existing_id
        session.commit()

    with Session(engine) as session:
        got = session.get(Receipt, new_id)
        assert got is not None
        assert got.duplicate_of == existing_id
        # The link is one-way: the original is not marked a duplicate.
        original = session.get(Receipt, existing_id)
        assert original is not None
        assert original.duplicate_of is None


def test_mark_duplicate_rejects_an_unknown_new_id(engine: sa.Engine) -> None:
    with Session(engine) as session:
        existing = _receipt(session)
        missing = uuid.uuid4()

        with pytest.raises(ValueError, match=str(missing)):
            mark_duplicate(session, missing, existing.id)


def test_mark_duplicate_rejects_an_unknown_existing_id(engine: sa.Engine) -> None:
    with Session(engine) as session:
        new = _receipt(session)
        missing = uuid.uuid4()

        with pytest.raises(ValueError, match=str(missing)):
            mark_duplicate(session, new.id, missing)

        # Nothing was written.
        assert new.duplicate_of is None


def test_mark_duplicate_rejects_linking_a_receipt_to_itself(engine: sa.Engine) -> None:
    with Session(engine) as session:
        receipt = _receipt(session)

        with pytest.raises(ValueError, match="itself"):
            mark_duplicate(session, receipt.id, receipt.id)

        assert receipt.duplicate_of is None


def test_mark_duplicate_does_not_commit(engine: sa.Engine) -> None:
    """The caller owns the transaction (the repository convention)."""
    with Session(engine) as session:
        existing = _receipt(session)
        new = _receipt(session)
        mark_duplicate(session, new.id, existing.id)
        session.rollback()

    with Session(engine) as session:
        # The rollback took the receipts with it -- nothing was committed.
        assert list(session.scalars(select(Receipt))) == []
