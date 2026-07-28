"""Review queue tests (spec §14.9): enqueue, claim, close, and stats.

Everything runs on an in-memory SQLite database with ``PRAGMA foreign_keys=ON``
(the same fixture pattern as ``test_repository.py``) -- no Postgres, no psycopg,
no network.

Three behaviours are load-bearing and each has a test that would fail loudly if
it regressed:

  * ``review_tasks.receipt_id`` is UNIQUE, so a second ``enqueue_review`` for
    one receipt must update the existing row rather than raise an
    ``IntegrityError``. Nothing is ever silently dropped -- and a receipt must
    never lose its place in the queue because it was routed twice.
  * A lower priority number is worked sooner (§12: ``0`` is the urgent case), so
    the claim order is ``priority`` then ``opened_at``.
  * The claim locks the row on backends that can (``FOR UPDATE SKIP LOCKED``)
    and omits the clause where it is meaningless. SQLite *silently drops* the
    locking clause instead of erroring, which is exactly why the guard lives in
    Python -- see the compile tests at the bottom, which prove both directions
    without a Postgres driver.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from receipts.persist import Receipt, ReviewState, ReviewTask
from receipts.persist.models import Base
from receipts.review import QueueStats, close_task, enqueue_review, next_task, queue_stats
from receipts.review.queue import _claim_stmt, _supports_skip_locked
from receipts.score.confidence import ReceiptStatus

PHASH = "0123456789abcdef"


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


def _receipt(session: Session) -> Receipt:
    """A minimal persisted receipt to hang a review task off."""
    receipt_id = uuid.uuid4()
    receipt = Receipt(
        id=receipt_id,
        image_key=f"receipts/2026/07/{receipt_id}/original.jpg",
        image_phash=PHASH,
        status=ReceiptStatus.NEEDS_REVIEW,
    )
    session.add(receipt)
    session.flush()
    return receipt


def _task(
    session: Session,
    priority: int,
    *,
    reason: str = "quick verify",
    opened_at: datetime | None = None,
) -> ReviewTask:
    """An open task at ``priority``, optionally with an explicit ``opened_at``.

    ``opened_at`` defaults to ``CURRENT_TIMESTAMP``, which SQLite resolves only
    to the second, so tie-breaking tests set it explicitly rather than hoping
    two inserts land in different seconds.
    """
    task = enqueue_review(session, _receipt(session).id, reason, priority)
    if opened_at is not None:
        task.opened_at = opened_at
        session.flush()
    return task


# --------------------------------------------------------------------------- #
# enqueue_review
# --------------------------------------------------------------------------- #


def test_enqueue_review_creates_an_open_task(engine: sa.Engine) -> None:
    with Session(engine) as session:
        receipt = _receipt(session)

        task = enqueue_review(session, receipt.id, "full re-key", 1)

        assert task.receipt_id == receipt.id
        assert task.reason == "full re-key"
        assert task.priority == 1
        assert task.state is ReviewState.OPEN
        assert task.assigned_to is None
        assert task.closed_at is None
        session.commit()

    with Session(engine) as session:
        rows = list(session.scalars(select(ReviewTask)))
        assert len(rows) == 1
        assert rows[0].state is ReviewState.OPEN


def test_enqueue_review_twice_does_not_raise_and_keeps_one_row(engine: sa.Engine) -> None:
    with Session(engine) as session:
        receipt = _receipt(session)

        first = enqueue_review(session, receipt.id, "quick verify", 2)
        # receipt_id is UNIQUE: a second enqueue must update, not insert.
        second = enqueue_review(session, receipt.id, "urgent: total is missing", 0)
        session.commit()

        assert second.id == first.id

    with Session(engine) as session:
        rows = list(session.scalars(select(ReviewTask)))
        assert len(rows) == 1
        assert rows[0].priority == 0
        assert rows[0].reason == "urgent: total is missing"


def test_enqueue_review_keeps_the_more_urgent_priority(engine: sa.Engine) -> None:
    with Session(engine) as session:
        receipt = _receipt(session)

        enqueue_review(session, receipt.id, "urgent: total is missing", 0)
        # A later, less urgent routing decision must not demote the task.
        task = enqueue_review(session, receipt.id, "quick verify", 2)

        assert task.priority == 0
        assert task.reason == "urgent: total is missing"


def test_enqueue_review_reopens_a_closed_task(engine: sa.Engine) -> None:
    with Session(engine) as session:
        receipt = _receipt(session)
        task = enqueue_review(session, receipt.id, "quick verify", 2)
        next_task(session, "ada")
        close_task(session, task.id)

        # Re-routed after review: the one row per receipt is reopened, because
        # a receipt that needs review again must not be dropped.
        reopened = enqueue_review(session, receipt.id, "full re-key", 1)

        assert reopened.id == task.id
        assert reopened.state is ReviewState.OPEN
        assert reopened.closed_at is None
        assert reopened.assigned_to is None
        assert reopened.priority == 1


def test_enqueue_review_rejects_an_unknown_receipt(engine: sa.Engine) -> None:
    with Session(engine) as session:
        missing = uuid.uuid4()

        with pytest.raises(ValueError, match=str(missing)):
            enqueue_review(session, missing, "quick verify", 2)


@pytest.mark.parametrize("priority", [-1, -5])
def test_enqueue_review_rejects_a_negative_priority(engine: sa.Engine, priority: int) -> None:
    """``-1`` is the sentinel ``route()`` returns for "no review needed" (§12).

    Enqueuing it would create a task that the more-urgent-wins rule pins
    permanently ahead of genuine priority-0 work, and nothing can ever demote it.
    """
    with Session(engine) as session:
        receipt = _receipt(session)

        with pytest.raises(ValueError, match="priority"):
            enqueue_review(session, receipt.id, "auto-approved", priority)

        session.flush()
        assert list(session.scalars(select(ReviewTask))) == []


def test_enqueue_review_rejects_a_negative_priority_on_an_existing_task(
    engine: sa.Engine,
) -> None:
    with Session(engine) as session:
        receipt = _receipt(session)
        task = enqueue_review(session, receipt.id, "quick verify", 2)

        with pytest.raises(ValueError, match="priority"):
            enqueue_review(session, receipt.id, "auto-approved", -1)

        assert task.priority == 2
        assert task.reason == "quick verify"


# --------------------------------------------------------------------------- #
# next_task
# --------------------------------------------------------------------------- #


def test_next_task_claims_the_task_and_records_the_assignee(engine: sa.Engine) -> None:
    with Session(engine) as session:
        task = _task(session, 1)

        claimed = next_task(session, "ada")

        assert claimed is not None
        assert claimed.id == task.id
        assert claimed.state is ReviewState.IN_PROGRESS
        assert claimed.assigned_to == "ada"


def test_next_task_returns_tasks_in_priority_order(engine: sa.Engine) -> None:
    with Session(engine) as session:
        # Inserted out of order on purpose: 0 must come out first.
        quick = _task(session, 2, reason="quick verify")
        rekey = _task(session, 1, reason="full re-key")
        urgent = _task(session, 0, reason="urgent: total is missing")

        claimed = [next_task(session, "ada") for _ in range(3)]

        assert [task.id for task in claimed if task is not None] == [
            urgent.id,
            rekey.id,
            quick.id,
        ]


def test_next_task_breaks_priority_ties_by_opened_at(engine: sa.Engine) -> None:
    with Session(engine) as session:
        later = _task(session, 1, opened_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC))
        earlier = _task(session, 1, opened_at=datetime(2026, 7, 27, 9, 0, tzinfo=UTC))

        first = next_task(session, "ada")
        second = next_task(session, "ada")

        assert first is not None and first.id == earlier.id
        assert second is not None and second.id == later.id


def test_next_task_does_not_hand_out_the_same_task_twice(engine: sa.Engine) -> None:
    with Session(engine) as session:
        _task(session, 0)
        _task(session, 1)

        first = next_task(session, "ada")
        second = next_task(session, "grace")

        assert first is not None and second is not None
        assert first.id != second.id
        assert second.assigned_to == "grace"
        # The queue is now empty: every task is claimed.
        assert next_task(session, "ada") is None


def test_next_task_returns_none_on_an_empty_queue(engine: sa.Engine) -> None:
    with Session(engine) as session:
        assert next_task(session, "ada") is None


def test_next_task_ignores_closed_tasks(engine: sa.Engine) -> None:
    with Session(engine) as session:
        task = _task(session, 0)
        next_task(session, "ada")
        close_task(session, task.id)

        assert next_task(session, "grace") is None


# --------------------------------------------------------------------------- #
# close_task
# --------------------------------------------------------------------------- #


def test_close_task_sets_done_and_closed_at(engine: sa.Engine) -> None:
    with Session(engine) as session:
        task_id = _task(session, 1).id

        closed = close_task(session, task_id)

        assert closed.state is ReviewState.DONE
        assert closed.closed_at is not None
        # A timezone-aware UTC instant, not a naive local one.
        assert closed.closed_at.tzinfo is not None
        assert closed.closed_at.utcoffset() == UTC.utcoffset(None)
        session.commit()

    with Session(engine) as session:
        stored = session.get(ReviewTask, task_id)
        assert stored is not None
        assert stored.state is ReviewState.DONE
        assert stored.closed_at is not None


def test_close_task_is_idempotent(engine: sa.Engine) -> None:
    with Session(engine) as session:
        task = _task(session, 1)

        first = close_task(session, task.id)
        closed_at = first.closed_at
        again = close_task(session, task.id)

        assert again.state is ReviewState.DONE
        # The original close time is kept, not overwritten.
        assert again.closed_at == closed_at


def test_close_task_rejects_an_unknown_id(engine: sa.Engine) -> None:
    with Session(engine) as session:
        missing = uuid.uuid4()

        with pytest.raises(ValueError, match=str(missing)):
            close_task(session, missing)


# --------------------------------------------------------------------------- #
# queue_stats
# --------------------------------------------------------------------------- #


def test_queue_stats_on_an_empty_queue(engine: sa.Engine) -> None:
    with Session(engine) as session:
        stats = queue_stats(session)

        assert stats == QueueStats()
        assert stats.total == 0
        assert stats.by_priority == {}


def test_queue_stats_counts_states_and_open_priorities(engine: sa.Engine) -> None:
    with Session(engine) as session:
        _task(session, 0)
        _task(session, 2)
        _task(session, 2)
        _task(session, 1)
        done = _task(session, 1)

        next_task(session, "ada")  # claims the priority-0 task
        close_task(session, done.id)

        stats = queue_stats(session)

        assert isinstance(stats, QueueStats)
        assert stats.total == 5
        assert stats.done == 1
        assert stats.in_progress == 1
        assert stats.open == 3
        # Open tasks only: the claimed one and the closed one are not counted.
        assert stats.by_priority == {1: 1, 2: 2}


# --------------------------------------------------------------------------- #
# The locking clause -- proved without a Postgres driver.
#
# `_claim_stmt` is the seam these tests compile: it takes the guard's decision as
# an argument, so the generated SQL can be inspected for both backends offline.
# --------------------------------------------------------------------------- #


def test_claim_statement_locks_the_row_on_postgresql() -> None:
    sql = str(_claim_stmt(skip_locked=True).compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" in sql


def test_claim_statement_has_no_locking_clause_when_the_guard_is_off() -> None:
    sql = str(_claim_stmt(skip_locked=False).compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" not in sql
    assert "SKIP LOCKED" not in sql


def test_sqlite_silently_drops_the_locking_clause() -> None:
    """Why the guard exists: SQLite ignores ``FOR UPDATE`` instead of erroring.

    A claim that *looked* locked but was not would let two reviewers work the
    same receipt, so the decision is made in Python, not left to the compiler.
    """
    sql = str(_claim_stmt(skip_locked=True).compile(dialect=sqlite.dialect()))

    assert "FOR UPDATE" not in sql


def test_claim_statement_orders_by_priority_then_opened_at() -> None:
    sql = str(_claim_stmt(skip_locked=False).compile(dialect=sqlite.dialect()))

    priority_at = sql.index("review_tasks.priority")
    opened_at = sql.index("review_tasks.opened_at", priority_at)
    assert "ORDER BY" in sql
    assert priority_at < opened_at


def test_skip_locked_guard_is_on_for_postgresql_and_off_for_sqlite(engine: sa.Engine) -> None:
    with Session(engine) as session:
        # The real bind in these tests is SQLite: no locking clause.
        assert _supports_skip_locked(session.get_bind()) is False

    # A stub bind is enough to prove the other direction -- no driver needed.
    assert _supports_skip_locked(SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    assert not _supports_skip_locked(SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    assert not _supports_skip_locked(None)
