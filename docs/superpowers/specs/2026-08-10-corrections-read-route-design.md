# The corrections read route — design

**Date:** 2026-08-10
**Milestone:** Phase 5 follow-up #1 (the last one blocked on a ruling)
**Branch:** `feat/corrections-read-route`
**Decision record:** ADR-0031 (to be written with this milestone)

`GET /receipts/{receipt_id}/corrections` — the correction history of one
receipt, readable by the reviewer who holds or held it and by any admin.

Every count and enumeration below was derived on 2026-08-10, with the query
recorded beside it (ADR-0028 rule 2). Re-run them rather than quoting them.

---

## 1. Context, measured

### 1.1 Nothing reads the table

```
git grep -nE 'select\(\s*Correction' -- src     ->  no matches
git grep -noE '\bCorrection\b' -- src | grep -v Patch
```

Six mentions under `src/`, none of them a read: two re-exports in
`persist/__init__.py`, the class in `persist/models.py`, and three in
`persist/repository.py` (the import, the `session.add_all` construction inside
`apply_corrections`, and its `__all__` entry). The `corrections` table has been
written since Phase 3 and read by nothing since.

Two consequences, both stated in `docs/NEXT_SESSION_PROMPT.md` §2.1: a reviewer
cannot see the correction history of the receipt they are correcting, and an
auditor needs database access. This milestone closes the first and narrows the
second; §6 says what it deliberately leaves.

### 1.2 The row

`Correction` carries `id`, `receipt_id`, `field_path`, `value_before`,
`value_after`, `corrected_by`, `created_at`. There is **no `task_id`** — a
correction points at a receipt, not at the review task that produced it. So any
reviewer-scoping predicate has to reach the caller through
`review_tasks.receipt_id`, which is what §2.2 does.

`corrected_by` is a `users.username`, and `User`'s own docstring says why: *"a
shared key cannot attribute a correction to a reviewer, which would hollow out
the one audit trail the review UI depends on."* That sentence is the reason this
route needs a scope at all — see §3.2.

### 1.3 PAN is already redacted, on the write side, on purpose

`apply_corrections` calls `_plan_change`, whose `after = redact_pan(after)`
covers every coerced text path. Its docstring gives the reason in the exact
terms this route cares about:

> Only `payment.card_last4` is narrowed by `_last4`; every other text path —
> `payment.method` above all, which is where a reviewer types "VISA
> 4111111111111111" off the slip — would otherwise land a full card number in
> `receipts.payment_method` *and* in `corrections.value_after`, and the audit
> trail is precisely the copy nothing later scrubs.

`value_before` is rendered by `_as_text` from a column `save_extraction` already
redacted. `_as_text` itself does **not** redact, and does not need to: both of
its inputs are post-redaction values.

**So this route reads pre-redacted text and adds no redaction of its own.** That
is a relied-on invariant, not an absence of thought, and §3.1 pins it.

### 1.4 Receipt existence is already public to any signed-in user

`GET /receipts/{receipt_id}` takes `Depends(require_user)` and nothing else: any
authenticated reviewer reads any receipt in full — line items, findings, totals
— and gets 404 only when the row genuinely does not exist. `GET /receipts` and
`GET /receipts/{id}/image` are the same.

This is load-bearing for §2.3. A 404-instead-of-403 on this sub-route would hide
nothing, because the caller confirms existence with one request to the parent
route.

### 1.5 The scoping precedent

`list_tasks(session, *, visible_to=None, ...)` in `review/queue.py` already
expresses "admin sees everything, a named reviewer sees a subset". Its docstring
records the convention this design copies verbatim: *"`visible_to=None` is
unrestricted — the admin case, spelled explicitly at the call site rather than
as a bare boolean."*

ADR-0026 also settled *where* such a property gets pinned: at the queue layer,
with the route-level check acknowledged as catching a regression "only if some
test exercises it". §4 follows that.

---

## 2. The route

### 2.1 Contract

| | |
|---|---|
| Path | `GET /receipts/{receipt_id}/corrections` |
| Guard | `Depends(require_user)` — **not** `require_role` |
| 200 | `{"items": [...], "has_more": bool}` |
| 403 | the caller may not see this receipt's history |
| 404 | no receipt with that id |
| 401 | anonymous, or the machine upload key |

Nested under the receipt rather than a top-level `/corrections?receipt_id=`
because the resource *is* a property of one receipt, and because a path
parameter puts the receipt id where the existing `/receipts/{id}/image` and
`PATCH /receipts/{id}` already put it.

Query parameters `limit` (default 50, 1–200) and `offset` (≥ 0), matching
`GET /receipts` and `GET /review/tasks` exactly.

### 2.2 Scope — held or previously held

**Ruling, confirmed verbatim by the user on 2026-08-10:**

> "both, scoped differently: reviewers see corrections for the receipt they
> hold, admins see any receipt's"

An answer to this question was first given on 2026-08-05 but arrived alongside a
system notice disclaiming it as user input, so it was never recorded as settled.
It was put back to the user unchanged at the start of this milestone and
confirmed. **That is the wording this design implements.**

"Hold" is read as **held or previously held**: a receipt whose review task is
assigned to the caller in *any* state.

```sql
receipt_id IN (SELECT receipt_id FROM review_tasks WHERE assigned_to = :username)
```

Chosen over "currently claimed only" (`state = IN_PROGRESS`) because
`close_task` deliberately leaves `assigned_to` set on a `DONE` task — ADR-0025
made that choice so the row remains "the only record in the system that a human
looked at it". Scoping to `IN_PROGRESS` would throw that away the instant a
reviewer hits Approve, and a reviewer could not see the corrections they
themselves had just made.

Chosen over mirroring `list_tasks` exactly (`state == OPEN OR assigned_to = me`)
because the `OPEN` half exists to show a reviewer the *backlog they may claim*.
Correction history is not backlog: including `OPEN` would let any reviewer read
any unclaimed receipt's attribution, which is the disclosure §3.2 exists to
prevent.

**An admin is unrestricted**, spelled at the call site as `visible_to=None`.

### 2.3 An out-of-scope receipt is 403, not 404 and not an empty 200

* **Not 404.** §1.4: existence is already disclosed by the parent route, so a
  404 here buys no secrecy and costs a legitimate reviewer a misleading error.
* **Not `200 {"items": []}`.** A receipt that is in scope and has never been
  corrected is *also* an empty list, and that is a true, useful answer. Using
  the same response for "you may not see this" would make the empty list
  ambiguous and would state something false. This is ADR-0027 §4's rule —
  `null` ≠ `0` ≠ empty — one layer below the UI: **"not permitted" is not
  "none exist."**
* **So: 403**, with the standard `ErrorBody`. It discloses that the receipt
  exists, which §1.4 establishes is not a secret.

Ordering matters and is part of the contract: **existence first, then scope.**
`get_receipt` → 404 if absent; then the scope check → 403; then the read. A
reviewer probing a random UUID gets 404; a real receipt they never held gets
403.

### 2.4 Ordering

`created_at`, then `id` as a tiebreaker — oldest first, so a page reads as a
history in the order it happened, and the total order is stable under
pagination. `id` is a UUID and carries no time information, so it is a
tiebreaker only, present because `created_at` has a `server_default` of
`now()` and a single `apply_corrections` call writes every row of one patch in
one flush — ties are the normal case, not the exception.

### 2.5 Response shape, and the third envelope

Each item is a serializer output, envelope-typed and payload-untyped like the
other two list routes:

```python
{
  "id": str,            "field_path": str,
  "value_before": str | None,   "value_after": str | None,
  "corrected_by": str,  "created_at": str,   # ISO-8601
}
```

`value_before` / `value_after` stay `str | None` and are **not** coerced through
`money()`. They are already text — `_as_text` rendered them at write time and
the column is `Text`. Re-parsing a stored string as a `Decimal` to re-render it
would invent precision the audit trail never recorded, and would fail on
`field_path`s that are not money at all.

`null` here means the field had no value on that side of the change, which is
exactly what the UI's null rule is for. It is not "empty" and not `"0"`.

**The third envelope earns a base.** `docs/MEMORY.md`'s deferred follow-ups
records: *"`ReviewTaskListResponse`'s body is byte-identical to
`ReceiptListResponse`'s. Defensible — distinct response models give distinct
OpenAPI schema names — but a third page envelope earns a base."* This milestone
is that third envelope, so it introduces the base and resolves the deferred
item:

```python
class _PageResponse(BaseModel):
    items: list[dict[str, Any]]
    has_more: bool

class ReceiptListResponse(_PageResponse):      ...
class ReviewTaskListResponse(_PageResponse):   ...
class CorrectionListResponse(_PageResponse):   ...
```

Three named subclasses are kept deliberately — the recorded reason for the
duplication was that *"distinct response models give distinct OpenAPI schema
names"*, and subclassing preserves that while removing the copied body. Each
subclass keeps its own docstring.

`has_more` comes off a `limit + 1` fetch, like both existing list routes. **The
mutation trap applies here:** `api.py` already carries `limit=limit + 1` twice,
and review standard 16 exists because two mutation runs landed on the wrong
route and reported the suite passing. This route makes it three. Anchor on text
unique to the target when mutating.

### 2.6 Where the query lives

`list_corrections` goes in **`review/queue.py`**, beside `list_tasks`:

```python
def list_corrections(
    session: Session,
    receipt_id: uuid.UUID,
    *,
    visible_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Correction] | None:
```

**The return type carries the distinction §2.3 draws.** `None` means "this
caller may not see this receipt's history"; `[]` means "they may, and there is
none". A single `list[Correction]` return would make the two indistinguishable
and 403 unreachable, which is the collapse §2.3 rules out — so the signature
enforces it rather than a comment describing it.

`queue.py` over `repository.py` for three reasons: the scoping predicate is
about `review_tasks`, which `queue.py` owns and `repository.py` does not import;
`queue.py` already imports `ReviewTask` and `redact_pan`, so only `Correction`
is new; and `repository.py` is 1342 lines against `queue.py`'s 518 (`wc -l` over
tracked `src/**/*.py`, 2026-08-10), so the smaller module is the better home for
a function neither one strictly owns.

A **pure read** under ADR-0006: explicit `Session` first, no flush, no commit,
no `ValueError`. Route-level validation rejects a bad `limit` before this is
reached, exactly as `list_tasks` documents.

The serializer — `correction_summary` — goes in `review/serializers.py` beside
`receipt_summary` and `_finding`, and is exported from `__all__`.

---

## 3. The invariants this route relies on

### 3.1 PAN: relied on, and pinned end-to-end

The route performs no redaction (§1.3). Rather than adding a defensive
`redact_pan` at egress — which under the write-side invariant never fires, and
would therefore be untestable dead code — this follows ADR-0026's posture:
**rely on the invariant and pin it**, and say so.

The pin is an end-to-end test, not a unit test of the reader: `PATCH` a receipt
with `payment.method = "VISA 4111111111111111"`, then `GET` the corrections and
assert the full number appears nowhere in the response body, while the masked
form does. It fails if `_plan_change`'s `redact_pan` is removed, which is the
mutation that matters.

**Stated limit** (ADR-0029's discipline): this pins the *reviewer-typed* path.
A row written to `corrections` by any future code path that bypasses
`_plan_change` would not be covered, and no schema constraint prevents one. That
is the same shape of limit ADR-0026 records for the privacy property, and it is
recorded here rather than claimed closed.

### 3.2 What the scope actually protects

Not the receipt — §1.4 establishes any signed-in user reads that already. It
protects **attribution**: which named person changed which field, and what the
value was before they changed it. That is personnel information about
colleagues, and it is the reason a reviewer's view is scoped while the receipt
itself is not. The apparent inconsistency is deliberate and belongs in the ADR.

---

## 4. Testing

**Route level** (`tests/test_api_read.py`):

1. An admin reads a receipt they have never held → 200, rows present.
2. The holding reviewer reads it → 200, same rows.
3. A reviewer who has *never* held it → **403**.
4. A reviewer whose task on it is `DONE` → **200** (the §2.2 ruling; fails
   under a `state == IN_PROGRESS` scope).
5. Unknown receipt id, as admin → **404** (proves existence is checked before
   scope).
6. In-scope receipt with no corrections → **200 `{"items": [], ...}`**, which
   with (3) is what makes 403 and empty-list distinguishable.
7. Anonymous and machine-key → **401**.
8. Pagination: `has_more` true *and* false. **`GET /receipts`' `has_more` is
   unpinned in the `True` direction** — a constant `has_more: False` survives
   all 979 tests, measured at the admin-UI-routes close. This route pins both
   directions, as `/review/tasks` does.

**Queue level** (`tests/test_review_queue.py`, where `list_tasks`' own scope
tests already live):

9. `visible_to=None` returns rows for a receipt with no review task at all.
10. `visible_to="carol"` returns `None` — not `[]` — for a receipt carol never
    held. This is the pin that keeps 403 reachable; it goes red if the signature
    is flattened to `list[Correction]`.
11. Ordering by `created_at` across two separate `apply_corrections` calls.

**End-to-end:** the PAN test in §3.1.

### 4.1 This route does **not** join `READ_ROUTES`

`tests/test_api_read.py`'s `READ_ROUTES` matrix asserts `200` for every actor in
the allowed set. A reviewer reaching this route gets 200 or 403 **depending on a
row in `review_tasks`, not on their role**, so a one-boolean-per-role entry
would either lie or silently depend on whether the `receipt_id` fixture happens
to be assigned to the fixture reviewer.

This is the same exclusion `POST /review/{task_id}/complete` already carries,
for the same stated reason: *"the actual rule is 'assignee or admin' — a
reviewer who is not the assignee gets 403 despite holding an allowed role. That
is not a role/actor predicate this table's shape can express."* The 401 half
(anonymous, machine key) is still pinned, by test 7 above, written explicitly.

A block comment at the table records why the route is absent, so the next reader
does not "fix" the omission.

---

## 5. Tasks and dispatch

Three tasks, strictly serial — they share `api.py`, `schemas.py` and the test
modules, and ADR-0023 (as corrected 2026-08-06) serialises on shared files
**and** on a shared global gate.

| # | Deliverable | Files |
|---|---|---|
| 1 | `list_corrections` + its queue-level tests | `review/queue.py`, `tests/test_review_queue.py` |
| 2 | `correction_summary`, `_PageResponse` + the three subclasses | `review/serializers.py`, `review/schemas.py`, their tests |
| 3 | The route, its eight route-level tests, the PAN end-to-end test, the `READ_ROUTES` comment | `review/api.py`, `tests/test_api_read.py` |

Task 2 touches two shipped response models. Its bound: **all 979 existing tests
pass unmodified; anything requiring a test to change is a stop-and-report.**

---

## 6. What this milestone does not do

* **No cross-receipt audit feed.** "What did carol change last week?" still
  needs database access. Ruled out on 2026-08-10 as its own milestone: the
  filter vocabulary an auditor wants is unspecified, and guessing it here would
  put an implementer's judgement in place of the design's.
* **No frontend.** No React work, no route in `route.ts`, nothing under
  `frontend/`. The reviewer-facing view of this history is a separate milestone
  with its own design, and it will need ADR-0027's token vocabulary and the
  `null` rule for the `value_before is None` case.
* **No delete or edit.** `corrections` stays append-only.
* **No `task_id` on the row.** Adding one would be a migration and would change
  what the audit trail means; the receipt-level join is sufficient for this
  scope.
* **No change to `PATCH /receipts/{id}`.** It stays claim-unaware (ADR-0024 §3's
  premise). A reviewer whose claim was released can still write, and this route
  will show that they did.

## 7. Recorded follow-ups

* The cross-receipt audit feed above, if an auditor's filters get specified.
* `RECEIPT_SYSTEM_SPEC.md` §14.9's route inventory gains a row; its
  `# api.py  (FastAPI routes)` header is already recorded in `docs/MEMORY.md` as
  wrong (three routes live in `auth.py`) — in remit only if that line is edited.
* Whether `GET /receipts/{id}` *should* be scoped is a real question this design
  surfaces and does not answer. It is currently unscoped, and §2.3's reasoning
  depends on that staying true. **If it is ever scoped, revisit §2.3**, because
  403-vs-404 was decided on the premise that existence is public.

## 8. References

`docs/adr/0006` (repository conventions, the `ValueError` boundary),
`0007` + `0018` + `0020` (PAN), `0012` (auth and roles), `0024` (claim-unaware
`PATCH`), `0025` (`close_task` leaves `assigned_to` set), `0026` (the closest
analogue: scoped listing, where the pin lives, and the limit stated),
`0027` §4 (`null` ≠ `0` ≠ empty), `0028` (claims are re-derived),
`0029` (what the gates certify), `0030` (a finding is a claim);
`docs/superpowers/specs/2026-08-05-admin-ui-backend-routes-design.md` (the
design this one is shaped after); `docs/MEMORY.md` review standards 14, 16, 19
and 20.
