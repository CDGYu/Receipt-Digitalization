# ADR 0016 — `GET /review/next` resumes the caller's own in-progress task

**Status:** Accepted (P5.T3b, 2026-07-30)

## Context

Building the review UI (ADR-0015) exercised `GET /review/next` from a browser
for the first time, and a browser does something no test did: it reloads.

**A claimed review task could never be released.** Four measured facts, all read
off the code rather than reasoned about:

- `ReviewState.OPEN` is **assigned** in exactly three places, repo-wide: the
  column default (`persist/models.py:360`), a brand-new task in
  `enqueue_review`, and `enqueue_review`'s reopen branch. Line numbers as of
  this commit: `queue.py:195` and `queue.py:213`; they were `159` and `177`
  before this change added `_resume_stmt` above them.
- That reopen branch is gated on `if existing.state is ReviewState.DONE`
  (`queue.py:212`). `enqueue_review`'s own docstring states the other half:
  *"An `IN_PROGRESS` task keeps its state."*
- `_claim_stmt` selects `.where(ReviewTask.state == ReviewState.OPEN)`
  (`queue.py:85`) and nothing else, so an `IN_PROGRESS` row is invisible to
  every future claim.
- **None of the eleven routes in `review/api.py` releases or unclaims.**
  `POST /review/{task_id}/complete` calls `close_task`, which sets `DONE` — a
  completion, not a release.

Together those are a one-way door. A reviewer who reloaded the page, whose
browser crashed, or whose claim committed server-side while the response was
lost, left that task in `IN_PROGRESS` **permanently**: out of the queue, absent
from `queue_stats().by_priority` (which counts open tasks only), and reachable
by nothing. Task 3 fixed the UI so it stops *adding* claims, but no frontend
change can recover one already stranded.

The same milestone surfaced a second, smaller gap in the same screen, fixed
alongside this one because it has the same cause — two independently written
lists of the same columns that nothing bound together. `_RECEIPT_FIELDS`
(`persist/repository.py`) accepts corrections for 17 paths and `receipt_detail`
(`review/serializers.py`) returned 17 top-level keys, and they were **different**
17s: `receipt.number`, `receipt.time` and `payment.method` were correctable but
had no key in the response at all, so a reviewer could overwrite what the
machine read without ever being shown it. All three columns
(`receipt_number`, `txn_time`, `payment_method`) were present in the database
the whole time.

## Decision

**`GET /review/next` resumes the caller's own in-progress task before claiming a
new one.** If the requesting user already holds an `IN_PROGRESS` task assigned
to them, that task is returned; only a caller holding none draws from the queue.
The change lives in `queue.next_task`, so the route stays a thin wrapper and the
CLI and any future caller inherit it.

This shape was chosen over an explicit release route because it recovers from
the cases a release cannot. A `POST /review/{id}/release` on page unload relies
on `beforeunload`/`unload` firing and the request completing, which browsers
deliver unreliably and not at all on a crash or a lost connection — and it does
nothing for the tasks already stranded. Resuming needs no client call at all,
and it hands a reviewer back the receipt they were part-way through, which is
what they wanted from the reload anyway.

**Resume is per-user, by construction.** `_resume_stmt` filters on
`ReviewTask.assigned_to == assignee` as well as on the state. One user is never
handed another's work: that would be the "two reviewers, one receipt" failure
ADR-0008 exists to prevent, arriving through a new door.

**Resume outranks priority.** A held task comes back even when a priority-0 task
is waiting. §12's ranking orders the *queue*, and a claimed task has already
left it; handing a reviewer a different receipt on reload would abandon the one
they are mid-way through — the state this change exists to end.

**Among several held tasks, earliest `opened_at` wins, ties broken by `id`.** A
user can hold more than one only because of claims stranded before this ADR, but
those rows exist in the wild, so the pick must be deterministic. `opened_at`
first because the longest-held task is the one most at risk of being forgotten;
`id` second because `opened_at` defaults to `CURRENT_TIMESTAMP`, which SQLite
resolves only to whole seconds, so a burst of claims genuinely can tie and the
backend would otherwise be free to return a different row on each poll. This is
the same total-order discipline `_claim_stmt` already uses. `priority` is
deliberately **not** in the resume ordering.

**The resume query takes no lock, and that is deliberate.** `FOR UPDATE SKIP
LOCKED` here would reintroduce the exact defect being removed: a second
concurrent request from the *same* reviewer would skip its own locked row, fall
through to the claim path, and take a second task. Plain `FOR UPDATE` would
block one request on the other. Nothing needs serializing, because the
`assigned_to` filter means the only rows the statement can match already carry
this one caller's name — no other caller's request competes for them.

**ADR-0008's guarantees are untouched.** The claim path still applies
`.with_for_update(skip_locked=True)` on the dialects that support it, and
`_supports_skip_locked` still decides that in Python, because *SQLite silently
emits no locking clause rather than erroring*. The two statements select
disjoint states (`OPEN` vs `IN_PROGRESS`), so adding the second cannot let two
callers reach one row.

**`receipt_detail` returns `receipt_number`, `txn_time` and `payment_method`.**
Purely additive — no existing key moved or changed shape. `txn_time` is rendered
with `isoformat()`, not `strftime("%H:%M")`: `receipt.time` is a *correctable*
path, so what a reviewer reads has to be what `PATCH` takes back. Measured — for
`time(14, 30, 45)`, `_coerce_time(v.isoformat()) == v` while
`_coerce_time(v.strftime("%H:%M")) != v`; the lossy rendering would mean a
reviewer who merely *confirms* an untouched receipt rewrites its stored time and
earns a `corrections` row for an edit they never made.

## Consequences

- **A reviewer can hold at most one task through this API.** Claiming a second
  now requires completing the first. That is a deliberate narrowing of what the
  endpoint could previously do by accident, and it is what makes the queue's
  in-progress count meaningful.
- **Tasks stranded before this change come back on their owner's next poll**, one
  at a time, oldest first — no migration and no admin sweep. A task stranded
  under a username that no longer polls stays stranded; nothing here reassigns
  work between people, and doing so is a policy decision, not a bug fix.
- **`GET /review/next` is no longer side-effect-free-or-claiming; it is one or
  the other.** The resume branch writes nothing at all — no flush, no
  `assigned_to` rewrite, no timestamp moved.
- **`payment_method` is now readable over the API, and it is one of the two
  columns `save_extraction` redacts** — `merchant_name_raw` is the other, and
  `receipt_detail` already returned it. Redaction happens on the way *in*, on
  both of the column's writers: `save_extraction` calls `redact_pan` on it, and
  `_plan_change` redacts every coerced text value a reviewer submits.
  Those are the only two writes to `payment_method` under `src/`
  (`create_pending_receipt`, the only other `Receipt(...)` construction, leaves
  it NULL). So what leaves is what §18 already permits to be stored: measured
  through the route, `PATCH {"payment": {"method": "VISA 4111111111111111"}}`
  returns `"VISA ************1111"` and the unmasked digits appear nowhere in
  the body. Exposing it adds no new class of disclosure, only a new place to
  read one that was already stored and already served for its sibling column.
  **The guarantee belongs to the repository layer, not to the column**: seeding
  a row by constructing `Receipt(...)` directly — which is what the test
  fixtures do — bypasses both writers, so this key is only as clean as the code
  that filled it.
- **Three existing queue tests had to change**, and the change is the evidence
  the semantics moved: `test_next_task_returns_tasks_in_priority_order`,
  `test_next_task_breaks_priority_ties_by_opened_at` and
  `test_next_task_does_not_hand_out_the_same_task_twice` each claimed repeatedly
  as one assignee. Each now uses a distinct name per claim; what they assert is
  unchanged.
- **Six of this task's guarantees are absence-of-breakage claims that no RED run
  can prove.** They were bound by reverting each guarantee separately and
  recording which test failed — eleven mutations, every one caught. See the task
  report for the table.
- ADR-0012 is Accepted and unmodified. It documents `GET /review/next` as "next
  task for the caller"; this ADR narrows what "next" means for a caller who is
  already holding one.

## References

SPEC §14.9 (routes), §12 (review priorities), §6.7 (`review_tasks`), §18 (PAN,
silent drops); ADR-0006 (injected session, caller commits, `ValueError`
boundary); ADR-0008 (review-queue concurrency — the claim lock and the Python
dialect guard this ADR preserves); ADR-0012 (the review API contract this
extends, unmodified); ADR-0015 (the review UI that exposed both gaps);
`src/receipts/review/queue.py` (`_resume_stmt`, `next_task`);
`src/receipts/review/serializers.py` (`_iso_time`, `receipt_detail`);
`tests/test_review_queue.py`, `tests/test_api_read.py`, `tests/test_api_write.py`;
`.superpowers/sdd/2026-07-29-review-ui/task-3b-report.md` (RED/GREEN runs and the
mutation table).
