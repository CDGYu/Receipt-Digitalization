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
  * :func:`next_task` **resumes before it claims** (ADR-0016): a caller who
    already holds an ``IN_PROGRESS`` task gets that one back. Resume is the
    holder's *own* recovery and needs no client call, which is why it, and not
    a release, is what makes a reload or a lost response survivable.
    :func:`release_task` is the separate, admin-only case (ADR-0025): work
    taken back from someone who is not coming back for it.
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
from ..persist.repository import redact_pan

__all__ = [
    "QueueStats",
    "close_review_for_receipt",
    "close_task",
    "enqueue_review",
    "next_task",
    "queue_stats",
    "release_task",
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


def _resume_stmt(assignee: str) -> Select[tuple[ReviewTask]]:
    """``assignee``'s own in-progress task -- the one :func:`next_task` hands back.

    Ordered ``opened_at`` ASC then ``id``: the longest-held task first, with a
    total order so a backend whose ``opened_at`` resolution is coarse (SQLite's
    ``CURRENT_TIMESTAMP`` is whole seconds) cannot return a different row on
    each poll. **``priority`` is deliberately absent from the order** -- these
    rows are already claimed, so §12's queue ranking has nothing left to say
    about them, and "the one I have been holding longest" is the pick a
    reviewer holding several stranded tasks actually wants.

    **A user genuinely can hold several, which is why this is ordered and
    ``limit(1)``-ed rather than asserted to be unique.** Two sources: tasks
    stranded before ADR-0016, and concurrent polls from one user (see
    :func:`next_task` on the window that allows it).

    **No locking clause, on purpose.** ``FOR UPDATE SKIP LOCKED`` here would
    reintroduce the very defect this query removes: a second concurrent request
    from the *same* reviewer would skip its own locked row, fall through to
    :func:`_claim_stmt`, and take a second task. Plain ``FOR UPDATE`` would
    block one request on the other instead. Nothing needs serializing, because
    the ``assigned_to`` filter means the only rows this can match are already
    stamped with this one caller's name -- no other caller's request competes
    for them. Split out from :func:`next_task` for the same reason
    :func:`_claim_stmt` is: so a test can compile it and read the clauses off
    the SQL rather than infer them from a call that happened to pass.
    """
    return (
        select(ReviewTask)
        .where(ReviewTask.state == ReviewState.IN_PROGRESS)
        .where(ReviewTask.assigned_to == assignee)
        .order_by(ReviewTask.opened_at, ReviewTask.id)
        .limit(1)
    )


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
    # §18 at the sink: reasons are built from exception text, and exception text
    # interpolates raw model values (save_extraction's human-owned guard quotes
    # merchant.name; _bounded_optional_text quotes the overlong value). Redacting
    # here covers every producer, present and future.
    reason = redact_pan(reason)
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
    """``assignee``'s own in-progress task, else a freshly claimed one, else ``None``.

    **Resume before claim** (ADR-0016). If ``assignee`` already holds an
    ``IN_PROGRESS`` task it is returned unchanged -- nothing is written, and
    the queue is not drawn from. Only a caller holding none claims.

    Without this the queue had no way back. When ADR-0016 was written
    ``ReviewState.OPEN`` was assigned in exactly three places (the column
    default, a brand-new task in :func:`enqueue_review`, and its reopen branch,
    which is gated on ``state is ReviewState.DONE``), :func:`_claim_stmt`
    selects ``state == OPEN`` only, and nothing released a claim -- ``POST
    /review/{id}/complete`` closes a task, which is not a release. A reviewer
    who reloaded the page, whose browser died, or whose claim committed
    server-side while the response was lost took that task out of the queue
    permanently. Resuming is also what a reviewer wants on a reload: their own
    half-finished receipt back, not a different one.

    :func:`release_task` (ADR-0025) is a fourth writer of ``OPEN`` and changes
    none of that. It is admin-only at the route and is somebody *else* taking
    the work back; resume needs no client call at all, which is why it, and not
    a release, is what keeps a reload, a crash and a lost response survivable.
    The two reach different failures: resume returns a task to the person
    holding it, a release returns it to the queue for whoever polls next.

    **Resume outranks priority.** A held task comes back even when a
    priority-0 task is waiting; §12's ranking orders the queue, and a claimed
    task has already left it. Among several held tasks the earliest
    ``opened_at`` wins -- see :func:`_resume_stmt`, which also explains why
    that query takes no lock.

    **The guarantee is per *sequential* caller, not absolute.** A reviewer
    whose previous poll committed before the next one begins holds at most one
    task. Two *overlapping* polls from one user can still both claim, because
    the second one's resume query cannot see the first one's uncommitted
    write: measured on a file-backed SQLite database, with session A's claim
    flushed but not committed, ``session_b.scalars(_resume_stmt("ada")).first()``
    returned ``None``, so B falls through to the claim path. ``GET
    /review/next`` is a sync ``def``, so Starlette serves it from a threadpool
    and two tabs, a double-click, or a double-invoked effect genuinely
    overlap. This is **not** true of a poll that overlaps an already-committed
    claim: two concurrent calls then both resume the same row (measured -- both
    returned the held task, neither claimed a second), which is precisely what
    a locking clause here would break.

    **The overflow is self-correcting, which is why it is documented rather
    than fixed.** A user left holding several gets them back one per poll,
    oldest first, and nothing is stranded -- measured: a user holding two
    resumed the 09:00 task, then the 12:00 task after it closed, then ``None``.
    That is why :func:`_resume_stmt` is ordered and ``limit(1)``-ed instead of
    assuming a single row.

    The claim path is unchanged and keeps ADR-0008's guarantee: the row is
    selected ``FOR UPDATE SKIP LOCKED`` where the backend supports it (see
    :func:`_supports_skip_locked`, and note that SQLite drops the clause
    *silently*, which is why the decision is made in Python) and flipped to
    ``IN_PROGRESS`` with ``assigned_to`` set in the same transaction, so two
    reviewers polling at once still get two different tasks. The two queries
    cannot collide over a row: they select disjoint states, and the resume one
    additionally matches only rows already carrying this caller's own name.
    The lock is released when the caller commits -- which, per the layer's
    convention, the caller does.
    """
    held = session.scalars(_resume_stmt(assignee)).first()
    if held is not None:
        return held

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


def release_task(session: Session, task_id: uuid.UUID) -> tuple[ReviewTask, str | None]:
    """Return a claimed task to the queue, and name who was holding it.

    The inverse of :func:`next_task`'s claim, and the one transition this queue
    never had: ``IN_PROGRESS`` -> ``OPEN`` with ``assigned_to`` cleared, so
    :func:`_claim_stmt` -- which selects ``state == OPEN`` and nothing else --
    can see the row again.

    ADR-0016 left this out deliberately. It chose resume-before-claim *over* a
    release for the page-unload case and still wins that argument; what it also
    recorded is the gap resume cannot reach: "a task stranded under a username
    that no longer polls stays stranded; nothing here reassigns work between
    people, and doing so is a policy decision, not a bug fix." **ADR-0025 is
    that policy decision**, and it is admin-only at the route. Resume is
    unchanged and still handles the reload, the crash and the lost response.

    Returns ``(task, previously_assigned_to)``. The second element is the whole
    reason this does not simply return the task the way :func:`close_task`
    does: the call *destroys* that name, so handing it back keeps the
    information from depending on every caller remembering to read it first.

    **Idempotent on an ``OPEN`` task** -- nothing is written and the prior
    holder is ``None``, the same shape :func:`close_task` uses for a second
    close. ``OPEN`` carrying an assignee is unreachable, and what makes it so
    is that every write of ``assigned_to`` moves it in step with the state --
    not that the writers are few. There are three: :func:`enqueue_review`'s
    reopen branch clears it as the task reopens, :func:`next_task`'s claim
    sets it as the task leaves ``OPEN``, and this function clears it as the
    task returns. A fourth writer would have to keep the same discipline.

    **A ``DONE`` task is refused**, and that is not tidiness. :func:`close_task`
    leaves ``assigned_to`` set, no ``Receipt`` column records a reviewer, and a
    ``corrections`` row exists only for a field whose value actually changed --
    so for a receipt a reviewer confirmed without editing anything, this column
    is the only record in the system that a human ever looked at it. Reopening
    is :func:`enqueue_review`'s job, which clears the name deliberately.

    ``priority``, ``opened_at`` and ``reason`` are untouched: a released task
    returns to the queue position it already held rather than to the back,
    which would punish the receipt for its reviewer's absence. ``closed_at`` is
    ``None`` in both live states and is not written either.

    Raises ``ValueError`` for an unknown id and for a closed task. Flushes;
    does not commit.
    """
    task = session.get(ReviewTask, task_id)
    if task is None:
        raise ValueError(f"no review task with id {task_id}")

    if task.state is ReviewState.DONE:
        raise ValueError(
            f"review task {task_id} is closed; releasing it would clear "
            "assigned_to, which on a closed task is the only record that "
            "anyone reviewed this receipt. Reopening is enqueue_review's job."
        )

    if task.state is ReviewState.OPEN:
        return task, None

    previously_assigned_to = task.assigned_to
    task.assigned_to = None
    task.state = ReviewState.OPEN
    session.flush()
    return task, previously_assigned_to


def close_review_for_receipt(session: Session, receipt_id: uuid.UUID) -> ReviewTask | None:
    """Close ``receipt_id``'s review task, if it has one. ``None`` if it does not.

    The inverse of :func:`enqueue_review`, and the counterpart the pipeline needs
    when a re-run *resolves* what an earlier run flagged: the queue is keyed on
    the receipt (``review_tasks.receipt_id`` is UNIQUE), so a task left open
    after the receipt was auto-approved would be handed to a reviewer by
    ``GET /review/next`` and would keep inflating the ``/metrics`` backlog.

    A receipt with no task is a no-op rather than an error -- the overwhelmingly
    common case, and a caller should not have to look first. Closing delegates to
    :func:`close_task`, which is idempotent, so an already-``DONE`` task keeps its
    original ``closed_at``. Flushes; does not commit.
    """
    task = session.scalars(
        select(ReviewTask).where(ReviewTask.receipt_id == receipt_id)
    ).one_or_none()
    return None if task is None else close_task(session, task.id)


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
