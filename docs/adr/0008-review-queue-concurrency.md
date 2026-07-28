# ADR 0008 — Review-queue concurrency and idempotency

**Status:** Accepted (implements SPEC §14.9, §6.7, §12)

## Context

`review_tasks` is worked by multiple humans. Two reviewers must never be handed
the same receipt, and `review_tasks.receipt_id` is UNIQUE while a receipt can
legitimately be routed to review more than once (a repair pass, a re-extract, a
fresh routing decision after a correction).

## Decision

**Claiming is row-locked where the backend allows it.** `next_task` selects the
most urgent open task (`priority` ASC, then `opened_at`, then `id` — a total
order, so a coarse timestamp cannot make the hand-out nondeterministic) and flips
it to `IN_PROGRESS` in the same transaction. `FOR UPDATE SKIP LOCKED` is applied
via `.with_for_update(skip_locked=True)`.

**The dialect check lives in Python, not in the SQL compiler.** `SQLite silently
emits no locking clause` rather than erroring, so a claim that *looked* locked
would quietly hand two reviewers the same task. `_supports_skip_locked(bind)`
tests `bind.dialect.name` against `_SKIP_LOCKED_DIALECTS`. `_claim_stmt(*,
skip_locked)` exists as a seam so tests can compile the statement for both
dialects and assert the clause is present for Postgres and absent for SQLite —
proving both directions offline, with no driver.

**`enqueue_review` is idempotent by necessity.** It looks the row up and updates
in place rather than inserting: the **more urgent (lower) priority wins**, and
the `reason` moves with it so the review UI never shows a reason that contradicts
the priority; a `DONE` task is reopened; an `IN_PROGRESS` task keeps its state.

**Negative priorities are rejected.** `route()` returns `-1` as its "no review
needed" sentinel for auto-approved receipts. Passed here it would create a task
that the more-urgent-wins rule pins permanently above genuine priority-0 work and
that no later routing decision could demote. `0` is the most urgent real
priority (§12).

`queue_stats` uses grouped SQL aggregates (the queue is polled by `GET /metrics`
and the review UI header, so it must stay cheap as the backlog grows).

## Consequences

- Tests run on SQLite, where the lock is a no-op; the compile tests are what
  actually guard the production behaviour.
- **Known gap:** `enqueue_review` is check-then-insert, so genuinely concurrent
  enqueues for one receipt can still raise `IntegrityError`. Wrap it or use an
  upsert when the API layer lands (P4.T3).

## References

SPEC §14.9, §6.7, §12; ADR-0006.
