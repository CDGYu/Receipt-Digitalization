# ADR 0026 — The admin UI's backend routes: whoami, and a scoped task listing

**Status:** Accepted (2026-08-05)
**Builds on:** ADR-0012 (the auth model — the session cookie carries a username
only, the role is re-read per request, and the machine key is not a user),
ADR-0015 (the SPA served same-origin under `/app`, whose reload is what decision
1 exists for), ADR-0006 (injected session, caller commits, the `ValueError`
boundary — `list_tasks` follows it as a pure read), ADR-0016 (resume before
claim, whose `assigned_to` match is why a reviewer's own rows are already theirs
to see), ADR-0022 (failure text is redacted at its *writer*, which is what makes
`reason` safe to list), ADR-0025 (the admin release — the policy decision
decision 2 extends, and the reason a closed task keeps its assignee).

## Context

The admin UI needs two routes that did not exist, and neither is a screen
decision: both are API contracts worth settling before anything renders against
them.

**The frontend cannot learn a role after a reload.** `session.ts`'s `signedIn`
initializer is the whole of its identity state, and it is a *guess* off the URL
path — the module's own docstring says the session cookie is server state the
page cannot read, so the only way to learn otherwise is a rejected request. It
holds no role at all, so an admin surface cannot decide what to render.
`POST /auth/login` has returned `{"username", "role"}` since session auth first
shipped (`d255750`); `LoginPage.tsx` `await`s that call and discards the body,
and nothing gets it back. `GET /auth/me` is therefore not a new shape — it is
the **reload path for a shape the login route already produces**, which makes
"the two agree" a real and testable invariant rather than a nicety.

**Nothing lists review tasks.** `GET /metrics` returns counts and never rows: an
admin reading it learns *how many* tasks are in progress and nothing about
*which*. `POST /review/{task_id}/release` (ADR-0025) shipped without any
way to discover the task id it requires, so the route has been drivable only by
someone who already had the id from elsewhere.

## Decision

### 1. `GET /auth/me` answers 401, not `200 {"user": null}`

The route lives in `build_auth_router()` beside `/auth/login` and `/auth/logout`
— the auth router owns the `/auth/*` prefix — and is guarded by `require_user`,
so an anonymous caller and the machine `X-API-Key` both get 401. Three reasons,
in order of weight:

1. **No new authorization pattern.** A 200-with-null route must deliberately
   *bypass* `require_user`, in a codebase whose auth tests parametrize over a
   table of guarded routes (`READ_ROUTES` in `tests/test_api_read.py`). The 401
   form joins that table as a one-line row — `("GET", "/auth/me", {"reviewer",
   "admin"})` — and `test_auth_matrix` then asserts anonymous → 401,
   `api_key` → 401, reviewer → 200, admin → 200 for free. The 200-with-null form
   could not take that row at all.
2. **It corrects the frontend's guess for free.** `client.ts` calls
   `unauthorizedHandler()` on *every* 401 before it throws, and `session.ts`
   wires that handler to `setSignedIn(false)`. A signed-out user deep-linking to
   `/app/` currently starts with `signedIn === true`; one `/auth/me` call on
   mount corrects it with **no new client logic**.
3. **One "not authenticated" currency**, not two. A second spelling of the same
   condition is a second thing every caller has to remember to check.

**The accepted cost, stated rather than dressed up:** an anonymous cold load
produces a 401 in the server log and in the browser console. That is cosmetic,
and the route is deliberately *not* exempted from the global 401 handler — an
opt-out flag on `request()` would add surface to the one module every call
passes through, in exchange for console tidiness.

**The response is a bare `dict[str, str]`; no Pydantic model.** `POST
/auth/login` already returns this shape untyped, and declaring a `response_model`
on one of the pair and not the other is asymmetric. What actually pins the two
together is `test_auth_me_returns_the_same_body_as_login`, which compares the two
response bodies for one account; a declared model on one side would not have.

### 2. `GET /review/tasks` gives equal access with role-dependent content

Both roles get 200. They differ only in which rows come back:

| caller | rows |
|---|---|
| `admin` | every row |
| `reviewer` | `state == OPEN` **or** `assigned_to == <caller>` |

A reviewer therefore sees the open backlog plus their own history in any state —
their own closed rows keep their name because `close_task` leaves `assigned_to`
set, which is exactly ADR-0025's point about that column being the only record
that a human looked at a receipt.

The route is guarded by `require_user`, **not** `require_role`, because both
roles are allowed through; the role is consumed once, in one place, with no
default that could fail open:

```python
visible_to = None if user.role == ROLE_ADMIN else user.username
```

An unrecognised role lands on `user.username`, the *narrow* branch — the failure
direction that shows a caller too little rather than too much.

**This is a policy decision about who may see whose name**, of the same kind
ADR-0025 made for the release itself, and not a permissions question that the
existing role machinery answers on its own.

**The route reuses `_task_summary` unchanged.** It is the same eight-field
summary `GET /review/next`, `POST /review/{id}/complete` and
`POST /review/{id}/release` already return; listing rows adds a caller, not a
shape. **`reason` is safe to list** for two independent reasons: `enqueue_review`
calls `redact_pan` on the incoming reason before storing it, so under ADR-0022
the column is redacted at the *sink* for every producer present and future; and
`GET /review/next` already hands `reason` to any reviewer inside its `task`
payload, so listing it adds no egress surface. It is also the one human-readable
field that explains why a task exists, which is what an admin deciding whether to
release actually needs.

**The consequence for the auth matrix, recorded because it looks like an
omission.** `READ_ROUTES` takes a row for this route, and that row is true as far
as it goes — both roles do get 200. What the table cannot say is that the two
roles get *different rows back*: its shape is one boolean per role, and this is a
difference in content, not in access. That is the same reason
`POST /review/{id}/complete` was excluded from it. The content half is pinned
behaviourally instead, by
`test_the_reviewer_scope_never_returns_someone_elses_name`,
`test_a_reviewer_sees_their_own_claimed_task` and
`test_an_admin_sees_a_task_assigned_to_someone_else` — one per half of the
reviewer scope, plus the admin's.

### 3. The privacy property is derived, not structural

The reviewer scope discloses no other reviewer's name **only** because of an
invariant that no schema constraint enforces:

> **`state == OPEN` implies `assigned_to IS NULL`.**

It holds because of what the writers do, not because anything forbids the
alternative. Measured across `src/`: `state` is written in exactly five places
and `assigned_to` in exactly three, all eight in `review/queue.py`, and only
three of the five produce an `OPEN` row.

| `OPEN`-producer | what it does with `assigned_to` |
|---|---|
| the brand-new row in `enqueue_review` | never set — NULL by omission |
| `enqueue_review`'s reopen branch | cleared in the same block |
| `release_task` | cleared, after handing the prior holder back |

The two remaining `state` writes go the other way and are why the invariant is
not vacuous: `next_task`'s claim sets `IN_PROGRESS` **and** the assignee in one
step, and `close_task` sets `DONE` and leaves `assigned_to` alone.

**Two near-misses, named because anyone re-deriving that count will hit them.**
`release_task`'s `previously_assigned_to = task.assigned_to` matches a grep for
`assigned_to =` and is a *read* on the right-hand side, not a fourth write; and
`list_review_tasks`' `state=state` matches a grep for `state=` and is a keyword
argument passed into `list_tasks`, a filter rather than a write. Count writes,
not matches.

**Each producer's name-clearing is already pinned per path**, in
`tests/test_review_queue.py`, and this milestone adds no queue-layer duplicates:

- `test_enqueue_review_creates_an_open_task` — asserts `state is OPEN` and
  `assigned_to is None` on the new row;
- `test_enqueue_review_reopens_a_closed_task` — asserts `state is OPEN` and
  `assigned_to is None` on the reopened row;
- `test_release_task_clears_the_assignee_and_names_who_held_it` — asserts
  `assigned_to is None`, twice: on the returned object and again on the row
  re-read in a fresh session.

**A precision that matters if this list is ever re-derived.** The third test pins
the clearing — the *consequent*, which is the half the invariant needs — but not
that release leaves the row `OPEN`; that half sits in
`test_releasing_returns_the_task_to_the_open_backlog`, which watches
`queue_stats().open` go from 0 to 1. The other two tests carry both halves
themselves. Anyone auditing this record should count what each test asserts, not
what its name suggests.

**The closure is what is not pinned, and the route-level test is the guard.**
A *fourth* `OPEN`-producer that forgot to clear `assigned_to` would silently
widen every reviewer's page, and none of the three tests above would go red —
each pins its own path and knows nothing about a path that does not exist yet.
So the new pin is at the route, where the claim actually lives:
`test_the_reviewer_scope_never_returns_someone_elses_name` builds rows covering
the reachable state/assignment combinations **through the public queue API**
(enqueue, claim as carol, close), reads `/review/tasks` as alice, and asserts
every returned row's `assigned_to` is `None` or `"alice"` — after first asserting
the page is non-empty, because a vacuously-passing privacy test is worse than
none.

**The limit, stated plainly: that test catches a fourth producer only if some
test exercises it.** It is a property assertion over whatever rows the suite
happens to create; it cannot guard a path nobody has written, and it does not
make the invariant structural. This record claims exactly that much and no more.
The class is **not** closed.

**One concrete way in, recorded so it is not rediscovered.** `ReviewTask.state`
carries `default=ReviewState.OPEN` at the column. Nothing under `src/` reaches
it — the sole `ReviewTask(...)` construction is inside `enqueue_review` and
passes `state` explicitly — so it is unreachable in production code today. But a
fixture or a future writer that constructs a `ReviewTask` with an `assigned_to`
and no `state` would produce an `OPEN` row carrying a name without touching any
of the three producers above. This is the same shape of caveat ADR-0025 records
for `reason`: **the guarantee belongs to the functions, not to the column.**

## What was considered and rejected

**A defensive filter — `state == OPEN AND assigned_to IS NULL` in the reviewer
branch.** It is one clause and it would make the page safe even if the invariant
broke. Rejected: if the invariant ever *did* break, that clause would make an
open task silently invisible to every reviewer — it would drop the row from the
backlog rather than expose the defect. A queue that quietly stops offering work
is a worse failure than a name a colleague could already see on
`GET /review/next`'s payload, and it would hide precisely the condition the
route-level pin exists to surface.

**Masking `assigned_to` per caller — blanking the field on rows that are not the
caller's.** Rejected on two counts. Under the invariant that code never
executes, so it would be untestable except by breaking the invariant on purpose
to reach it. And it would make `_task_summary` mean two different things across
the four routes that share it: `assigned_to` would be "who holds this task"
everywhere except one listing, where it would be "who holds this task, if we
think you should know". One serializer with one meaning is worth more than a
branch that never runs.

## Consequences

- **The route table grew by two, and no prose figure was written to replace the
  count.** ADR-0015's and ADR-0016's dated notes (2026-08-04) already generalised
  this: the route list in the source is the durable reference, not a number in
  prose. Both notes hold unchanged here — ADR-0016's Context bullet is about
  routes that "release or unclaim", and neither new route does. §14.9's
  paragraph gained a clause instead of a number: its "the routes that
  require `admin`" sentence stays **true**, because `/review/tasks` does not
  require `admin`, but on its own it would let a reader conclude the new route
  behaves identically for both roles. The paragraph had no category for "equal
  access, role-dependent content" and now has one.
- **`GET /auth/me` gives the frontend its first way to hold an identity rather
  than a boolean.** Nothing consumes it yet: widening `session.ts` and building
  the `/app` admin surface are the second half of this milestone and are
  deliberately out of scope here.
- **A fourth caller of `_task_summary`, and no new task payload.** The envelope
  is typed — `ReviewTaskListResponse` in `schemas.py`, mirroring
  `ReceiptListResponse` down to `items: list[dict[str, Any]]` and `has_more` —
  for the reason that module's docstring gives: redeclaring a task's fields would
  be a second place for the shape to drift from `_task_summary`, silently, until
  one field disagreed.
- **A routing hazard is now live and is pinned rather than remembered.** FastAPI
  matches in declaration order, so a future `GET /review/{task_id}` declared
  *before* `/review/tasks` would bind `task_id="tasks"` and fail UUID validation
  with a 422. `test_the_literal_tasks_path_is_not_captured_by_a_task_id_route`
  is what makes that inversion loud.
- **`has_more` comes off a `limit + 1` fetch, not a `COUNT(*)` per page** — the
  `GET /receipts` pattern — and the page bounds (`ge=1, le=200`, offset `ge=0`)
  are `GET /receipts`' bounds deliberately, so two list routes do not have two
  page caps a caller must remember apart.
- **Deferred, and recorded so they are not mistaken for oversights:** an
  `assigned_to` filter ("show me everything Bob holds" — plausible, not the
  stated need, admin-only if added); receipt identity on a task row (merchant and
  total, which would make this a join and a new contract, with money as a string
  per ADR-0001); and a reviewer-facing queue screen, which would be the first
  consumer of the reviewer scope — today only the admin flow reads this route.

## References

ADR-0012 (identity, roles, and the machine key that `/auth/me` refuses);
ADR-0015 (the `/app` SPA whose reload path decision 1 serves); ADR-0016 (resume
before claim, and the `assigned_to` match that scopes it per user); ADR-0006
(`list_tasks` as a pure read under the repository conventions); ADR-0022
(`reason` redacted at `enqueue_review`'s sink, which is why listing it adds no
egress); ADR-0025 (the admin release this listing exists to make drivable, and
the record that a closed task's `assigned_to` is load-bearing); ADR-0023 (why
the two routes shipped as strictly serial tasks — they share
`tests/test_api_read.py`).

`RECEIPT_SYSTEM_SPEC.md` §14.9 (the `review/` surface, the route table, and the
prose over it — updated with this milestone), §6.7 (`review_tasks`).

`docs/superpowers/specs/2026-08-05-admin-ui-backend-routes-design.md` — the full
design: §2 `/auth/me` and its typing, §3 `/review/tasks` (path, parameters,
ordering, scope, response), §4 the invariant and what actually needed pinning,
§9 the recorded follow-ups.

`src/receipts/review/auth.py` (`build_auth_router`, the `me` handler,
`require_user`); `src/receipts/review/api.py` (`list_review_tasks`,
`_task_summary`); `src/receipts/review/queue.py` (`list_tasks`, and the three
`OPEN`-producers: `enqueue_review`'s new-row and reopen branches, and
`release_task`); `src/receipts/review/schemas.py`
(`ReviewTaskListResponse`); `src/receipts/persist/models.py` (`ReviewTask`, and
the column default named in decision 3).

`tests/test_auth.py` (`test_auth_me_returns_the_caller_identity`,
`test_auth_me_reports_the_admin_role`,
`test_auth_me_returns_the_same_body_as_login`,
`test_auth_me_reflects_a_deactivation_on_the_next_request`);
`tests/test_api_read.py` (`READ_ROUTES` and `test_auth_matrix`, plus the scope
and paging pins — `test_the_reviewer_scope_never_returns_someone_elses_name`,
`test_a_reviewer_sees_their_own_claimed_task`,
`test_an_admin_sees_a_task_assigned_to_someone_else`,
`test_tasks_come_back_in_queue_order`,
`test_has_more_is_true_only_when_a_further_page_exists`,
`test_the_state_filter_narrows_and_rejects_an_unknown_value`,
`test_the_literal_tasks_path_is_not_captured_by_a_task_id_route`);
`tests/test_review_queue.py` (the per-path invariant pins cited in decision 3,
and `test_releasing_returns_the_task_to_the_open_backlog`).
