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
from receipts.review import (
    QueueStats,
    close_review_for_receipt,
    close_task,
    enqueue_review,
    next_task,
    queue_stats,
)
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


@pytest.fixture()
def receipt_id(engine: sa.Engine) -> uuid.UUID:
    """A persisted, *committed* receipt id.

    Committed rather than merely flushed: the concurrency test below opens two
    independent ``Session`` objects against ``engine``, and both must be able
    to find the row.
    """
    with Session(engine) as session:
        receipt = _receipt(session)
        session.commit()
        return receipt.id


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


def test_concurrent_enqueue_for_one_receipt_does_not_raise(
    engine: sa.Engine, receipt_id: uuid.UUID
) -> None:
    """Two sessions enqueue the same receipt with no coordination.

    **What this does NOT establish**: that the insert race is handled. This
    fixture's engine is in-memory SQLite (``sqlite+pysqlite:///:memory:``),
    and SQLAlchemy backs an in-memory SQLite engine with a
    ``SingletonThreadPool`` by default -- every ``Session`` opened from this
    thread shares the *same* underlying DBAPI connection. Session ``b``'s
    existence check therefore sees session ``a``'s uncommitted insert
    directly (there is no connection boundary between them), so ``b`` takes
    the update branch instead of ever attempting a colliding insert -- no
    race window opens. This test passes identically against the pre-fix
    check-then-insert code and the SAVEPOINT-based fix; it does not
    distinguish between them. See
    ``test_enqueue_review_recovers_when_the_insert_loses_the_race`` below for
    a test that actually forces the ``except IntegrityError:`` branch.

    **What this DOES establish**: the more-urgent-wins outcome (§12) still
    holds when two enqueues for one receipt interleave -- the lower ("full
    re-key") priority wins and its reason is what survives, regardless of
    which of the two calls happened to run its update logic.
    """
    with Session(engine) as a, Session(engine) as b:
        enqueue_review(a, receipt_id, "quick verify", 2)
        enqueue_review(b, receipt_id, "full re-key", 1)
        a.commit()
        b.commit()  # must not raise IntegrityError

    with Session(engine) as check:
        tasks = check.scalars(
            select(ReviewTask).where(ReviewTask.receipt_id == receipt_id)
        ).all()
        assert len(tasks) == 1
        assert tasks[0].priority == 1  # more urgent wins, as before
        assert tasks[0].reason == "full re-key"


def test_enqueue_review_recovers_when_the_insert_loses_the_race(
    engine: sa.Engine, receipt_id: uuid.UUID
) -> None:
    """Forces the ``except IntegrityError:`` recovery branch, deterministically.

    Two real ``Session`` objects cannot open a genuine race window on this
    in-memory SQLite engine (see the docstring above), so this test
    manufactures the window explicitly instead of hoping thread scheduling
    produces it:

      1. A competing task is inserted and committed for this ``receipt_id``
         in an ordinary, fully sequential session -- *before*
         ``enqueue_review`` is even called.
      2. The session ``enqueue_review`` then runs on has its **first**
         ``.scalars()`` call -- the existence check that decides whether to
         take the insert branch -- shadowed to report "nothing found",
         exactly what it would have seen had it run a moment earlier than
         the commit in (1): the real race window ADR-0008 records.

    Nothing past that point is mocked: the SAVEPOINT-wrapped INSERT that
    follows genuinely collides with the row from (1), and SQLite genuinely
    raises ``IntegrityError`` -- the recovery re-select (the *second*
    ``.scalars()`` call) is left unpatched and runs for real against the
    real database. The assertions are about the resulting row, not about the
    patch.

    Verified locally that this test pins the recovery branch and not just its
    own scaffolding: with the ``except IntegrityError:`` block in
    ``enqueue_review`` temporarily deleted, this test failed with an
    unhandled ``sqlalchemy.exc.IntegrityError`` (the SAVEPOINT-wrapped
    INSERT's UNIQUE violation propagating out uncaught); restoring the block
    made it pass again.
    """
    with Session(engine) as setup:
        setup.add(
            ReviewTask(
                receipt_id=receipt_id, reason="quick verify", priority=2,
                state=ReviewState.OPEN,
            )
        )
        setup.commit()

    with Session(engine) as session:
        real_scalars = session.scalars
        calls = 0

        def _lie_on_the_first_call(statement, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                # The existence check enqueue_review is about to make: report
                # "nothing found", even though the row from `setup` above
                # already exists -- the caller checked a moment "before" it
                # was committed.
                class _EmptyResult:
                    def one_or_none(self) -> None:
                        return None

                return _EmptyResult()
            # The recovery re-select after the IntegrityError: unpatched, runs
            # for real against the real (colliding) row.
            return real_scalars(statement, *args, **kwargs)

        session.scalars = _lie_on_the_first_call

        task = enqueue_review(session, receipt_id, "full re-key", 1)
        session.commit()
        task_id = task.id

        # The lie fired once and the real recovery query ran once: confirms
        # this test actually exercised both halves of the branch, not just
        # the happy path.
        assert calls == 2

    with Session(engine) as check:
        tasks = check.scalars(
            select(ReviewTask).where(ReviewTask.receipt_id == receipt_id)
        ).all()
        assert len(tasks) == 1
        assert tasks[0].id == task_id
        # More-urgent-wins applied to the row that survived the collision:
        # the pre-existing task (priority 2) was updated in place to the
        # caller's more urgent priority 1, not duplicated or dropped.
        assert tasks[0].priority == 1
        assert tasks[0].reason == "full re-key"


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


def test_close_review_for_receipt_closes_the_task_a_receipt_has(engine: sa.Engine) -> None:
    """The inverse of ``enqueue_review``, for a re-run that resolves the flag."""
    with Session(engine) as session:
        task = _task(session, 1)

        closed = close_review_for_receipt(session, task.receipt_id)

        assert closed is not None
        assert closed.id == task.id
        assert closed.state is ReviewState.DONE
        assert closed.closed_at is not None


def test_close_review_for_receipt_is_a_no_op_for_a_receipt_with_no_task(
    engine: sa.Engine,
) -> None:
    """The common case: an auto-approved receipt never had a task."""
    with Session(engine) as session:
        receipt = Receipt(image_key="k", image_phash="", status=ReceiptStatus.AUTO_APPROVED)
        session.add(receipt)
        session.flush()

        assert close_review_for_receipt(session, receipt.id) is None
        assert close_review_for_receipt(session, uuid.uuid4()) is None


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
