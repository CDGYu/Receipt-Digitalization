# The admin release: returning a claimed review task to the queue

**Status:** design, approved 2026-08-04
**Branch:** `feat/admin-release` (off `main@c3a268c`)
**Milestone:** Phase 5 follow-up #3
**Decides:** ADR-0025 (new); dated notes on ADR-0016 and ADR-0015

`POST /review/{task_id}/release` lets an **admin** return a claimed review task
to the queue: `IN_PROGRESS` → `OPEN`, `assigned_to` cleared. It is the inverse
of a claim, which nothing in the system has had.

This is deliberately **API-only**. The admin surface that would drive it from a
browser is a separate, larger milestone — see §10.

Line numbers below were read off the tree at `c3a268c`. They drift; **the symbol
names are the durable half** (ADR-0016 makes the same caveat about its own
citations, and its `queue.py:85` has since become `:86`).

---

## 1. Context, measured

### 1.1 What exists today, and what does not

`review/queue.py` owns the task lifecycle: `enqueue_review` creates or refreshes,
`next_task` resumes-then-claims, `close_task` marks `DONE`, `queue_stats` counts.
`ReviewState` has exactly three members — `OPEN`, `IN_PROGRESS`, `DONE`
(`persist/models.py:67`).

`ReviewTask.assigned_to` is written in **exactly two places** repo-wide:

- `queue.py:225` — `enqueue_review`'s reopen branch clears it, gated on
  `existing.state is ReviewState.DONE`.
- `queue.py:295` — `next_task`'s claim sets it, together with `IN_PROGRESS`.

So `OPEN` with a non-null `assigned_to` is unreachable, and there is **no
transition from `IN_PROGRESS` back to `OPEN` at all**. `_claim_stmt` filters
`state == ReviewState.OPEN` (`queue.py:86`), so an `IN_PROGRESS` row is
invisible to every future claim.

### 1.2 The gap ADR-0016 deferred, verbatim

ADR-0016 chose resume-before-claim **over** an explicit release route, and that
argument still stands: a release fired on page unload depends on `beforeunload`,
which browsers deliver unreliably and not at all on a crash. **Nothing here
replaces resume.** But ADR-0016 also named what resume cannot reach
(`0016:135-138`):

> **Tasks stranded before this change come back on their owner's next poll**,
> one at a time, oldest first — no migration and no admin sweep. A task stranded
> under a username that no longer polls stays stranded; nothing here reassigns
> work between people, and **doing so is a policy decision, not a bug fix.**

This milestone is that policy decision. It is not a correction to ADR-0016 and
must not be recorded as one.

### 1.3 The consumer that is already built

ADR-0024 §3 shipped a terminal `taken` state in the review UI, entered on a
**403 from `POST /review/{task_id}/complete`**, offering one exit and a dead
⌘↵. ADR-0024's own Consequences say it plainly:

> The admin release for a claimed task (`IN_PROGRESS` → `OPEN`) now has a
> consumer: the terminal `taken` state was designed for exactly the 403 it will
> produce. Until it ships, that path is reachable only in tests.

Traced against the real route rather than the prose: after a release,
`assigned_to` is `None`, so `api.py:540`'s `task.assigned_to != user.username
and user.role != ROLE_ADMIN` is true for the displaced reviewer and the route
raises **403 `only the assignee or an admin may complete this task`**. That is
the exact status and the exact path the UI branches on.

### 1.4 What `assigned_to` actually records — the fact that shapes §3

`close_task` (`queue.py:301-321`) sets `DONE` and `closed_at` and **does not
touch `assigned_to`**. `Receipt` has no `reviewed_by`, `reviewer_id` or
`approved_by` column anywhere under `src/` — verified by grep, zero hits. And a
`corrections` row exists only for a field whose value actually changed.

Therefore: **for a receipt a reviewer confirmed without changing anything,
`review_tasks.assigned_to` is the only record in the entire system that a human
ever looked at it.** That is why §3 refuses to release a `DONE` task.

---

## 2. Decisions made this session (user rulings)

1. **Admin-only, on any claimed task.** Not reviewer self-release. The admin
   sweep is the ADR-0016 gap; a self-release is a different need and never
   produces the 403 the UI consumes.
2. **`OPEN` is idempotent; `DONE` is refused.** Per §1.4.
3. **Audit is a log line plus a response echo.** No new column, no new table.
   The limit is stated rather than hidden: the log is the only durable trace,
   and logs are not the database.
4. **API-only this milestone.** The admin UI is a separate milestone (§10).
5. **The re-claim residual is accepted with its mechanism recorded** (§7).

---

## 3. `release_task` — the queue function

```python
def release_task(session: Session, task_id: uuid.UUID) -> tuple[ReviewTask, str | None]:
    """Return a claimed task to the queue. Returns (task, previously_assigned_to)."""
```

Placed in `review/queue.py` beside `close_task`, added to `__all__`, following
the layer's conventions exactly (ADR-0006): explicit `Session` first, **flushes,
does not commit**, raises `ValueError` — never a bare DB error — for anything it
is asked about that cannot be done.

| State on entry | Effect | Returns |
|---|---|---|
| `IN_PROGRESS` | `state = OPEN`, `assigned_to = None`, flush | `(task, "<prior holder>")` |
| `OPEN` | nothing written | `(task, None)` |
| `DONE` | — | raises `ValueError` |
| no such id | — | raises `ValueError` |

**`priority`, `opened_at` and `reason` are untouched.** A released task returns
to the queue position it already had; moving `opened_at` would send it to the
back and punish the receipt for its reviewer's absence. `closed_at` is untouched
too — it is `None` in both live states.

**Why a tuple rather than `close_task`'s bare `ReviewTask`.** The call
*destroys* the prior holder's name. Returning it makes the function
self-contained; the alternative — having every caller read `assigned_to` before
calling — leaves the information recoverable only by remembering to look first,
and a caller that forgets loses it silently.

**The `DONE` refusal is a `ValueError`, not a 409.** `_install_error_handlers`
(`api.py:129-131`) already maps `ValueError` → 400 with the standard envelope,
so this needs no new machinery and keeps one boundary (ADR-0006) and one place
that knows what a task may do. 409 is the more precise HTTP semantic and buys
nothing while the only caller is `curl`; the frontend classifier renders an
unmapped status as `other` with the server's text either way. Should 409 be
wanted later it is a one-line route change with `release_task` untouched.

---

## 4. `POST /review/{task_id}/release` — the route

Installed in `_install_write_routes` (`api.py:300`), which already owns
`/review/next`, `/review/{task_id}/complete` and `/export/xlsx`, immediately
after the complete route ends at `:547`.

```python
@app.post("/review/{task_id}/release")
def review_release(
    task_id: uuid.UUID,
    request: Request,
    admin: Annotated[SessionUser, Depends(require_role(ROLE_ADMIN))],
) -> dict[str, Any]:
```

| Condition | Result |
|---|---|
| no credentials | **401** `authentication required` (`require_user` inside `require_role`) |
| signed in, role `reviewer` | **403** `insufficient role` (`auth.py:126-133`) |
| no such task | **404** `no review task with id {task_id}` |
| task is `DONE` | **400**, `release_task`'s `ValueError` through the envelope |
| `IN_PROGRESS` or `OPEN` | **200** `{**_task_summary(task), "released_from": prior}` |

**The 404 needs the route's own `session.get` first**, exactly as
`/complete:537-539` does. `release_task`'s own `ValueError` for an unknown id
would render **400**, and "unknown task" must be 404. The two error paths are
distinct and are pinned separately (§8).

**Authorization is declarative** — `Depends(require_role(ROLE_ADMIN))`,
precedent `/export/xlsx:552`, enforced before the body runs. `/complete` does
its check in-body only because *assignee-or-admin* needs the task row first;
this one is a pure role test and belongs in the dependency.

**`released_from` is a sibling key, not a replacement.** `_task_summary`
(`api.py:273-284`) already carries `assigned_to`, which is now `null` — who
holds it, nobody. `released_from` says who held it. On the idempotent `OPEN`
path it is `null`, so an admin can distinguish "I took Ada's task" from "there
was nothing to release."

**The log line lives in the route, not in `release_task`** — only the route
knows the acting admin, and `queue.py` imports no logger at all. `logger.info`
(`api.py:87`) naming `task_id`, the prior holder and `admin.username`.

**The task's `reason` is deliberately not logged.** It is built from exception
text and is redacted only at `enqueue_review`'s sink (`queue.py:180`); putting
it in a second sink would extend ADR-0022's egress inventory for no gain. Ids
and usernames only.

---

## 5. Concurrency

**No locking clause**, matching `close_task`. This is a single-row state flip
whose every interleaving converges:

- **Two admins releasing at once** — both write `OPEN`/`None`; both are told
  they released Ada. Harmless.
- **Release racing the holder's own `complete`** — complete-first leaves `DONE`
  and the release gets its 400; release-first leaves the complete with a **403**,
  which is the terminal `taken` state working as designed. Both coherent.
- **Release racing another reviewer's `GET /review/next`** — the row becomes
  `OPEN` and enters `_claim_stmt`'s result set normally. That is the point.

ADR-0008's claim guarantee is untouched: `_claim_stmt` still takes
`FOR UPDATE SKIP LOCKED` where the dialect supports it, and this route does not
go near that statement.

**A released task re-enters `queue_stats`.** ADR-0016 records that a stranded
task is *"absent from `queue_stats().by_priority`, which counts open tasks
only"*. Releasing decrements `in_progress`, increments `open`, and returns the
task to the priority backlog — so `/metrics` stops under-reporting.

---

## 6. What must not change

- **Resume-before-claim (ADR-0016).** The release is an *admin acting on someone
  else's task*; resume is *the reviewer's own recovery*, needs no client call,
  and still handles the reload/crash/lost-response cases a release cannot. Both
  exist; neither replaces the other.
- **`PATCH /receipts/{receipt_id}` stays claim-unaware.** It depends on
  `require_user` alone (`api.py:379`). A displaced reviewer's edits therefore
  still land, and only the close fails — which is not an oversight but exactly
  ADR-0024 §3's premise: *"a 403 or 404 on complete means the PATCH landed and
  the task is no longer the reviewer's to close."* Making `PATCH` claim-aware
  would invalidate that shipped contract and is its own milestone.
- **`enqueue_review` keeps sole ownership of reopening.** Release never touches
  a `DONE` task.
- **No schema change**, so no Alembic migration and no new model. The SQLite
  migration drift guard should stay green untouched.
- ADR-0006 (`ValueError` boundary), ADR-0008 (claim locking), ADR-0012 (roles),
  ADR-0022 (egress), ADR-0024 (the terminal states) all hold unmodified.

---

## 7. Residuals, accepted and recorded

**The displaced reviewer can immediately re-claim the same task.** Because §3
preserves `opened_at` and `priority`, a released task returns near the front of
the queue. If the displaced reviewer is *still polling*, her next
`GET /review/next` finds no held task, falls through to `_claim_stmt`, and can
hand back the very task an admin just took.

- **Reachability:** only when the displaced reviewer is still active. Against
  the case this feature exists for — a reviewer who stopped polling — it never
  arises.
- **Cost of closing it:** a "do not re-offer this task to the person it was
  taken from" rule, which needs a new column and a new claim-time policy —
  larger than this entire milestone.
- **Ruling:** accepted, mechanism recorded here and in ADR-0025. Not silently
  omitted.

**The audit trail is a log line.** Nothing queryable records who released what.
Accepted per §2.3; a durable record is the `released_*` columns priced and
declined.

---

## 8. The prose sweep — claims this milestone falsifies

Two distinct classes, swept separately. Treatment differs by document type.

- **The substantive claim** — "nothing releases a claim": **eight matching
  lines across six locations** (five in `src/` and `tests/`, one in ADR-0016).
- **The route count** — "eleven routes": **three live sites** (ADR-0015:7,
  ADR-0016:25, `docs/MEMORY.md:396`) plus two historical ones left alone.
  Adding a row changes every sentence that quantifies over the table (review
  standard 12); this is that sentence, three times.

Neither figure quantifies over the other, and neither covers the build-spec
edit below, which is a third thing.

**Updated in place** — the house convention for the build spec, precedent
`a5bf75d` *"absorb the P4.T3 spec drift"* and `19e1f97` *"update spec 14.10 to
the CLI as implemented"*:

- `RECEIPT_SYSTEM_SPEC.md` §14.9 — add `def release_task(task_id: UUID) -> ReviewTask`
  to the `queue.py` block and `POST /review/{id}/release -> {id} is the TASK id;
  admin only` to the route block. **Also the paragraph beneath**, which
  currently ends "`/export/xlsx` requires `admin`" and must now name both.

**Rewritten, not deleted** — five live claims that "nothing releases a claim".
Each exists to explain *why resume was necessary*, and that reason survives; the
rewrite keeps the argument and adds the distinction in §6:

| Site | What it says today |
|---|---|
| `src/receipts/review/api.py:492` | "nothing else in this service releases a claim" |
| `src/receipts/review/queue.py:26` | module docstring, same claim |
| `src/receipts/review/queue.py:241` | `next_task` docstring, same claim |
| `tests/test_api_write.py:520-524` | test docstring, same claim |
| `tests/test_review_queue.py:481-484` | comment, same claim |

**Dated notes, never rewrites** (ADRs are immutable once Accepted):

- **ADR-0016** — three things move: the Context claim at `:25`, its "eleven
  routes" count, and the Consequence at `:137` that a task under a
  no-longer-polling username "stays stranded", now narrowed. **The note must
  state that resume-before-claim itself is unchanged**, or a reader will
  conclude the release replaced it.
- **ADR-0015** — `:7`, count only, eleven → twelve.

**Deliberately untouched, because they were true when written:**
`docs/superpowers/plans/2026-07-28-review-api.md:66`,
`docs/superpowers/specs/2026-07-29-review-ui-design.md:11`, and
`IMPLEMENTATION_PLAN.md:279`'s P4.T3 "produces" list. Past-milestone artefacts;
plans do not self-amend.

**At session end (ADR-0021):** the handoff pair, folding in `docs/MEMORY.md:396`'s
route count and the stale `0708fd4` at `docs/MEMORY.md:471` (it names the
failure-egress refresh, two milestones back).

---

## 9. Tests

Every row carries the single-variable mutation that must turn it red. **A pin
never proven to fail is not a pin** (review standard 14).

**`tests/test_review_queue.py`** — beside the `close_task` block at `:660`:

| Test | Mutation that must turn it red |
|---|---|
| returns a claimed task to the queue (`OPEN`) | drop `task.state = ReviewState.OPEN` |
| clears the assignee, returns the prior holder | drop `task.assigned_to = None` |
| a released task is claimable **by a different reviewer** | drop the state write — `_claim_stmt` filters on `OPEN` |
| idempotent on an `OPEN` task, prior is `None` | make the `OPEN` branch raise |
| refuses a `DONE` task | remove the `DONE` guard |
| **leaves a closed task's assignee intact** | move the `assigned_to` clear *above* the `DONE` check |
| rejects an unknown id | drop the `None` check |
| leaves `priority` / `opened_at` / `reason` alone | bump `opened_at` inside `release_task` |
| returns the task to the open backlog (`queue_stats`) | drop the state write |

**`tests/test_api_write.py`** — beside the complete block at `:551`; fixtures
`reviewer_client` (`:132`), `admin_client` (`:218`), `task_id` (`:205`),
`session_factory` (`:85`) all already exist:

| Test | Mutation |
|---|---|
| admin releases → 200, `assigned_to` null, `released_from` set | drop `released_from` from the body |
| a reviewer gets 403 | swap `require_role(ROLE_ADMIN)` → `require_user` |
| anonymous gets 401 | drop the dependency parameter |
| unknown task → **404, not 400** | delete the route's own `session.get` guard |
| a `DONE` task → 400 | remove the `DONE` guard |
| **claim → admin releases → the reviewer's `complete` gets 403** | drop `task.assigned_to = None`; complete then returns 200 |
| the log names task, prior holder and admin — **and not `reason`** | add `task.reason` to the log call (`caplog`, an established pattern in `test_image_ops.py` and `test_process_receipt.py`) |

The bolded end-to-end test is the milestone's headline claim — it is what turns
ADR-0024's terminal `taken` state from theoretical into live. The last
whole-branch review found *its* milestone's headline deliverable deletable with
all five gates green, so this mutation is **run and recorded**, not asserted.

No frontend change, so no Vitest change.

---

## 10. Verification

- `python scripts/verify.py` — all five gates.
- **The outside-repo import check re-applies.** This is the first `src/` change
  since before the review-UI error-recovery milestone (`git diff --name-only
  7c811fa..02edcd0 -- src` → zero files). A green suite is not evidence that
  installed software works: an entry point gets exercised from **outside** the
  repository directory.
- Confirm the SQLite migration drift guard is still green **and that no
  migration was generated** — a non-change worth proving rather than assuming.
- `python -m ruff check .`; pytest counts read from `--junitxml`, never from a
  piped summary.

---

## 11. ADRs

**ADR-0025 — the admin release.** `Supersedes, in part: ADR-0016's Context claim
that no route releases or unclaims.` Records §2's five rulings, §1.4's argument
for the `DONE` refusal, the log-only audit and its stated limit, §6's deliberate
non-change to `PATCH`, and §7's residual with its reachability condition.
Builds on ADR-0016, ADR-0008, ADR-0006, ADR-0012, ADR-0024, ADR-0022.

Dated notes on **ADR-0016** and **ADR-0015** per §8. README indexed to 0025.

---

## 12. Open facts the plan must settle before briefing (probe, don't assume)

The recurring failure across six milestones is that a plan's prose is reliable
while its claims about existing artefacts are not. Before any task brief quotes
these, re-derive them by command:

1. **Every line number in this document.** ADR-0016's own citations drifted by
   four lines once and `queue.py:85` has since become `:86`.
2. **The exact 403 text** at `api.py:540` and the exact 401/403 texts
   `require_role` produces — quoted here from a read, not from a pin.
3. **Whether `admin_client`'s admin actually has role `admin`** rather than
   being an alias fixture; read `test_api_write.py:218-226` before briefing.
4. **Whether any test asserts the current route count** or enumerates routes
   (e.g. an OpenAPI-shape test), which would break additively.
5. **Whether `_task_summary` has any other caller** that a new sibling key
   would surprise.
6. **That `release_task` is genuinely absent** from `queue.py`'s `__all__` and
   the `review/__init__` re-exports before adding it.
