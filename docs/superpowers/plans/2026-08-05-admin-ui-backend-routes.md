# The Admin UI's Two Backend Routes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /auth/me` and `GET /review/tasks`, the two backend contracts the admin UI needs before any frontend work can start.

**Architecture:** Both are read routes over machinery that already exists. `/auth/me` is a one-line handler behind `require_user`, which already resolves the session cookie and re-reads role and `is_active` per request. `/review/tasks` adds one query function to `review/queue.py` and one route to `review/api.py`, reusing `_task_summary` and the `limit + 1` pagination pattern `GET /receipts` established.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.x ORM, pytest. Offline and Node-free; SQLite in tests.

**Design:** `docs/superpowers/specs/2026-08-05-admin-ui-backend-routes-design.md` (approved 2026-08-05). Read it before Task 1 — §4 in particular, which is the reasoning the tests encode.

## Global Constraints

- **ADR-0006** — every queue/repository function takes an explicit `Session` first and **the caller commits**. `list_tasks` is a pure read: no flush, no commit, no `ValueError`.
- **ADR-0012** — roles are `ROLE_REVIEWER` / `ROLE_ADMIN` from `receipts.persist.users`. The machine `X-API-Key` authorizes `POST /upload` and nothing else, and `require_user` never accepts it.
- **ADR-0022** — `reason` is already redacted at the sink by `enqueue_review`. Do not add redaction here and do not remove it there.
- **ADR-0023** — **Tasks 1 and 2 both modify `tests/test_api_read.py` and MUST run strictly serially.** Commit every green step. Never repair a peer's tree.
- **ADR-0025** — `close_task` deliberately leaves `assigned_to` set on a `DONE` task. That is load-bearing, not an oversight: do not "tidy" it.
- **Review standard 2/3** — every new test is proven to fail with its own change reverted, each guarantee reverted **separately**.
- **Review standard 15** — when a mutation kills a test, **read the failure**. If the assertion that failed is not the one the pin exists for, the mutation changed more than one thing.
- **The working tree is CRLF.** A script-applied patch anchored on `\n` matches nothing and still reports success. Confirm `git diff --stat` is non-empty before believing any mutation result.
- **`pytest -k` matches substrings, not words.** `-k list_tasks` will also select `test_list_tasks_*`; that is fine here, but never assume a selector's scope — check the collected count.
- Gates: `python scripts/verify.py` (all five). Lint is `python -m ruff check .`. `src/` changes here, so also run the entry point from outside the repo before the milestone closes.

---

## Task 1: `GET /auth/me`

**Files:**
- Modify: `src/receipts/review/auth.py` — add the route to `build_auth_router()`, widen its docstring, add two imports
- Modify: `tests/test_auth.py` — four new tests
- Modify: `tests/test_api_read.py` — one `READ_ROUTES` row

**Interfaces:**
- Consumes: `require_user` and `SessionUser` (`auth.py`), both unchanged.
- Produces: `GET /auth/me` → `200 {"username": str, "role": str}` | `401`. Task 3 documents it; nothing else in this plan depends on it.

**Context the implementer needs:** `tests/test_auth.py` builds a *probe app* (`_probe_app`, `:93`) that mounts the real `build_auth_router()`. Adding a route to that router means the probe app gets it automatically — no fixture change. The probe's existing `/probe/any` route (`:100-102`) already returns exactly the body this route returns; `/auth/me` promotes that probe into a real route.

- [ ] **Step 1: Write the four failing tests**

Append to `tests/test_auth.py` (after `test_a_deactivated_accounts_login_failure_matches_the_others`, keeping the file's existing section flow):

```python
def test_auth_me_returns_the_caller_identity(client):
    client.post("/auth/login", json={"username": "alice", "password": "pw-alice"})

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "role": ROLE_REVIEWER}


def test_auth_me_reports_the_admin_role(client):
    """Two accounts, not one: a handler that hardcoded ``"reviewer"`` would
    pass the test above and fail this one.
    """
    client.post("/auth/login", json={"username": "bob", "password": "pw-bob"})

    assert client.get("/auth/me").json() == {"username": "bob", "role": ROLE_ADMIN}


def test_auth_me_returns_the_same_body_as_login(client):
    """The drift pin. ``POST /auth/login`` has disclosed the role since P4.T3
    and ``/auth/me`` exists only because the frontend discards that body and a
    reload cannot get it back (design 1.3). If the two ever disagree, a
    reloaded page and a freshly signed-in page would render different roles
    for one account -- and the reloaded one would be the wrong half.
    """
    login = client.post("/auth/login", json={"username": "alice", "password": "pw-alice"})

    me = client.get("/auth/me")

    assert login.status_code == me.status_code == 200
    assert login.json() == me.json()


def test_auth_me_reflects_a_deactivation_on_the_next_request(client, session_factory):
    """``_current_user`` re-reads ``is_active`` from the database on every
    request, so a deactivated account's *live* session dies immediately rather
    than at cookie expiry (ADR-0012). This proves ``/auth/me`` sits on that
    path and does not answer from the cookie alone -- which is exactly the
    mistake a whoami route invites.
    """
    client.post("/auth/login", json={"username": "alice", "password": "pw-alice"})
    assert client.get("/auth/me").status_code == 200

    with session_factory() as session:
        deactivate(session, "alice")
        session.commit()

    assert client.get("/auth/me").status_code == 401
```

`ROLE_REVIEWER`, `ROLE_ADMIN` and `deactivate` are already imported at `tests/test_auth.py:52-58`. Add nothing to the import block.

- [ ] **Step 2: Run them and read the failures**

```
python -m pytest tests/test_auth.py -k auth_me -v
```

Expected: **4 failed**. All four fail on `404`, not on an assertion about the body — the route does not exist. Confirm the collected count is 4; `-k` matches substrings, so a stray match would inflate it.

- [ ] **Step 3: Add the two imports**

In `src/receipts/review/auth.py`, change:

```python
from typing import Callable
```

to:

```python
from typing import Annotated, Callable
```

and:

```python
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
```

to:

```python
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
```

`Annotated[T, Depends(...)]` rather than a `Depends(...)` default argument: the default-argument form is flake8-bugbear B008 and would need a per-file ignore. `tests/test_auth.py`'s module docstring records the same reasoning for the probe routes.

- [ ] **Step 4: Add the route**

In `build_auth_router()`, between the `login` and `logout` handlers:

```python
    @router.get("/auth/me")
    def me(user: Annotated[SessionUser, Depends(require_user)]) -> dict[str, str]:
        """Who the caller is -- the reload path for what login already returns.

        The session cookie carries the username only and the browser cannot
        read it, so after a reload a page knows it *has* a session but not
        whose. ``POST /auth/login`` has always returned this exact body; this
        route is what makes it reachable a second time.

        Guarded by :func:`require_user`, so an anonymous caller and the
        machine key both get 401 rather than a ``{"user": null}`` body. Two
        consequences, both wanted (ADR-0026): the route stays inside the guard
        every other authenticated route uses and joins ``READ_ROUTES``; and
        the frontend's global 401 handler already turns that 401 into "signed
        out" with no new client logic. The cost is a 401 in the log on every
        anonymous cold load, which is accepted and recorded.
        """
        return {"username": user.username, "role": user.role}
```

- [ ] **Step 5: Widen the router docstring**

`build_auth_router`'s docstring currently reads:

```python
    """``POST /auth/login`` and ``POST /auth/logout``."""
```

It now quantifies over three routes (review standard 12). Replace with:

```python
    """``POST /auth/login``, ``GET /auth/me`` and ``POST /auth/logout``."""
```

- [ ] **Step 6: Run the tests and verify they pass**

```
python -m pytest tests/test_auth.py -v
```

Expected: the whole module passes, 4 new tests included. Run the module, not just `-k auth_me` — the new route is mounted on the shared probe app and must not disturb the existing guard tests.

- [ ] **Step 7: Prove the pins can fail — two separate mutations**

One mutation cannot exercise all three role assertions, because the drift test
and the identity test both use **alice**, a reviewer. Hardcoding `"reviewer"`
makes login and `/auth/me` *agree*, so the drift test stays green. Run both,
separately (review standard 3 — revert each guarantee on its own):

**Mutation A** — return `{"username": user.username, "role": "reviewer"}`:

```
python -m pytest tests/test_auth.py -k auth_me -v
```

Predicted: `test_auth_me_reports_the_admin_role` red on its dict equality; the
other three green. This proves the role is read per-user rather than constant.

**Mutation B** — return `{"username": user.username}` (drop the key entirely):

```
python -m pytest tests/test_auth.py -k auth_me -v
```

Predicted: `test_auth_me_returns_the_caller_identity`,
`test_auth_me_reports_the_admin_role` and
`test_auth_me_returns_the_same_body_as_login` all red; the deactivation test
green. The drift test's red is the one that matters — it fails because
`login.json()` carries `role` and `me.json()` does not.

**These predictions are this plan author's and have been wrong before**
(recorded: 3 of 4 wrong in one task, 1 of 6 in another). Read every failure
reason. If a test goes red for a reason other than the one named above, the
mutation changed more than one thing and proves nothing (review standard 15).
Restore from a byte copy, never `git checkout --` (ADR-0023), and confirm
`git diff --stat` is empty before continuing.

- [ ] **Step 8: Add the `READ_ROUTES` row**

In `tests/test_api_read.py`, add to the `READ_ROUTES` list (`:503`):

```python
    ("GET", "/auth/me", {"reviewer", "admin"}),
```

This covers anonymous → 401 and `api_key` → 401 against the *real* app, which is why Task 1's own module does not repeat them.

- [ ] **Step 9: Run the matrix**

```
python -m pytest tests/test_api_read.py -k auth_matrix -v
```

Expected: PASS, with four more cases than before (one per actor).

- [ ] **Step 10: Gates and commit**

```
python -m ruff check .
python -m pytest -q
```

```bash
git add src/receipts/review/auth.py tests/test_auth.py tests/test_api_read.py
git commit -m "feat(api): add GET /auth/me so a reloaded page can learn its role"
```

---

## Task 2: `GET /review/tasks`

**Runs only after Task 1 is committed** — both tasks modify `tests/test_api_read.py` (ADR-0023).

**Files:**
- Modify: `src/receipts/review/queue.py` — add `list_tasks`, extend `__all__`, add the `or_` import
- Modify: `src/receipts/review/__init__.py` — re-export `list_tasks` (import block **and** `__all__`)
- Modify: `src/receipts/review/schemas.py` — add `ReviewTaskListResponse`, extend `__all__`
- Modify: `src/receipts/review/api.py` — add the route, move `_task_summary`, extend three imports
- Modify: `tests/test_review_queue.py` — seven queue-layer tests
- Modify: `tests/test_api_read.py` — six route tests and one `READ_ROUTES` row

**Interfaces:**
- Consumes: `_task_summary(task: ReviewTask) -> dict[str, Any]` (`api.py`), `_claimed`/`_task`/`_receipt` helpers (`tests/test_review_queue.py:761/119/91`), the `clients`/`reviewer_client`/`admin_client`/`session_factory` fixtures (`tests/test_api_read.py:232/212/217/155`).
- Produces:
  ```python
  def list_tasks(
      session: Session,
      *,
      visible_to: str | None = None,
      state: ReviewState | None = None,
      limit: int = 50,
      offset: int = 0,
  ) -> list[ReviewTask]:
  ```
  and `GET /review/tasks?state=&limit=&offset=` → `{"items": [...], "has_more": bool}`.

### Part A — the queue layer

- [ ] **Step 1: Write the seven failing queue tests**

Append to `tests/test_review_queue.py`, after the `release_task` section and before the `queue_stats` section:

```python
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
```

Note `_claimed(session, "ada")` internally creates its own task at priority 1 (`:761-766`), so the two-task assertions above are correct as written.

- [ ] **Step 2: Add the import that makes the re-export load-bearing**

In `tests/test_review_queue.py`, extend the **package-level** import (`:37-45`) — not `from receipts.review.queue import ...`:

```python
from receipts.review import (
    QueueStats,
    close_review_for_receipt,
    close_task,
    enqueue_review,
    list_tasks,
    next_task,
    queue_stats,
    release_task,
)
```

This is deliberate. `list_tasks` must appear in **two** `__all__` lists (`queue.py:46` and `review/__init__.py:24`) plus `__init__.py`'s import block. The admin-release close measured that deleting `release_task` from either `__all__` left the suite green — two surviving mutants. Importing from the package makes at least the `__init__.py` half load-bearing for this function from day one.

- [ ] **Step 3: Run them and read the failures**

```
python -m pytest tests/test_review_queue.py -v
```

Expected: **collection error** — `ImportError: cannot import name 'list_tasks' from 'receipts.review'`. That is a whole-module failure, not seven test failures; do not mistake it for something else.

- [ ] **Step 4: Implement `list_tasks`**

In `src/receipts/review/queue.py`, change the SQLAlchemy import:

```python
from sqlalchemy import Select, func, select
```

to:

```python
from sqlalchemy import Select, func, or_, select
```

Add `"list_tasks"` to `__all__` (it is alphabetically sorted — between `enqueue_review` and `next_task`).

Add the function after `release_task` and before `close_review_for_receipt`:

```python
def list_tasks(
    session: Session,
    *,
    visible_to: str | None = None,
    state: ReviewState | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ReviewTask]:
    """Review tasks in queue order, scoped to what ``visible_to`` may see.

    ``visible_to=None`` is unrestricted -- the admin case, spelled explicitly
    at the call site rather than as a bare boolean. A username scopes the
    result to ``state == OPEN`` plus that caller's own rows in any state, so a
    reviewer keeps their own history (``close_task`` leaves ``assigned_to``
    set -- ADR-0025) without seeing anyone else's.

    **That scope discloses no other reviewer's name**, because every path
    producing an ``OPEN`` row clears ``assigned_to``: it is written in exactly
    three places -- :func:`enqueue_review`'s reopen branch, :func:`next_task`'s
    claim, and :func:`release_task` -- and a brand-new row never sets it at
    all. Each of the three is pinned individually by
    ``test_enqueue_review_creates_an_open_task``,
    ``test_enqueue_review_reopens_a_closed_task`` and
    ``test_release_task_clears_the_assignee_and_names_who_held_it``. A **fourth**
    producer that forgot to clear it would widen this scope silently, which is
    what ``test_the_reviewer_scope_never_returns_someone_elses_name`` exists to
    catch -- and ADR-0026 records the limit of that guard: it catches such a
    producer only if some test exercises it.

    Ordered ``priority`` then ``opened_at`` then ``id``, the same total order
    :func:`_claim_stmt` uses, so the first row of a ``state=open`` page is the
    row :func:`next_task` would hand out next.

    A pure read: no flush, no commit, and no ``ValueError``. The route's own
    query validation rejects an unknown ``state`` and an out-of-range ``limit``
    before this is reached.
    """
    query = select(ReviewTask)
    if visible_to is not None:
        query = query.where(
            or_(
                ReviewTask.state == ReviewState.OPEN,
                ReviewTask.assigned_to == visible_to,
            )
        )
    if state is not None:
        query = query.where(ReviewTask.state == state)
    query = query.order_by(ReviewTask.priority, ReviewTask.opened_at, ReviewTask.id)
    return list(session.scalars(query.limit(limit).offset(offset)))
```

- [ ] **Step 5: Re-export it**

In `src/receipts/review/__init__.py`, add `list_tasks` to **both** the import block (`:14-22`) and `__all__` (`:24-32`), keeping both alphabetical.

- [ ] **Step 6: Run and verify**

```
python -m pytest tests/test_review_queue.py -v
```

Expected: PASS, including the seven new tests.

- [ ] **Step 7: Prove the scope pin fails**

Delete the whole `if visible_to is not None:` block, then:

```
python -m pytest tests/test_review_queue.py -v
```

Expected: `test_list_tasks_hides_another_users_claim_from_a_reviewer` goes red on the set equality — `held.id` is present. **Read the failure**: it must be the set assertion, not an error. Confirm `git diff --stat` is non-empty before trusting the result (the tree is CRLF). Restore from a byte copy, re-run, confirm green.

- [ ] **Step 8: Commit**

```bash
git add src/receipts/review/queue.py src/receipts/review/__init__.py tests/test_review_queue.py
git commit -m "feat(review): add list_tasks, the queue's first scoped read"
```

### Part B — the route

- [ ] **Step 9: Write the six failing route tests**

Append to `tests/test_api_read.py`. First the helper, then the tests:

```python
def _extra_tasks(session_factory) -> None:
    """Three more tasks so a scope has something to hide.

    Every row is produced through the **public queue API** -- enqueue, claim,
    close -- so the shapes are exactly the ones the system can actually reach,
    rather than hand-built rows that might not be.

    ``next_task`` resumes before it claims (ADR-0016), so carol's second call
    would return her first task unchanged; closing the first is what lets her
    hold one ``DONE`` row and one ``IN_PROGRESS`` row.
    """
    with session_factory() as session:
        for _ in range(3):
            extra_id = uuid.uuid4()
            session.add(
                Receipt(
                    id=extra_id,
                    status=ReceiptStatus.NEEDS_REVIEW,
                    confidence=Decimal("0.400"),
                    image_key=f"receipts/2026/08/{extra_id}/original.jpg",
                    image_phash="",
                )
            )
            session.flush()
            enqueue_review(session, extra_id, reason="needs_review", priority=2)

        first = next_task(session, "carol")
        assert first is not None
        close_task(session, first.id)
        second = next_task(session, "carol")
        assert second is not None
        session.commit()


def test_the_reviewer_scope_never_returns_someone_elses_name(session_factory, reviewer_client):
    """The privacy pin for ADR-0026's dual scope.

    A reviewer's page may contain only rows whose ``assigned_to`` is NULL or
    their own. That holds because every path producing an ``OPEN`` row clears
    ``assigned_to`` -- pinned per-path in ``tests/test_review_queue.py`` -- and
    this asserts the property the *route* actually claims, which is where a
    fourth ``OPEN``-producer would show up.

    Goes red if ``list_tasks`` stops scoping: carol's ``IN_PROGRESS`` row
    arrives with her name on it.
    """
    _extra_tasks(session_factory)

    body = reviewer_client.get("/review/tasks?limit=200").json()

    # Not decoration: without rows this assertion set is vacuous, and a
    # vacuously-passing privacy test is worse than none.
    assert body["items"]
    assert {row["assigned_to"] for row in body["items"]} <= {None, "alice"}


def test_an_admin_sees_a_task_assigned_to_someone_else(session_factory, admin_client):
    """The other half of the scope: an admin needs the holder's name, because
    that is who they are taking the task away from (ADR-0025).
    """
    _extra_tasks(session_factory)

    body = admin_client.get("/review/tasks?limit=200").json()

    assert any(row["assigned_to"] == "carol" for row in body["items"])


def test_tasks_come_back_in_queue_order(session_factory, admin_client):
    """Lower priority number first -- the same total order ``_claim_stmt``
    uses. The seeded ``RECEIPT_B`` task is priority 1 and ``_extra_tasks``
    adds priority 2s, so the seeded one must lead.
    """
    _extra_tasks(session_factory)

    items = admin_client.get("/review/tasks?limit=200").json()["items"]

    priorities = [row["priority"] for row in items]
    assert priorities == sorted(priorities)
    assert priorities[0] == 1


def test_has_more_is_true_only_when_a_further_page_exists(session_factory, admin_client):
    """Read off a ``limit + 1`` fetch, like ``GET /receipts`` -- never a
    ``COUNT(*)`` per page. Four tasks total: the seeded one plus three.
    """
    _extra_tasks(session_factory)

    first = admin_client.get("/review/tasks?limit=2").json()
    rest = admin_client.get("/review/tasks?limit=2&offset=2").json()

    assert len(first["items"]) == 2
    assert first["has_more"] is True
    assert len(rest["items"]) == 2
    assert rest["has_more"] is False


def test_the_state_filter_narrows_and_rejects_an_unknown_value(session_factory, admin_client):
    _extra_tasks(session_factory)

    in_progress = admin_client.get("/review/tasks?state=in_progress").json()

    assert in_progress["items"]
    assert {row["state"] for row in in_progress["items"]} == {"in_progress"}
    assert admin_client.get("/review/tasks?state=nonsense").status_code == 422


def test_the_literal_tasks_path_is_not_captured_by_a_task_id_route(admin_client):
    """``/review/tasks`` must never be matched as ``/review/{task_id}``.
    FastAPI matches in declaration order, so a future ``GET /review/{task_id}``
    declared *before* this route would bind ``task_id="tasks"`` and fail UUID
    validation with a 422. No such route exists today; this asserts the
    outcome rather than the absence, so it keeps guarding if one is added.
    """
    assert admin_client.get("/review/tasks").status_code == 200
```

Extend `tests/test_api_read.py`'s queue import (`:47`):

```python
from receipts.review.queue import close_task, enqueue_review, next_task  # noqa: E402
```

- [ ] **Step 10: Run them and read the failures**

Run the **whole module**, not a `-k` selector. A selector is the trap here:
`-k tasks` does **not** match `test_an_admin_sees_a_task_assigned_to_someone_else`
(the name contains `a_task`, not `tasks`), so it would silently collect 5 of the
6 and the missing one would look like it passed. This project has already been
bitten by exactly that — `-k release` collecting 8 of 9.

```
python -m pytest tests/test_api_read.py -v
```

Expected: **6 failed**, everything else green. Every failure traces to the route
returning 404 — `test_the_state_filter_...` fails on `in_progress["items"]`
raising `KeyError` because the error body has no `items` key, which is still the
route's absence. Confirm each rather than assuming; count the failures.

- [ ] **Step 11: Add the response envelope**

In `src/receipts/review/schemas.py`, add `"ReviewTaskListResponse"` to `__all__` (alphabetically, after `ReceiptListResponse`) and the class after `ReceiptListResponse`:

```python
class ReviewTaskListResponse(BaseModel):
    """One page of ``_task_summary`` rows (``GET /review/tasks``).

    Same envelope-typed / payload-untyped split as
    :class:`ReceiptListResponse`, for the reason the module docstring gives:
    redeclaring a task's fields here would be a second place for the shape to
    drift from ``_task_summary``, silently, until one field disagreed.
    ``has_more`` is read off the extra row a ``limit + 1`` fetch returns.
    """

    items: list[dict[str, Any]]
    has_more: bool
```

- [ ] **Step 12: Move `_task_summary` above the read routes**

`_task_summary` currently sits under `api.py`'s `# Write routes (P4.T5)` banner. A read route now consumes it, so that banner is wrong. Move the function (unchanged) to just above `_install_read_routes`, under a new banner:

```python
# --------------------------------------------------------------------------- #
# Shared serialization helpers
# --------------------------------------------------------------------------- #
```

Move only `_task_summary`. Leave `_image_key_for` where it is — it has no read-route consumer.

- [ ] **Step 13: Extend the three imports**

In `src/receipts/review/api.py`:

```python
from ..persist.models import Receipt, ReviewState, ReviewTask
```

```python
from .queue import close_task, list_tasks, next_task, queue_stats, release_task
```

```python
from .schemas import (
    CorrectionPatch,
    ErrorBody,
    ErrorDetail,
    HealthStatus,
    MetricsResponse,
    ReceiptListResponse,
    ReviewTaskListResponse,
)
```

`ROLE_ADMIN` is already imported (`:62`) and `Query` already imported (`:43`). Add neither.

- [ ] **Step 14: Add the route**

At the end of `_install_read_routes`, after the `metrics` handler:

```python
    @app.get("/review/tasks", response_model=ReviewTaskListResponse)
    def list_review_tasks(
        request: Request,
        user: Annotated[SessionUser, Depends(require_user)],
        state: ReviewState | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> Any:
        """The review queue as rows, so an admin can find a task id (§14.9).

        Guarded by ``require_user``, **not** ``require_role``: both roles reach
        this route and differ only in which rows come back -- an admin sees
        every task, a reviewer sees the open backlog plus their own (ADR-0026).
        That is exactly why this route cannot express its own rule in
        ``test_api_read.py``'s ``READ_ROUTES`` table, for the same reason
        ``POST /review/{id}/complete`` cannot: the table's shape is one boolean
        per role, and this difference is not one.

        Declared here rather than beside ``GET /review/next``, which lives with
        the write routes because claiming a task *writes*. This one does not.

        ``has_more`` comes off a ``limit + 1`` fetch, like ``GET /receipts``.
        """
        visible_to = None if user.role == ROLE_ADMIN else user.username
        with request.app.state.session_factory() as session:
            rows = list_tasks(
                session,
                visible_to=visible_to,
                state=state,
                limit=limit + 1,
                offset=offset,
            )
            items = [_task_summary(task) for task in rows[:limit]]
        return {"items": items, "has_more": len(rows) > limit}
```

- [ ] **Step 15: Run the route tests**

```
python -m pytest tests/test_api_read.py -v
```

Expected: the whole module passes, six new tests included.

- [ ] **Step 16: Prove the privacy pin fails at the route**

In `list_tasks`, change `visible_to is not None` to `visible_to is None`, then:

```
python -m pytest tests/test_api_read.py -k scope -v
```

Expected: `test_the_reviewer_scope_never_returns_someone_elses_name` red on the `<= {None, "alice"}` subset assertion, with `"carol"` in the set. **Read the failure** — a red on `assert body["items"]` instead would mean the mutation emptied the list, proving nothing about the scope. Confirm `git diff --stat` non-empty. Restore from a byte copy, re-run, confirm green.

- [ ] **Step 17: Add the `READ_ROUTES` row**

```python
    ("GET", "/review/tasks", {"reviewer", "admin"}),
```

Then re-read the block comment at `tests/test_api_read.py:527-541`. It explains which routes the table can and cannot express. This route is a **second** example of the "cannot" case that still takes a row (both roles 200, differing content), and the comment currently names only `POST /review/{id}/complete`. Add one sentence naming this route and why its row covers status codes only. Review standard 12: adding a row changes every sentence quantifying over the table.

- [ ] **Step 18: Gates and commit**

```
python -m ruff check .
python scripts/verify.py
```

```bash
git add src/receipts/review/api.py src/receipts/review/schemas.py tests/test_api_read.py
git commit -m "feat(api): add GET /review/tasks, the queue's first listing route"
```

---

## Task 3: Spec §14.9 and ADR-0026

**Runs last.** ADR-0026 cites symbols written in Tasks 1 and 2; drafting it earlier is how the admin release produced its worst plan defect (#7).

**Files:**
- Modify: `RECEIPT_SYSTEM_SPEC.md:1435-1468`
- Create: `docs/adr/0026-admin-ui-backend-routes.md`
- Modify: `docs/adr/README.md`

**Interfaces:**
- Consumes: everything Tasks 1 and 2 shipped. Read the code before writing about it — do not copy claims from this plan without checking them (every one of this project's 33 recorded plan defects across seven milestones was a controller claim about an artefact that nobody verified).

- [ ] **Step 1: Update the §14.9 function list**

In the `# queue.py` block, after `def release_task(...)`:

```python
def list_tasks(visible_to: str | None, state: ReviewState | None, limit: int, offset: int) -> list[ReviewTask]
```

- [ ] **Step 2: Update the §14.9 route table**

Add, keeping the block's existing alignment:

```
GET    /auth/me                   -> the caller's username and role
GET    /review/tasks              -> paginated list; scope depends on role
```

Place `/auth/me` directly after `POST /auth/login`, and `/review/tasks` directly before `GET /review/next`.

- [ ] **Step 3: Amend the prose that quantifies over the table**

The paragraph at `:1462-1468` currently ends:

> ...`GET /export/xlsx` and `POST /review/{id}/release` are the routes that require `admin`.

That sentence stays **true** — `/review/tasks` does not require `admin`. But left alone it lets a reader conclude the new route behaves identically for both roles. Add one sentence after it:

> `GET /review/tasks` is a third case: both roles reach it, and the role decides
> which rows come back — an admin sees every task, a reviewer sees the open
> backlog plus their own (ADR-0026).

- [ ] **Step 4: Write ADR-0026**

Create `docs/adr/0026-admin-ui-backend-routes.md`, following the house structure (`# ADR 0026 — …`, `**Status:** Accepted`, `## Context`, `## Decision`, `## Consequences`, `## References`). It must record these, and must not overclaim any of them:

1. **`GET /auth/me` answers 401, not `200 {"user": null}`.** Reasons in priority order: it stays inside `require_user` and joins `READ_ROUTES`, where a 200-with-null route could not; it corrects `session.ts`'s "signed in unless the URL says otherwise" guess through the existing global 401 handler with no new client logic; and it keeps one "not authenticated" currency. **The accepted cost is stated:** a 401 in the log and console on every anonymous cold load.

2. **`GET /review/tasks` gives equal access with role-dependent content.** Both roles get 200; a reviewer sees `state == OPEN` plus their own rows in any state, an admin sees everything. This is a policy decision about who may see whose name, of the same kind ADR-0025 made for the release itself. Record that the route reuses `_task_summary` unchanged, and that `reason` is safe to list because `enqueue_review` redacts it at the sink (ADR-0022) and `GET /review/next` already exposes it to reviewers.

3. **The privacy property is derived, not structural.** State the invariant — `state == OPEN` implies `assigned_to IS NULL` — and that it holds because the three `assigned_to` writes and the one row-creating path all clear or omit it. Cite the three existing per-path pins by name. **Then state the limit plainly:** the new route-level pin catches a fourth `OPEN`-producer only if some test exercises it, and cannot guard a path nobody has written. Do not write that the class is closed.

Also record what was **considered and rejected**, since both were live options: a defensive filter (`state == OPEN AND assigned_to IS NULL`), rejected because a broken invariant would then silently drop an open task from every reviewer's list; and masking `assigned_to` per caller, rejected because under the invariant that code never executes and it would make `_task_summary` mean two different things across four routes.

- [ ] **Step 5: Add the README row**

In `docs/adr/README.md`, add to the table:

```markdown
| [0026](0026-admin-ui-backend-routes.md) | The admin UI's backend routes: whoami, and a scoped task listing | Accepted |
```

Then check the prose below the table (`:35-40`), which names which ADRs to read before touching what. It quantifies over the list; decide whether 0026 belongs in it and say so either way rather than leaving it unconsidered.

- [ ] **Step 6: Verify every citation**

For each line number and symbol name in ADR-0026, run the command that confirms it. `git grep -n` for symbols; `sed -n` for line ranges. A citation nobody checked is the defect class this project has caught in all seven prior milestones.

- [ ] **Step 7: Gates and commit**

```
python scripts/verify.py
```

```bash
git add RECEIPT_SYSTEM_SPEC.md docs/adr/0026-admin-ui-backend-routes.md docs/adr/README.md
git commit -m "docs: record ADR-0026 and absorb the two routes into spec 14.9"
```

---

## Plan self-review

**Spec coverage.** Design §2 → Task 1. §3.1-3.7 → Task 2 Steps 4, 11-14. §4.2's cited pins → the `list_tasks` docstring (Step 4) and ADR-0026 (Task 3 Step 4.3). §4.3's route-level pin → Task 2 Step 9, proven red at Step 16. §5's fifteen tests → Task 1 Steps 1/8 (5) and Task 2 Steps 1/9/17 (10). §6's serialization → the ADR-0023 note in Global Constraints and Task 2's opening line. §7 → Task 3. §8 and §9 are deliberately out of scope and produce no task.

**Placeholder scan.** No TBD/TODO. Every code step carries the code. Task 3 Step 4 enumerates the ADR's required claims rather than its prose — deliberate, because the ADR must cite line numbers that do not exist until Tasks 1 and 2 land, and Step 6 makes verifying them a step.

**Type consistency.** `list_tasks`'s signature is identical in the Interfaces block, Task 2 Step 4, and the §14.9 entry. `visible_to` is `str | None` throughout; `_task_summary` is never re-typed. `ReviewTaskListResponse` matches `ReceiptListResponse`'s field names (`items`, `has_more`) exactly.

**Two defects this review found in the plan itself, both fixed above.** Recorded rather than quietly corrected, because both are the plan author's and both are recurring classes:

- Task 1 Step 7 originally predicted one mutation would turn **two** tests red. It would not: the drift test and the identity test both use alice, a reviewer, so hardcoding `"reviewer"` makes login and `/auth/me` agree and the drift test stays green. Now two separate mutations, one guarantee each.
- Task 2 Step 10 originally used `-k "tasks or scope or …"`, which does not match `test_an_admin_sees_a_task_assigned_to_someone_else` — the name contains `a_task`, not `tasks`. It would have collected 5 of 6 and the missing test would have looked green. Now runs the whole module.

**Two things this plan cannot promise.** Both are recorded here so nobody reports them as surprises:

- The `has_more` test at Task 2 Step 9 assumes the seeded database holds exactly one task before `_extra_tasks` runs. That is true at `7aa0a22` (`_seed` enqueues only `RECEIPT_B`, `tests/test_api_read.py:150`). If a future seed adds a second, that test's arithmetic breaks — and it will break loudly, on the count, not silently.
- Task 2 Step 17's edit to the `READ_ROUTES` block comment is a judgement call about prose. The reviewer should check the resulting sentence against the table rather than accept that it was touched.
