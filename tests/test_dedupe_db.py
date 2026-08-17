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
from datetime import UTC, date, datetime
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


def test_find_duplicate_by_phash_excludes_rows_already_marked_a_duplicate_of_it(
    engine: sa.Engine,
) -> None:
    """The one-step-further case of excluding the receipt itself.

    A row that duplicates ``exclude_id`` holds a copy of that very image, so
    without this a reprocessed original matches its own copy and is marked a
    duplicate of it: an ``A <-> B`` cycle in which both rows are ``rejected``
    and the transaction silently leaves the default export.
    """
    with Session(engine) as session:
        original = _receipt(session)
        copy = _receipt(session)
        mark_duplicate(session, copy.id, original.id)
        session.flush()

        # The copy is still a perfectly good match for anyone else.
        assert find_duplicate_by_phash(session, PHASH) is not None
        assert find_duplicate_by_phash(session, PHASH, exclude_id=original.id) is None
        # ...and excluding an unrelated id does not drop it.
        assert find_duplicate_by_phash(session, PHASH, exclude_id=uuid.uuid4()) is not None


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


def test_find_duplicate_by_content_excludes_rows_already_marked_a_duplicate_of_it(
    engine: sa.Engine,
) -> None:
    """The content twin of the phash exclusion, and for the same reason.

    A row that duplicates ``exclude_id`` still carries the merchant, date and
    total it was merged over, so it matches the original on every key. Offering
    it back is how a reprocessed original is marked a duplicate of its own copy
    -- an ``A -> B -> A`` cycle that ``mark_duplicate`` then refuses by raising,
    taking the reprocess down with it.
    """
    with Session(engine) as session:
        merchant = _merchant(session)
        keys = dict(
            merchant_id=merchant.id, txn_date=date(2026, 7, 27), total=Decimal("761.60")
        )
        original = _receipt(session, **keys)
        copy = _receipt(session, **keys)
        mark_duplicate(session, copy.id, original.id)
        session.flush()

        # The copy is still a perfectly good match for anyone else.
        assert find_duplicate_by_content(session, **keys) is not None
        assert find_duplicate_by_content(session, **keys, exclude_id=original.id) is None
        # ...and excluding an unrelated id does not drop it.
        assert find_duplicate_by_content(session, **keys, exclude_id=uuid.uuid4()) is not None


def test_find_duplicate_by_content_excludes_a_row_that_resolves_back_down_a_chain(
    engine: sa.Engine,
) -> None:
    """"Resolves back to it" is the whole chain, not one hop.

    ``mark_duplicate`` refuses any link that closes a cycle *anywhere* along
    ``duplicate_of``, so a finder that only drops direct back-links still hands
    out targets the writer will reject -- which turns that ``ValueError`` from a
    last-resort invariant into a routine outcome. The two sides have to refuse
    the same set.
    """
    with Session(engine) as session:
        merchant = _merchant(session)
        keys = dict(
            merchant_id=merchant.id, txn_date=date(2026, 7, 27), total=Decimal("761.60")
        )
        first = _receipt(session, **keys)
        second = _receipt(session, **keys)
        third = _receipt(session, **keys)
        # third -> second -> first, so only `third` is a *direct* back-link of
        # `second`, while both resolve back to `first`.
        mark_duplicate(session, third.id, second.id)
        mark_duplicate(session, second.id, first.id)
        session.flush()

        assert find_duplicate_by_content(session, **keys, exclude_id=first.id) is None


def test_find_duplicate_by_content_still_offers_a_candidate_that_does_not_resolve_back(
    engine: sa.Engine,
) -> None:
    """The exclusion drops the copies, not the queue behind them.

    Refusing every candidate as soon as one of them resolves back would satisfy
    "never offered its own copy" by never offering anything, and would quietly
    turn semantic dedupe off for every receipt that has ever been copied. The
    copy sorts first here, so the answer has to come from behind it.
    """
    with Session(engine) as session:
        merchant = _merchant(session)
        keys = dict(
            merchant_id=merchant.id, txn_date=date(2026, 7, 27), total=Decimal("761.60")
        )
        mine = _receipt(session, **keys)
        copy = _receipt(session, **keys)
        other = _receipt(session, **keys)
        mark_duplicate(session, copy.id, mine.id)
        # `created_at` is a second-resolution server default here, so the order
        # the query promises is stated rather than assumed: the copy is older
        # than the unrelated receipt and would otherwise win.
        copy.created_at = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
        other.created_at = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
        session.flush()

        found = find_duplicate_by_content(session, **keys, exclude_id=mine.id)

        assert found is not None, "the only cycle-free candidate was dropped too"
        assert found.id == other.id


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


def test_mark_duplicate_rejects_a_link_that_closes_a_cycle(engine: sa.Engine) -> None:
    """Self-reference is only the one-hop case of the rule the docstring states.

    ``A <-> B`` leaves both rows ``rejected``, so both drop out of the default
    export and the transaction leaves the ledger with no un-rejected row left to
    follow the chain to. Refusing the link keeps the original intact.
    """
    with Session(engine) as session:
        original = _receipt(session)
        copy = _receipt(session)
        mark_duplicate(session, copy.id, original.id)

        with pytest.raises(ValueError, match="cycle"):
            mark_duplicate(session, original.id, copy.id)

        assert original.duplicate_of is None
        assert copy.duplicate_of == original.id


def test_mark_duplicate_rejects_a_cycle_further_down_the_chain(engine: sa.Engine) -> None:
    """The walk follows ``duplicate_of``, so a longer chain is caught too."""
    with Session(engine) as session:
        first = _receipt(session)
        second = _receipt(session)
        third = _receipt(session)
        mark_duplicate(session, third.id, second.id)
        mark_duplicate(session, second.id, first.id)

        # first -> third would close first -> third -> second -> first.
        with pytest.raises(ValueError, match="cycle"):
            mark_duplicate(session, first.id, third.id)

        assert first.duplicate_of is None


def test_mark_duplicate_still_allows_a_chain_that_stays_acyclic(engine: sa.Engine) -> None:
    """The guard must not refuse an ordinary chain of three distinct copies."""
    with Session(engine) as session:
        first = _receipt(session)
        second = _receipt(session)
        third = _receipt(session)
        mark_duplicate(session, second.id, first.id)
        mark_duplicate(session, third.id, second.id)

        assert second.duplicate_of == first.id
        assert third.duplicate_of == second.id


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
