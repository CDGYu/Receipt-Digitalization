"""The review queue: enqueue, claim, close, and count (spec §14.9).

Receipts the confidence router did not auto-approve land here. One row per
receipt in ``review_tasks``, worked **lowest ``priority`` first** (§12: ``0`` is
the urgent case -- validation errors *and* a missing total -- then ``1`` for a
full re-key and ``2`` for a quick verify), oldest first within a priority.

Conventions inherited from the repository layer (:mod:`receipts.persist`): every
function takes an explicit :class:`~sqlalchemy.orm.Session` first and **the
caller commits**. These functions flush so ids and defaults exist, and raise
``ValueError`` -- never a bare ``IntegrityError`` -- when asked about something
that does not exist.

Two details are load-bearing:

  * ``review_tasks.receipt_id`` is UNIQUE (§6.7). A receipt can be routed to
    review more than once (a repair pass, a re-extract, a reopened review), so
    :func:`enqueue_review` updates the existing row instead of inserting a
    second one. Nothing is silently dropped and nothing raises.
  * :func:`next_task` claims a task, and two reviewers must never claim the same
    one. On backends that support it the row is locked with
    ``FOR UPDATE SKIP LOCKED``; see :func:`_supports_skip_locked` for why that is
    decided in Python rather than left to the SQL compiler.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..persist.models import Receipt, ReviewState, ReviewTask

__all__ = [
    "QueueStats",
    "close_task",
    "enqueue_review",
    "next_task",
    "queue_stats",
]

#: Dialects whose ``SELECT ... FOR UPDATE`` accepts ``SKIP LOCKED``. Everything
#: else -- SQLite above all -- is deliberately absent; see
#: :func:`_supports_skip_locked`.
_SKIP_LOCKED_DIALECTS = frozenset({"postgresql", "cockroachdb", "mysql", "mariadb", "oracle"})


def _supports_skip_locked(bind: Engine | Connection | None) -> bool:
    """Whether ``bind``'s backend can lock a row with ``FOR UPDATE SKIP LOCKED``.

    The guard has to live here, in Python, because SQLite does not complain about
    a locking clause -- its compiler **silently emits nothing**. A claim that
    looked locked but was not would let two reviewers work the same receipt, so
    the capability is decided explicitly rather than inferred from the absence of
    an error. ``tests/test_review_queue.py`` compiles
    :func:`_claim_stmt` for both dialects to prove each direction offline.
    """
    return bind is not None and bind.dialect.name in _SKIP_LOCKED_DIALECTS


def _claim_stmt(*, skip_locked: bool) -> Select[tuple[ReviewTask]]:
    """The "next open task" query, optionally row-locked.

    Split out from :func:`next_task` for one reason beyond readability: taking the
    guard's decision as an argument makes the statement compilable in a test
    against either dialect, so the locking clause is verified without a Postgres
    driver or a live database.

    Ordered ``priority`` ASC (lower is more urgent), then ``opened_at`` ASC, then
    ``id`` -- the last is a tiebreaker that makes the order total, so a backend
    with coarse timestamp resolution still hands out tasks deterministically.
    """
    stmt = (
        select(ReviewTask)
        .where(ReviewTask.state == ReviewState.OPEN)
        .order_by(ReviewTask.priority, ReviewTask.opened_at, ReviewTask.id)
        .limit(1)
    )
    if skip_locked:
        # Concurrent reviewers step over each other's locked rows instead of
        # blocking on them -- or, worse, both claiming the same task.
        stmt = stmt.with_for_update(skip_locked=True)
    return stmt


@dataclass(frozen=True)
class QueueStats:
    """Queue depth by state, plus the open backlog by priority (§14.9).

    ``by_priority`` counts **open tasks only**: it answers "what is waiting", so
    a claimed or closed task does not inflate the backlog.
    """

    open: int = 0
    in_progress: int = 0
    done: int = 0
    total: int = 0
    by_priority: dict[int, int] = field(default_factory=dict)


def enqueue_review(
    session: Session, receipt_id: uuid.UUID, reason: str, priority: int
) -> ReviewTask:
    """Put ``receipt_id`` in the review queue and return its task.

    Idempotent by necessity: ``review_tasks.receipt_id`` is UNIQUE, so a receipt
    routed to review twice (repair, re-extract, a fresh routing decision after a
    correction) updates the one row rather than raising an ``IntegrityError``.

      * **The more urgent priority wins** -- lower number, reviewed sooner. A
        later, calmer routing decision never demotes a task that something has
        already flagged as urgent, and the ``reason`` shown in the review UI is
        kept in step with the priority it explains.
      * A task already ``DONE`` is **reopened** (state ``OPEN``, ``closed_at``
        and ``assigned_to`` cleared): the receipt genuinely needs review again,
        and the UNIQUE constraint means reusing the row is the only way not to
        drop it.
      * An ``IN_PROGRESS`` task keeps its state -- someone is working it -- and
        only its priority and reason are refreshed.

    Raises ``ValueError`` for an unknown receipt, and for a **negative
    priority**: ``-1`` is the sentinel :func:`~receipts.score.confidence.route`
    returns for "no review needed", so an auto-approved receipt passed here
    straight from the router would become a task that the more-urgent-wins rule
    above pins permanently ahead of genuine priority-0 work -- and that no later
    routing decision could ever demote. ``0`` is the most urgent real priority
    (§12). Flushes; does not commit.
    """
    if priority < 0:
        raise ValueError(
            f"review priority must be >= 0, got {priority}; "
            "-1 is route()'s 'no review needed' sentinel, not a queue priority"
        )
    if session.get(Receipt, receipt_id) is None:
        raise ValueError(f"no receipt with id {receipt_id}")

    existing = session.scalars(
        select(ReviewTask).where(ReviewTask.receipt_id == receipt_id)
    ).one_or_none()

    if existing is None:
        # SAVEPOINT, not check-then-insert: receipt_id is UNIQUE, so a
        # genuinely concurrent enqueue for one receipt could otherwise raise
        # IntegrityError and lose the review task (ADR-0008's recorded gap).
        # Nesting means the failed INSERT rolls back to the savepoint without
        # poisoning the caller's transaction.
        try:
            with session.begin_nested():
                task = ReviewTask(
                    receipt_id=receipt_id,
                    reason=reason,
                    priority=priority,
                    state=ReviewState.OPEN,
                )
                session.add(task)
                session.flush()
            return task
        except IntegrityError:
            existing = session.scalars(
                select(ReviewTask).where(ReviewTask.receipt_id == receipt_id)
            ).one()

    # Reached either because the initial lookup above found the row first
    # time, or because the insert above lost the race and the row was
    # re-fetched after the IntegrityError: either way, the same
    # more-urgent-wins update applies.
    if priority <= existing.priority:
        existing.priority = priority
        existing.reason = reason
    if existing.state is ReviewState.DONE:
        existing.state = ReviewState.OPEN
        existing.closed_at = None
        existing.assigned_to = None
    session.flush()
    return existing


def next_task(session: Session, assignee: str) -> ReviewTask | None:
    """Claim the most urgent open task for ``assignee``, or ``None`` if empty.

    Atomic where the backend allows it: the row is selected ``FOR UPDATE SKIP
    LOCKED`` (see :func:`_supports_skip_locked`) and flipped to
    ``IN_PROGRESS`` with ``assigned_to`` set in the same transaction, so two
    reviewers polling at once get two different tasks. The lock is released when
    the caller commits -- which, per the layer's convention, the caller does.
    """
    stmt = _claim_stmt(skip_locked=_supports_skip_locked(session.get_bind()))
    task = session.scalars(stmt).first()
    if task is None:
        return None

    task.assigned_to = assignee
    task.state = ReviewState.IN_PROGRESS
    session.flush()
    return task


def close_task(session: Session, task_id: uuid.UUID) -> ReviewTask:
    """Mark a task ``DONE`` with a timezone-aware UTC ``closed_at``.

    Idempotent: closing an already-closed task keeps the original ``closed_at``
    rather than rewriting history -- the timestamp is audit data, and a double
    ``POST /review/{id}/complete`` must not move it.

    Raises ``ValueError`` for an unknown id. Flushes; does not commit.
    """
    task = session.get(ReviewTask, task_id)
    if task is None:
        raise ValueError(f"no review task with id {task_id}")

    if task.state is ReviewState.DONE and task.closed_at is not None:
        return task

    task.state = ReviewState.DONE
    if task.closed_at is None:
        task.closed_at = datetime.now(UTC)
    session.flush()
    return task


def queue_stats(session: Session) -> QueueStats:
    """Queue depth by state plus the open backlog by priority.

    Two grouped aggregates, not a table scan in Python: the queue is meant to be
    polled (``GET /metrics``, the review UI header) and must stay cheap as the
    backlog grows.
    """
    by_state = dict(
        session.execute(select(ReviewTask.state, func.count()).group_by(ReviewTask.state))
        .tuples()
        .all()
    )
    by_priority = dict(
        session.execute(
            select(ReviewTask.priority, func.count())
            .where(ReviewTask.state == ReviewState.OPEN)
            .group_by(ReviewTask.priority)
            .order_by(ReviewTask.priority)
        )
        .tuples()
        .all()
    )

    return QueueStats(
        open=by_state.get(ReviewState.OPEN, 0),
        in_progress=by_state.get(ReviewState.IN_PROGRESS, 0),
        done=by_state.get(ReviewState.DONE, 0),
        total=sum(by_state.values()),
        by_priority=by_priority,
    )
