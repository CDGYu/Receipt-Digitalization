"""Review layer: the human-in-the-loop queue over routed receipts (spec §14.9).

Whatever the confidence router did not auto-approve becomes a review task, one
per receipt, worked lowest ``priority`` first (§12 -- ``0`` is urgent).
:mod:`receipts.review.queue` is the queue API: enqueue, claim, release, close,
count.

Same convention as the persistence layer: every function takes an explicit
:class:`~sqlalchemy.orm.Session` and the caller owns the transaction.
"""

from __future__ import annotations

from .queue import (
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

__all__ = [
    "QueueStats",
    "close_review_for_receipt",
    "close_task",
    "enqueue_review",
    "list_corrections",
    "list_tasks",
    "next_task",
    "queue_stats",
    "release_task",
]
