"""Bring interrupted receipts to a terminal state.

The terminal-state guarantee -- *every receipt reaches a terminal state* -- is
carried in the pipeline by normal return and by exception handling. **An
interruption is neither.** A SIGKILLed work-horse raises nothing in its own
process, and a CLI run that is simply stopped runs no handler at all, so no
amount of ``try``/``except`` anywhere can close this. Something that *survives*
has to notice, and it has to do so without knowing which runner died.

That is why this module reads the receipt row rather than the queue: a reaper
keyed on RQ would cover exactly one of the four ways a receipt is processed.

**Imports are deliberately narrow.** This module is imported by both the CLI
and the review API, and ``receipts.pipeline`` pulls in the optional ``pipeline``
extra. Importing it here would drag that extra into every command, which is the
trap ``cli.py`` documents above ``cmd_process``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from config.settings import Settings

from .persist.models import Receipt
from .persist.repository import find_stranded, redact_pan
from .review.queue import enqueue_review
from .score.confidence import ReceiptStatus

__all__ = ["STRAND_MARGIN", "strand_receipt", "sweep_stranded"]

log = logging.getLogger(__name__)

#: HTTP attempts per model call -- the SDK's default ``max_retries`` of 2 plus
#: the initial attempt (ADR-0047 decision 8). Duplicated from
#: ``receipts.worker`` rather than imported: importing the worker here would
#: drag the optional extras this module exists to avoid. ``test_sweep.py`` pins
#: the two against each other so they cannot drift.
_SDK_ATTEMPTS = 3

#: How much longer than one model call a run may be silent before it is
#: presumed stranded. Multiplicative, not additive: the risk of sweeping a live
#: run scales with how long a legitimate call can take.
STRAND_MARGIN = 2

#: How much longer than a whole receipt a *never-started* row may sit before it
#: is presumed dropped. Deliberately generous: a receipt queued behind a
#: backlog looks exactly like one that was never enqueued, and marking a
#: healthy queued receipt is worse than noticing a dropped one late.
UNSTARTED_MARGIN = 12

#: Same urgency a failed stage gets. An interrupted receipt is not a lesser
#: problem than a broken one.
_STRANDED_PRIORITY = 1


def _cutoffs(settings: Settings, now: datetime) -> tuple[datetime, datetime]:
    """The two clocks, both derived from one model call.

    Deriving both from the same quantity is what stops the sweep and the job
    ceiling disagreeing about what "too long" means.
    """
    one_call = settings.vlm_timeout_s * _SDK_ATTEMPTS
    calls = 2 + max(0, settings.max_repair_attempts)
    started = now - timedelta(seconds=one_call * STRAND_MARGIN)
    unstarted = now - timedelta(seconds=one_call * calls * UNSTARTED_MARGIN)
    return started, unstarted


def strand_receipt(session: Session, receipt: Receipt) -> bool:
    """Land one interrupted receipt in ``needs_review``. Flushes; does not commit.

    Returns whether it changed anything, so a concurrent sweeper that lost the
    race reports nothing rather than reporting a receipt it did not move.

    Follows :func:`receipts.pipeline._persist_failure`'s convention -- the
    stage named in the reason, a review task opened at the same urgency -- but
    is a sibling rather than a caller: that function needs a ``_StageFailure``,
    a ``ReceiptJob`` and a phash, and a sweep has a row.
    """
    if receipt.status is not ReceiptStatus.PENDING:
        return False
    stage = receipt.progress_stage or "before any stage reported"
    reason = redact_pan(f"processing was interrupted at {stage} and never resumed")
    receipt.status = ReceiptStatus.NEEDS_REVIEW
    enqueue_review(session, receipt.id, reason, _STRANDED_PRIORITY)
    session.flush()
    return True


def sweep_stranded(
    session_factory: Callable[[], Session],
    *,
    settings: Settings,
    now: datetime | None = None,
    dry_run: bool = False,
) -> list[uuid.UUID]:
    """Bring every stranded receipt to a terminal state. Returns what moved.

    ``dry_run`` reports what *would* move and writes nothing: a command that
    marks receipts should be inspectable before it is trusted.
    """
    now = now or datetime.now(UTC)
    started_cutoff, unstarted_cutoff = _cutoffs(settings, now)
    moved: list[uuid.UUID] = []
    session = session_factory()
    try:
        for receipt in find_stranded(
            session, started_cutoff=started_cutoff, unstarted_cutoff=unstarted_cutoff
        ):
            if dry_run:
                moved.append(receipt.id)
            elif strand_receipt(session, receipt):
                moved.append(receipt.id)
                log.warning("receipt %s was stranded; sent to review", receipt.id)
        if dry_run:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return moved
