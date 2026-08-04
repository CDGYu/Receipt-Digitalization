# ADR 0025 — Admin release for a claimed review task

**Status:** Accepted (2026-08-04)
**Builds on:** ADR-0016 (`GET /review/next` resumes the caller's own task — the
decision this one deliberately leaves untouched), ADR-0006 (injected session,
caller commits, the `ValueError` boundary), ADR-0008 (review-queue concurrency
and the claim lock), ADR-0012 (the review API's roles and error envelope),
ADR-0022 (failure text is redacted at every egress), ADR-0024 (the review UI's
error-recovery contract, whose terminal `taken` state this feeds).
**Supersedes, in part:** ADR-0016's Context claim that none of the routes in
`review/api.py` "releases or unclaims". One now does. Nothing else in ADR-0016
is superseded; one Consequence is narrowed — see the dated note appended there.

## Context

**The one-way door.** ADR-0016 measured it: `_claim_stmt` selects
`state == OPEN` and nothing else, `enqueue_review`'s reopen branch is gated on
`DONE`, and until this milestone no route moved a task from `IN_PROGRESS` back
to `OPEN`. A task claimed by a reviewer who then stopped polling was out of the
queue permanently — invisible to every future claim, and absent from
`queue_stats().by_priority`, which counts open tasks only.

ADR-0016 closed most of that door with resume-before-claim. It also named
exactly what resume cannot reach, and left the remedy open in its own words:

> A task stranded under a username that no longer polls stays stranded; nothing
> here reassigns work between people, and **doing so is a policy decision, not a
> bug fix.**

**This ADR is that policy decision.** It is not a correction to ADR-0016 and
must not be read as one. ADR-0016 rejected a release *as the page-unload
recovery mechanism* — a `POST` fired from `beforeunload`, which browsers deliver
unreliably and not at all on a crash — and it still wins that argument.
**Resume-before-claim is unchanged.** It is the reviewer's own recovery, needs
no client call, and still handles the reload, the crash and the lost response.
A release is an *admin acting on someone else's task*, which resume by
construction cannot be: `_resume_stmt` filters on `assigned_to == assignee`, so
it can only ever hand a task back to the person already holding it. Both exist;
neither replaces the other.

**What `assigned_to` actually records**, measured, because it is the entire
argument for decision 2 below. `close_task` writes `state` and `closed_at` and
does not touch `assigned_to`. No `Receipt` column anywhere under `src/` names a
reviewer — no `reviewed_by`, no `reviewer_id`, no `approved_by`. And a
`corrections` row exists only for a field whose value actually changed. So for
a receipt a reviewer confirmed **without changing anything**,
`review_tasks.assigned_to` is the only record in the entire system that a human
ever looked at it.

**A consumer was already built.** ADR-0024 §3 shipped a terminal `taken` state
in the review UI, entered on a 403 from `POST /review/{task_id}/complete`, and
its own Consequences said the admin release "now has a consumer: the terminal
`taken` state was designed for exactly the 403 it will produce. Until it ships,
that path is reachable only in tests." It has shipped.

## Decision

`POST /review/{task_id}/release` returns a claimed task to the queue:
`IN_PROGRESS` → `OPEN`, `assigned_to` cleared. `release_task(session, task_id)`
in `review/queue.py` owns the transition and returns
`(task, previously_assigned_to)` rather than the bare `ReviewTask`
`close_task` returns — the call *destroys* that name, so the function hands it
back instead of leaving it recoverable only by a caller who remembers to read
it first.

### 1. Admin-only, on any claimed task

Not reviewer self-release. The gap ADR-0016 named is **work reassigned between
people**, which is an admin act by nature; a self-release is a different need,
and it never produces the 403 the UI's terminal state was built for.

Authorization is declarative — `Depends(require_role(ROLE_ADMIN))`, the shape
`GET /export/xlsx` already uses — because this is a pure role test and belongs
in the dependency, where it is enforced before the body runs. `/complete` checks
in-body only because *assignee-or-admin* needs the task row first.

### 2. `OPEN` is idempotent; `DONE` is refused

Releasing an already-open task writes nothing and reports a prior holder of
`null`, the same shape `close_task` uses for a second close. Releasing a closed
one raises, and that is not tidiness: per the Context above, clearing
`assigned_to` on a `DONE` task destroys the only trace that anyone reviewed the
receipt. Reopening stays `enqueue_review`'s job, which clears the name
deliberately as part of reopening.

The refusal is a `ValueError`, not a 409. `_install_error_handlers` already maps
`ValueError` to 400 with ADR-0012's envelope, so this needs no new machinery and
keeps one boundary (ADR-0006) and one place that knows what a task may do. 409
is the more precise HTTP semantic and buys nothing while the only client is a
script; should it be wanted later it is a route change with `release_task`
untouched.

**The unknown-task 404 is the route's own** `session.get`, exactly as
`/complete` does it. `release_task`'s `ValueError` for a missing id would render
400, and "no such task" and "that task cannot be released" are different
answers. The two error paths are pinned separately.

### 3. The audit trail is a log line plus a response echo, and its limit is stated

No new column and no new table. The route logs the task id, the prior holder and
the acting admin after the commit, so a rolled-back release is never announced
as one; the response carries `released_from` beside `_task_summary`'s
`assigned_to`, which is now `null` — `assigned_to` says who holds it (nobody),
`released_from` says who held it. On the idempotent `OPEN` path `released_from`
is `null` too, so an admin can tell a real release from a no-op.

**The limit, stated rather than hidden: the log is the only durable trace, and
logs are not the database.** Nothing queryable records who released what. A
durable record would be `released_by` / `released_at` columns; they were priced
and declined for this milestone.

### 4. The egress boundary: `reason` leaves in the body, deliberately not in the log

The response is `{**_task_summary(task), "released_from": released_from}`, and
`_task_summary` carries the task's `reason`. That is what the route's payload
contract asks for, and it is the same summary `POST /review/{task_id}/complete`
returns and `GET /review/next` nests under `task`. **Under ADR-0022 this is not
a new kind of sink — it is one more caller of an existing one**, and the
boundary is recorded here rather than left for a reader to infer: `reason` is
built from exception text and is redacted at its *writer*. `enqueue_review`
calls `redact_pan` on the incoming reason before it stores it, on the new-task
path and the refresh path alike, so every reader of `review_tasks.reason`
serves already-redacted text. Adding a reader adds no unredacted egress. Adding
a *writer* that skipped that call would.

**The guarantee belongs to `enqueue_review`, not to the column** — the same
caveat ADR-0016 records for `payment_method`: "seeding a row by constructing
`Receipt(...)` directly — which is what the test fixtures do — bypasses both
writers, so this key is only as clean as the code that filled it." It holds for
everything under `src/`, which reaches this column only through
`enqueue_review`; the sole `ReviewTask(...)` construction and the sole
`existing.reason` write both sit inside it, downstream of the `redact_pan`
call. A fixture assigning `task.reason` directly bypasses the sink entirely,
which is exactly how `test_the_release_is_logged_without_the_tasks_reason`
plants its sentinel.

**The log line's contents are the other half of the same decision.** Task id,
prior holder, acting admin — and `reason` deliberately absent, pinned by
`test_the_release_is_logged_without_the_tasks_reason`. A log site is a new
egress in ADR-0022's own enumeration ("a new log site, an API field, a queue
payload"), and `reason` is redacted only at `enqueue_review`'s sink, so putting
it there would extend that ADR's inventory for no gain. Ids and usernames only.

### 5. API-only this milestone

There is no admin screen. The route is driven by a script or `curl` until the
admin surface exists, which is a separate and larger milestone. No frontend file
changed.

### 6. `PATCH /receipts/{receipt_id}` stays claim-unaware — a deliberate non-change

It depends on `require_user` alone. A displaced reviewer's edits therefore still
land and only the close fails, and that is not an oversight left standing: it is
exactly ADR-0024 §3's premise, *"A 403 or 404 on `complete` means the PATCH
landed and the task is no longer the reviewer's to close."* Making `PATCH`
claim-aware would invalidate a shipped contract, and is its own milestone.

## Accepted residuals

### The displaced reviewer can immediately re-claim the same task

`priority` and `opened_at` are deliberately untouched, so a released task
returns to the queue position it already held rather than to the back — which
would punish the receipt for its reviewer's absence. The cost is that a
**still-polling** displaced reviewer's next `GET /review/next` finds no held
task, falls through to the claim path, and can be handed back the very task an
admin just took.

- **Reachability:** only while the displaced reviewer is still polling. Against
  the case this feature exists for — someone who has stopped — it never arises.
- **Cost of closing it:** a "do not re-offer this task to the person it was
  taken from" rule, which needs a new column and a claim-time policy. Larger
  than this entire milestone.
- **Ruling:** accepted, with the mechanism recorded rather than omitted.

### No row lock, and the third race order

`release_task` takes no locking clause, matching `close_task`. Two
release-vs-complete interleavings were reasoned about before implementation and
both are coherent: complete-first leaves `DONE` and the release gets its 400;
release-first leaves the complete with the 403 that is ADR-0024's terminal
`taken` state working as designed.

**There is a third order, and it was found during execution rather than
design.** `POST /review/{task_id}/complete` reads the task row for its
permission check and then calls `close_task`, which sets `DONE`
unconditionally. Because neither route takes a row lock, a release that commits
*between* those two steps is invisible to the complete already in flight: the
permission check has already passed against the pre-release `assigned_to`,
`close_task` writes only `state` and `closed_at`, and the release's committed
`assigned_to = NULL` therefore stands. The result is a **closed task with
`assigned_to = None`** — the very state decision 2's refusal exists to prevent.

**This does not make the `DONE` refusal wrong.** The refusal closes the
single-request path into that state, which is the path an admin can take by
hand and the one worth defending. What it cannot do is make the invariant
unconditional — and `release_task`'s docstring, which argues the refusal from
"the only record in the system that a human ever looked at it", currently claims
a guarantee the system does not give. This ADR is where that gap is recorded
instead of being rediscovered.

**Accepted, with its cost stated.** It needs two concurrent requests — an admin
release landing inside the window of the holder's own complete. What it degrades
is an audit record, not money and not a PAN: the receipt is still marked
reviewed, its `corrections` rows are intact, and the log line still names who
released what from whom. Closing it means a row lock on both routes, or
re-reading `assigned_to` after `close_task` and refusing to close a task nobody
holds — a transaction-shape change larger than the record it protects, and one
that would give `/complete` a second way to fail. Traced against the shipped
code rather than reproduced under load; what is recorded here is the mechanism
and its reachability.

## Consequences

- **ADR-0024's terminal `taken` state now has a live producer.** After a
  release `assigned_to` is `None`, so `/complete`'s *assignee-or-admin* check
  fails for the displaced reviewer and raises 403 — the status ADR-0024's
  classifier maps to `taken`. That path was previously reachable only from
  tests that set `assigned_to` by hand;
  `test_a_released_reviewer_gets_403_on_complete` now drives it end to end
  through two real requests.
- **`/metrics` stops under-reporting a stranded task.** Releasing decrements
  `in_progress`, increments `open`, and returns the row to
  `queue_stats().by_priority`, which selects `OPEN` only.
- **ADR-0016's Context claim is superseded and its stranding Consequence is
  narrowed**, both by the dated note appended to that ADR. Any sentence that
  quantifies over `review/api.py`'s route table is now short by this route;
  ADR-0015 and ADR-0016 each contain one and each carries a dated note. The
  durable reference is the route list in `review/api.py`, not a figure written
  in prose.
- **No new `ReviewState` member and no schema change**, so there is no Alembic
  migration and no new model. `assigned_to` gains another writer, and what keeps
  `OPEN`-carrying-an-assignee unreachable is that every writer moves the name in
  step with the state — not that the writers are few.
- **ADR-0008's claim guarantee is untouched.** `_claim_stmt` still takes
  `FOR UPDATE SKIP LOCKED` where the dialect supports it, and this route goes
  nowhere near that statement.
- **What proves the claims this record rests hardest on.** The admin gate is
  proven by replacing `Depends(require_role(ROLE_ADMIN))` with a stand-in
  dependency returning an admin `SessionUser` — the gate and nothing else, so
  the `admin` binding the log line reads survives. Measured, that mutant kills
  two tests: `test_a_reviewer_cannot_release_a_task` fails
  `assert 200 == 403` and `test_release_requires_authentication` fails
  `assert 200 == 401`. Both are direct evidence that the dependency is what
  refuses, not an inference from the route's shape. The `reason` omission is
  proven by capturing the task's `reason` inside the route's session block and
  logging it, which puts the sentinel genuinely in the emitted line.
- **Two mutations from the task brief proved nothing and are cited nowhere
  above.** Deleting the `admin` parameter also deletes the binding the log line
  reads, so it changes two things, not one; there is then no authorization
  decision left to test at all, and the `NameError` it raises fires at the log
  line *after* `session.commit()` — the release has already committed by the
  time anything fails. And logging `task.reason` from outside the route's
  `with` block raises `DetachedInstanceError` before formatting, so that mutant
  could not leak even in principle and never exercised the ADR-0022 pin.

## References

ADR-0016 (`GET /review/next` resumes the caller's own task — the deferral this
ADR takes up, and the decision it does not disturb); ADR-0006 (the injected
session, caller-commits and `ValueError` conventions `release_task` follows);
ADR-0008 (review-queue concurrency, whose claim lock is untouched); ADR-0012
(roles, the session cookie, and the error envelope the 400 renders through);
ADR-0022 (failure-text egress — the rule decision 4 applies); ADR-0024 (the
review UI's error-recovery contract, whose terminal `taken` state this route
produces).

SPEC §14.9 (the `review/` surface and the routes, updated with this milestone),
§12 (review priorities), §6.7 (`review_tasks`).

`docs/superpowers/specs/2026-08-04-admin-release-design.md` (the full design:
§1.4 the measured argument for the `DONE` refusal, §2 the five rulings, §5
concurrency, §7 the residuals);
`docs/superpowers/plans/2026-08-04-admin-release.md` (the three-task plan).
`.superpowers/sdd/2026-08-04-admin-release/progress.md` is the milestone ledger,
where the execution findings above were first recorded; it is gitignored and so
invisible to anything that searches this repository (ADR-0019's standing
caveat), which is why the load-bearing ones are written out here rather than
cited to it.

`src/receipts/review/queue.py` (`release_task`, and `enqueue_review`'s
`redact_pan` sink); `src/receipts/review/api.py` (`review_release`,
`_task_summary`, `review_complete`'s permission check);
`tests/test_review_queue.py` (the queue-layer pins, among them
`test_release_task_leaves_a_closed_tasks_assignee_intact` and
`test_releasing_returns_the_task_to_the_open_backlog`);
`tests/test_api_write.py` (the route pins, among them
`test_a_released_reviewer_gets_403_on_complete` and
`test_the_release_is_logged_without_the_tasks_reason`).
