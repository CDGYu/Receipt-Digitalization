"""Review queue tests (spec §14.9): enqueue, claim, release, close, and stats.

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

from receipts.persist import Correction, Receipt, ReviewState, ReviewTask
from receipts.persist.models import Base
from receipts.review import (
    QueueStats,
    close_review_for_receipt,
    close_task,
    enqueue_review,
    list_corrections,
    list_tasks,
    next_task,
    queue_stats,
    release_task,
)
from receipts.review.queue import _claim_stmt, _resume_stmt, _supports_skip_locked
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


@pytest.fixture()
def file_engine(tmp_path) -> sa.Engine:
    """File-backed SQLite: two ``Session`` objects on **separate** connections.

    The ``engine`` fixture above is in-memory, and SQLAlchemy backs an in-memory
    SQLite engine with a ``SingletonThreadPool`` -- every session opened from
    this thread shares one DBAPI connection, so there is no connection boundary
    for two sessions to interleave across (spelled out in
    ``test_concurrent_enqueue_for_one_receipt_does_not_raise``). A file gives
    each session its own connection, which is the shape the two routes have:
    ``sessionmaker`` hands each request its own ``Session``.
    """
    eng = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'queue.db').as_posix()}")

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


def test_enqueue_review_redacts_a_pan_inside_the_reason(engine: sa.Engine) -> None:
    """§18 at the sink: ``reason`` is built from exception text elsewhere
    (``save_extraction``'s human-owned-status guard quotes ``merchant.name``
    raw; ``_bounded_optional_text`` quotes an overlong value raw), so patching
    every producer would miss the next one. Redacting once, here, covers all
    of them -- present and future. Exercises both branches: the insert (a
    fresh task) and the idempotent update (an existing task's reason
    refreshed) go through the same redaction, since it runs once before either
    branch reads ``reason``.
    """
    pan_reason = (
        "persist: ValueError: receipt 11111111-1111-1111-1111-111111111111 has "
        "already been reviewed by a human (status reviewed) and a machine run "
        "must not overwrite it; this run produced status=needs_review, "
        "total=Decimal('12.34'), merchant='SUPERMART 4111111111111111'"
    )
    expected = pan_reason.replace("4111111111111111", "************1111")

    with Session(engine) as session:
        receipt = _receipt(session)

        task = enqueue_review(session, receipt.id, pan_reason, 2)
        assert task.reason == expected
        assert "4111111111111111" not in task.reason

        # Idempotent-update branch: same receipt, a more urgent priority so
        # the more-urgent-wins rule actually refreshes ``reason``, and a
        # second, different PAN so the update path -- not a stale value left
        # over from the insert -- is what is actually under test.
        second_reason = pan_reason.replace("SUPERMART", "OTHER MART CO")
        updated = enqueue_review(session, receipt.id, second_reason, 0)

        assert updated.id == task.id
        assert updated.reason == second_reason.replace(
            "4111111111111111", "************1111"
        )
        session.commit()


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
    """One reviewer per claim: since ADR-0016 a caller who already holds a task
    is handed that one back rather than a second, so draining the queue takes
    three different names. What is asserted -- the order the queue hands work
    out in -- is unchanged.
    """
    with Session(engine) as session:
        # Inserted out of order on purpose: 0 must come out first.
        quick = _task(session, 2, reason="quick verify")
        rekey = _task(session, 1, reason="full re-key")
        urgent = _task(session, 0, reason="urgent: total is missing")

        claimed = [next_task(session, name) for name in ("ada", "grace", "hopper")]

        assert [task.id for task in claimed if task is not None] == [
            urgent.id,
            rekey.id,
            quick.id,
        ]


def test_next_task_breaks_priority_ties_by_opened_at(engine: sa.Engine) -> None:
    """Two names for the same reason as the test above (ADR-0016)."""
    with Session(engine) as session:
        later = _task(session, 1, opened_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC))
        earlier = _task(session, 1, opened_at=datetime(2026, 7, 27, 9, 0, tzinfo=UTC))

        first = next_task(session, "ada")
        second = next_task(session, "grace")

        assert first is not None and first.id == earlier.id
        assert second is not None and second.id == later.id


def test_next_task_does_not_hand_out_the_same_task_twice(engine: sa.Engine) -> None:
    """The drained-queue check needs a *third* name since ADR-0016.

    Asking ``ada`` again would now resume the task she is already holding --
    the right answer, but not an answer about whether the queue still has
    anything open in it. ``hopper`` holds nothing, so ``None`` means the queue
    is genuinely empty.
    """
    with Session(engine) as session:
        _task(session, 0)
        _task(session, 1)

        first = next_task(session, "ada")
        second = next_task(session, "grace")

        assert first is not None and second is not None
        assert first.id != second.id
        assert second.assigned_to == "grace"
        # The queue is now empty: every task is claimed.
        assert next_task(session, "hopper") is None


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
# next_task resumes the caller's own in-progress task (ADR-0016)
#
# When ADR-0016 was written nothing released a claim: ``_claim_stmt`` selects
# ``state == OPEN`` only, ``enqueue_review`` reopens a task only when it is
# ``DONE``, and no route in ``review/api.py`` unclaimed. So a reviewer who
# reloaded the page, or whose response was lost, stranded the task
# permanently. ``next_task`` now hands them their own work back before it
# claims anything new -- that is what the tests below pin. ``release_task``
# (ADR-0025) is the separate, admin-only case: work taken back from someone
# who is not coming back for it. Resume needs no client call, which is why it,
# and not a release, is what makes a reload survivable.
# --------------------------------------------------------------------------- #

EARLY = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
MIDDLE = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
LATE = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def test_next_task_resumes_the_callers_own_in_progress_task(engine: sa.Engine) -> None:
    """A second call returns the same task instead of claiming a second one."""
    with Session(engine) as session:
        held = _task(session, 1, opened_at=EARLY)
        waiting = _task(session, 1, opened_at=LATE)

        first = next_task(session, "ada")
        again = next_task(session, "ada")

        assert first is not None and first.id == held.id
        assert again is not None and again.id == held.id
        assert again.assigned_to == "ada"
        assert again.state is ReviewState.IN_PROGRESS
        # The queue was not drawn from a second time.
        assert session.get(ReviewTask, waiting.id).state is ReviewState.OPEN


def test_next_task_never_resumes_another_users_task(engine: sa.Engine) -> None:
    """Resume matches ``assigned_to``. Grace must never be handed Ada's work.

    The queue holds exactly one task, so if the resume path ignored the
    assignee this call would return it -- the "two reviewers, one receipt"
    failure ADR-0008 exists to prevent, arriving through the new door rather
    than the claim.
    """
    with Session(engine) as session:
        only = _task(session, 1, opened_at=EARLY)

        ada = next_task(session, "ada")
        grace = next_task(session, "grace")

        assert ada is not None and ada.id == only.id
        assert grace is None
        assert session.get(ReviewTask, only.id).assigned_to == "ada"


def test_a_held_task_comes_back_even_when_something_more_urgent_waits(
    engine: sa.Engine,
) -> None:
    """Priority does not override resume (§12 orders the *queue*, not a claim).

    A reviewer mid-receipt is holding context no urgency ranking can restore;
    handing them a different task on reload would abandon the one they are
    part-way through, which is the state this change exists to end.
    """
    with Session(engine) as session:
        held = _task(session, 2, reason="quick verify", opened_at=EARLY)
        claimed = next_task(session, "ada")
        assert claimed is not None and claimed.id == held.id

        urgent = _task(session, 0, reason="urgent: total is missing", opened_at=LATE)

        resumed = next_task(session, "ada")

        assert resumed is not None and resumed.id == held.id
        assert resumed.priority == 2
        assert session.get(ReviewTask, urgent.id).state is ReviewState.OPEN


def test_a_caller_whose_only_task_is_done_claims_a_new_one(engine: sa.Engine) -> None:
    """Resume matches ``IN_PROGRESS`` only -- finished work is not held work.

    ``close_task`` is what ``POST /review/{id}/complete`` calls, so this is the
    ordinary loop: a reviewer who has just completed a receipt is asking for
    the next one, and must get it.
    """
    with Session(engine) as session:
        finished = _task(session, 1, opened_at=EARLY)
        waiting = _task(session, 1, opened_at=LATE)
        next_task(session, "ada")
        close_task(session, finished.id)

        claimed = next_task(session, "ada")

        assert claimed is not None and claimed.id == waiting.id
        assert claimed.state is ReviewState.IN_PROGRESS
        assert claimed.assigned_to == "ada"


def test_resume_returns_the_earliest_opened_of_several_held_tasks(engine: sa.Engine) -> None:
    """One user, several claims: **earliest ``opened_at`` wins**, not priority.

    Tasks stranded before this change already exist, so a user can hold more
    than one and the pick has to be deterministic. The three tasks below carry
    priorities 0/2/1 in ``opened_at`` order specifically so an ordering that
    led with ``priority`` -- the claim path's -- would return a different row
    and fail here.
    """
    with Session(engine) as session:
        middle = _task(session, 0, opened_at=MIDDLE)
        earliest = _task(session, 2, opened_at=EARLY)
        latest = _task(session, 1, opened_at=LATE)
        for task in (middle, earliest, latest):
            task.state = ReviewState.IN_PROGRESS
            task.assigned_to = "ada"
        session.flush()

        resumed = next_task(session, "ada")

        assert resumed is not None and resumed.id == earliest.id


def test_resume_breaks_an_opened_at_tie_by_id(engine: sa.Engine) -> None:
    """``opened_at`` then ``id`` -- a total order, as ``_claim_stmt`` already uses.

    ``opened_at`` defaults to ``CURRENT_TIMESTAMP``, which SQLite resolves only
    to the second, so several tasks claimed in one burst genuinely can share a
    timestamp; without the ``id`` tiebreaker the backend would be free to
    return a different one of them on each poll.
    """
    with Session(engine) as session:
        tasks = [_task(session, 1, opened_at=EARLY) for _ in range(3)]
        for task in tasks:
            task.state = ReviewState.IN_PROGRESS
            task.assigned_to = "ada"
        session.flush()
        lowest = min(task.id for task in tasks)

        resumed = next_task(session, "ada")

        assert resumed is not None and resumed.id == lowest


def test_two_reviewers_polling_at_once_still_get_two_different_tasks(
    engine: sa.Engine,
) -> None:
    """Adding a second query must not open a way for two callers to share a row.

    **What this does NOT establish**: that the row lock works. This engine is
    in-memory SQLite, which drops ``FOR UPDATE SKIP LOCKED`` silently (see
    ``test_sqlite_silently_drops_the_locking_clause``) and which SQLAlchemy
    backs with a ``SingletonThreadPool``, so the two ``Session`` objects below
    share one DBAPI connection and ``b`` sees ``a``'s uncommitted write. The
    production lock is guarded by the compile tests at the bottom of this
    module, exactly as ADR-0008 says.

    **What this DOES establish**: the resume path cannot re-offer a row the
    claim path has just taken. ``b``'s call runs after ``a`` flipped its row to
    ``IN_PROGRESS`` and before either committed -- so the row has left
    ``_claim_stmt``'s ``state == OPEN`` filter and entered ``_resume_stmt``'s
    reach -- and ``b`` still does not get it, because it is assigned to ``a``.
    """
    with Session(engine) as setup:
        first_id = _task(setup, 0, opened_at=EARLY).id
        second_id = _task(setup, 0, opened_at=LATE).id
        setup.commit()

    with Session(engine) as a, Session(engine) as b:
        claimed_by_a = next_task(a, "ada")
        claimed_by_b = next_task(b, "grace")
        a.commit()
        b.commit()

        assert claimed_by_a is not None and claimed_by_b is not None
        assert claimed_by_a.id != claimed_by_b.id
        assert {claimed_by_a.id, claimed_by_b.id} == {first_id, second_id}

    with Session(engine) as check:
        assert check.get(ReviewTask, first_id).assigned_to == "ada"
        assert check.get(ReviewTask, second_id).assigned_to == "grace"


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
# release_task
# --------------------------------------------------------------------------- #


def _claimed(session: Session, assignee: str = "ada") -> ReviewTask:
    """An ``IN_PROGRESS`` task at priority 1, held by ``assignee``."""
    _task(session, 1)
    task = next_task(session, assignee)
    assert task is not None
    return task


def test_release_task_returns_a_claimed_task_to_the_queue(engine: sa.Engine) -> None:
    with Session(engine) as session:
        task_id = _claimed(session).id

        released, _ = release_task(session, task_id)

        assert released.state is ReviewState.OPEN
        session.commit()

    with Session(engine) as session:
        stored = session.get(ReviewTask, task_id)
        assert stored is not None
        assert stored.state is ReviewState.OPEN


def test_release_task_clears_the_assignee_and_names_who_held_it(engine: sa.Engine) -> None:
    with Session(engine) as session:
        task_id = _claimed(session, "ada").id

        released, previously_assigned_to = release_task(session, task_id)

        assert previously_assigned_to == "ada"
        assert released.assigned_to is None
        session.commit()

    with Session(engine) as session:
        stored = session.get(ReviewTask, task_id)
        assert stored is not None
        assert stored.assigned_to is None


def test_a_released_task_is_claimable_by_a_different_reviewer(engine: sa.Engine) -> None:
    """The behavioural point. ``_claim_stmt`` selects ``state == OPEN`` only, so
    until the state is written back the row is invisible to every future claim.
    """
    with Session(engine) as session:
        task_id = _claimed(session, "ada").id

        release_task(session, task_id)
        claimed = next_task(session, "bob")

        assert claimed is not None
        assert claimed.id == task_id
        assert claimed.assigned_to == "bob"
        assert claimed.state is ReviewState.IN_PROGRESS


def test_release_task_is_idempotent_on_an_open_task(engine: sa.Engine) -> None:
    """The same shape ``close_task`` uses for a second close: reaching the goal
    state is not an error. ``OPEN`` with an assignee is unreachable -- every
    writer of ``assigned_to`` keeps it in step with the state.

    ``release_task``'s docstring says **nothing is written** on this path, and
    ``state``/``assigned_to``/the ``None`` holder do not establish that: they
    are already the goal state, so a call that also touched some *other* column
    would satisfy all three. The whole row is therefore snapshotted and
    compared -- in memory and again from the stored row -- because a release
    that quietly demoted a task in the §12 backlog is invisible to every gate
    the moment this test only looks at the three fields it is about.

    Snapshotted from a re-read row rather than from ``_task``'s return value so
    the ``opened_at`` comparison is naive-against-naive: SQLite's ``DATETIME``
    keeps no offset, the same wrinkle the claimed-task version of this pin
    below already documents.
    """
    with Session(engine) as session:
        task_id = _task(session, 1).id
        session.commit()

    with Session(engine) as session:
        stored = session.get(ReviewTask, task_id)
        assert stored is not None
        untouched = (stored.priority, stored.reason, stored.opened_at, stored.closed_at)

        released, previously_assigned_to = release_task(session, task_id)

        assert released.state is ReviewState.OPEN
        assert released.assigned_to is None
        assert previously_assigned_to is None
        assert (
            released.priority,
            released.reason,
            released.opened_at,
            released.closed_at,
        ) == untouched
        session.commit()

    with Session(engine) as session:
        after = session.get(ReviewTask, task_id)
        assert after is not None
        assert (after.priority, after.reason, after.opened_at, after.closed_at) == untouched


def test_release_task_refuses_a_closed_task(engine: sa.Engine) -> None:
    with Session(engine) as session:
        task_id = _claimed(session).id
        close_task(session, task_id)

        with pytest.raises(ValueError, match=str(task_id)):
            release_task(session, task_id)


def test_release_task_leaves_a_closed_tasks_assignee_intact(engine: sa.Engine) -> None:
    """``assigned_to`` on a ``DONE`` task is the only record in the system that
    anyone reviewed the receipt: ``close_task`` leaves it set, no ``Receipt``
    column names a reviewer, and a ``corrections`` row exists only for a field
    whose value actually changed.
    """
    with Session(engine) as session:
        task_id = _claimed(session, "ada").id
        close_task(session, task_id)

        with pytest.raises(ValueError):
            release_task(session, task_id)

        stored = session.get(ReviewTask, task_id)
        assert stored is not None
        assert stored.assigned_to == "ada"


def test_release_task_rejects_an_unknown_id(engine: sa.Engine) -> None:
    with Session(engine) as session:
        missing = uuid.uuid4()

        with pytest.raises(ValueError, match=str(missing)):
            release_task(session, missing)


def test_release_task_leaves_priority_opened_at_and_reason_alone(engine: sa.Engine) -> None:
    """A released task returns to the queue position it already held. Moving
    ``opened_at`` would send it to the back and punish the receipt for its
    reviewer's absence. ``closed_at`` is checked with them: it is ``None`` in
    both live states, so a release that wrote it would leave a task that is
    open and closed at once.
    """
    opened_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    with Session(engine) as session:
        _task(session, 2, reason="quick verify", opened_at=opened_at)
        task = next_task(session, "ada")
        assert task is not None
        # Compared against the claimed task's own timestamp rather than the
        # aware literal above: SQLite's DATETIME keeps no offset, and the
        # identity map holds tasks weakly, so the row ``next_task`` reloads
        # carries a naive 09:00. The pin is that releasing does not move it.
        claimed_at = task.opened_at

        released, _ = release_task(session, task.id)

        assert released.priority == 2
        assert released.opened_at == claimed_at
        assert released.reason == "quick verify"
        assert released.closed_at is None


def test_releasing_returns_the_task_to_the_open_backlog(engine: sa.Engine) -> None:
    """A claimed task is absent from ``by_priority``, which counts open tasks
    only (ADR-0016). Releasing puts it back, so ``/metrics`` stops
    under-reporting the backlog.
    """
    with Session(engine) as session:
        task_id = _claimed(session).id

        before = queue_stats(session)
        release_task(session, task_id)
        after = queue_stats(session)

        assert before.in_progress == 1
        assert before.open == 0
        assert before.by_priority == {}
        assert after.in_progress == 0
        assert after.open == 1
        assert after.by_priority == {1: 1}


def test_a_release_inside_a_completes_window_erases_the_reviewers_name(
    file_engine: sa.Engine,
) -> None:
    """ADR-0025's third race order, reproduced -- not reasoned about.

    The ADR records an accepted residual: because neither route takes a row
    lock, a release that commits *between* ``POST /review/{task_id}/complete``'s
    permission check and its ``close_task`` is invisible to the complete already
    in flight, and the result is a ``DONE`` task whose reviewer's name has been
    erased -- the loss the ``DONE`` refusal exists to prevent, reached anyway.

    **Deterministic, and no concurrency is needed to reach it.** No threads, no
    load, no scheduling luck: the two routes each get their own ``Session``
    (hence ``file_engine`` -- see that fixture), and the three steps below are
    ordered by hand in the one order that matters. That is the whole cost of
    measuring this, which is why it is a test rather than a paragraph.

    This pins an **accepted** residual, so it is not a bug report -- but
    **read which assertion failed before concluding anything**, because the two
    kinds here fail for different reasons. The final block asserts the
    *outcome*; if those go red the interleaving has genuinely stopped producing
    it, and ADR-0025 is what needs editing. Step 3's ``closed.assigned_to ==
    "ada"`` asserts the *mechanism*, and it can go red on its own with the
    outcome unchanged -- identity-map entries are held weakly, so merely losing
    the in-flight reference is enough to break it. That is a test to repair,
    not a residual that moved.
    """
    with Session(file_engine) as setup:
        _task(setup, 2)
        held = next_task(setup, "ada")
        assert held is not None
        task_id = held.id
        setup.commit()

    completing = Session(file_engine)  # POST /review/{task_id}/complete, ada's own
    releasing = Session(file_engine)  # POST /review/{task_id}/release, an admin's

    # 1. `/complete` reads the row for its assignee-or-admin check, and passes.
    in_flight = completing.get(ReviewTask, task_id)
    assert in_flight is not None
    assert in_flight.assigned_to == "ada"

    # 2. The whole release route runs and commits inside that window.
    _, released_from = release_task(releasing, task_id)
    releasing.commit()
    assert released_from == "ada"

    # 3. `/complete` carries on. The mechanism, asserted rather than described:
    #    the in-flight session still holds the pre-release name -- which is what
    #    its permission check passed against -- and `close_task` marks only
    #    `state` and `closed_at` dirty, so the UPDATE cannot write it back.
    closed = close_task(completing, task_id)
    assert closed.assigned_to == "ada"
    completing.commit()

    completing.close()
    releasing.close()

    with Session(file_engine) as check:
        stored = check.get(ReviewTask, task_id)
        assert stored is not None
        assert stored.state is ReviewState.DONE
        assert stored.closed_at is not None
        assert stored.assigned_to is None  # the record the DONE refusal defends


# --------------------------------------------------------------------------- #
# list_tasks
# --------------------------------------------------------------------------- #


def test_list_tasks_is_unrestricted_when_visible_to_is_none(engine: sa.Engine) -> None:
    """``visible_to=None`` is the admin case, spelled explicitly at the call
    site rather than as a bare boolean.
    """
    with Session(engine) as session:
        open_task = _task(session, 2)
        held = _claimed(session, "ada")

        rows = list_tasks(session)

        assert {row.id for row in rows} == {open_task.id, held.id}


def test_list_tasks_hides_another_users_claim_from_a_reviewer(engine: sa.Engine) -> None:
    """The scope ADR-0026 records: the open backlog plus the caller's own
    rows, never a row carrying someone else's name.
    """
    with Session(engine) as session:
        open_task = _task(session, 2)
        held = _claimed(session, "ada")

        rows = list_tasks(session, visible_to="bob")

        assert {row.id for row in rows} == {open_task.id}
        assert held.id not in {row.id for row in rows}


def test_list_tasks_includes_the_callers_own_claim(engine: sa.Engine) -> None:
    with Session(engine) as session:
        held = _claimed(session, "ada")

        rows = list_tasks(session, visible_to="ada")

        assert [row.id for row in rows] == [held.id]


def test_list_tasks_includes_the_callers_own_closed_task(engine: sa.Engine) -> None:
    """``close_task`` leaves ``assigned_to`` set (ADR-0025), so a reviewer's
    own history stays visible to them after the task closes. That is the whole
    reason the scope is ``assigned_to == caller`` rather than a state filter.
    """
    with Session(engine) as session:
        held = _claimed(session, "ada")
        close_task(session, held.id)

        rows = list_tasks(session, visible_to="ada")

        assert [row.id for row in rows] == [held.id]
        assert rows[0].state is ReviewState.DONE


def test_list_tasks_orders_by_priority_then_opened_at(engine: sa.Engine) -> None:
    """The same total order :func:`_claim_stmt` uses, so the first row of a
    ``state=open`` page is the row :func:`next_task` would hand out next.
    ``opened_at`` is set explicitly because SQLite resolves
    ``CURRENT_TIMESTAMP`` only to the second.
    """
    with Session(engine) as session:
        urgent = _task(session, 0, opened_at=datetime(2026, 8, 5, 12, 0, tzinfo=UTC))
        latest = _task(session, 2, opened_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC))
        middle = _task(session, 1, opened_at=datetime(2026, 8, 5, 11, 0, tzinfo=UTC))

        rows = list_tasks(session)

        assert [row.id for row in rows] == [urgent.id, middle.id, latest.id]


def test_list_tasks_filters_by_state(engine: sa.Engine) -> None:
    with Session(engine) as session:
        open_task = _task(session, 2)
        _claimed(session, "ada")

        rows = list_tasks(session, state=ReviewState.OPEN)

        assert [row.id for row in rows] == [open_task.id]


def test_list_tasks_pages_with_limit_and_offset(engine: sa.Engine) -> None:
    with Session(engine) as session:
        first = _task(session, 0)
        second = _task(session, 1)
        third = _task(session, 2)

        assert [row.id for row in list_tasks(session, limit=2)] == [first.id, second.id]
        assert [row.id for row in list_tasks(session, limit=2, offset=2)] == [third.id]


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


def test_the_resume_statement_takes_no_lock(engine: sa.Engine) -> None:
    """The resume query is deliberately an unlocked read (ADR-0016).

    ``FOR UPDATE SKIP LOCKED`` here would be actively harmful, not merely
    redundant: a second request from the *same* reviewer -- two tabs, an
    impatient double-refresh -- would skip its own locked row, fall through to
    the claim path, and take a second task. That is the exact defect this
    change exists to remove, reintroduced by the fix. Plain ``FOR UPDATE``
    would instead block one of the two requests on the other.

    It is safe unlocked because the statement can only ever match rows already
    stamped with the caller's own ``assigned_to``: no *other* caller's request
    is competing for them, so there is nothing to serialize.
    """
    sql = str(_resume_stmt("ada").compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" not in sql
    assert "SKIP LOCKED" not in sql


def test_the_resume_statement_filters_on_state_and_assignee() -> None:
    """Both filters, in the compiled SQL -- not inferred from a passing call."""
    sql = str(
        _resume_stmt("ada").compile(
            dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "review_tasks.state = 'in_progress'" in sql
    assert "review_tasks.assigned_to = 'ada'" in sql


def test_the_resume_statement_orders_by_opened_at_then_id() -> None:
    """``opened_at`` leads; ``priority`` is deliberately not in the order at all."""
    sql = str(_resume_stmt("ada").compile(dialect=sqlite.dialect()))
    order_by = sql[sql.index("ORDER BY"):]

    opened_at = order_by.index("review_tasks.opened_at")
    task_id = order_by.index("review_tasks.id")
    assert opened_at < task_id
    assert "review_tasks.priority" not in order_by


def test_skip_locked_guard_is_on_for_postgresql_and_off_for_sqlite(engine: sa.Engine) -> None:
    with Session(engine) as session:
        # The real bind in these tests is SQLite: no locking clause.
        assert _supports_skip_locked(session.get_bind()) is False

    # A stub bind is enough to prove the other direction -- no driver needed.
    assert _supports_skip_locked(SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    assert not _supports_skip_locked(SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    assert not _supports_skip_locked(None)


def _correction(
    session: Session,
    receipt_id: uuid.UUID,
    field_path: str,
    *,
    before: str | None,
    after: str | None,
    by: str = "alice",
    at: datetime | None = None,
) -> Correction:
    """One audit row. ``at`` is explicit where ordering is under test, because
    SQLite's CURRENT_TIMESTAMP resolves only to the second."""
    row = Correction(
        receipt_id=receipt_id,
        field_path=field_path,
        value_before=before,
        value_after=after,
        corrected_by=by,
    )
    if at is not None:
        row.created_at = at
    session.add(row)
    session.flush()
    return row


def test_list_corrections_is_unrestricted_for_the_admin_case(engine: sa.Engine):
    """``visible_to=None`` needs no review task at all -- an auto-approved
    receipt that was never queued still has readable history for an admin."""
    with Session(engine) as session:
        receipt = _receipt(session)
        _correction(session, receipt.id, "receipt.total", before="900", after="1000")
        session.commit()

        rows = list_corrections(session, receipt.id)

        assert rows is not None
        assert [row.field_path for row in rows] == ["receipt.total"]


def test_list_corrections_refuses_a_receipt_the_reviewer_never_held(engine: sa.Engine):
    with Session(engine) as session:
        receipt = _receipt(session)
        _correction(session, receipt.id, "receipt.total", before="900", after="1000")
        session.commit()

        assert list_corrections(session, receipt.id, visible_to="carol") is None


def test_list_corrections_refuses_a_receipt_held_by_a_different_reviewer(engine: sa.Engine):
    """The pin on ``assigned_to == visible_to`` itself.

    Every other refusal case here uses a receipt with **no review task at all**,
    so all of them stay green if the scope predicate is deleted outright: a bare
    existence check on the receipt's task would refuse those receipts too, for
    the wrong reason. Only a receipt whose task belongs to *someone else* tells
    the two apart -- and that is the case that matters, because without the
    predicate every receipt in the queue discloses its correction history, and
    its attribution, to every reviewer.
    """
    with Session(engine) as session:
        receipt = _receipt(session)
        session.add(
            ReviewTask(receipt_id=receipt.id, reason="quick verify", assigned_to="dave",
                       state=ReviewState.IN_PROGRESS)
        )
        _correction(session, receipt.id, "receipt.total", before="900", after="1000")
        session.commit()

        assert list_corrections(session, receipt.id, visible_to="carol") is None


def test_refusal_and_emptiness_are_different_answers(engine: sa.Engine):
    """The pin that keeps 403 reachable.

    ``None`` is "you may not see this"; ``[]`` is "you may, and there is
    none". Flattening the return type to ``list[Correction]`` -- returning
    ``[]`` for both -- turns the route's 403 into an indistinguishable empty
    200, which is ADR-0027 section 5's collapse one layer below the UI. This
    test is the one that goes red for it.
    """
    with Session(engine) as session:
        held = _receipt(session)
        session.add(
            ReviewTask(receipt_id=held.id, reason="quick verify", assigned_to="carol",
                       state=ReviewState.DONE)
        )
        never_held = _receipt(session)
        session.commit()

        assert list_corrections(session, held.id, visible_to="carol") == []
        assert list_corrections(session, never_held.id, visible_to="carol") is None


def test_a_closed_task_still_grants_its_holder_the_history(engine: sa.Engine):
    """"Held **or previously held**" -- the 2026-08-10 ruling.

    ``close_task`` deliberately leaves ``assigned_to`` set on a ``DONE`` task
    (ADR-0025), so a reviewer keeps the history of what they reviewed. Goes red
    if the scope narrows to ``state == IN_PROGRESS``.
    """
    with Session(engine) as session:
        receipt = _receipt(session)
        session.add(
            ReviewTask(receipt_id=receipt.id, reason="quick verify", assigned_to="carol",
                       state=ReviewState.DONE)
        )
        _correction(session, receipt.id, "receipt.total", before="900", after="1000")
        session.commit()

        rows = list_corrections(session, receipt.id, visible_to="carol")

        assert rows is not None and len(rows) == 1


def test_list_corrections_orders_oldest_first(engine: sa.Engine):
    with Session(engine) as session:
        receipt = _receipt(session)
        _correction(session, receipt.id, "second", before=None, after="b",
                    at=datetime(2026, 7, 3, 9, 0, 1, tzinfo=UTC))
        _correction(session, receipt.id, "first", before=None, after="a",
                    at=datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC))
        session.commit()

        rows = list_corrections(session, receipt.id)

        assert [row.field_path for row in rows] == ["first", "second"]


def test_list_corrections_returns_only_the_receipt_asked_for(engine: sa.Engine):
    """The pin on ``.where(Correction.receipt_id == receipt_id)``.

    Every other test in this group puts corrections on one receipt only, so
    deleting that predicate leaves all of them green while the function hands
    each permitted caller **every** receipt's history -- the same cross-receipt
    disclosure the ``assigned_to`` scope exists to prevent, one line lower down.
    Two receipts, each carrying a correction, is the smallest case that sees it.
    """
    with Session(engine) as session:
        asked_for = _receipt(session)
        other = _receipt(session)
        _correction(session, asked_for.id, "receipt.total", before="900", after="1000")
        _correction(session, other.id, "merchant.name", before="Acme", after="Acme Ltd")
        session.commit()

        rows = list_corrections(session, asked_for.id)

        assert rows is not None
        field_paths = [row.field_path for row in rows]
        assert field_paths == ["receipt.total"]
        assert "merchant.name" not in field_paths


def test_list_corrections_breaks_a_created_at_tie_by_field_path(engine: sa.Engine):
    """One patch, one ``created_at``, one stable order -- the 2026-08-10 ruling.

    ``apply_corrections`` writes a whole patch in a single ``add_all``, so every
    row of it shares a timestamp: ties are the normal case here, not an edge
    one. ``field_path`` is what orders them, and it reproduces that function's
    own write order, ``sorted(flatten(patch).items())``. Ordering by ``id``
    instead would arrange them differently on every write -- ``id`` is a
    ``uuid4`` and carries neither time nor write order -- which is an order no
    test could honestly pin. Inserted deliberately out of order below, so a
    passing assertion means the query sorted rather than that it got lucky.
    """
    shared = datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC)
    with Session(engine) as session:
        receipt = _receipt(session)
        for field_path in ("totals.total", "merchant.name", "totals.subtotal"):
            _correction(session, receipt.id, field_path, before=None, after="x", at=shared)
        session.commit()

        rows = list_corrections(session, receipt.id)

        assert rows is not None
        assert [row.field_path for row in rows] == [
            "merchant.name",
            "totals.subtotal",
            "totals.total",
        ]


def test_list_corrections_paginates_with_limit_and_offset(engine: sa.Engine):
    """Both pagination arguments, exercised at non-default values.

    Task 3 builds a paginated route straight on top of these and passes them
    through untouched. With no test supplying either, dropping
    ``.limit(limit).offset(offset)`` from the query left every other test in
    this file green.
    """
    shared = datetime(2026, 7, 3, 9, 0, 0, tzinfo=UTC)
    with Session(engine) as session:
        receipt = _receipt(session)
        for field_path in ("a", "b", "c", "d"):
            _correction(session, receipt.id, field_path, before=None, after="x", at=shared)
        session.commit()

        def paths(**kwargs) -> list[str]:
            rows = list_corrections(session, receipt.id, **kwargs)
            assert rows is not None
            return [row.field_path for row in rows]

        assert paths() == ["a", "b", "c", "d"]
        assert paths(limit=2) == ["a", "b"]
        assert paths(limit=2, offset=2) == ["c", "d"]
        assert paths(offset=1) == ["b", "c", "d"]
        assert paths(limit=10, offset=4) == []
