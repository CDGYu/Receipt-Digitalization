# Admin Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `POST /review/{task_id}/release` — an admin returns a claimed review task to the queue (`IN_PROGRESS` → `OPEN`, `assigned_to` cleared), the inverse of a claim, which nothing in the system has had.

**Architecture:** One new queue function (`release_task`) beside `close_task`, one new route beside `POST /review/{task_id}/complete`, and a documentation sweep for the claims this falsifies. No schema change, no migration, no frontend change. Design: `docs/superpowers/specs/2026-08-04-admin-release-design.md`.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.x ORM, pytest, ruff. Backend only.

## Global Constraints

Every task's requirements implicitly include all of these.

- **ADR-0006 — the queue/repository layer's contract.** Every function takes an explicit `Session` first; **it flushes and does NOT commit** (the caller commits); it raises `ValueError`, never a bare DB error, for anything it is asked about that cannot be done.
- **ADR-0017 — `python scripts/verify.py` is what "passing" means.** `npm test` does not type-check. This milestone changes no frontend file, but the gate runner still runs all five.
- **ADR-0022 — failure text is redacted at every process egress.** `ReviewTask.reason` is built from exception text and is redacted only at `enqueue_review`'s sink (`queue.py:180`). **It must not enter a second sink.** No log line, response field, or error message added by this milestone may contain it.
- **ADR-0024 — `PATCH /receipts/{receipt_id}` stays claim-unaware.** Do not add a claim check to it. Its `require_user`-only dependency (`api.py:379`) is the premise of the shipped terminal-state contract.
- **ADR-0023 — parallel task agents share one worktree.** Commit every green step. Stage by explicit path, never `git add -A`. Restore a RED-proof mutation from a **byte copy** taken before mutating, never `git checkout --`, and **re-take the copy after any commit touching that file**. Never repair another agent's tree.
- **Review standard 14 — a pin never proven to fail is not a pin.** Every new test has a named single-variable mutation in this plan. Run it, record the actual failure output, restore, re-run green.
- **Review standard 5 — no rotting numbers in comments.** Do not write a suite count into any comment or docstring.
- **No schema change.** No Alembic migration is generated. If one appears, something is wrong.
- Lint with `python -m ruff check .` (bare `ruff` is not on PATH). Read pytest counts from `--junitxml`, never from a piped summary line.
- Conventional commit messages (`feat(scope): …`, `docs: …`).

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/receipts/review/queue.py` | `release_task` beside `close_task`; `__all__`; two falsified docstring claims | 1 |
| `src/receipts/review/__init__.py` | re-export `release_task` (import list **and** `__all__` — two edits) | 1 |
| `tests/test_review_queue.py` | nine queue tests; one falsified comment | 1 |
| `src/receipts/review/api.py` | the route in `_install_write_routes`; the `.queue` import; one falsified docstring claim | 2 |
| `tests/test_api_write.py` | seven route tests; one falsified docstring claim | 2 |
| `RECEIPT_SYSTEM_SPEC.md` | §14.9 gains the function and the route, plus the paragraph beneath | 3 |
| `docs/adr/0025-admin-release-for-a-claimed-task.md` | new | 3 |
| `docs/adr/0016-…md`, `docs/adr/0015-…md`, `docs/adr/README.md` | dated notes; index | 3 |

**No two tasks share a file.** That is deliberate (ADR-0023 rule 2) — the prose sweep is folded into the task that owns each file rather than collected into a separate task that would collide with both. Tasks are still dispatched **strictly serially**: Task 2 needs Task 1's function, and Task 3 documents what actually shipped.

---

### Task 1: `release_task` in the queue layer

**Files:**
- Modify: `src/receipts/review/queue.py` (add function after `close_task`, which ends at `:321`; `__all__` at `:44-51`; docstring claims at `:26` and `:241`)
- Modify: `src/receipts/review/__init__.py` (import block at `:13-20`, `__all__` at `:22-29`)
- Test: `tests/test_review_queue.py` (new block after the `close_task` block ending `:698`; import at `:37-44`; comment at `:481-484`)

**Interfaces:**
- Consumes: `ReviewState`, `ReviewTask` (`persist/models.py`); `_task(session, priority, *, reason="quick verify", opened_at=None)` and `_receipt` test helpers (`tests/test_review_queue.py:94`); the `engine: sa.Engine` fixture.
- Produces: `release_task(session: Session, task_id: uuid.UUID) -> tuple[ReviewTask, str | None]`, importable as `from receipts.review import release_task` **and** `from receipts.review.queue import release_task`. Task 2 imports it from `.queue`.

- [ ] **Step 1: Read the real code before writing anything**

Read `src/receipts/review/queue.py` in full — in particular `close_task` (`:301-321`), which this mirrors, `next_task`'s claim (`:286-298`), and `enqueue_review`'s reopen branch (`:222-226`), which is the only existing code that clears `assigned_to`. Confirm `ReviewState` has exactly three members. Do not trust the line numbers in this plan; they drift. The symbol names are the durable half.

- [ ] **Step 2: Write the failing tests**

Add `release_task` to the `from receipts.review import (...)` block at `tests/test_review_queue.py:37`, keeping the list alphabetical (it goes after `queue_stats`). Then append this block after the `close_task` tests:

```python
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
    state is not an error. ``OPEN`` with an assignee is unreachable -- both
    writers of ``assigned_to`` keep it in step with the state.
    """
    with Session(engine) as session:
        task = _task(session, 1)

        released, previously_assigned_to = release_task(session, task.id)

        assert released.state is ReviewState.OPEN
        assert released.assigned_to is None
        assert previously_assigned_to is None


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
    reviewer's absence.
    """
    opened_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    with Session(engine) as session:
        _task(session, 2, reason="quick verify", opened_at=opened_at)
        task = next_task(session, "ada")
        assert task is not None

        released, _ = release_task(session, task.id)

        assert released.priority == 2
        assert released.opened_at == opened_at
        assert released.reason == "quick verify"


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
```

- [ ] **Step 3: Run them to confirm they fail**

Run: `python -m pytest tests/test_review_queue.py -k release -v`
Expected: collection error — `ImportError: cannot import name 'release_task' from 'receipts.review'`. That is the correct first failure; it proves the import wiring is part of the deliverable.

- [ ] **Step 4: Implement `release_task`**

In `src/receipts/review/queue.py`, add `"release_task"` to `__all__` (alphabetical: after `queue_stats`), and add this function immediately after `close_task`:

```python
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
    close. ``OPEN`` carrying an assignee is unreachable: ``assigned_to`` is
    written in exactly two places (:func:`enqueue_review`'s reopen branch and
    the claim below), and both keep it in step with the state.

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
```

Then in `src/receipts/review/__init__.py`, add `release_task` to **both** the `from .queue import (...)` block and `__all__`, alphabetically after `queue_stats` in each.

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `python -m pytest tests/test_review_queue.py -v`
Expected: all pass, including the nine new ones. No pre-existing test in this file changes.

- [ ] **Step 6: Prove every new test can fail (review standard 14)**

Take a byte copy of `queue.py` first: `cp src/receipts/review/queue.py /tmp/queue.py.bak` (or the scratchpad). Apply each mutation **one at a time**, run, record the real output, restore from the copy, re-run green before the next one.

| # | Mutation (single variable) | Must turn red |
|---|---|---|
| 1 | delete `task.state = ReviewState.OPEN` | `…returns_a_claimed_task_to_the_queue`, `…claimable_by_a_different_reviewer`, `…returns_the_task_to_the_open_backlog` |
| 2 | delete `task.assigned_to = None` | `…clears_the_assignee_and_names_who_held_it` |
| 3 | change the `OPEN` early return to `raise ValueError("nope")` | `…is_idempotent_on_an_open_task` |
| 4 | delete the `if task.state is ReviewState.DONE:` block | `…refuses_a_closed_task` |
| 5 | move `task.assigned_to = None` **above** the `DONE` check | `…leaves_a_closed_tasks_assignee_intact` |
| 6 | delete the `if task is None:` block | `…rejects_an_unknown_id` |
| 7 | add `task.opened_at = datetime.now(UTC)` before the flush | `…leaves_priority_opened_at_and_reason_alone` |

Mutations 1 and 4 each kill more than one test — that is expected and fine; what matters is that **every** test has at least one mutation that kills it. If any mutation kills nothing, the test is not a pin: say so and fix it rather than reporting a green run. If a mutation's real failure differs from the prediction above, **record what actually happened** — do not adjust the claim to match.

- [ ] **Step 7: Fix the two falsified claims in this task's files**

These say the opposite of what now ships. **Rewrite, do not delete** — each explains why resume-before-claim was necessary, and that argument survives.

`src/receipts/review/queue.py:26` (module docstring) and `:241` (`next_task`'s docstring) both assert that nothing releases a claim. Replace each with wording that keeps the history and adds the distinction, e.g. for the module docstring's bullet:

```
  * :func:`next_task` **resumes before it claims** (ADR-0016): a caller who
    already holds an ``IN_PROGRESS`` task gets that one back. Resume is the
    holder's *own* recovery and needs no client call, which is why it, and not
    a release, is what makes a reload or a lost response survivable.
    :func:`release_task` is the separate, admin-only case (ADR-0025): work
    taken back from someone who is not coming back for it.
```

`tests/test_review_queue.py:481-484` carries the same claim as a comment above a test. Rewrite it the same way, keeping the sentence about what the test pins.

- [ ] **Step 8: Gates**

Run: `python -m pytest --junitxml=<scratch>/j.xml` and read the counts from the XML; `python -m ruff check .`
Expected: all pass, ruff clean, count is the previous total **+9**.

- [ ] **Step 9: Commit**

```bash
git add src/receipts/review/queue.py src/receipts/review/__init__.py tests/test_review_queue.py
git commit -m "feat(review): release_task returns a claimed task to the queue"
```

---

### Task 2: `POST /review/{task_id}/release`

**Files:**
- Modify: `src/receipts/review/api.py` (import at `:74`; route into `_install_write_routes` after the complete route ends at `:547`; docstring claim at `:492`)
- Test: `tests/test_api_write.py` (new tests after the complete block ending `:598`; docstring claim at `:520-524`)

**Interfaces:**
- Consumes: `release_task` from Task 1, imported as `from .queue import close_task, next_task, queue_stats, release_task`. Also existing `require_role`, `ROLE_ADMIN`, `SessionUser`, `_task_summary`, `logger`, `ReviewTask` — all already imported in `api.py`.
- Produces: `POST /review/{task_id}/release` → 200 `{**_task_summary(task), "released_from": str | None}`; 401 / 403 / 404 / 400 per the table below.

- [ ] **Step 1: Read the real code before writing anything**

Read `review_complete` (`api.py:520-547`) — the route this mirrors — and `review_next` (`:481-518`) for the "build the payload inside the `with`, commit, then return" idiom. Read `require_role` (`auth.py:126-133`). Confirm the exact 403 detail string at `api.py:543` before pinning it.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_api_write.py` after the complete-route tests. Confirm `import logging` and `from starlette.testclient import TestClient` (or equivalent) are already present at the top; add `logging` if absent.

```python
def test_an_admin_can_release_a_claimed_task(admin_client, session_factory, task_id):
    response = admin_client.post(f"/review/{task_id}/release")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "open"
    assert body["assigned_to"] is None
    # A sibling key, not a replacement: assigned_to says who holds it (nobody),
    # released_from says who held it.
    assert body["released_from"] == "alice"

    with session_factory() as session:
        stored = session.get(ReviewTask, task_id)
        assert stored.state.value == "open"
        assert stored.assigned_to is None


def test_a_reviewer_cannot_release_a_task(reviewer_client, task_id):
    response = reviewer_client.post(f"/review/{task_id}/release")

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "insufficient role"


def test_release_requires_authentication(app, task_id):
    response = TestClient(app).post(f"/review/{task_id}/release")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "authentication required"


def test_releasing_an_unknown_task_is_404(admin_client):
    """Not 400. ``release_task``'s own ValueError for an unknown id would render
    400 through the error handler, so the route keeps its own existence check --
    "no such task" and "that task cannot be released" are different answers.
    """
    missing = uuid.uuid4()

    response = admin_client.post(f"/review/{missing}/release")

    assert response.status_code == 404
    assert str(missing) in response.json()["error"]["message"]


def test_releasing_a_closed_task_is_400(admin_client, task_id):
    assert admin_client.post(f"/review/{task_id}/complete").status_code == 200

    response = admin_client.post(f"/review/{task_id}/release")

    assert response.status_code == 400
    assert str(task_id) in response.json()["error"]["message"]


def test_a_released_reviewer_gets_403_on_complete(admin_client, reviewer_client, task_id):
    """The milestone's headline claim: this is the exact 403 ADR-0024's terminal
    `taken` state was built for, produced by a real release rather than a
    hand-set fixture. Until this route shipped, that UI path was reachable only
    by tests that set ``assigned_to`` by hand.
    """
    assert admin_client.post(f"/review/{task_id}/release").status_code == 200

    response = reviewer_client.post(f"/review/{task_id}/complete")

    assert response.status_code == 403
    assert (
        response.json()["error"]["message"]
        == "only the assignee or an admin may complete this task"
    )


def test_the_release_is_logged_without_the_tasks_reason(
    admin_client, session_factory, task_id, caplog
):
    """``reason`` is built from exception text and is redacted only at
    ``enqueue_review``'s sink, so putting it in a log line would extend
    ADR-0022's egress inventory. Ids and usernames only.
    """
    with session_factory() as session:
        task = session.get(ReviewTask, task_id)
        task.reason = "SENTINEL-REASON-TEXT"
        session.commit()

    with caplog.at_level(logging.INFO, logger="receipts.review.api"):
        assert admin_client.post(f"/review/{task_id}/release").status_code == 200

    lines = [r.getMessage() for r in caplog.records if "released" in r.getMessage()]
    assert len(lines) == 1
    assert str(task_id) in lines[0]
    assert "alice" in lines[0]
    assert "bob" in lines[0]
    assert "SENTINEL-REASON-TEXT" not in lines[0]
```

- [ ] **Step 3: Run them to confirm they fail**

Run: `python -m pytest tests/test_api_write.py -k releas -v`

**The selector is `releas`, not `release`.** `-k release` does not match `test_releasing_…` — "releasing" does not contain the substring "release" — so it silently collects 5 of the 7 new tests and reports green on a partial run. Measured during Task 1, where `-k release` collected 8 of 9. Confirm the count you get matches the count you wrote.

Expected: 404 on every route call (Starlette's own "Not Found" for an unmatched path), so the assertions on status and body fail. `test_releasing_an_unknown_task_is_404` **passes vacuously** at this point — an unmatched route is also a 404. That is a real vacuity, disclosed rather than hidden; Step 6's mutation 4 is what actually earns that test its keep.

- [ ] **Step 4: Implement the route**

Change `api.py:74` to `from .queue import close_task, next_task, queue_stats, release_task`. Then add this immediately after `review_complete` in `_install_write_routes`:

```python
    @app.post("/review/{task_id}/release")
    def review_release(
        task_id: uuid.UUID,
        request: Request,
        admin: Annotated[SessionUser, Depends(require_role(ROLE_ADMIN))],
    ) -> dict[str, Any]:
        """Return a claimed task to the queue. Admin only (ADR-0025).

        The inverse of a claim, and the case ``GET /review/next``'s resume
        cannot cover: resume hands back *the holder's own* task, so a task held
        by someone who has stopped polling stays out of the queue forever.
        ADR-0016 named that gap and left closing it as a policy decision; this
        is it. Resume is unchanged.

        ``{task_id}`` is a **review task** id, not a receipt id -- the same
        convention as ``POST /review/{task_id}/complete``.

        Authorization is declarative rather than in-body. ``/complete`` checks
        inside its body only because *assignee-or-admin* needs the task row
        first; this is a pure role test, so it belongs in the dependency, where
        it is enforced before the body runs.

        The unknown-task 404 is raised here rather than left to
        :func:`release_task`'s ``ValueError``, which the handler renders as
        400. A *closed* task does come back as 400 through that handler, and
        the split is the point: "no such task" and "that task cannot be
        released" are different answers.

        ``released_from`` sits beside ``assigned_to`` rather than replacing it:
        ``assigned_to`` is now ``null`` -- who holds it, nobody -- and
        ``released_from`` says who held it. On an already-open task it is
        ``null`` too, so an admin can tell a real release from a no-op.
        """
        with request.app.state.session_factory() as session:
            task = session.get(ReviewTask, task_id)
            if task is None:
                raise HTTPException(status_code=404, detail=f"no review task with id {task_id}")
            task, released_from = release_task(session, task_id)
            payload = {**_task_summary(task), "released_from": released_from}
            session.commit()

        # Logged here rather than in release_task for two reasons: only the
        # route knows who acted, and queue.py imports no logger at all. Emitted
        # after the commit, so a rolled-back release is never announced as one.
        # The task's `reason` is deliberately absent -- see ADR-0022.
        logger.info(
            "review task %s released from %s by admin %s",
            task_id,
            released_from,
            admin.username,
        )
        return payload
```

Note the payload is built **inside** the `with` block, before `session.commit()`, exactly as `review_next` does. Reading `task`'s attributes after the session closes would raise `DetachedInstanceError`.

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `python -m pytest tests/test_api_write.py -v`
Expected: all pass. No pre-existing test in this file changes.

- [ ] **Step 6: Prove every new test can fail**

Byte copy of `api.py` first. One mutation at a time; restore and re-run green between each.

| # | Mutation (single variable) | Must turn red |
|---|---|---|
| 1 | drop `"released_from": released_from` from the payload | `…admin_can_release_a_claimed_task` |
| 2 | `require_role(ROLE_ADMIN)` → `require_user` | `…reviewer_cannot_release_a_task` |
| 3 | delete the `admin: Annotated[...]` parameter entirely | `…release_requires_authentication` |
| 4 | delete the route's `if task is None: raise HTTPException(404…)` | `…releasing_an_unknown_task_is_404` (now 400 — this is what makes that test non-vacuous) |
| 5 | in `queue.py`, delete the `DONE` guard | `…releasing_a_closed_task_is_400` |
| 6 | in `queue.py`, delete `task.assigned_to = None` | `…released_reviewer_gets_403_on_complete` (complete returns 200) |
| 7 | add `task.reason` as a fourth `logger.info` argument and `%s` to the format | `…logged_without_the_tasks_reason` |

**Mutations 5 and 6 are in `queue.py`, which Task 1 committed.** Per ADR-0023's second dated note, take a **fresh** byte copy of `queue.py` now — a copy taken before Task 1's commit would restore the file to its pre-commit state and silently revert the committed function. Prove each restore with `git diff --stat -- src/receipts/review/queue.py` returning empty.

**Two mechanical traps, both measured during Task 1:**

- **The working tree is CRLF.** A mutation applied by a script whose pattern is anchored on `\n` matches nothing and reports a false "mutation applied, tests still green" — which reads exactly like a surviving mutant. Edit the file directly, or anchor on `\r\n`, and always confirm the mutation landed (`git diff --stat` non-empty) *before* believing a green run.
- **Anchor mutations on a unique string.** `if task is None:` appears in both `close_task` and `release_task`; `assigned_to = None` appears at `queue.py:228` as `existing.assigned_to = None` and at `:391` as `task.assigned_to = None`. Include enough surrounding context that the edit can only land in the function you mean.

- [ ] **Step 7: Fix the two falsified claims in this task's files**

`src/receipts/review/api.py:492` — inside `review_next`'s docstring, "nothing else in this service releases a claim -- `POST /review/{id}/complete` closes a task, which is not the same thing". Rewrite to keep why resume matters and name the new route as the separate admin case.

`tests/test_api_write.py:520-524` — the same claim in a test docstring. Rewrite the same way, keeping what the test pins.

Also add a short comment beside the new tests recording **why the release route is not a row in `tests/test_api_read.py`'s `READ_ROUTES` matrix**, since that file already documents the analogous exclusion for `/complete` and a reviewer will otherwise ask: `test_auth_matrix` builds its URL with `path.format(id=receipt_id)` and asserts 200 for an allowed actor, but this route's path parameter is a **task** id — a receipt id substituted there is a legitimate 404, so the matrix's shape cannot express it. **Do not modify `tests/test_api_read.py`** (it belongs to no task here).

- [ ] **Step 8: Gates**

Run: `python scripts/verify.py`
Expected: all five PASS. pytest count is Task 1's total **+7**.

**Then the outside-repo import check.** This is the first `src/` change since before the review-UI error-recovery milestone, so a green suite is not sufficient evidence. From a directory **outside** the repository:

```bash
cd /c/Users && python -c "from receipts.review.api import create_app; import receipts.review as r; print(r.release_task); print(r.__all__)"
```

Expected: no `ImportError`; the function object prints; `__all__` has **seven** entries. This exact command was run against `main` before this plan was written and succeeded, printing the six pre-release exports — so a failure here is your change, not the environment. If the interpreter cannot see the package from outside the repo, report that rather than working around it: it is exactly the failure this check exists to catch.

- [ ] **Step 9: Commit**

```bash
git add src/receipts/review/api.py tests/test_api_write.py
git commit -m "feat(api): POST /review/{task_id}/release, admin-only"
```

---

### Task 3: The spec update and the ADRs

**Files:**
- Modify: `RECEIPT_SYSTEM_SPEC.md` §14.9 (the code block at `:1435-1462` and the paragraph beneath it)
- Create: `docs/adr/0025-admin-release-for-a-claimed-task.md`
- Modify: `docs/adr/0016-review-next-resumes-the-callers-task.md` (append a dated note), `docs/adr/0015-review-ui-same-origin-and-app-prefix.md` (append a dated note), `docs/adr/README.md` (index row)

**Interfaces:**
- Consumes: the shipped behaviour from Tasks 1 and 2. Read both commits before writing — the ADR records what shipped, not what was planned.
- Produces: nothing code-facing.

- [ ] **Step 1: Update the build spec**

`RECEIPT_SYSTEM_SPEC.md` §14.9 is updated in place; that is this repo's convention for the build spec (precedent: `a5bf75d` "absorb the P4.T3 spec drift", `19e1f97` "update spec 14.10 to the CLI as implemented"). Add to the `queue.py` block:

```
def release_task(task_id: UUID) -> tuple[ReviewTask, str | None]
```

and to the routes block, directly after the `/complete` line:

```
POST   /review/{id}/release       -> {id} is the TASK id; admin only
```

Then fix the paragraph beneath the block, which currently ends "`/export/xlsx` requires `admin`". It must now name both admin-only routes. Adding a row changes every sentence that quantifies over the table (review standard 12).

- [ ] **Step 2: Write ADR-0025**

`docs/adr/0025-admin-release-for-a-claimed-task.md`, following the house shape (Status / Builds on / Context / Decision / Consequences / References). It must record:

- **Status:** Accepted (2026-08-04). **Supersedes, in part:** ADR-0016's Context claim that no route releases or unclaims.
- **Context:** the one-way door, and ADR-0016's own deferral quoted verbatim — "doing so is a policy decision, not a bug fix". State plainly that resume-before-claim is unchanged and that this does not reopen ADR-0016's rejection of a release-on-unload.
- **The measured fact behind the `DONE` refusal:** `close_task` leaves `assigned_to` set; no `Receipt` column names a reviewer; a `corrections` row exists only for a field that actually changed.
- **The five rulings:** admin-only; `OPEN` idempotent and `DONE` refused; audit is a log line plus a response echo, with the limit stated (the log is the only durable trace and logs are not the database); API-only this milestone; the re-claim residual accepted.
- **The residual, with its reachability condition:** because `opened_at` and `priority` are preserved, a *still-polling* displaced reviewer can re-claim the same task on her next `GET /review/next`. Against the case this exists for — someone who stopped polling — it never arises. Closing it needs a new column and a claim-time policy.
- **The deliberate non-change:** `PATCH /receipts/{id}` stays claim-unaware, because ADR-0024 §3's contract is built on the PATCH landing and only the close failing.
- **Consequence:** ADR-0024's terminal `taken` state now has a live producer.
- **References:** ADR-0016, 0008, 0006, 0012, 0022, 0024; the design doc; `queue.py`, `api.py`, and both test modules.

- [ ] **Step 3: Append the dated notes**

ADRs are immutable once Accepted — **append a dated note, never edit the body.**

On **ADR-0016**, one note covering three things: its Context bullet at `:25` ("None of the eleven routes in `review/api.py` releases or unclaims") is superseded by ADR-0025; the count is now twelve; and the Consequence at `:137` that a task under a no-longer-polling username "stays stranded" is narrowed — an admin can now recover it. **The note must say explicitly that the resume decision itself is unchanged**, or a reader will conclude the release replaced it.

On **ADR-0015**, a one-line dated note: `:7`'s "eleven routes" is now twelve. Count only; nothing else in that ADR moves.

- [ ] **Step 4: Index the new ADR**

Add the row to `docs/adr/README.md`'s table:

```
| [0025](0025-admin-release-for-a-claimed-task.md) | Admin release for a claimed review task | Accepted |
```

- [ ] **Step 5: Verify the sweep is complete**

Run: `git grep -n "releases a claim\|release a claim\|unclaims\|no route releases" -- src tests docs`
Expected: every remaining hit is either a rewritten sentence that now names `release_task`, or ADR-0016's original line (immutable, now covered by its dated note). No live claim that nothing releases a claim survives in `src/` or `tests/`.

Run: `git grep -n "eleven routes" -- src tests docs *.md`
Expected: only `docs/superpowers/plans/2026-07-28-review-api.md:66` and `docs/superpowers/specs/2026-07-29-review-ui-design.md:11` — past-milestone artefacts, true when written, deliberately untouched. `docs/MEMORY.md:396` is handled at the session-end handoff refresh, not here.

- [ ] **Step 6: Gates**

Run: `python scripts/verify.py`
Expected: all five PASS, unchanged counts (this task touches no code).

- [ ] **Step 7: Commit**

```bash
git add RECEIPT_SYSTEM_SPEC.md docs/adr/0025-admin-release-for-a-claimed-task.md docs/adr/0016-review-next-resumes-the-callers-task.md docs/adr/0015-review-ui-same-origin-and-app-prefix.md docs/adr/README.md
git commit -m "docs(adr): ADR-0025, the admin release for a claimed task"
```

---

## Self-Review

**Spec coverage.** §1 context → Task 3's ADR. §2's five rulings → Tasks 1, 2 (rulings 1-3), Task 3 (all five recorded). §3 `release_task` → Task 1. §4 the route → Task 2. §5 concurrency → no code (no locking clause is the decision); the `queue_stats` claim is pinned by Task 1's last test. §6 what must not change → Global Constraints, plus Task 3's ADR. §7 residuals → Task 3 Step 2. §8 the prose sweep → Task 1 Step 7, Task 2 Step 7, Task 3 Steps 1-5. §9 tests → Tasks 1-2. §10 verification → Task 2 Step 8 (including the outside-repo check) and Task 3 Step 6. §11 ADRs → Task 3. §12 probes → all six were run before this plan was written; their answers are baked into the tasks (notably: `admin_client` is bob/`ROLE_ADMIN`, `reviewer_client` is alice/`ROLE_REVIEWER`, `task_id` claims as alice, `_task_summary` has exactly two callers, and the `READ_ROUTES` exclusion in Task 2 Step 7). **No gap.**

**Placeholder scan.** No TBD/TODO. Every code step carries runnable code. No "similar to Task N".

**Type consistency.** `release_task(session, task_id) -> tuple[ReviewTask, str | None]` is spelled identically in Task 1's Interfaces, its implementation, Task 2's Interfaces, the route body, and the spec block in Task 3. The tuple is unpacked as `(task, released_from)` at the one call site and `(released, previously_assigned_to)` in tests — different local names, same shape, deliberate.

**One vacuity disclosed rather than hidden:** `test_releasing_an_unknown_task_is_404` passes before the route exists, because an unmatched path is also a 404. Task 2 Step 3 says so, and Step 6's mutation 4 is what earns the test its keep.
