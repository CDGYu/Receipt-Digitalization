# The admin UI's two backend routes: `GET /auth/me` and `GET /review/tasks`

**Status:** design, approved 2026-08-05
**Branch:** `feat/admin-ui-routes` (off `main@7aa0a22`)
**Milestone:** the admin UI, part 1 of 2 — the backend contracts
**Decides:** ADR-0026 (new)

Two read routes that do not exist, both of which the admin UI needs before any
frontend work can start:

- **`GET /auth/me`** — the frontend cannot learn a role after a reload.
- **`GET /review/tasks`** — nothing lists review tasks, so an admin has no way
  to find the task id that `POST /review/{task_id}/release` requires.

This is deliberately **backend-only**. The frontend's first role-awareness and
the new `/app` admin surface are the second half of this milestone and get their
own design — see §8.

Line numbers below were read off the tree at `7aa0a22`. They drift; **the symbol
names are the durable half.** The previous milestone's design makes the same
caveat and has already been overtaken by it: its §1.1 states `assigned_to` is
written in "exactly two places", which was true at `c3a268c` and is now four.

---

## 1. Context, measured

### 1.1 What exists today

Thirteen routes, all declared in `review/api.py` except the two auth ones
(`review/auth.py`):

```
GET   /health                        POST  /upload
GET   /receipts                      PATCH /receipts/{receipt_id}
GET   /receipts/{receipt_id}         GET   /receipts/{receipt_id}/image
GET   /metrics                       GET   /receipts/{receipt_id}/image/blob
GET   /review/next                   POST  /review/{task_id}/complete
GET   /export/xlsx                   POST  /review/{task_id}/release
POST  /auth/login                    POST  /auth/logout
```

There is **no `GET /review/{task_id}`**, which matters for §3.1's path choice.

`git grep "select(Correction)" -- src` returns nothing, and `create_app` has no
caller under `src/` — both are separate Phase 5 follow-ups, out of scope here.

### 1.2 What the frontend actually holds

`session.ts:21` is the whole of the frontend's identity state:

```ts
let signedIn = window.location.pathname !== '/app/login'
```

Two facts follow. It has **no role** — so a `/app` admin surface cannot decide
what to render. And its signed-in flag is a **guess**, corrected only by a
rejected request; the module docstring says so explicitly ("the session cookie
is server state the page cannot read, so the only way to learn otherwise is a
rejected request").

`LoginPage.tsx:15` calls `await request('/auth/login', …)` and **discards the
response body** — which already contains the role.

### 1.3 The payload already exists

`auth.py:178`, the last line of the login handler:

```python
return {"username": user.username, "role": user.role}
```

`GET /auth/me` is therefore not a new shape. It is the **reload path** for a
shape the login route already produces, which makes "the two must agree" a real
and testable invariant rather than a nicety (§5).

### 1.4 `_current_user` already does the whole job

`auth.py:101` resolves the session cookie against the database and returns
`SessionUser | None`, re-reading `role` and `is_active` on **every** request so
a demotion or deactivation takes effect on the next request rather than at
cookie expiry (ADR-0012). `require_user` (`auth.py:119`) wraps it and raises
`401 "authentication required"`.

The route is a thin wrapper over existing, tested machinery — not new
authorization code.

### 1.5 `/metrics` is not a listing

`MetricsResponse` carries `counts_by_status`, `auto_approval_rate`, a
`QueueStatsOut` (`open`/`in_progress`/`done`/`total`/`by_priority`) and
`ThresholdsOut`. Counts, never rows. An admin reading `/metrics` learns that
four tasks are in progress and learns **nothing** about which four.

---

## 2. `GET /auth/me`

### 2.1 Contract

| | |
|---|---|
| signed in | `200 {"username": str, "role": str}` |
| no session | `401 {"error": {"message": "authentication required"}}` |
| machine `X-API-Key` | `401` — `require_user` never accepts the key |

Guarded by `require_user`. The handler body is one line.

### 2.2 Why 401 and not `200 {"user": null}`

**Decision: 401, reusing `require_user`.** Three reasons, in order of weight:

1. **No new authorization pattern.** A 200-with-null route must deliberately
   bypass `require_user`, in a codebase whose auth tests parametrize over
   guarded routes (`READ_ROUTES`, `tests/test_api_read.py:503`). The 401 form
   joins that table as a one-line row; the 200 form cannot.
2. **It corrects `session.ts:21`'s guess for free.** `client.ts:143-146` fires
   `unauthorizedHandler()` on *every* 401 before throwing, and `session.ts:47`
   wires that to `setSignedIn(false)`. A signed-out user deep-linking to
   `/app/` currently starts with `signedIn === true`; one `/auth/me` call
   corrects it with no new frontend logic.
3. **One "not authenticated" currency**, not two.

**Accepted cost, stated rather than dressed up:** an anonymous cold load
produces a 401 in the server log and the browser console. This is cosmetic. The
route is *not* exempted from the global 401 handler — an opt-out flag on
`request()` would add surface to the one module every call passes through, in
exchange for console tidiness.

### 2.3 Response typing

**Returns a bare `dict[str, str]`. No new Pydantic model.**

`POST /auth/login` already returns this shape untyped. Adding a `response_model`
to one and not the other is asymmetric, and the drift test in §5 is what
actually pins the two together — a declared model on one side would not.

There is a second, concrete reason. A `SessionUserOut` would live in
`schemas.py`, which Task 2 also edits; under ADR-0023 that makes Tasks 1 and 2
share a file for no gain. See §6.

### 2.4 Where it lives

`build_auth_router()` in `auth.py`, beside `/auth/login` and `/auth/logout`.
Not `api.py` — the auth router owns the `/auth/*` prefix.

---

## 3. `GET /review/tasks`

### 3.1 Path

`/review/tasks`. Collision-free at `7aa0a22`: the only `/review/{task_id}/…`
routes are POSTs, and there is no `GET /review/{task_id}`.

**Recorded hazard.** FastAPI matches routes in declaration order. If a
`GET /review/{task_id}` is ever added, it must be declared **after**
`/review/tasks`, or a request for the literal path binds `task_id="tasks"` and
fails UUID validation with a 422. A test pins the literal path against the
route table, so the ordering cannot silently invert.

### 3.2 Parameters

| param | type | default |
|---|---|---|
| `state` | `ReviewState \| None` | `None` (all states) |
| `limit` | `int` | `Query(50, ge=1, le=200)` |
| `offset` | `int` | `Query(0, ge=0)` |

Identical bounds to `GET /receipts`, deliberately: two list routes with
different page caps is a difference a caller has to remember for no reason.

**No `assigned_to` filter this milestone** (YAGNI). The stated need is "find a
task id to release"; `state=in_progress` plus a page of rows answers it.
Recorded as a follow-up in §9.

### 3.3 Ordering

`priority, opened_at, id` — byte-for-byte the order `_claim_stmt` uses
(`queue.py:90`). Three consequences, all wanted: the list reads as *the queue*
rather than a second opinion about it; `id` makes the order total, so paging is
stable on SQLite's whole-second `opened_at` resolution; and the first row of
`?state=open` is the row `GET /review/next` would hand out next.

### 3.4 Scope

| caller | rows |
|---|---|
| `admin` | every row |
| `reviewer` | `state == OPEN OR assigned_to == <caller>` |

A reviewer therefore sees the open backlog plus their own history in any state.
Why this leaks no names, and what pins that, is §4.

The route maps role to scope in one place, with no default that could fail
open — an unrecognised role must not reach `visible_to=None`:

```python
visible_to = None if user.role == ROLE_ADMIN else user.username
```

`ROLE_ADMIN` is `receipts.persist.users`'s constant (`users.py:42`), which
`api.py` already imports and uses at `:557` and `:624` — the route is guarded by
`require_user`, not `require_role`, because **both** roles are allowed through.

Both roles receive `200`; they differ only in which rows come back. That is
what makes this route unable to express its own rule in the `READ_ROUTES`
table (§5).

### 3.5 Response

```json
{"items": [ /* _task_summary(task) */ ], "has_more": false}
```

`_task_summary` (`api.py:273`) unchanged — the same shape `GET /review/next`,
`POST /review/{id}/complete` and `POST /review/{id}/release` already return:
`id`, `receipt_id`, `reason`, `priority`, `assigned_to`, `state`, `opened_at`,
`closed_at`.

**`reason` is safe to list.** `enqueue_review` redacts it at the sink
(`queue.py:183`, ADR-0022), so it is redacted at write time for every producer
present and future; and it is already visible to any reviewer through
`GET /review/next`. Listing it adds no egress surface. It is also the one
human-readable field explaining why a task exists, which is what an admin
deciding whether to release needs.

`has_more` comes from fetching `limit + 1` rows and reporting on the extra one,
the `GET /receipts` pattern (`api.py:182-185`) — not a `COUNT(*)` per page.

The envelope is typed: a `ReviewTaskListResponse` in `schemas.py` with
`items: list[dict[str, Any]]` and `has_more: bool`, used as the route's
`response_model`. This mirrors `ReceiptListResponse` exactly, including *why*
`items` stays `dict[str, Any]` — schemas.py's module docstring records the rule
that the envelope is typed in full while the payload's real shape is proven
against the serializer's own output, so the two cannot drift apart silently.
`schemas.py` is edited by Task 2 alone; §2.3 explains why `/auth/me`
deliberately does not join it.

**No receipt join.** Merchant name and total would let an admin see *what* they
are releasing without a second request, but a join makes this a new contract
rather than a reuse, and money must serialize as a string (ADR-0001). Recorded
as a follow-up in §9.

### 3.6 Where the query lives

A new function in `queue.py`, beside every other `ReviewTask` query:

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

`visible_to=None` means unrestricted — the admin case, explicit at the call
site rather than a bare `True`/`False`. `visible_to="alice"` applies §3.4's
reviewer scope.

ADR-0006 holds: explicit `Session` first, caller commits. It is a **pure read**,
so there is no flush and no `ValueError` boundary to cross — an invalid `state`
is rejected by FastAPI's enum validation and an out-of-range `limit` by
`Query`, both 422 before the function is reached.

### 3.7 One housekeeping consequence

`_task_summary` currently sits below `api.py`'s `# Write routes (P4.T5)` banner
(`api.py:268-273`). A read-route consumer makes that banner wrong. It moves to a
shared-helpers section above `_install_read_routes`, in the same task that adds
the consumer.

---

## 4. The invariant, and what actually needs pinning

### 4.1 The invariant

§3.4's reviewer scope leaks no names **only** because:

> **`state == OPEN` implies `assigned_to IS NULL`.**

Verified exhaustively at `7aa0a22`. Every write to either column repo-wide —
**five to `state`, three to `assigned_to`**, all eight in `queue.py`:

| site | transition | `assigned_to` |
|---|---|---|
| `:208` | new row → `OPEN` | never set → NULL |
| `:226` | reopen a `DONE` task → `OPEN` | `:228` sets `None` |
| `:306` | → `IN_PROGRESS` | `:305` sets the assignee |
| `:327` | → `DONE` | untouched — ADR-0025's whole point |
| `:403` | release → `OPEN` | `:402` sets `None` |

So a reviewer's rows are either `OPEN` (name is NULL) or their own (a name they
already know). No masking is required, and no defensive filtering.

**A grep for `assigned_to =` returns a fourth hit that is not a write.**
`queue.py:401` is `previously_assigned_to = task.assigned_to` — a *read*, on
the right-hand side, which `release_task` returns so the route can log who held
the task. Anyone re-verifying this table must count writes, not matches.

### 4.2 What is already pinned — cited, not rewritten

All three `OPEN`-producing paths are pinned per-path in the committed suite:

| producer | test | assertion |
|---|---|---|
| new task | `test_enqueue_review_creates_an_open_task` (`:144`) | `:154` |
| reopen | `test_enqueue_review_reopens_a_closed_task` (`:233`) | `:247` |
| release | `test_release_task_clears_the_assignee_and_names_who_held_it` (`:784`) | `:791`, `:797` |

**This milestone adds no queue-layer invariant tests.** They exist. Writing
duplicates would be a plan defect of the exact class this project keeps
catching: a claim about existing artefacts that nobody checked.

### 4.3 What is *not* pinned, and the new test that guards it

The **closure** is unpinned. A future fourth `OPEN`-producer that forgets to
clear `assigned_to` would silently widen every reviewer's view, and nothing
above would go red.

The new pin is therefore route-level, where the claim actually lives:

> **`test_the_reviewer_scope_never_returns_someone_elses_name`** — build tasks
> covering every state and assignment combination reachable through the public
> queue API (enqueue, claim as bob, release, close), call `GET /review/tasks`
> as `alice`, and assert every returned row's `assigned_to` is `None` or
> `"alice"`.

Red under a single-variable mutation: drop the scoping clause from `list_tasks`
and bob's `IN_PROGRESS` row appears. That mutation must be run and the failure
**read**, not just observed — review standard 15.

### 4.4 The limit, stated

This test catches a fourth producer **only if some test exercises it.** It
cannot guard a path nobody has written yet. The design claims exactly that much
and no more; ADR-0026 records the same limit, so a later reader does not mistake
"pinned" for "closed".

---

## 5. Testing

Every test below is named, and each is proven to fail with its own change
reverted (review standards 2 and 3 — each guarantee reverted **separately**).

**`GET /auth/me`**

1. a signed-in reviewer gets their own username and role
2. a signed-in admin gets `"admin"` — proves the role is read, not hard-coded
3. the `READ_ROUTES` matrix row: anonymous → 401, `api_key` → 401,
   reviewer → 200, admin → 200
4. **the drift pin** — the `POST /auth/login` response body equals the
   `GET /auth/me` body for the same user (§1.3)
5. a user deactivated *after* signing in gets 401 — proves `_current_user`'s
   live re-read is on this path and not bypassed

**`GET /review/tasks`**

6. an admin sees an `IN_PROGRESS` task assigned to someone else
7. a reviewer does **not** see another reviewer's `IN_PROGRESS` task
8. a reviewer sees their own `IN_PROGRESS` task
9. a reviewer sees `OPEN` tasks
10. **§4.3's property pin**
11. ordering matches `_claim_stmt` — priority first, then `opened_at`, then
    `id` as tiebreaker
12. `has_more` is true and false either side of a page boundary
13. `?state=` filters, and an unknown value is a 422
14. the literal path `/review/tasks` resolves to this route (§3.1's hazard)
15. the `READ_ROUTES` matrix row

**Both routes take a `READ_ROUTES` row (`{reviewer, admin}`).** The listing's
*scoping* cannot live in that table — precisely the reason the block comment at
`tests/test_api_read.py:534-541` excludes `POST /review/{id}/complete`: both
roles get 200, and a boolean-per-role table cannot express a difference in
which rows come back. Adding rows to that table also requires re-reading every
sentence around it that quantifies over it (review standard 12).

---

## 6. Tasks and dispatch lanes

Three tasks, the same shape as the admin release (queue/route, then route, then
spec + ADR):

| # | task | files |
|---|---|---|
| 1 | `GET /auth/me` | `auth.py`, `tests/test_auth.py`, `tests/test_api_read.py` |
| 2 | `GET /review/tasks` | `api.py`, `queue.py`, `schemas.py`, `tests/test_review_queue.py`, `tests/test_api_read.py` |
| 3 | spec §14.9 + ADR-0026 | `RECEIPT_SYSTEM_SPEC.md`, `docs/adr/0026-*.md`, `docs/adr/README.md` |

**Tasks 1 and 2 both touch `tests/test_api_read.py` and therefore run strictly
serially** (ADR-0023). Folding both `READ_ROUTES` rows into one task is *not*
the fix: it would assert a route that does not exist at that commit, which is
the failure the admin-release ledger recorded verbatim ("admin-only at the
route asserted three times about a route that does not exist at this commit").

Task 3 runs last: ADR-0026 cannot cite line numbers for code that is not yet
written, and the admin release's worst plan defect (#7) came from a Task 3
sweep expectation drafted before its own subjects existed.

---

## 7. ADR-0026

Three decisions are load-bearing enough to need a record:

1. **`GET /auth/me` answers 401, not `200 {"user": null}`** — with §2.2's
   reasoning and its accepted cost.
2. **`GET /review/tasks` gives equal access with role-dependent content** —
   both roles get 200; a reviewer sees the open backlog plus their own rows, an
   admin sees everything. This is a policy decision about who may see whose
   name, of the same kind ADR-0025 made for the release itself.
3. **The privacy property is derived from `OPEN ⟹ assigned_to IS NULL`**, with
   §4.2's existing pins cited and §4.4's closure limit stated.

**§14.9's prose needs a clause.** The sentence at `RECEIPT_SYSTEM_SPEC.md:1465`
— "`GET /export/xlsx` and `POST /review/{id}/release` are the routes that
require `admin`" — stays **true** after this milestone, because `/review/tasks`
does not require `admin`. But leaving it alone would let a reader conclude the
new route behaves identically for both roles. The paragraph has no category for
"equal access, role-dependent content", and gains one.

---

## 8. What this milestone does not do

The frontend half is a separate design: reading `/auth/me` on mount, widening
`session.ts` from one boolean to an identity, and a new `/app` admin surface
that lists tasks and drives `POST /review/{task_id}/release` from a browser.

It stays out because each of these routes is an API contract that deserves
settling before a screen is built on it, and because §9's follow-ups are
exactly the kind of thing a first consumer discovers.

**Nobody has viewed any of the review UI in a browser** (recorded at the
review-UI error-recovery close, still true). That is a live risk for the
frontend half and is called out here so the next design does not inherit it
silently.

---

## 9. Recorded follow-ups

- **An `assigned_to` filter** on `/review/tasks` — "show me everything Bob
  holds" is plausible, is not the stated need, and is admin-only if added.
- **Receipt identity on a task row** — merchant name and total, so an admin can
  see what they are releasing without a second request. A join, a new contract,
  and money as a string (ADR-0001).
- **A reviewer-facing queue screen** would be the first consumer of §3.4's
  reviewer scope; today only the admin flow consumes this route.

---

## 10. References

- **ADR-0006** repository conventions (explicit session, caller commits,
  `ValueError` boundary) · **ADR-0012** auth model, roles, the machine key ·
  **ADR-0015** same-origin and the `/app` prefix · **ADR-0016** resume before
  claim · **ADR-0022** failure-text egress (`reason` redacted at the sink) ·
  **ADR-0023** parallel task agents share one worktree · **ADR-0025** the admin
  release, and the `DONE`-refusal reasoning that makes `assigned_to` on a closed
  task load-bearing.
- `RECEIPT_SYSTEM_SPEC.md` §14.9 (the route table and the prose over it).
- `docs/superpowers/specs/2026-08-04-admin-release-design.md` — the milestone
  this one continues, and the source of §6's dispatch shape.
