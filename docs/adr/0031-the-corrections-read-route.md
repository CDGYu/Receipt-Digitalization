# ADR 0031 — The corrections read route: who may see a receipt's attribution

**Status:** Accepted (2026-08-10)
**Builds on:** ADR-0025 (the admin release — `close_task` leaves `assigned_to`
set on a `DONE` task, which is what lets a reviewer read back what they just
did, and `release_task` clears it, which is what takes that back), ADR-0026
(the closest analogue: a scoped listing guarded by `require_user`,
`visible_to=None` spelled at the call site for the admin case, and a limit
stated rather than a class claimed closed), ADR-0027 decision 5 (*"`null` must
never look like `0`, and neither may look like 'empty'"* — the rule this route
applies one layer below the UI), ADR-0018 + ADR-0022 (PAN is masked at its
writer, which is the invariant this route reads through), ADR-0006 (pure read:
injected session, no flush, no commit, no `ValueError`), ADR-0012 (identity and
roles), ADR-0028 (claims about the tree are re-derived, not restated).

Derived 2026-08-10, against `feat/corrections-read-route`; `src/` has not moved
since `bc67c31`. **Re-derive rather than quote** (ADR-0028 rule 1).

## Context

`corrections` has been written since Phase 3 and read by nothing since.
Measured at the branch point: `git grep -nE 'select\(\s*Correction' e2ec316 --
src` returns **no matches**, and `git grep -noE '\bCorrection\b' e2ec316 -- src`
(minus `CorrectionPatch`) returns six mentions. **None of the six is a read**,
and one of them is not about this table at all:

| where | what it is |
|---|---|
| `persist/__init__.py` | the re-export import |
| `persist/__init__.py` | its `__all__` entry |
| `persist/models.py` | the class definition |
| `persist/repository.py` | the import |
| `persist/repository.py` | **a false positive** — the comment *"Recorded in ADR-0020's Correction (2026-08-02)"*, where "Correction" means a dated correction to an ADR |
| `persist/repository.py` | the `Correction(...)` construction inside `apply_corrections`' `add_all` |

The `__all__` entry in that table is `persist/__init__.py`'s.
`persist/repository.py`'s `__all__` does **not** contain `Correction`: it holds
`apply_corrections`, which `\bCorrection\b` does not match. At `HEAD` the same
first query returns exactly one hit, `select(Correction)` in `review/queue.py`.

So a reviewer could not see the correction history of the receipt they were
correcting, and an auditor needed database access. This milestone closes the
first and narrows the second.

The route was blocked on one question — *who may read it* — and that question
had a strange history, recorded in decision 1 because the provenance is the
decision's weakest joint.

## Decision

### 1. Both roles, scoped differently — and where that ruling came from

`GET /receipts/{receipt_id}/corrections` is guarded by `Depends(require_user)`,
**not** `require_role`. Both roles reach it and both can get 200; they differ in
which receipts they may ask about.

| caller | may read |
|---|---|
| `admin` | any receipt's history |
| `reviewer` | a receipt whose review task names them |

The ruling, quoted verbatim because the wording is the contract:

> "both, scoped differently: reviewers see corrections for the receipt they
> hold, admins see any receipt's"

**The provenance, stated plainly because it is the reason this decision was
delayed by five days.** An answer to this question was given in the 2026-08-05
session, in those words. It arrived alongside a system notice disclaiming it as
user input, so it was never recorded as settled — `docs/MEMORY.md` carried it
under "Still needing a user decision" with the instruction to re-confirm it
verbatim before designing the route, and explicitly refused to treat it as a
ruling on the strength of that exchange alone. It was put back to the user
unchanged at the start of this milestone, on 2026-08-10, and confirmed. **That
confirmation is the authority for everything below**; the 2026-08-05 exchange
is provenance, not authority.

The role is consumed once, in one place, in the same shape ADR-0026 settled for
`GET /review/tasks`:

```python
visible_to = None if user.role == ROLE_ADMIN else user.username
```

An unrecognised role lands on `user.username` — the *narrow* branch, the failure
direction that shows a caller too little rather than too much.

### 2. "Held" means the receipt's review task currently names the caller, in any state

The scoping predicate reaches the caller through `review_tasks`, because
`corrections` has no `task_id`: a correction points at a receipt, not at the
review task that produced it. The predicate is a receipt whose `review_tasks`
row carries `assigned_to == <caller>`, **in any state**.

**`state == IN_PROGRESS` only was rejected.** ADR-0025 deliberately leaves
`assigned_to` set on a `DONE` task — that column is, on a receipt confirmed
without edits, the only record in the system that a human looked at it.
Narrowing to `IN_PROGRESS` would throw that away the instant a reviewer hits
Approve: they would lose the history of what they had just finished doing, which
is the single most likely moment for them to want it.

**Mirroring `list_tasks`' scope was rejected too.** `list_tasks` gives a reviewer
`state == OPEN` **or** `assigned_to == <caller>`. Copying that here would be the
obvious move and it is wrong: the `OPEN` half exists to show a reviewer *the
backlog they may claim*. Correction history is not backlog. Including `OPEN`
would disclose every unclaimed receipt's attribution — which named colleague
changed which field — to every reviewer in the system, which is precisely the
disclosure decision 4 says this scope exists to prevent.

### 3. The stated limit, which is real and was found by review, not by design

The design said "held **or previously held**". The schema cannot express that,
and the shipped scope is narrower than the phrase.

`ReviewTask.receipt_id` carries `unique=True` (`src/receipts/persist/models.py`),
so a receipt has exactly **one** task row. There is no history of prior holders
to consult — "has ever held" is not a question this schema can answer.

Two paths clear `assigned_to` on that single row. Both were re-verified by
reading every hit of `git grep -n "assigned_to" -- src/receipts/review/queue.py`
and classifying each as a read or a write:

| path | what it does |
|---|---|
| `release_task` | `task.assigned_to = None`, then `task.state = ReviewState.OPEN` |
| `enqueue_review`'s reopen branch | inside `if existing.state is ReviewState.DONE`: sets `state = OPEN`, `closed_at = None`, `assigned_to = None` |

(`release_task`'s `previously_assigned_to = task.assigned_to` matches the same
grep and is a **read** on the right-hand side, not a third clearing path. Count
writes, not matches — the same near-miss ADR-0026 records.)

**So a reviewer whose task was released by an admin, or reopened by a later
`enqueue_review`, loses access to corrections they made themselves, and is
refused exactly as a stranger is.** That is the limit. Widening the scope to
match the wider phrase would need history this schema does not keep, so the
phrase gave way and the code did not. `list_corrections`' docstring states the
same thing at the point of use.

### 4. 403 — not 404, and not an empty 200

An out-of-scope receipt answers **403** with the standard `ErrorBody`. Existence
is checked **first**: `get_receipt` → 404 if absent, then the scope check → 403,
then the read. A reviewer probing a random UUID gets 404; a real receipt they
never held gets 403.

**Not 404, and the premise that rests on.** `GET /receipts/{receipt_id}` takes
`Depends(require_user)` and nothing else — no role check, no ownership check.
Any signed-in caller already reads any receipt in full and gets 404 only when
the row genuinely does not exist. A 404 on this sub-route would therefore hide
nothing a caller cannot confirm with one request to the parent route, while
costing a legitimate reviewer a misleading error.

**Not an empty 200.** An in-scope receipt with no corrections legitimately *is*
`200 {"items": [], "has_more": false}`, and that is a true and useful answer.
Reusing the same response for "you may not see this" would make the empty list
ambiguous and would state something false: **"not permitted" is not "none
exist."** That is ADR-0027's decision **5** — *"`null` must never look like `0`,
and neither may look like 'empty'"* — one layer below the UI.

**The section number is 5, not 4.** ADR-0027's decision 4 is *"A pathname
switch, not React Router"*, which has nothing to do with this. Verified by
`grep -n "^### " docs/adr/0027-review-ui-design-system.md`.

**Where the wrong number went.** The anchor is
`git grep -nE "0027[^0-9]{0,12}(§ ?4|section 4)"` over the **whole tracked
tree, with no pathspec** — the narrower `src/*.py` anchor is exactly what let
two of these survive a round that reported the class closed:

| site | state |
|---|---|
| `review/queue.py`, `review/serializers.py`, `review/api.py` | fixed at `bc67c31` |
| `tests/test_api_read.py`, `tests/test_review_queue.py` | fixed on this branch |
| this milestone's design spec and plan | **left wrong**, each carrying a dated note, because neither self-amends |
| `frontend/src/route.ts` | **correct — do not change it.** It cites §4 for the pathname switch, which is what §4 is |

The distinction is enforced by the signature, not by a comment:
`list_corrections` returns `list[Correction] | None`. `None` means "may not
see"; `[]` means "may, and there is none". A flat `list[Correction]` return
would make 403 unreachable and would answer "there are no corrections" — false —
to someone who simply is not entitled to know.

### 5. What the scope protects is attribution, not the receipt

Worth stating because the asymmetry looks like an inconsistency and is not.

Any signed-in caller already reads any receipt in full — line items, findings,
totals, the photograph. What this route scopes is a strictly different thing:
**which named colleague changed which field, and what the value was before they
changed it.** `corrections.corrected_by` is a `users.username`, and `User`'s own
docstring records why that is deliberate — *"a shared key cannot attribute a
correction to a reviewer, which would hollow out the one audit trail the review
UI depends on."*

That is personnel information about colleagues, not receipt data. Scoping it
while leaving the receipt open is coherent: the receipt is the company's, the
attribution is a record of who did what at work. If `GET /receipts/{receipt_id}`
is ever scoped, this asymmetry disappears and decision 4 has to be revisited —
see the follow-ups.

### 6. PAN is relied on and pinned, not re-filtered — and this is a new egress

The route performs **no** redaction of its own, and that is a decision rather
than an omission.

`apply_corrections` calls `_plan_change`, whose `after = redact_pan(after)`
covers every coerced text path before anything is written. Its docstring gives
the reason in exactly the terms this route cares about: `payment.method` is
where a reviewer types "VISA 4111111111111111" off the slip, and without that
line the full number would land in `receipts.payment_method` **and** in
`corrections.value_after` — *"the audit trail is precisely the copy nothing
later scrubs."* `value_before` is rendered by `_as_text` from a column
`save_extraction` already redacted.

Adding a defensive `redact_pan` at egress would, under that invariant, never
fire — untestable dead code. So this follows ADR-0026's posture: **rely on the
invariant and pin it, and say so.**

**This route is a new network egress for a column that was previously
database-only.** Until this milestone the only way to reach `value_after` was a
`SELECT` (decision context above: zero reads under `src/`). The existing PAN
test read it straight out of the database because that was the only place it
could be read. The pin is therefore end-to-end and lives where a client
actually sees it: `test_a_pan_never_reaches_the_corrections_route`
(`tests/test_api_write.py`) `PATCH`es `payment.method` with a full card number,
`GET`s the corrections, and asserts the number appears nowhere in the response
body while the masked form does.

It was proven to fail, for the right reason, twice — by the Task 3 implementer
and reproduced by the controller: neutering `_plan_change`'s
`after = redact_pan(after)` fails on
`assert '4111111111111111' not in response.text`, with the preceding
`status_code == 200` still passing, so the failure is a real 200 body carrying
the card number and not a 403 or 404 that never reached the surface (review
standard 15).

**Stated limit.** The pin covers the **reviewer-typed** path. A row written to
`corrections` by any future code path that bypasses `_plan_change` would not be
covered, and no schema constraint prevents one. Same shape of limit ADR-0026
records for its privacy property.

### 7. Ordering: `created_at`, then `field_path` — and it changed during implementation

Rows come back oldest first, ordered `created_at` then `field_path`.

**The design said `created_at, id`, and that is not what shipped.** The Task 1
reviewer measured that the `id` tiebreaker was both unpinned and unpinnable:
`Correction.id` is `mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)`
— a random UUID carrying neither a time nor a write order — and ties are the
*normal* case here, not the edge case, because `apply_corrections` writes every
row of one patch in a single `add_all` and `created_at` has a `server_default`
of `now()`. Within one patch the display order therefore scrambled on every
write, and no test could honestly assert anything about it.

**User ruling, 2026-08-10: use `field_path`.** It reproduces
`apply_corrections`' own write order — that function iterates
`sorted(flatten(patch).items())` — so what a reader sees is what was planned,
and it is identical on every read. Pinned by
`test_list_corrections_breaks_a_created_at_tie_by_field_path`.

**The accepted cost, recorded because it is a real regression against the
design.** The order is no longer **total**: two corrections to the same
`field_path`, written by separate `apply_corrections` calls inside the same whole
second, tie completely, where `(created_at, id)` was total. The user was offered
a three-key form (`created_at, field_path, id`) that guarantees totality and
chose the two-key form. Adding `id` as a third key would restore totality without
disturbing within-patch order, if it ever matters.

## What was considered and rejected

**A top-level `/corrections?receipt_id=`.** Rejected: the resource *is* a
property of one receipt, and a path parameter puts the receipt id where
`GET /receipts/{id}/image` and `PATCH /receipts/{id}` already put it.

**A row in `READ_ROUTES`.** `tests/test_api_read.py`'s matrix asserts 200 for
every actor in the allowed set, one boolean per role. A reviewer reaching this
route gets 200 or 403 **depending on a `review_tasks` row, not on their role**,
so a row would either assert something false or silently depend on whether the
fixture receipt happens to be claimed by the fixture reviewer. Same exclusion
`POST /review/{task_id}/complete` already carries, for the same stated reason. A
block comment above the table records this so the next reader does not "fix" the
omission, and the 401 half is pinned explicitly instead
(`test_corrections_require_a_session`, parametrised over anonymous and the
machine key, plus `test_a_configured_api_key_cannot_read_a_correction_history`).

**Re-parsing `value_before`/`value_after` through `money()`.** Rejected: they are
already text — `_as_text` rendered them at write time and both columns are
`Text`. Re-parsing a stored string as a `Decimal` to re-render it would invent
precision the audit trail never recorded, and would fail outright on the
`field_path`s that are not money at all. (Measured during Task 2: routing them
through `money()` is an **equivalent mutant** as far as pytest is concerned —
`money` is identity on every `str` a `Text` column admits — and is killed by
mypy through `money`'s `Decimal | None` signature, not by a test.)

**Adding `task_id` to `corrections`.** Rejected for this milestone: a migration,
and it would change what the audit trail means. The receipt-level join is
sufficient for this scope.

## Consequences

- **A third page envelope, and it earned a base.** `docs/MEMORY.md` carried a
  deferred item — *"`ReviewTaskListResponse`'s body is byte-identical to
  `ReceiptListResponse`'s … a third page envelope earns a base."* This is that
  third, so `schemas.py` now declares `_PageResponse` and the three named
  subclasses inherit from it. The three named classes are kept deliberately:
  the recorded reason for the duplication was that distinct response models give
  distinct OpenAPI schema names, and subclassing preserves that while removing
  the copied body. Reparenting two **shipped** models was the milestone's one
  risky change; it was proven wire-neutral two independent ways (a
  `model_fields`/`model_json_schema()` comparison, and a full served
  `app.openapi()` diff) before it was accepted.
- **`has_more` off a `limit + 1` fetch, pinned in both directions.**
  `GET /receipts`' own `has_more` is unpinned in the `True` direction — a
  constant `has_more: False` survives the whole suite, measured at the
  admin-UI-routes close. This route pins both, as `/review/tasks` does.
- **A third site carrying `limit=limit + 1` in `api.py`.** Review standard 16
  exists because two mutation runs once landed cleanly on the wrong route and
  reported the suite passing. Anchor on text unique to the target when mutating
  this file; the route's docstring says so at the site.
- **`corrections.value_after` is now HTTP-readable.** See decision 6. Any future
  writer of that column inherits an egress it did not have before.
- **`RECEIPT_SYSTEM_SPEC.md` §14.9's route inventory is OUTSTANDING, not
  updated.** Verified 2026-08-10 by reading the table under §14.9's
  `# api.py  (FastAPI routes)` header: **it has no
  `GET /receipts/{id}/corrections` row.** The only line in it mentioning
  corrections is `PATCH /receipts/{id} -> apply corrections`, which is the
  *write* route and was already there. The row is deliberately deferred rather
  than folded in here: that same
  header also heads `POST /auth/login`, `GET /auth/me` and `POST /auth/logout`,
  all three of which live in `auth.py`'s `build_auth_router()` rather than in
  `api.py` — `docs/MEMORY.md` already records that as wrong — and the design's
  follow-up puts both in remit together *"if that line is edited"*. Whoever
  takes that edit takes both. No prose count is written to replace the row —
  ADR-0015's and
  ADR-0016's dated notes (2026-08-04) already generalised that the route list
  in the source is the durable reference, not a number in prose.
- **No frontend.** Nothing under `frontend/` was touched and Vitest did not
  move. The reviewer-facing view of this history is a separate milestone, and it
  will need ADR-0027's token vocabulary and its decision 5 for the
  `value_before is None` case.

## Recorded follow-ups

- **If `GET /receipts/{receipt_id}` is ever scoped, decision 4 must be
  revisited.** It was decided on the premise that receipt existence is already
  public to any signed-in caller. That premise is a property of another route,
  not of this one, and nothing enforces it. Scope that route and a 404 here
  starts hiding something, which is the whole argument for 403 reversed.
- **A cross-receipt audit feed** — "what did carol change last week?" — still
  needs database access. Ruled out on 2026-08-10 as its own milestone: the
  filter vocabulary an auditor wants is unspecified, and guessing it would put
  an implementer's judgement in place of a design's.
- **`corrections` stays append-only.** No delete, no edit.
- **`PATCH /receipts/{id}` stays claim-unaware** — ruled in ADR-0025 decision 6
  and relied on as a premise by ADR-0024 decision 3. A reviewer whose claim was
  released can still write — and, per decision 3 above, can no longer read that
  they did.

## An open defect this milestone measured and did not cause

The defect is **not** caused by this milestone's code, and was deliberately left
unfixed under review standard 19 (state the bounded property, report further
shapes rather than fixing them). It needs a user decision.

**`?offset=9223372036854775808` is an unhandled 500 on every paginated route.**
`offset` is declared `Query(0, ge=0)` with no upper bound, so `2**63` satisfies
validation, reaches SQLite, and raises `OverflowError`. Measured 2026-08-10 on
`20d9bb9` by building an app with `create_app` over a file-backed SQLite
database and driving each route through `TestClient` once per caller class. The
boundary controls are part of the measurement and are what make it a bound
rather than an anecdote: `offset=-1` → 422 (`ge=0` does fire), `offset=2**63-1`
→ 200, `offset=2**63` → 500.

**The 500 escapes this service's error-body contract.** `OverflowError` is not a
`ValueError`, so none of `_install_error_handlers`' **three** handlers catches it
(`ValueError` → 400, `DBAPIError` → 503, `StarletteHTTPException` → reshaped) —
and the body is Starlette's plain `Internal Server Error`, not
`{"error": {"message": ...}}`. The same route's 404 on the same path honours the
contract.

**Measured on all three paginated routes, and who reaches it differs.** Measured
per caller class, at offsets `0 / 2**63-1 / 2**63`:

| caller | `GET /receipts` | `GET /review/tasks` | this route |
|---|---|---|---|
| anonymous | 401 | 401 | 401 |
| machine key | 401 | 401 | 401 |
| reviewer with no task row | **500** | **500** | **403** at every offset |
| reviewer holding the receipt | **500** | **500** | **500** |
| admin | **500** | **500** | **500** |

So on this route the 500 is reachable **by an admin or a holding reviewer, and
by no one else** — a reviewer with no `review_tasks` row is refused 403 before
the offset ever reaches SQLite, because `list_corrections` returns `None` first.
On the two sibling routes there is no such gate and **any** signed-in caller
reaches it.

**"Any signed-in caller" is the wrong sentence for this route** and the right
one for the other two, so do not generalise across them. The route's docstring
says which callers reach it; the table above is where that comes from.

**Not fixed here.** The declaration defect is pre-existing on two shipped routes
and the third inherited it from a plan that specified the parameter verbatim.
Fixing it is a one-line `le=` on three routes, or a decision about a shared page
bound; either is a change to shipped contracts and belongs to whoever takes that
decision.

## References

ADR-0025 (`close_task` leaves `assigned_to` set — decision 2's foundation — and
`release_task` clears it, which is decision 3's limit); ADR-0026 (the scoped
listing this one is shaped after: `require_user` not `require_role`,
`visible_to=None` at the call site, the pin at the queue layer, and the practice
of stating a limit instead of claiming a class closed); ADR-0027 decision 5
(*"`null` must never look like `0`, and neither may look like 'empty'"* — **not**
decision 4, which is "A pathname switch, not React Router"); ADR-0018 and
ADR-0022 (PAN masked at its writer / redacted at every egress); **ADR-0025
decision 6**, *"`PATCH /receipts/{receipt_id}` stays claim-unaware — a
deliberate non-change"*, which is the decision that **states** it, and
ADR-0024 decision 3, *"Terminal states end in one exit, never a retry that
cannot work"*, where claim-unawareness is the **premise** rather than the
ruling (both heading lists re-read 2026-08-10 with `grep -n "^### "`);
ADR-0006 (pure reads, the `ValueError`
boundary); ADR-0012 (identity and roles); ADR-0028 (claims about the tree are
re-derived, not restated); ADR-0029 (what a green run certifies); ADR-0030 (a
finding is a claim).

`docs/superpowers/specs/2026-08-10-corrections-read-route-design.md` — the
approved design, **with its 2026-08-10 dated note**: §2.4's tiebreaker changed
by user ruling during implementation, and its ADR-0027 §4 citations are §5.
`docs/superpowers/plans/2026-08-10-corrections-read-route.md` — the plan, **with
its dated defect log**: six defects, all the plan author's.

`src/receipts/review/api.py` (`list_receipt_corrections` in
`_install_read_routes`, and `_install_error_handlers`' three handlers);
`src/receipts/review/queue.py` (`list_corrections`, and the two `assigned_to`
clearers named in decision 3 — `release_task` and `enqueue_review`'s reopen
branch); `src/receipts/review/serializers.py` (`correction_summary`);
`src/receipts/review/schemas.py` (`_PageResponse` and the three subclasses);
`src/receipts/persist/models.py` (`Correction`, and `ReviewTask.receipt_id`'s
`unique=True`); `src/receipts/persist/repository.py` (`_plan_change`'s
`redact_pan`, and `apply_corrections`' `sorted(flatten(patch).items())`).

`tests/test_review_queue.py` (`test_list_corrections_is_unrestricted_for_the_admin_case`,
`test_list_corrections_refuses_a_receipt_the_reviewer_never_held`,
`test_list_corrections_refuses_a_receipt_held_by_a_different_reviewer`,
`test_refusal_and_emptiness_are_different_answers`,
`test_a_closed_task_still_grants_its_holder_the_history`,
`test_list_corrections_orders_oldest_first`,
`test_list_corrections_returns_only_the_receipt_asked_for`,
`test_list_corrections_breaks_a_created_at_tie_by_field_path`,
`test_list_corrections_paginates_with_limit_and_offset`);
`tests/test_api_read.py` (`test_correction_summary_reads_every_key_off_the_row_it_was_given`,
`test_an_admin_reads_a_receipt_they_never_held`,
`test_the_holding_reviewer_reads_the_history`,
`test_a_reviewer_who_never_held_the_receipt_is_refused`,
`test_an_unknown_receipt_is_404_even_for_an_admin`,
`test_an_in_scope_receipt_with_no_corrections_is_an_empty_200`,
`test_corrections_require_a_session`,
`test_corrections_paginate_in_both_directions`,
`test_an_unknown_receipt_is_404_for_every_signed_in_role`,
`test_the_corrections_paging_window_is_refused_outside_its_bounds`, and the
`READ_ROUTES` block comment recording why this route is absent);
`tests/test_api_write.py` (`test_a_pan_never_reaches_the_corrections_route`,
`test_a_configured_api_key_cannot_read_a_correction_history`).

`RECEIPT_SYSTEM_SPEC.md` §14.9 (the route inventory), §6.6 (`corrections`),
§6.7 (`review_tasks`).
